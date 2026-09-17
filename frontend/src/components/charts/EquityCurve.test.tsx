import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { EquityCurve, TradersCurve, type EquityPoint } from './EquityCurve'

const acc: EquityPoint[] = [
  { date: '2026-09-10', value: 1_000_000 },
  { date: '2026-09-11', value: 1_020_000 },
  { date: '2026-09-12', value: 990_000 },
]

describe('净值曲线（01 §5.3）', () => {
  it('双线渲染（账户 + 基准）', () => {
    render(<EquityCurve account={acc} benchmark={acc.map((p) => ({ date: p.date, value: 900_000 }))} />)
    expect(screen.getByTestId('equity-curve')).toBeInTheDocument()
    expect(screen.getByTestId('eq-account')).toBeInTheDocument()
    expect(screen.getByTestId('eq-benchmark')).toBeInTheDocument()
  })

  it('快照 <2 日空态（§4.9 口径）', () => {
    render(<EquityCurve account={[acc[0]]} />)
    expect(screen.getByText(/净值数据积累中/)).toBeInTheDocument()
  })

  it('多交易员对比组件渲染', () => {
    render(
      <TradersCurve
        series={[
          { name: 'A', points: acc },
          { name: 'B', points: acc.map((p) => ({ date: p.date, value: p.value * 1.01 })) },
        ]}
      />,
    )
    expect(screen.getByTestId('traders-curve')).toBeInTheDocument()
  })
})
