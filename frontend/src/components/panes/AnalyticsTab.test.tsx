import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { TraderDetail } from '../../api/types'
import { AnalyticsTab } from './AnalyticsTab'

const detail: TraderDetail = {
  traderId: 1,
  name: 'Alpha',
  mode: 'manual',
  status: 'running',
  initCash: 1_000_000,
  cash: 800_000,
  frozenCash: 0,
  availableCash: 800_000,
  marketValue: 260_000,
  equity: 1_060_000,
  totalReturn: 0.06,
  positions: [],
  metrics: {
    insufficient: false,
    totalReturn: 0.06,
    annualized: 0.31,
    maxDrawdown: -0.03,
    maxDrawdownDays: 2,
    sharpe: 1.42,
    winRate: 0.6,
    excess: 0.02,
    days: 5,
  },
  orders: [],
  trades: [],
  equitySeries: [
    { trader_id: 1, date: '2026-09-10', total_equity: 1_000_000, cash: 800_000 },
    { trader_id: 1, date: '2026-09-11', total_equity: 1_030_000, cash: 810_000 },
    { trader_id: 1, date: '2026-09-12', total_equity: 1_060_000, cash: 800_000 },
  ],
  plans: [],
  strategyParams: null,
}

describe('收益分析 Tab（01 §4.9）', () => {
  it('统计卡 + 净值曲线（真实 equity 序列）', () => {
    render(<AnalyticsTab detail={detail} />)
    expect(screen.getByTestId('analytics-tab')).toBeInTheDocument()
    expect(screen.getByText('总收益率')).toBeInTheDocument()
    expect(screen.getByText('+6.00%')).toBeInTheDocument()
    expect(screen.getByText('夏普')).toBeInTheDocument()
    expect(screen.getByTestId('equity-curve')).toBeInTheDocument()
  })

  it('快照 <2 日：指标 -- 且提示数据积累中', () => {
    const short: TraderDetail = {
      ...detail,
      metrics: {
        insufficient: true,
        totalReturn: null,
        annualized: null,
        maxDrawdown: null,
        maxDrawdownDays: null,
        sharpe: null,
        winRate: null,
        excess: null,
        days: 1,
      },
      equitySeries: [{ trader_id: 1, date: '2026-09-12', total_equity: 1_000_000, cash: 1_000_000 }],
    }
    render(<AnalyticsTab detail={short} />)
    expect(screen.getAllByText('--').length).toBeGreaterThan(0)
    expect(screen.getByText(/净值数据积累中/)).toBeInTheDocument()
  })
})
