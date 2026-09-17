import type { Quote, QuotesEnvelope, SessionState } from '../../api/types'
import { FiveMetricBand, TraderSwitcher } from '../traders/TraderSwitcher'
import { fmtPrice, fmtPct, pctChange, trendClass } from '../../lib/format'

export interface TopbarStatusProps {
  session: SessionState | null
  envelope: QuotesEnvelope | null
}

const SESSION_TEXT: Record<SessionState['state'], string> = {
  trading: '交易中',
  closed: '已收盘',
  auction: '集合竞价',
  degraded: '已降级',
}

export function sessionCapsuleClass(state: SessionState['state'] | null): string {
  switch (state) {
    case 'trading':
      return 'up'
    case 'auction':
      return 'warn'
    case 'degraded':
      return 'warn'
    default:
      return 'flat'
  }
}

/**
 * 顶栏（01 §4.1 左段，T17-5）：品牌区 + 市场状态胶囊 + 沪深300 指数单元。
 * 交易员切换器与五指标带由 T19-1 装配。
 */
export function Topbar({ session, envelope }: TopbarStatusProps) {
  const indexQuote: Quote | undefined = envelope?.quotes.find((q) => q.code === 'sh000300')
  const indexPct = indexQuote ? pctChange(indexQuote.last, indexQuote.prevClose) : null
  const state = session?.state ?? null

  return (
    <div className="topbar-inner">
      <div className="tb-brand">
        <span className="tb-logo" aria-hidden />
        <span className="tb-title">模拟盘</span>
        <span className="tb-pill micro-label">PAPER</span>
      </div>
      <span className={`tb-session num ${sessionCapsuleClass(state)}`} data-testid="session-capsule">
        {state ? SESSION_TEXT[state] : '--'}
      </span>
      {indexQuote && (
        <span className="tb-index num">
          <span className="micro-label">沪深300</span>
          <span className={trendClass(indexPct)}>{fmtPrice(indexQuote.last)}</span>
          <span className={trendClass(indexPct)}>{fmtPct(indexPct)}</span>
        </span>
      )}
      <TraderSwitcher />
      <FiveMetricBand />
      <span className="tb-clock num micro-label">
        {envelope?.ts?.slice(11, 19) ?? '--:--:--'}
      </span>
    </div>
  )
}
