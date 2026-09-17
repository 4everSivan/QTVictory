import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Quote } from '../../api/types'
import { QuoteHeader } from './QuoteHeader'

const quote: Quote = {
  code: '600519',
  name: '贵州茅台',
  last: 1700.5,
  prevClose: 1680,
  open: 1685,
  high: 1712,
  low: 1678.2,
  volume: 1234567,
  bids: [],
  asks: [],
}

describe('个股头部（01 §4.4）', () => {
  it('Doto 现价 + 8 项 chips', () => {
    render(<QuoteHeader quote={quote} />)
    expect(screen.getByTestId('quote-header')).toBeInTheDocument()
    expect(screen.getByText('1700.50')).toBeInTheDocument()
    const chips = document.querySelectorAll('.qh-chip')
    expect(chips).toHaveLength(8)
    expect(screen.getByText('最高')).toBeInTheDocument()
    expect(screen.getByText('1712.00')).toBeInTheDocument()
    expect(screen.getByText('量(手)')).toBeInTheDocument()
    expect(screen.getByText('12345')).toBeInTheDocument()
  })

  it('涨跌语义色作用于数值本体', () => {
    render(<QuoteHeader quote={quote} />)
    const price = document.querySelector('.qh-price')
    expect(price?.classList.contains('up')).toBe(true)
  })

  it('无数据时空态', () => {
    render(<QuoteHeader quote={null} />)
    expect(screen.getByTestId('quote-header')).toBeInTheDocument()
  })
})
