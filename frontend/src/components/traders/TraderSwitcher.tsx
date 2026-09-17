import { useEffect, useRef, useState } from 'react'
import { useTraders } from '../../state/traders'
import { fmtPct, fmtPrice } from '../../lib/format'

const METRICS: Array<{ key: string; label: string; fmt: (v: number | null) => string }> = [
  { key: 'equity', label: '总资产', fmt: fmtPrice },
  { key: 'marketValue', label: '持仓市值', fmt: fmtPrice },
  { key: 'availableCash', label: '可用资金', fmt: fmtPrice },
  { key: 'dayPnl', label: '当日盈亏', fmt: (v) => (v === null ? '--' : `${v >= 0 ? '+' : ''}${fmtPrice(v)}`) },
  { key: 'totalReturn', label: '总收益率', fmt: fmtPct },
]

/**
 * 顶栏五指标均分数据带（01 §4.1 v2.1）：flex:1 等分、项间 1px 细线、
 * 15px 数据档 tabular-nums；全部跟随当前交易员（§2.1 v2 语义）。
 */
export function FiveMetricBand() {
  const { account, dayPnl } = useTraders()
  const values: Record<string, number | null> = {
    equity: account?.equity ?? null,
    marketValue: account?.marketValue ?? null,
    availableCash: account?.availableCash ?? null,
    dayPnl,
    totalReturn: account?.totalReturn ?? null,
  }

  return (
    <div className="metric-band num" data-testid="metric-band">
      {METRICS.map((m, i) => {
        const v = values[m.key]
        const cls =
          m.key === 'dayPnl' || m.key === 'totalReturn'
            ? v === null
              ? 'flat'
              : v > 0
                ? 'up'
                : v < 0
                  ? 'down'
                  : 'flat'
            : 'flat'
        return (
          <div key={m.key} className={`metric ${i > 0 ? 'metric-divided' : ''}`}>
            <span className="micro-label">{m.label}</span>
            <span className={`metric-value ${cls}`}>{m.fmt(v)}</span>
          </div>
        )
      })}
    </div>
  )
}

/**
 * 当前交易员切换器（01 §4.1〔v2 新增〕）：胶囊下拉（名称+模式徽标+总资产速览）；
 * 无交易员时空态按钮"创建交易员"。
 */
export function TraderSwitcher() {
  const { list, currentId, current, account, setCurrent, openCreate } = useTraders()
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  if (list.length === 0) {
    return (
      <button type="button" className="switcher-empty" onClick={openCreate}>
        ＋ 创建交易员
      </button>
    )
  }

  return (
    <div className="switcher" ref={wrapRef} data-testid="trader-switcher">
      <button type="button" className="switcher-capsule" onClick={() => setOpen((v) => !v)}>
        <span className="switcher-name">{current?.name ?? '--'}</span>
        <span className={`mode-badge mode-${current?.mode ?? 'manual'}`}>
          {current?.mode === 'strategy' ? 'STRAT' : 'MANUAL'}
        </span>
        <span className="switcher-equity num">{fmtPrice(account?.equity ?? null)}</span>
      </button>
      {open && (
        <div className="switcher-menu" role="menu">
          {list.map((t) => (
            <button
              key={t.id}
              type="button"
              role="menuitem"
              className={`switcher-item ${t.id === currentId ? 'active' : ''}`}
              onClick={() => {
                setCurrent(t.id)
                setOpen(false)
              }}
            >
              <span>{t.name}</span>
              <span className={`mode-badge mode-${t.mode}`}>{t.mode === 'strategy' ? 'STRAT' : 'MANUAL'}</span>
              <span className="num flat">{fmtPrice(t.equity ?? null)}</span>
            </button>
          ))}
          <button
            type="button"
            className="switcher-item switcher-add"
            onClick={() => {
              setOpen(false)
              openCreate()
            }}
          >
            ＋ 新建交易员
          </button>
        </div>
      )}
    </div>
  )
}
