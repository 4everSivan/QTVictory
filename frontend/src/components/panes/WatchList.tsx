import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../../api/client'
import { presentError } from '../../api/errors'
import { fmtPct, fmtPrice, isIndexCode, pctChange, trendClass } from '../../lib/format'
import { watchlistOps, type WatchRow } from '../../state/watchlist'
import { toast } from './Toasts'
import { WatchAddPop } from './WatchAddPop'

interface WatchListProps {
  rows: WatchRow[]
  selected: string | null
  onSelect: (code: string) => void
  /** 编辑（增删）生效后回调：重拉自选集驱动重排（行情刷新链路不变） */
  onChanged: () => void
}

type Flash = 'up' | 'down'

/**
 * 自选股列表（01 §4.2 v5）：grid 1fr 76px 60px、涨跌闪动、选中左白条、底部涨跌统计。
 * 编辑能力：头部 "+" 弹层联想添加；hover 自选行尾显现删除钮（仅自选项，
 * 动态项无此 affordance）。键稳定（code），tick 更新仅重渲数值格。
 */
export function WatchList({ rows, selected, onSelect, onChanged }: WatchListProps) {
  const prevPrices = useRef(new Map<string, number>())
  const [flashes, setFlashes] = useState<Record<string, Flash>>({})
  const [addOpen, setAddOpen] = useState(false)

  useEffect(() => {
    const next: Record<string, Flash> = {}
    const prev = prevPrices.current
    for (const r of rows) {
      const q = r.quote
      if (!q) continue
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
  }, [rows])

  const remove = async (code: string) => {
    try {
      await watchlistOps.remove(code) // 幂等：删除不存在视为成功
      onChanged()
    } catch (e) {
      toast('error', presentError(e as ApiError).text)
    }
  }

  const stocks = rows.filter((r) => !isIndexCode(r.code))
  const pctOf = (r: WatchRow) => (r.quote ? pctChange(r.quote.last, r.quote.prevClose) : null)
  const up = stocks.filter((r) => (pctOf(r) ?? 0) > 0).length
  const down = stocks.filter((r) => (pctOf(r) ?? 0) < 0).length
  const flat = stocks.length - up - down

  return (
    <div className="watchlist" data-testid="watchlist">
      <div className="wl-head">
        <span className="micro-label">自选股 · WATCHLIST</span>
        <span className="wl-tools">
          <span className="num wl-count">{stocks.length}</span>
          <button
            type="button"
            className="wl-add"
            aria-label="添加自选"
            onClick={() => setAddOpen((o) => !o)}
          >
            ＋
          </button>
        </span>
      </div>
      {addOpen && (
        <WatchAddPop
          onClose={() => setAddOpen(false)}
          onAdded={() => {
            setAddOpen(false)
            onChanged()
          }}
        />
      )}
      <div className="wl-body">
        {stocks.length === 0 && <div className="wl-empty">暂无关注标的（由持仓/计划池驱动）</div>}
        {stocks.map((r) => {
          const q = r.quote
          const pct = pctOf(r)
          const cls = trendClass(pct)
          const flash = flashes[r.code]
          const suspended = !q || q.last <= 0
          return (
            <div
              role="button"
              tabIndex={0}
              key={r.code}
              data-code={r.code}
              data-pinned={r.pinned ? 'true' : undefined}
              className={`wl-row num ${selected === r.code ? 'selected' : ''} ${suspended ? 'suspended' : ''}`}
              onClick={() => onSelect(r.code)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  onSelect(r.code)
                }
              }}
            >
              <span className="wl-name">
                <span className="wl-code">{r.name || q?.name || r.code}</span>
                <span className="wl-sub">{r.code}</span>
              </span>
              <span className={`wl-last ${flash ? `flash-${flash}` : ''}`}>
                <span className={cls}>{fmtPrice(suspended ? null : q?.last)}</span>
              </span>
              <span className={cls}>{fmtPct(pct)}</span>
              {r.pinned && (
                <button
                  type="button"
                  className="wl-del"
                  aria-label={`删除 ${r.code}`}
                  title="移出自选"
                  onClick={(e) => {
                    e.stopPropagation()
                    void remove(r.code)
                  }}
                >
                  ×
                </button>
              )}
            </div>
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
