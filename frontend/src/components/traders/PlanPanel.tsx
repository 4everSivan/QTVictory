import { useState } from 'react'
import { api, ApiError } from '../../api/client'
import { presentError } from '../../api/errors'
import { useQuery, useSubscription } from '../../api/hooks'
import { toast } from '../panes/Toasts'
import type { EntryRow, PlanView, ServerFrame, TriggerType } from '../../api/types'

type PlansFrame = Extract<ServerFrame, { topic: 'plans' }>

const TRIGGER_TEXT: Record<TriggerType, string> = {
  price_cross: '价格穿越',
  pct_change: '当日涨跌幅',
  time: '定时',
  ma_cross: '均线交叉',
}

const STATUS_TEXT: Record<EntryRow['status'], string> = {
  waiting: 'WAITING',
  triggered: 'TRIGGERED',
  filled: 'FILLED',
}

function parseJson(s: string | null): Record<string, unknown> {
  try {
    return s ? (JSON.parse(s) as Record<string, unknown>) : {}
  } catch {
    return {}
  }
}

function kvRows(obj: Record<string, unknown>): Array<[string, string]> {
  return Object.entries(obj).map(([k, v]) => [k, typeof v === 'number' ? String(v) : JSON.stringify(v)])
}

function describeTrigger(entry: EntryRow): string {
  const p = parseJson(entry.trigger_params)
  switch (entry.trigger_type) {
    case 'price_cross':
      return `价格穿越 ${p.side === 'sell' ? '≥' : '≤'} ${p.price}`
    case 'pct_change':
      return `当日涨跌幅 ${p.side === 'sell' ? '≥' : '≤'} ${p.pct}%`
    case 'time':
      return `定时 ${p.at ?? '--'}`
    case 'ma_cross':
      return `MA${p.fast ?? 5}×MA${p.slow ?? 20} 交叉`
  }
}

function describeAction(entry: EntryRow): string {
  const a = parseJson(entry.action)
  const qty = a.qty ? `×${a.qty}` : a.pctOfPosition ? `仓位 ${Number(a.pctOfPosition) * 100}%` : ''
  const price = a.type === 'limit' && a.price ? `@${a.price}` : ''
  return `${a.side === 'sell' ? '卖出' : '买入'} ${qty} ${a.type === 'limit' ? '限价' : '市价'}${price}`
}

interface PlanPanelProps {
  traderId: number
}

/**
 * 交易计划面板（01 §4.10〔v2 新增〕）：
 * 计划卡（状态/预算水位条/风控参数/执行进度/目标仓位偏差）+
 * 条件单列表（触发器 → 动作 → 状态 waiting/triggered/filled）+
 * 新建条件单表单（四类触发器；动作 qty|pctOfPosition × 限价|市价；有效期 day/gtc）。
 */
export function PlanPanel({ traderId }: PlanPanelProps) {
  const plansQuery = useQuery<{ data: PlanView[] }>(`/traders/${traderId}/plans`)
  const plansFrame = useSubscription<PlansFrame>('plans')
  void plansFrame // plans topic 到达即触发重渲染；reload 由下方 effect 承担

  const plans = plansQuery.data?.data ?? []

  return (
    <div className="plan-panel" data-testid="plan-panel">
      {plans.length === 0 && <div className="wl-empty">暂无交易计划</div>}
      {plans.map((plan) => (
        <PlanCard key={plan.id} plan={plan} onChanged={() => void plansQuery.reload()} />
      ))}
    </div>
  )
}

function scopeCodes(plan: PlanView): string[] {
  const codes = plan.scope.codes
  return Array.isArray(codes) ? (codes as string[]) : []
}

