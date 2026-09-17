import { EquityCurve } from '../charts/EquityCurve'
import { fmtPct } from '../../lib/format'
import type { TraderDetail } from '../../api/types'

/**
 * 收益分析 Tab（01 §4.9）：统计卡 + 净值曲线（真实 equity_snapshots，
 * v1 布朗桥示意废止）；快照 <2 个交易日指标 `--` 并提示"数据积累中"。
 */
export function AnalyticsTab({ detail }: { detail: TraderDetail }) {
  const m = detail.metrics
  const insufficient = m.insufficient

  const cards: Array<[string, string]> = [
    ['总收益率', insufficient ? '--' : fmtPct(m.totalReturn)],
    ['年化', insufficient ? '--' : fmtPct(m.annualized)],
    ['最大回撤', insufficient ? '--' : fmtPct(m.maxDrawdown)],
    ['夏普', insufficient ? '--' : (m.sharpe ?? 0).toFixed(2)],
    ['胜率', insufficient ? '--' : fmtPct(m.winRate)],
    ['超额(vs 沪深300)', insufficient ? '--' : fmtPct(m.excess)],
  ]

  return (
    <div className="analytics-tab" data-testid="analytics-tab">
      <div className="stats-grid num">
        {cards.map(([label, value]) => (
          <div key={label} className="stat-card">
            <span className="micro-label">{label}</span>
            <span className={value.startsWith('+') ? 'up' : value.startsWith('-') ? 'down' : 'flat'}>
              {value}
            </span>
          </div>
        ))}
      </div>
      {insufficient ? (
        <div className="detail-plans-placeholder">
          <span className="flat">净值数据积累中（每日收盘快照，≥2 个交易日后展示曲线）</span>
        </div>
      ) : (
        <EquityCurve account={detail.equitySeries.map((p) => ({ date: p.date, value: p.total_equity }))} />
      )}
    </div>
  )
}
