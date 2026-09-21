import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import { setCache } from '../../state/marketData'
import { ChartArea } from './ChartArea'

const quote = {
  code: '600519', name: '测试标的', last: 10, prevClose: 9.5, change: 0.5,
  changePct: 5, open: 9.8, high: 10.2, low: 9.7, volume: 1000,
  bids: [], asks: [], source: 'tencent', live: true,
}

describe('ChartArea 周期 Tab（01 §5.5 D1，T27-1）', () => {
  beforeEach(() => {
    setCache('minute:600519', [])
    setCache('kline:600519:day', [])
  })

  it('四枚 Tab：分时｜日K｜周K｜月K', () => {
    render(<ChartArea code="600519" quote={quote} />)
    for (const label of ['分时', '日K', '周K', '月K']) {
      expect(screen.getByRole('tab', { name: label })).toBeInTheDocument()
    }
  })

  it('C021①：叠加胶丸归位顶栏 ca-bar（第二胶丸组，不再浮于主图）', () => {
    render(<ChartArea code="600519" quote={quote} />)
    const bar = document.querySelector('.ca-bar')
    for (const name of ['MA', 'EMA', 'BOLL']) {
      expect(bar?.querySelector(`[aria-label="${name}"]`)).toBeTruthy()
    }
    expect(document.querySelector('[data-testid="kline-chart"] [aria-label="MA"]')).toBeNull()
  })

  it('C021②：副图胶丸沉底 ca-foot，与顶栏上下对称', () => {
    render(<ChartArea code="600519" quote={quote} />)
    const foot = document.querySelector('.ca-foot')
    for (const name of ['VOL', 'MACD', 'RSI', 'KDJ']) {
      expect(foot?.querySelector(`[aria-label="${name}"]`)).toBeTruthy()
    }
    expect(document.querySelector('[data-testid="kline-chart"] [aria-label="VOL"]')).toBeNull()
  })

  it('点周K：缺缓存时按 period=week 拉取并渲染 K 线', async () => {
    const spy = vi.spyOn(api, 'get').mockResolvedValue({
      code: '600519', period: 'week', data: [],
    })
    try {
      render(<ChartArea code="600519" quote={quote} />)
      fireEvent.click(screen.getByRole('tab', { name: '周K' }))
      await waitFor(() => {
        expect(spy).toHaveBeenCalledWith('/market/kline?code=600519&period=week')
      })
    } finally {
      spy.mockRestore()
    }
  })

  it('点月K：按 period=month 拉取', async () => {
    const spy = vi.spyOn(api, 'get').mockResolvedValue({
      code: '600519', period: 'month', data: [],
    })
    try {
      render(<ChartArea code="600519" quote={quote} />)
      fireEvent.click(screen.getByRole('tab', { name: '月K' }))
      await waitFor(() => {
        expect(spy).toHaveBeenCalledWith('/market/kline?code=600519&period=month')
      })
    } finally {
      spy.mockRestore()
    }
  })

  it('已缓存周期不重复拉取', async () => {
    const spy = vi.spyOn(api, 'get').mockResolvedValue({
      code: '600519', period: 'week', data: [],
    })
    try {
      setCache('kline:600519:week', [])
      render(<ChartArea code="600519" quote={quote} />)
      fireEvent.click(screen.getByRole('tab', { name: '周K' }))
      await waitFor(() => {
        expect(screen.getByTestId('kline-chart')).toBeInTheDocument()
      })
      expect(spy).not.toHaveBeenCalled()
    } finally {
      spy.mockRestore()
    }
  })
})
