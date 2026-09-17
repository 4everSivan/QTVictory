import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Quote } from '../../api/types'
import { OrderBook } from './OrderBook'

function q(bids: Array<[number, number]>, asks: Array<[number, number]>, prevClose = 10): Quote {
  return {
    code: '600519',
    name: 'M',
    last: 10,
    prevClose,
    open: 10,
    high: 10.5,
    low: 9.8,
    volume: 0,
    bids,
    asks,
  }
}

describe('盘口五档 + 逐笔（01 §4.6）', () => {
  it('卖5→卖1 降序、中价带、买1→买5 升序', () => {
    render(
      <OrderBook
        quote={q([[9.96, 100], [9.95, 200]], [[10.04, 50], [10.05, 60]])}
        quality="live"
      />,
    )
    const book = screen.getByTestId('orderbook')
    const tags = [...book.querySelectorAll('.ob-tag')].map((el) => el.textContent)
    expect(tags).toEqual(['卖5', '卖4', '卖3', '卖2', '卖1', '买1', '买2', '买3', '买4', '买5'])
    const prices = [...book.querySelectorAll('.ob-row span:nth-child(2)')].map((el) => el.textContent)
    expect(prices[4]).toBe('10.04') // 卖1
    expect(prices[5]).toBe('9.96') // 买1
    expect(screen.getByText('10.00')).toBeInTheDocument() // 中价
  })

  it('缺档显示占位，不渲染 NaN', () => {
    render(<OrderBook quote={q([[9.96, 100]], [])} quality="live" />)
    expect(screen.getAllByText('--').length).toBeGreaterThan(0)
  })

  it('行情降级显示 DEGRADED 状态条', () => {
    render(<OrderBook quote={q([], [])} quality="fallback" />)
    expect(screen.getByText('DEGRADED')).toBeInTheDocument()
    expect(screen.getByText(/行情降级/)).toBeInTheDocument()
  })

  it('实时质量不显示降级条', () => {
    render(<OrderBook quote={q([], [])} quality="live" />)
    expect(screen.queryByText('DEGRADED')).toBeNull()
  })
})
