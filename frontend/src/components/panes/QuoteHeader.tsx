import type { Quote } from '../../api/types'
import { fmtPct, fmtPrice, fmtSigned, fmtVol, pctChange, trendClass } from '../../lib/format'

interface QuoteHeaderProps {
  quote: Quote | null
}

/** 个股头部（01 §4.4）：Doto 36px+ 现价 + 8 项指标 chips，v1 定稿版式 */
export function QuoteHeader({ quote }: QuoteHeaderProps) {
  if (!quote) {
    return (
      <div className="qheader empty" data-testid="quote-header">
        <span className="micro-label">个股 · QUOTE</span>
      </div>
    )
  }
  const pct = pctChange(quote.last, quote.prevClose)
  const cls = trendClass(pct)
  const amplitude = quote.prevClose
    ? (quote.high - quote.low) / quote.prevClose
    : null
  const change = quote.last > 0 && quote.prevClose ? quote.last - quote.prevClose : null

  const chips: Array<[string, string]> = [
    ['涨跌额', fmtSigned(change)],
    ['涨幅', fmtPct(pct)],
    ['开盘', fmtPrice(quote.open)],
    ['最高', fmtPrice(quote.high)],
    ['最低', fmtPrice(quote.low)],
    ['昨收', fmtPrice(quote.prevClose)],
    ['振幅', fmtPct(amplitude)],
    ['量(手)', fmtVol(quote.volume)],
  ]

  return (
    <div className="qheader" data-testid="quote-header">
      <div className="qh-title">
        <span className="qh-name">{quote.name || quote.code}</span>
        <span className="qh-code num">{quote.code}</span>
        {quote.last <= 0 && <span className="qh-suspended">停牌</span>}
      </div>
      <div className={`qh-price price num ${cls}`}>
        {fmtPrice(quote.last <= 0 ? null : quote.last)}
      </div>
      <div className="qh-chips num">
        {chips.map(([label, value]) => {
          const valueCls = label === '涨跌额' || label === '涨幅' ? cls : 'flat'
          return (
            <span key={label} className="qh-chip">
              <span className="micro-label">{label}</span>
              <span className={valueCls}>{value}</span>
            </span>
          )
        })}
      </div>
    </div>
  )
}
