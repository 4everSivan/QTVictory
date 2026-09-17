import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '../../api/hooks'
import { useTraders, traderOps } from '../../state/traders'
import { toast } from '../panes/Toasts'
import { ApiError } from '../../api/client'
import { presentError } from '../../api/errors'
import type { Template } from '../../api/types'

interface TraderFormDialogProps {
  mode: 'create' | 'edit'
  onClose: () => void
}

/**
 * 交易员创建/编辑对话框（01 §4.10〔v2 新增〕）：
 * 名称 / 模式（手动｜策略）/ 策略模板（8 示例 + 参数 schema 驱动表单）/
 * 任意初始资金 / 可选计划速设（标的池 + 止损止盈 + 日亏损上限）。
 */
export function TraderFormDialog({ mode, onClose }: TraderFormDialogProps) {
  const { editTarget, refresh } = useTraders()
  const templatesQuery = useQuery<{ data: Template[] }>('/templates')
  const templates = templatesQuery.data?.data ?? []

  const [name, setName] = useState(mode === 'edit' ? (editTarget?.name ?? '') : '')
  const [traderMode, setTraderMode] = useState<'manual' | 'strategy'>(editTarget?.mode ?? 'manual')
  const [templateKey, setTemplateKey] = useState('')
  const [params, setParams] = useState<Record<string, number>>({})
  const [initCash, setInitCash] = useState('1000000')
  const [withPlan, setWithPlan] = useState(false)
  const [pool, setPool] = useState('')
  const [stopLossPct, setStopLossPct] = useState('')
  const [takeProfitPct, setTakeProfitPct] = useState('')
  const [dailyMaxLoss, setDailyMaxLoss] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const selectedTemplate = useMemo(
    () => templates.find((t) => t.template === templateKey),
    [templates, templateKey],
  )

  useEffect(() => {
    // 编辑态参数基底 = 所属模板默认值（后端未暴露单交易员 strategyParams 读取端点，登记后续迭代）
    if (mode === 'edit' && editTarget?.mode === 'strategy' && editTarget.strategyType) {
      const tpl = templates.find((t) => t.template === editTarget.strategyType)
      if (tpl) {
        const defaults: Record<string, number> = {}
        for (const [k, v] of Object.entries(tpl.params)) defaults[k] = v.default
        setParams(defaults)
      }
    }
  }, [mode, editTarget, templates])

  useEffect(() => {
    if (mode !== 'create') return
    if (selectedTemplate) {
      const defaults: Record<string, number> = {}
      for (const [k, v] of Object.entries(selectedTemplate.params)) defaults[k] = v.default
      setParams(defaults)
    } else {
      setParams({})
    }
  }, [selectedTemplate, mode])

  const nameError = name.trim() === '' ? '名称必填' : null
  const cashError = (() => {
    const v = Number(initCash)
    return !Number.isFinite(v) || v <= 0 ? '初始资金必须为正数' : null
  })()
  const strategyError =
    mode === 'create' && traderMode === 'strategy' && !templateKey ? '策略模式需选择模板' : null
  const planError = withPlan
    ? pool.split(/[,，\s]+/).filter(Boolean).length === 0
      ? '标的池至少一个代码'
      : null
    : null
  const formError = nameError ?? cashError ?? strategyError ?? planError

  const submit = async () => {
    if (formError || submitting) return
    setSubmitting(true)
    try {
      if (mode === 'create') {
        const payload: Record<string, unknown> = {
          name: name.trim(),
          mode: traderMode,
          initCash: Number(initCash),
        }
        if (traderMode === 'strategy' && templateKey) {
          payload.template = templateKey
          payload.params = params
        }
        if (withPlan) {
          const codes = pool.split(/[,，\s]+/).filter(Boolean)
          const risk: Record<string, number> = {}
          if (stopLossPct) risk.stopLossPct = Number(stopLossPct)
          if (takeProfitPct) risk.takeProfitPct = Number(takeProfitPct)
          if (dailyMaxLoss) risk.dailyMaxLoss = Number(dailyMaxLoss)
          payload.plan = { name: `${name.trim()}·计划`, scope: { codes }, risk }
        }
        await traderOps.create(payload)
        toast('success', '交易员已创建')
      } else if (editTarget) {
        await traderOps.patch(editTarget.id, { name: name.trim(), strategy_params: params })
        toast('success', '已保存')
      }
      refresh()
      onClose()
    } catch (e) {
      toast('error', presentError(e as ApiError).text)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog dialog-wide" onClick={(e) => e.stopPropagation()} data-testid="trader-form">
        <div className="dialog-title">{mode === 'create' ? '新建交易员' : `编辑 · ${editTarget?.name ?? ''}`}</div>

        <div className="field-row">
          <label className="field">
            <span className="micro-label">名称</span>
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field">
            <span className="micro-label">模式</span>
            <div className="seg">
              {(
                [
                  ['manual', '手动'],
                  ['strategy', '策略'],
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  className={traderMode === key ? 'active' : ''}
                  onClick={() => setTraderMode(key)}
                  disabled={mode === 'edit'}
                >
                  {label}
                </button>
              ))}
            </div>
          </label>
        </div>

        {mode === 'create' && (
          <label className="field">
            <span className="micro-label">初始资金（任意金额）</span>
            <input className="num" value={initCash} onChange={(e) => setInitCash(e.target.value)} />
          </label>
        )}

        {mode === 'create' && traderMode === 'strategy' && (
          <>
            <div className="field">
              <span className="micro-label">策略模板（GET /api/templates 8 示例）</span>
              <div className="template-grid">
                {templates.map((t) => (
                  <button
                    key={t.template}
                    type="button"
                    className={`template-card ${templateKey === t.template ? 'active' : ''}`}
                    onClick={() => setTemplateKey(t.template)}
                  >
                    <span>{t.name}</span>
                    <span className="micro-label">{t.template}</span>
                  </button>
                ))}
              </div>
            </div>
            {selectedTemplate && (
              <div className="field">
                <span className="micro-label">参数（schema 驱动）</span>
                <div className="field-row">
                  {Object.entries(selectedTemplate.params).map(([k, meta]) => (
                    <label key={k} className="field">
                      <span className="micro-label">{k}</span>
                      <input
                        className="num"
                        value={String(params[k] ?? meta.default)}
                        onChange={(e) => setParams((p) => ({ ...p, [k]: Number(e.target.value) }))}
                      />
                    </label>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {mode === 'edit' && editTarget?.mode === 'strategy' && (
          <div className="field">
            <span className="micro-label">策略参数（改参）</span>
            <div className="field-row">
              {Object.entries(params).map(([k, v]) => (
                <label key={k} className="field">
                  <span className="micro-label">{k}</span>
                  <input className="num" value={String(v)} onChange={(e) => setParams((p) => ({ ...p, [k]: Number(e.target.value) }))} />
                </label>
              ))}
            </div>
          </div>
        )}

        {mode === 'create' && (
          <label className="field field-inline">
            <input type="checkbox" checked={withPlan} onChange={(e) => setWithPlan(e.target.checked)} />
            <span>可选计划速设（标的池 + 止损止盈 + 日亏损上限）</span>
          </label>
        )}
        {mode === 'create' && withPlan && (
          <div className="field">
            <label className="field">
              <span className="micro-label">标的池（逗号分隔代码）</span>
              <input className="num" value={pool} placeholder="600519, 000001" onChange={(e) => setPool(e.target.value)} />
            </label>
            <div className="field-row">
              <label className="field">
                <span className="micro-label">止损 %（stopLossPct）</span>
                <input className="num" value={stopLossPct} onChange={(e) => setStopLossPct(e.target.value)} />
              </label>
              <label className="field">
                <span className="micro-label">止盈 %（takeProfitPct）</span>
                <input className="num" value={takeProfitPct} onChange={(e) => setTakeProfitPct(e.target.value)} />
              </label>
              <label className="field">
                <span className="micro-label">日亏损上限（dailyMaxLoss）</span>
                <input className="num" value={dailyMaxLoss} onChange={(e) => setDailyMaxLoss(e.target.value)} />
              </label>
            </div>
          </div>
        )}

        {formError && <p className="form-error">{formError}</p>}

        <div className="dialog-actions">
          <button type="button" onClick={onClose}>取消</button>
          <button type="button" className="btn-primary" disabled={formError !== null || submitting} onClick={() => void submit()}>
            {submitting ? '提交中…' : mode === 'create' ? '创建' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}
