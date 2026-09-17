import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { state } from '../../test/mockTraders'
import type { OrderRow, TradeRow } from '../../api/types'

vi.mock('../../state/traders', () => import('../../test/mockTraders'))

import { Dock, orderShortId } from './Dock'

const orders: OrderRow[] = [
  {
    id: 0x7a1f, trader_id: 1, origin: 'operator', plan_entry_id: null, client_order_id: null,
    side: 'buy', type: 'limit', market_type: null, code: '600519', price: 1285.5, qty: 100,
    filled_qty: 60, avg_filled_price: 1285.5, frozen_amount: 128800, fill_model: 'real',
    status: 'partial', created_at: '2026-09-17T10:00:00', trading_date: '2026-09-17', filled_at: null,
  },
  {
    id: 0x7a20, trader_id: 1, origin: 'operator', plan_entry_id: null, client_order_id: null,
    side: 'sell', type: 'market', market_type: 'best5_cancel', code: '000001', price: null, qty: 200,
    filled_qty: 200, avg_filled_price: 10.5, frozen_amount: null, fill_model: 'fallback',
    status: 'filled', created_at: '2026-09-17T10:01:00', trading_date: '2026-09-17', filled_at: '2026-09-17T10:01:05',
  },
]

const trades: TradeRow[] = [
  {
    id: 1, order_id: 0x7a1f, trader_id: 1, code: '600519', side: 'buy', price: 1285.5, qty: 40,
    amount: 51420, commission: 12.86, stamp_tax: 0, transfer_fee: 5.14, realized_pnl: null,
    origin: 'operator', ts: '2026-09-17T10:00:05', trading_date: '2026-09-17',
  },
  {
    id: 2, order_id: 0x7a1f, trader_id: 1, code: '600519', side: 'buy', price: 1285.5, qty: 20,
    amount: 25710, commission: 6.43, stamp_tax: 0, transfer_fee: 2.57, realized_pnl: null,
    origin: 'operator', ts: '2026-09-17T10:00:08', trading_date: '2026-09-17',
  },
]

function stub(feeds: Record<string, unknown>) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const body = Object.entries(feeds).find(([k]) => url.includes(k))?.[1] ?? { data: [] }
      return Promise.resolve({ ok: true, status: 200, text: async () => JSON.stringify(body) } as Response)
    }),
  )
}

describe('底部 Dock（01 §4.8）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.unstubAllGlobals()
    state.currentId = 1
    state.current = state.list[0]
    state.account = null
    stub({ '/traders/1/orders': { data: orders, nextCursor: null }, '/traders/1/trades': { data: trades, nextCursor: null } })
  })

  it('委托表：partial 列与 PARTIAL 胶囊', async () => {
    render(<Dock session={{ state: 'trading', phase: 'continuous', tradingDate: '2026-09-17' }} clock="10:05" />)
    fireEvent.click(await screen.findByRole('tab', { name: '当日委托' }))
    expect(screen.getByTestId('dock-orders')).toBeInTheDocument()
    expect(screen.getByText('60/100')).toBeInTheDocument()
    expect(screen.getByText('PARTIAL 60/100')).toBeInTheDocument()
    expect(screen.getByText('市价·最优五档')).toBeInTheDocument()
  })

  it('撤单按钮：连续竞价可用，集合竞价 9:20–9:25 禁用', async () => {
    const { rerender } = render(
      <Dock session={{ state: 'trading', phase: 'continuous', tradingDate: '2026-09-17' }} clock="10:05" />,
    )
    fireEvent.click(await screen.findByRole('tab', { name: '当日委托' }))
    expect(screen.getAllByText('撤单')[0].closest('button')).toBeEnabled()

    rerender(<Dock session={{ state: 'trading', phase: 'auction', tradingDate: '2026-09-17' }} clock="09:21" />)
    fireEvent.click(screen.getByRole('tab', { name: '当日委托' }))
    expect(screen.getAllByText('撤单')[0].closest('button')).toBeDisabled()
  })

  it('成交表：ORD 微标签分组（#7A1F · 限价买入 ×100 · PARTIAL 60/100）', async () => {
    render(<Dock session={{ state: 'trading', phase: 'continuous', tradingDate: '2026-09-17' }} clock="10:05" />)
    fireEvent.click(await screen.findByRole('tab', { name: '成交记录' }))
    expect(screen.getByTestId('dock-trades')).toBeInTheDocument()
    expect(screen.getByText(/ORD #7A1F · 限价买入 1285\.50 ×100 · PARTIAL 60\/100/)).toBeInTheDocument()
  })

  it('跟随当前交易员指示器', () => {
    render(<Dock session={null} clock="" />)
    expect(screen.getByTestId('dock-follow').textContent).toContain('跟随 当前交易员 · Alpha')
  })

  it('orderShortId 十六进制微标签', () => {
    expect(orderShortId(0x7a1f)).toBe('7A1F')
    expect(orderShortId(7)).toBe('0007')
  })
})
