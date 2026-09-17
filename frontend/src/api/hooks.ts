import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from './client'
import type { ServerFrame, Topic } from './types'
import { WSManager, wsManager } from './ws'

interface QueryState<T> {
  data: T | null
  error: ApiError | null
  loading: boolean
  reload: () => Promise<void>
}

/** REST 初始化/兜底拉取（01 §7.3：先 REST 全量，WS 增量） */
export function useQuery<T>(path: string | null): QueryState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(path !== null)

  const reload = useCallback(async () => {
    if (path === null) return
    try {
      setData(await api.get<T>(path))
      setError(null)
    } catch (e) {
      setError(e as ApiError)
    } finally {
      setLoading(false)
    }
  }, [path])

  useEffect(() => {
    setLoading(path !== null)
    void reload()
  }, [path, reload])

  return { data, error, loading, reload }
}

/** WS 订阅：多组件同 topic 共享单连接单订阅帧；组件卸载自动退订 */
export function useSubscription<T extends ServerFrame>(topic: Topic | null): T | null {
  const [frame, setFrame] = useState<T | null>(null)
  useEffect(() => {
    if (topic === null) return
    wsManager.connect()
    return wsManager.subscribe(topic, (frame) => setFrame(frame as T))
  }, [topic])
  return frame
}

/* ---- WS 不可用 → REST 轮询降级（01 §7.3：quotes 3s / traders 5s） ---- */

export interface Poller {
  key: string
  intervalMs: number
  run: () => void | Promise<void>
}

export class FallbackPoller {
  private readonly pollers = new Map<string, Poller>()
  private readonly timers = new Map<string, ReturnType<typeof setInterval>>()
  private offState: (() => void) | null = null
  private running = false

  constructor(private readonly ws: WSManager) {}

  register(poller: Poller): () => void {
    this.pollers.set(poller.key, poller)
    if (this.running) this.startTimer(poller)
    return () => {
      this.pollers.delete(poller.key)
      this.stopTimer(poller.key)
    }
  }

  start(): () => void {
    if (this.offState) return this.offState
    this.offState = this.ws.onState((state) => {
      if (state === 'open') {
        this.stopAll()
      } else if (state === 'reconnecting' || state === 'closed') {
        this.startAll()
      }
    })
    if (this.ws.state === 'reconnecting' || this.ws.state === 'closed') this.startAll()
    return this.offState
  }

  get active(): boolean {
    return this.running
  }

  private startAll(): void {
    if (this.running) return
    this.running = true
    for (const poller of this.pollers.values()) this.startTimer(poller)
  }

  private stopAll(): void {
    this.running = false
    for (const key of [...this.timers.keys()]) this.stopTimer(key)
  }

  private startTimer(poller: Poller): void {
    if (this.timers.has(poller.key)) return
    this.timers.set(
      poller.key,
      setInterval(() => void poller.run(), poller.intervalMs),
    )
  }

  private stopTimer(key: string): void {
    const timer = this.timers.get(key)
    if (timer) clearInterval(timer)
    this.timers.delete(key)
  }
}

export const fallbackPoller = new FallbackPoller(wsManager)

/** 注册降级轮询：wsManager 断开期间按 intervalMs 轮询，恢复自动停止 */
export function useFallbackPoll(key: string, intervalMs: number, run: () => void | Promise<void>): void {
  useEffect(() => {
    fallbackPoller.start()
    return fallbackPoller.register({ key, intervalMs, run })
  }, [key, intervalMs, run])
}
