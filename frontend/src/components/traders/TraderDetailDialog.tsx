import { useState } from 'react'
import { ApiError } from '../../api/client'
import { presentError } from '../../api/errors'
import { useTraders, traderOps } from '../../state/traders'
import { toast } from '../panes/Toasts'
import { EquityCurve } from '../charts/EquityCurve'
import { PlanPanel } from './PlanPanel'
import { fmtPct, fmtPrice } from '../../lib/format'
import type { TraderDetail } from '../../api/types'

const TABS = [
  ['stats', '统计'],
  ['equity', '净值'],
  ['positions', '持仓'],
  ['trades', '最近成交'],
  ['plans', '计划'],
] as const

interface TraderDetailDialogProps {
  detail: TraderDetail
  onClose: () => void
}

/** 交易员详情弹窗（01 §4.10，720px）：统计卡 / 净值 / 持仓 / 最近成交 / 计划页签 */
export function TraderDetailDialog({ detail, onClose }: TraderDetailDialogProps) {
  const { refresh } = useTraders()
  const [tab, setTab] = useState<(typeof TABS)[number][0]>('stats')
  const [confirmReset, setConfirmReset] = useState(false)

  const doReset = async () => {
    setConfirmReset(false)
    try {
      await traderOps.reset(detail.traderId)
      toast('success', '已重置')
      refresh()
    } catch (e) {
      toast('error', presentError(e as ApiError).text)
    }
  }

  const m = detail.metrics
  const stats: Array<[string, string]> = [
    ['总收益率', m.insufficient ? '--' : fmtPct(m.totalReturn)],
    ['年化', m.insufficient ? '--' : fmtPct(m.annualized)],
    ['最大回撤', m.insufficient ? '--' : fmtPct(m.maxDrawdown)],
    ['回撤天数', m.insufficient ? '--' : String(m.maxDrawdownDays ?? '--')],
    ['夏普', m.insufficient ? '--' : (m.sharpe ?? 0).toFixed(2)],
    ['胜率', m.insufficient ? '--' : fmtPct(m.winRate)],
    ['超额(vs 沪深300)', m.insufficient ? '--' : fmtPct(m.excess)],
    ['天数', String(m.days)],
  ]

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog dialog-detail" onClick={(e) => e.stopPropagation()} data-testid="trader-detail">
        <div className="dialog-title">
          <span>{detail.name}</span>
          <span className={`mode-badge mode-${detail.mode}`}>{detail.mode === 'strategy' ? 'STRAT' : 'MANUAL'}</span>
          <span className="micro-label">{detail.status}</span>
          <button type="button" className="dialog-close" onClick={onClose}>×</button>
        </div>

        <div className="detail-tabs" role="tablist">
          {TABS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              className={`ca-tab ${tab === key ? 'active' : ''}`}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
          <span className="detail-account num flat">
            总资产 {fmtPrice(detail.equity)} · 可用 {fmtPrice(detail.availableCash)}
          </span>
        </div>

        <div className="detail-body">
          {tab === 'stats' && (
            <div className="stats-grid num" data-testid="detail-stats">
              {stats.map(([label, value]) => (
                <div key={label} className="stat-card">
                  <span className="micro-label">{label}</span>
                  <span className={value.startsWith('+') ? 'up' : value.startsWith('-') ? 'down' : 'flat'}>{value}</span>
                </div>
              ))}
            </div>
          )}
          {tab === 'equity' && (
            <EquityCurve
              account={detail.equitySeries.map((p) => ({ date: p.date, value: p.total_equity }))}
            />
          )}
          {tab === 'positions' && (
            <table className="dtable num" data-testid="detail-positions">
              <thead>
                <tr><th>代码</th><th>持仓</th><th>成本</th><th>现价</th><th>市值</th><th>浮动盈亏</th></tr>
              </thead>
              <tbody>
                {detail.positions.length === 0 && (
                  <tr><td colSpan={6} className="flat">无持仓</td></tr>
                )}
                {detail.positions.map((p) => (
                  <tr key={p.code}>
                    <td>{p.code}</td>
                    <td>{p.qty}</td>
                    <td>{fmtPrice(p.avgCost)}</td>
                    <td>{fmtPrice(p.price)}</td>
                    <td>{fmtPrice(p.value)}</td>
                    <td className={p.unrealizedPnl > 0 ? 'up' : p.unrealizedPnl < 0 ? 'down' : 'flat'}>
                      {fmtPrice(p.unrealizedPnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {tab === 'trades' && (
            <table className="dtable num" data-testid="detail-trades">
              <thead>
                <tr><th>时间</th><th>代码</th><th>方向</th><th>价格</th><th>数量</th><th>金额</th></tr>
              </thead>
              <tbody>
                {detail.trades.length === 0 && (
                  <tr><td colSpan={6} className="flat">暂无成交</td></tr>
                )}
                {[...detail.trades].reverse().slice(0, 50).map((t) => (
                  <tr key={t.id}>
                    <td>{t.ts.slice(5, 16)}</td>
                    <td>{t.code}</td>
                    <td className={t.side === 'buy' ? 'up' : 'down'}>{t.side === 'buy' ? '买入' : '卖出'}</td>
                    <td>{fmtPrice(t.price)}</td>
                    <td>{t.qty}</td>
                    <td>{fmtPrice(t.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {tab === 'plans' && <PlanPanel traderId={detail.traderId} />}
        </div>

        <div className="dialog-actions">
          <button type="button" onClick={() => setConfirmReset(true)}>重置交易员</button>
          <button type="button" onClick={onClose}>关闭</button>
        </div>

        {confirmReset && (
          <div className="dialog-overlay" onClick={() => setConfirmReset(false)}>
            <div className="dialog" onClick={(e) => e.stopPropagation()}>
              <div className="dialog-title">重置 · {detail.name}</div>
              <p className="dialog-note">清空持仓/委托/成交并恢复初始资金，确认重置？</p>
              <div className="dialog-actions">
                <button type="button" onClick={() => setConfirmReset(false)}>取消</button>
                <button type="button" className="btn-danger" onClick={() => void doReset()}>确认重置</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
