import { useEffect, useSyncExternalStore } from 'react'
import { api } from '../api/client'
import type { KlineRow, MinuteRow, Quote } from '../api/types'
import { lsGet, lsSet } from '../lib/storage'

/**
 * 行情数据缓存（01 §9 服务端状态缓存）：kline/minute 预取与逐笔派生。
 * 逐笔：后端未单设逐笔端点，以相邻 quotes 包络的累计量差派生
 * （降级时 ΔV=0 不产生记录——见 T17 变更记录）。
 */

/** K 线周期（T27-1，01 §5.5 D1）：分时走 minute 端点，其余走 /market/kline period */
export type KlinePeriod = 'day' | 'week' | 'month'

const PERIOD_STORAGE_KEY = 'qtv_kline_period'

function isKlinePeriod(v: string | null): v is KlinePeriod {
  return v === 'day' || v === 'week' || v === 'month'
}

/** 选中周期持久化（01 §5.5：ChartArea 周期 Tab 经 lib/storage 持久化） */
export function loadKlinePeriod(): KlinePeriod {
  const stored = lsGet(PERIOD_STORAGE_KEY)
  return isKlinePeriod(stored) ? stored : 'day'
}

export function saveKlinePeriod(period: KlinePeriod): void {
  lsSet(PERIOD_STORAGE_KEY, period)
}

const cache = new Map<string, unknown>()
const listeners = new Set<() => void>()

function emit(): void {
  for (const l of listeners) l()
}

export function setCache<T>(key: string, value: T): void {
  cache.set(key, value)
  emit()
}

export function getCache<T>(key: string): T | undefined {
  return cache.get(key) as T | undefined
}

export function useCache<T>(key: string | null): T | undefined {
  const subscribe = (onStoreChange: () => void) => {
    listeners.add(onStoreChange)
    return () => listeners.delete(onStoreChange)
  }
  return useSyncExternalStore(subscribe, () =>
    key === null ? undefined : (cache.get(key) as T | undefined),
  )
}

/** kline 缓存键按周期分键（T27-1）：kline:{code}:{period}，day 为默认兼容态 */
export function klineKey(code: string, period: KlinePeriod = 'day'): string {
  return `kline:${code}:${period}`
}

/** 拉取指定周期 K 线入缓存（缺键时； ChartArea 周期切换与预取共用） */
export function fetchKlinePeriod(code: string, period: KlinePeriod): void {
  const key = klineKey(code, period)
  if (cache.has(key)) return
  api
    .get<{ code: string; period: string; data: KlineRow[] }>(
      `/market/kline?code=${code}&period=${period}`,
    )
    .then((r) => setCache(key, r.data))
    .catch(() => setCache(key, [] as KlineRow[]))
}

export function minuteKey(code: string): string {
  return `minute:${code}`
}

/** 选中标的切换时预取日K与分时（T17-4），供图表区（T18）直读 */
export function useMarketSelection(code: string | null): void {
  useEffect(() => {
    if (code === null) return
    const k = klineKey(code)
    const m = minuteKey(code)
    if (!cache.has(k)) {
      api
        .get<{ code: string; period: string; data: KlineRow[] }>(`/market/kline?code=${code}&period=day`)
        .then((r) => setCache(k, r.data))
        .catch(() => setCache(k, [] as KlineRow[]))
    }
    if (!cache.has(m)) {
      api
        .get<{ code: string; date: string; data: MinuteRow[] }>(`/market/minute?code=${code}`)
        .then((r) => setCache(m, r.data))
        .catch(() => setCache(m, [] as MinuteRow[]))
    }
  }, [code])
}

/* ---- 逐笔派生 -------------------------------------------------------- */

export interface TickRecord {
  ts: string
  price: number
  volume: number
}

const tickCache = new Map<string, TickRecord[]>()
const lastCum = new Map<string, number>()
const tickListeners = new Set<() => void>()
const NO_TICKS: TickRecord[] = []

function tickEmit(): void {
  for (const l of tickListeners) l()
}

/** C018：已预取分时的码随 quotes 包络滚动刷新（每自然分钟至多一次），
 *  修复"选中即永久缓存、盘中须手动 reload"缺陷。 */
const minuteRefetchStamp = new Map<string, string>()

function maybeRefetchMinute(code: string, ts: string): void {
  const key = minuteKey(code)
  if (!cache.has(key)) return // 未预取的码不主动拉
  const stamp = ts.slice(0, 16) // YYYY-MM-DDTHH:MM
  if (stamp.length < 16 || minuteRefetchStamp.get(code) === stamp) return
  minuteRefetchStamp.set(code, stamp)
  api
    .get<{ code: string; date: string; data: MinuteRow[] }>(`/market/minute?code=${code}`)
    .then((r) => setCache(key, r.data))
    .catch(() => undefined) // 刷新失败沿用旧缓存，下一分钟再试
}

export function ingestQuotesEnvelope(quotes: Quote[], ts: string): void {
  let changed = false
  for (const q of quotes) {
    if (q.last <= 0) continue
    maybeRefetchMinute(q.code, ts)
    const prev = lastCum.get(q.code)
    lastCum.set(q.code, q.volume)
    if (prev === undefined || q.volume <= prev) continue
    const rec: TickRecord = { ts, price: q.last, volume: q.volume - prev }
    const list = tickCache.get(q.code) ?? []
    list.push(rec)
    if (list.length > 200) list.splice(0, list.length - 200)
    tickCache.set(q.code, list)
    changed = true
  }
  if (changed) tickEmit()
}

export function useTicks(code: string | null): TickRecord[] {
  const subscribe = (onStoreChange: () => void) => {
    tickListeners.add(onStoreChange)
    return () => tickListeners.delete(onStoreChange)
  }
  return useSyncExternalStore(subscribe, () =>
    code === null ? NO_TICKS : (tickCache.get(code) ?? NO_TICKS),
  )
}
