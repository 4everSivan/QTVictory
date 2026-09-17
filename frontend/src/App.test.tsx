import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

const fetchMock = vi.fn((url: string) => {
  if (url.includes('/session')) {
    return Promise.resolve({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ state: 'degraded', phase: 'continuous', tradingDate: '2026-09-17' }),
    } as Response)
  }
  return Promise.resolve({
    ok: true,
    status: 200,
    text: async () =>
      JSON.stringify({
        source: 'anchor',
        live: false,
        ts: '2026-09-17T09:31:00',
        quotes: [
          { code: 'sh000300', name: '沪深300', last: 4479.85, prevClose: 4400, open: 4400, high: 4480, low: 4390, volume: 0, bids: [], asks: [] },
        ],
      }),
  } as Response)
})

class DeadWebSocket {
  static readonly OPEN = 1
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(_url: string) {
    setTimeout(() => this.onerror?.(), 0)
  }
  send(): void {}
  close(): void {
    this.onclose?.()
  }
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('WebSocket', DeadWebSocket)
})

afterEach(() => {
  fetchMock.mockClear()
  vi.unstubAllGlobals()
})

describe('App 栅格外壳（01 §2.2 一屏五区）', () => {
  it('渲染行情/盘口/个股头/图表区与未完成占位区，主题按钮存在', async () => {
    render(<App />)
    expect(screen.getByTestId('watchlist')).toBeInTheDocument()
    expect(screen.getByTestId('quote-header')).toBeInTheDocument()
    expect(screen.getByTestId('orderbook')).toBeInTheDocument()
    expect(screen.getByTestId('chart-area')).toBeInTheDocument()
    expect(await screen.findByText('已降级')).toBeInTheDocument()
    expect(screen.getByTestId('trader-board')).toBeInTheDocument()
    expect(screen.getByTestId('order-panel')).toBeInTheDocument()
    expect(screen.getByTestId('dock')).toBeInTheDocument()
  })

  it('栅格容器挂载 .app 类', () => {
    const { container } = render(<App />)
    expect(container.querySelector('.app')).toBeTruthy()
    expect(container.querySelector('.topbar')).toBeTruthy()
    expect(container.querySelector('.leftcol')).toBeTruthy()
    expect(container.querySelector('.dock')).toBeTruthy()
  })

  it('主题切换按钮存在（NOTHING/TERMINAL）', () => {
    render(<App />)
    expect(screen.getByRole('button', { name: /NOTHING|TERMINAL/ })).toBeInTheDocument()
  })
})