function PlanCard({ plan, onChanged }: { plan: PlanView; onChanged: () => void }) {
  const entriesQuery = useQuery<{ data: EntryRow[] }>(`/plans/${plan.id}/entries`)
  const entries = entriesQuery.data?.data ?? []
  const [showForm, setShowForm] = useState(false)
  const codes = scopeCodes(plan)

  const riskRows = kvRows(plan.risk)
  const ruleRows = kvRows(plan.positionRule)
  const budgetTotal = typeof plan.budget.total === 'number' ? plan.budget.total : null
  const budgetUsed = typeof plan.budget.used === 'number' ? plan.budget.used : null
  const filledCount = entries.filter((e) => e.status === 'filled').length
  const triggeredCount = entries.filter((e) => e.status !== 'waiting').length

  return (
    <div className="plan-card" data-testid="plan-card">
      <div className="plan-head">
        <span className="plan-name">{plan.name}</span>
        <span className={`status-pill st-${plan.status === 'active' ? 'wait' : 'filled'}`}>{plan.status.toUpperCase()}</span>
        <span className="micro-label">池: {codes.join(', ') || '--'}</span>
        <button type="button" className="tb-add num" onClick={() => setShowForm((v) => !v)}>
          ＋ 条件单
        </button>
      </div>

      <div className="plan-grid num">
        {budgetTotal !== null && (
          <div className="plan-budget">
            <span className="micro-label">预算水位 {budgetUsed ?? 0}/{budgetTotal}</span>
            <div className="water-bar">
              <div
                className="water-fill"
                style={{ width: `${Math.min(100, ((budgetUsed ?? 0) / budgetTotal) * 100)}%` }}
              />
            </div>
          </div>
        )}
        <div className="plan-block">
          <span className="micro-label">风控参数</span>
          {riskRows.length === 0 && <span className="flat">--</span>}
          {riskRows.map(([k, v]) => (
            <span key={k} className="plan-kv">{`${k}: ${v}`}</span>
          ))}
        </div>
        <div className="plan-block">
          <span className="micro-label">执行进度</span>
          <span>{`条件单 ${entries.length} · 触发 ${triggeredCount} · 成交 ${filledCount}`}</span>
        </div>
        <div className="plan-block">
          <span className="micro-label">目标仓位规则</span>
          {ruleRows.length === 0 && <span className="flat">--</span>}
          {ruleRows.map(([k, v]) => (
            <span key={k} className="plan-kv">{`${k}: ${v}`}</span>
          ))}
        </div>
      </div>

      <table className="dtable num" data-testid="entry-list">
        <thead>
          <tr><th>触发器</th><th>参数</th><th>动作</th><th>有效期</th><th>状态</th></tr>
        </thead>
        <tbody>
          {entries.length === 0 && <tr><td colSpan={5} className="flat">无条件单</td></tr>}
          {entries.map((e) => (
            <tr key={e.id}>
              <td>{TRIGGER_TEXT[e.trigger_type]}</td>
              <td className="flat">{describeTrigger(e)}</td>
              <td>{describeAction(e)}</td>
              <td className="flat">{e.tif.toUpperCase()}</td>
              <td>
                <span className={`status-pill st-${e.status === 'waiting' ? 'wait' : e.status === 'triggered' ? 'partial' : 'filled'}`}>
                  {STATUS_TEXT[e.status]}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {showForm && (
        <EntryForm
          planId={plan.id}
          defaultCode={codes[0] ?? ''}
          onClose={() => setShowForm(false)}
          onCreated={() => {
            setShowForm(false)
            onChanged()
            void entriesQuery.reload()
          }}
        />
      )}
    </div>
  )
}

const TRIGGER_TYPES: Array<[TriggerType, string]> = [
  ['price_cross', '价格穿越'],
  ['pct_change', '当日涨跌幅'],
  ['time', '定时'],
  ['ma_cross', '均线交叉'],
]

function EntryForm({
  planId,
  defaultCode,
  onClose,
  onCreated,
}: {
  planId: number
  defaultCode: string
  onClose: () => void
  onCreated: () => void
}) {
  const [trigger, setTrigger] = useState<TriggerType>('price_cross')
  const [side, setSide] = useState<'buy' | 'sell'>('buy')
  const [price, setPrice] = useState('')
  const [pct, setPct] = useState('')
  const [at, setAt] = useState('14:50')
  const [fast, setFast] = useState('5')
  const [slow, setSlow] = useState('20')
  const [code, setCode] = useState(defaultCode)
  const [qtyMode, setQtyMode] = useState<'qty' | 'pct'>('qty')
  const [qty, setQty] = useState('')
  const [pctOfPosition, setPctOfPosition] = useState('')
  const [orderType, setOrderType] = useState<'market' | 'limit'>('market')
  const [limitPrice, setLimitPrice] = useState('')
  const [tif, setTif] = useState<'day' | 'gtc'>('day')

  const submit = async () => {
    const triggerParams: Record<string, unknown> = { side }
    if (trigger === 'price_cross') triggerParams.price = Number(price)
    if (trigger === 'pct_change') triggerParams.pct = Number(pct)
    if (trigger === 'time') {
      delete triggerParams.side
      triggerParams.at = at
    }
    if (trigger === 'ma_cross') {
      triggerParams.fast = Number(fast)
      triggerParams.slow = Number(slow)
      if (code) triggerParams.code = code
    } else if (code) {
      triggerParams.code = code
    }
    const action: Record<string, unknown> = {
      side,
      type: orderType,
      ...(qtyMode === 'qty' ? { qty: Number(qty) } : { pctOfPosition: Number(pctOfPosition) }),
      ...(orderType === 'limit' ? { price: Number(limitPrice) } : {}),
    }
    try {
      await api.post(`/plans/${planId}/entries`, {
        triggerType: trigger,
        triggerParams,
        action,
        tif,
      })
      toast('success', '条件单已创建')
      onCreated()
    } catch (e) {
      toast('error', presentError(e as ApiError).text)
    }
  }

  const valid =
    (trigger !== 'price_cross' || price !== '') &&
    (trigger !== 'pct_change' || pct !== '') &&
    (qtyMode === 'qty' ? qty !== '' : pctOfPosition !== '') &&
    (orderType !== 'limit' || limitPrice !== '')

  return (
    <div className="entry-form" data-testid="entry-form">
      <div className="field">
        <span className="micro-label">触发器类型</span>
        <div className="seg">
          {TRIGGER_TYPES.map(([key, label]) => (
            <button key={key} type="button" className={trigger === key ? 'active' : ''} onClick={() => setTrigger(key)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="field-row">
        {trigger !== 'time' && (
          <label className="field">
            <span className="micro-label">方向（触发侧）</span>
            <div className="seg">
              <button type="button" className={side === 'buy' ? 'active' : ''} onClick={() => setSide('buy')}>买入侧</button>
              <button type="button" className={side === 'sell' ? 'active' : ''} onClick={() => setSide('sell')}>卖出侧</button>
            </div>
          </label>
        )}
        <label className="field">
          <span className="micro-label">标的代码</span>
          <input className="num" value={code} onChange={(e) => setCode(e.target.value)} placeholder={defaultCode || '600519'} />
        </label>
        {trigger === 'price_cross' && (
          <label className="field">
            <span className="micro-label">触发价</span>
            <input className="num" value={price} onChange={(e) => setPrice(e.target.value)} />
          </label>
        )}
        {trigger === 'pct_change' && (
          <label className="field">
            <span className="micro-label">涨跌幅 %（负=下跌买入）</span>
            <input className="num" value={pct} onChange={(e) => setPct(e.target.value)} />
          </label>
        )}
        {trigger === 'time' && (
          <label className="field">
            <span className="micro-label">触发时间 HH:MM</span>
            <input className="num" value={at} onChange={(e) => setAt(e.target.value)} />
          </label>
        )}
        {trigger === 'ma_cross' && (
          <>
            <label className="field">
              <span className="micro-label">快线</span>
              <input className="num" value={fast} onChange={(e) => setFast(e.target.value)} />
            </label>
            <label className="field">
              <span className="micro-label">慢线</span>
              <input className="num" value={slow} onChange={(e) => setSlow(e.target.value)} />
            </label>
          </>
        )}
      </div>
      <div className="field-row">
        <label className="field">
          <span className="micro-label">数量口径</span>
          <div className="seg">
            <button type="button" className={qtyMode === 'qty' ? 'active' : ''} onClick={() => setQtyMode('qty')}>数量</button>
            <button type="button" className={qtyMode === 'pct' ? 'active' : ''} onClick={() => setQtyMode('pct')}>仓位比例</button>
          </div>
        </label>
        {qtyMode === 'qty' ? (
          <label className="field">
            <span className="micro-label">数量（股）</span>
            <input className="num" value={qty} onChange={(e) => setQty(e.target.value)} />
          </label>
        ) : (
          <label className="field">
            <span className="micro-label">仓位比例（0–1）</span>
            <input className="num" value={pctOfPosition} onChange={(e) => setPctOfPosition(e.target.value)} />
          </label>
        )}
        <label className="field">
          <span className="micro-label">订单类型</span>
          <div className="seg">
            <button type="button" className={orderType === 'market' ? 'active' : ''} onClick={() => setOrderType('market')}>市价</button>
            <button type="button" className={orderType === 'limit' ? 'active' : ''} onClick={() => setOrderType('limit')}>限价</button>
          </div>
        </label>
        {orderType === 'limit' && (
          <label className="field">
            <span className="micro-label">限价</span>
            <input className="num" value={limitPrice} onChange={(e) => setLimitPrice(e.target.value)} />
          </label>
        )}
        <label className="field">
          <span className="micro-label">有效期</span>
          <div className="seg">
            <button type="button" className={tif === 'day' ? 'active' : ''} onClick={() => setTif('day')}>DAY</button>
            <button type="button" className={tif === 'gtc' ? 'active' : ''} onClick={() => setTif('gtc')}>GTC</button>
          </div>
        </label>
      </div>
      <div className="dialog-actions">
        <button type="button" onClick={onClose}>取消</button>
        <button type="button" className="btn-primary" disabled={!valid} onClick={() => void submit()}>
          创建条件单
        </button>
      </div>
    </div>
  )
}
