import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import type { Quote } from '../api/types'
import {
  getCache,
  ingestQuotesEnvelope,
  klineKey,
  minuteKey,
  setCache,
  useCache,
  useTicks,
} from './marketData'

function q(code: string, last: number, volume: number): Quote {
  return { code, name: code, last, prevClose: last, open: last, high: last, low: last, volume, bids: [], asks: [] }
}

describe('行情缓存与逐笔派生（T17-4）', () => {
  beforeEach(() => {
    ingestQuotesEnvelope([], '') // 触发一次无操作刷新（保持接口预热）
  })

  it('setCache/getCache/useCache 读写一致', () => {
    act(() => setCache(klineKey('600519'), [{ code: '600519' }]))
    expect(getCache(klineKey('600519'))).toEqual([{ code: '600519' }])
    const { result } = renderHook(() => useCache(klineKey('600519')))
    expect(result.current).toEqual([{ code: '600519' }])
    act(() => setCache(klineKey('600519'), []))
    expect(result.current).toEqual([])
  })

  it('相邻包络累计量差派生逐笔，倒挂/重复不派生', () => {
    ingestQuotesEnvelope([q('600519', 10, 1000)], '2026-09-17T09:31:00')
    ingestQuotesEnvelope([q('600519', 10.1, 1500)], '2026-09-17T09:31:03')
    ingestQuotesEnvelope([q('600519', 10.1, 1500)], '2026-09-17T09:31:06')
    ingestQuotesEnvelope([q('600519', 10.2, 1200)], '2026-09-17T09:31:09')
    const { result } = renderHook(() => useTicks('600519'))
    expect(result.current).toHaveLength(1)
    expect(result.current?.[0]).toEqual({ ts: '2026-09-17T09:31:03', price: 10.1, volume: 500 })
  })

  it('useTicks 空 code 返回空数组', () => {
    const { result } = renderHook(() => useTicks(null))
    expect(result.current).toEqual([])
  })

  it('act 内 ingest 触发订阅者刷新', () => {
    const { result } = renderHook(() => useTicks('000001'))
    act(() => {
      ingestQuotesEnvelope([q('000001', 10, 500)], '2026-09-17T09:31:00')
      ingestQuotesEnvelope([q('000001', 10, 700)], '2026-09-17T09:31:03')
    })
    expect(result.current).toHaveLength(1)
    expect(result.current?.[0].volume).toBe(200)
  })

  it('C018：分时缓存随包络分钟戳滚动刷新（同分钟不重复拉取）', async () => {
    const spy = vi.spyOn(api, 'get').mockResolvedValue({
      code: '600519', date: '2026-09-17',
      data: [{ code: '600519', date: '2026-09-17', minute: '09:31', price: 10, volume: 1000 }],
    })
    try {
      act(() => setCache(minuteKey('600519'), [])) // 模拟已预取
      act(() => ingestQuotesEnvelope([q('600519', 10, 1000)], '2026-09-17T09:31:00'))
      act(() => ingestQuotesEnvelope([q('600519', 10, 1000)], '2026-09-17T09:31:30'))
      act(() => ingestQuotesEnvelope([q('600519', 10, 1000)], '2026-09-17T09:32:00'))
      await vi.waitFor(() => {
        expect(getCache(minuteKey('600519'))).toHaveLength(1)
      })
      // 09:31 同分钟两次只拉一回 + 09:32 一回 = 2 次
      expect(spy).toHaveBeenCalledTimes(2)
      expect(spy).toHaveBeenCalledWith('/market/minute?code=600519')
    } finally {
      spy.mockRestore()
    }
  })

  it('C018：未预取分时的码不主动拉取', () => {
    const spy = vi.spyOn(api, 'get')
    try {
      act(() => ingestQuotesEnvelope([q('000002', 10, 500)], '2026-09-17T09:31:00'))
      expect(spy).not.toHaveBeenCalled()
    } finally {
      spy.mockRestore()
    }
  })
})
