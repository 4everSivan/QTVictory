import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { MinuteRow } from '../../api/types'
import { MinuteChart } from './MinuteChart'

function minute(min: string, price: number, volume: number): MinuteRow {
  return { code: '600519', date: '2026-09-17', minute: min, price, volume }
}

describe('分时组件（01 §5.2）', () => {
  it('无数据/无昨收时空态', () => {
    render(<MinuteChart minutes={[]} prevClose={0} />)
    expect(screen.getByTestId('minute-chart')).toBeInTheDocument()
    expect(screen.getByText(/分时数据积累中/)).toBeInTheDocument()
  })

  it('有数据渲染价格线与时间轴', () => {
    render(
      <MinuteChart
        minutes={[minute('09:31', 10.5, 1000), minute('09:32', 10.6, 1300), minute('09:33', 10.4, 1500)]}
        prevClose={10}
      />,
    )
    const svg = document.querySelector('.chart-svg')
    expect(svg).toBeTruthy()
    expect(screen.getByText('09:30')).toBeInTheDocument()
    expect(screen.getByText('15:00')).toBeInTheDocument()
  })
})
