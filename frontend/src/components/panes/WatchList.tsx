import { useEffect, useRef, useState } from 'react'
import type { Quote } from '../../api/types'
import { fmtPct, fmtPrice, isIndexCode, pctChange, trendClass } from '../../lib/format'

interface WatchListProps {
  quotes: Quote[]
  selected: string | null
  onSelect: (code: string) => void
}

type Flash = 'up' | 'down'

/**
 * 自选股列表（01 §4.2）：grid 1fr 76px 60px、涨跌闪动、选中左白条、底部涨跌统计。
 * 键稳定（code），tick 更新仅重渲数值格。
 */
export function WatchList({ quotes, selected, onSelect }: WatchListProps) {
  const prevPrices = useRef(new Map<string, number>())
  const [flashes, setFlashes] = useState<Record<string, Flash>>({})

  useEffect(() => {
    const next: Record<string, Flash> = {}
    const prev = prevPrices.current
    for (const q of quotes) {
      const before = prev.get(q.code)
      if (before !== undefined && before !== q.last && q.last > 0) {
        next[q.code] = q.last > before ? 'up' : 'down'
      }
      prev.set(q.code, q.last)
    }
    if (Object.keys(next).length > 0) {
      setFlashes((f) => ({ ...f, ...next }))
      const timer = setTimeout(() => {
        setFlashes((f) => {
          const rest = { ...f }
          for (const code of Object.keys(next)) delete rest[code]
          return rest
        })
      }, 260)
      return () => clearTimeout(timer)
    }
  }, [quotes])

  const stocks = quotes.filter((q) => !isIndexCode(q.code))
  const up = stocks.filter((q) => (pctChange(q.last, q.prevClose) ?? 0) > 0).length
  const down = stocks.filter((q) => (pctChange(q.last, q.prevClose) ?? 0) < 0).length
  const flat = stocks.length - up - down

  return (
    <div className="watchlist" data-testid="watchlist">
      <div className="wl-head">
        <span className="micro-label">自选股 · WATCHLIST</span>
        <span className="num wl-count">{stocks.length}</span>
      </div>
      <div className="wl-body">
        {stocks.length === 0 && <div className="wl-empty">暂无关注标的（由持仓/计划池驱动）</div>}
        {stocks.map((q) => {
          const pct = pctChange(q.last, q.prevClose)
          const cls = trendClass(pct)
          const flash = flashes[q.code]
          return (
            <button
              type="button"
              key={q.code}
              className={`wl-row num ${selected === q.code ? 'selected' : ''} ${q.last <= 0 ? 'suspended' : ''}`}
              onClick={() => onSelect(q.code)}
            >
              <span className="wl-name">
                <span className="wl-code">{q.name || q.code}</span>
                <span className="wl-sub">{q.code}</span>
              </span>
              <span className={`wl-last ${flash ? `flash-${flash}` : ''}`}>
                <span className={cls}>{fmtPrice(q.last <= 0 ? null : q.last)}</span>
              </span>
              <span className={cls}>{fmtPct(pct)}</span>
            </button>
          )
        })}
      </div>
      <div className="wl-stats num">
        <span className="up">涨 {up}</span>
        <span className="down">跌 {down}</span>
        <span className="flat">平 {flat}</span>
      </div>
    </div>
  )
}
