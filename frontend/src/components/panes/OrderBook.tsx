import type { BookLevel, Quote, QuoteQuality } from '../../api/types'
import { useTicks } from '../../state/marketData'
import { fmtPrice, trendClass } from '../../lib/format'

interface OrderBookProps {
  quote: Quote | null
  quality: QuoteQuality
}

function levelOrEmpty(levels: BookLevel[], i: number): BookLevel | null {
  return i < levels.length ? levels[i] : null
}

/**
 * 盘口五档 + 逐笔（01 §4.6）：卖5→买1 降序 + 中价带 + 逐笔滚动。
 * 数据为后端真实快照；行情降级（fallback）时显示 DEGRADED 状态条。
 */
export function OrderBook({ quote, quality }: OrderBookProps) {
  const ticks = useTicks(quote?.code ?? null)

  const bids = quote?.bids ?? []
  const asks = quote?.asks ?? []
  const ask1 = levelOrEmpty(asks, 0)
  const bid1 = levelOrEmpty(bids, 0)
  const mid = ask1 && bid1 ? (ask1[0] + bid1[0]) / 2 : null
  const ref = quote && quote.prevClose > 0 ? quote.prevClose : null

  const renderLevel = (level: BookLevel | null, label: string, side: 'sell' | 'buy') => (
    <div key={label} className={`ob-row num ${level ? '' : 'ob-empty'}`}>
      <span className={`ob-tag ${side === 'sell' ? 'ob-sell' : 'ob-buy'}`}>{label}</span>
      <span className={level && ref ? trendClass(level[0] - ref) : 'flat'}>
        {level ? fmtPrice(level[0]) : '--'}
      </span>
      <span className="flat">{level ? level[1] : '--'}</span>
    </div>
  )

  return (
    <div className="orderbook" data-testid="orderbook">
      <div className="ob-head">
        <span className="micro-label">盘口五档 · BOOK</span>
        {quality === 'fallback' && <span className="degraded-badge">DEGRADED</span>}
      </div>
      {quality === 'fallback' && <div className="degraded-bar">行情降级 · 锚点数据，撮合按固定滑点档</div>}
      <div className="ob-book num">
        {[4, 3, 2, 1, 0].map((i) => renderLevel(levelOrEmpty(asks, i), `卖${i + 1}`, 'sell'))}
        <div className="ob-mid">
          <span className={mid && ref ? trendClass(mid - ref) : 'flat'}>
            {mid ? fmtPrice(mid) : '--'}
          </span>
          <span className="micro-label">中价</span>
        </div>
        {[0, 1, 2, 3, 4].map((i) => renderLevel(levelOrEmpty(bids, i), `买${i + 1}`, 'buy'))}
      </div>
      <div className="ob-ticks">
        <div className="micro-label ob-ticks-head">逐笔成交 · TICKS</div>
        <div className="ob-ticks-body num">
          {ticks.length === 0 && <div className="wl-empty">暂无逐笔（降级模式 ΔV=0）</div>}
          {[...ticks].reverse().map((t, i) => (
            <div key={`${t.ts}-${i}`} className="ob-tick-row">
              <span className="flat">{t.ts.slice(11, 19)}</span>
              <span className={ref ? trendClass(t.price - ref) : 'flat'}>{fmtPrice(t.price)}</span>
              <span className="flat">{t.volume}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
