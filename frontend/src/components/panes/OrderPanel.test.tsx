import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { state, traderOps } from '../../test/mockTraders'

vi.mock('../../state/traders', () => import('../../test/mockTraders'))

import { OrderPanel } from './OrderPanel'
import type { Quote } from '../../api/types'

const quote: Quote = {
  code: '600519',
  name: 'M',
  last: 10,
  prevClose: 10,
  open: 10,
  high: 10,
  low: 10,
  volume: 0,
  bids: [[9.98, 300]],
  asks: [[10.02, 200]],
}

function setup(account: unknown = null) {
  state.currentId = 1
  state.current = state.list[0]
  state.account = account as never
  state.detail = null
  state.refresh = vi.fn()
  traderOps.create.mockClear()
}

describe('下单面板（01 §4.7）', () => {
  beforeEach(() => setup())

  it('未选中交易员禁用并提示', () => {
    state.currentId = null
    render(<OrderPanel quote={quote} />)
    expect(screen.getByText('未选中交易员')).toBeInTheDocument()
    expect(screen.getByTestId('order-panel').querySelector('.op-submit')).toBeDisabled()
  })

  it('数量校验：主板须 100 整数倍，违规显示文案且禁止提交', () => {
    render(<OrderPanel quote={quote} />)
    fireEvent.change(screen.getByPlaceholderText('100 的倍数'), { target: { value: '150' } })
    expect(screen.getByText(/100 股整数倍/)).toBeInTheDocument()
    expect(screen.getByTestId('order-panel').querySelector('.op-submit')).toBeDisabled()
  })

  it('价格双重区间校验：越界给两区间文案', () => {
    render(<OrderPanel quote={quote} />)
    fireEvent.change(screen.getByPlaceholderText('10.00'), { target: { value: '10.5' } })
    fireEvent.change(screen.getByPlaceholderText('100 的倍数'), { target: { value: '100' } })
    expect(screen.getByText(/±2%/)).toBeInTheDocument()
  })

  it('市价类型 seg 仅市价态出现', () => {
    render(<OrderPanel quote={quote} />)
    expect(screen.queryByText('最优五档剩余撤销')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '市价' }))
    expect(screen.getByText('最优五档剩余撤销')).toBeInTheDocument()
  })

  it('确认弹窗标注交易员身份 + 限价分批提示，确认后提交', async () => {
    const fetchMock = vi.fn((_url?: unknown, _init?: unknown) =>
      Promise.resolve({ ok: true, status: 201, text: async () => '{"id":9}' } as Response),
    )
    vi.stubGlobal('fetch', fetchMock)
    render(<OrderPanel quote={quote} />)
    fireEvent.change(screen.getByPlaceholderText('10.00'), { target: { value: '10.00' } })
    fireEvent.change(screen.getByPlaceholderText('100 的倍数'), { target: { value: '100' } })
    fireEvent.click(screen.getByTestId('order-panel').querySelector('.op-submit')!)
    expect(screen.getByText(/以 Alpha（交易员）身份下单/)).toBeInTheDocument()
    expect(screen.getByText(/可能分批部分成交/)).toBeInTheDocument()
    fireEvent.click(screen.getByText('确认'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const [url, init] = fetchMock.mock.calls[0] as [unknown, RequestInit]
    expect(String(url)).toContain('/api/traders/1/orders')
    expect(JSON.parse(init.body as string)).toMatchObject({
      code: '600519',
      side: 'buy',
      type: 'limit',
      price: 10,
      qty: 100,
    })
    vi.unstubAllGlobals()
  })

  it('卖出侧：可卖口径扣 T+1 锁定', () => {
    setup({
      traderId: 1, name: 'Alpha', mode: 'strategy', status: 'running', initCash: 1e6,
      cash: 0, frozenCash: 0, availableCash: 0, marketValue: 0, equity: 1e6, totalReturn: 0,
      positions: [{ code: '600519', qty: 500, avgCost: 9.5, todayBought: 200, price: 10, value: 5000, unrealizedPnl: 250 }],
    })
    render(<OrderPanel quote={quote} />)
    fireEvent.click(screen.getByRole('button', { name: '卖出' }))
    expect(screen.getByText(/全仓可卖 300/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /全仓可卖/ }))
    expect(screen.getByDisplayValue('300')).toBeInTheDocument()
    fireEvent.change(screen.getByDisplayValue('300'), { target: { value: '400' } })
    expect(screen.getByText(/超出可卖（持仓 500，T\+1 锁定 200）/)).toBeInTheDocument()
  })
})
