import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FallbackPoller } from './hooks'
import { WSManager, type WSFactory } from './ws'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(public readonly url: string) {
    FakeWebSocket.instances.push(this)
  }
  send(): void {}
  close(): void {
    this.onclose?.()
  }
  open(): void {
    this.onopen?.()
  }
}

const factory: WSFactory = (url) => new FakeWebSocket(url) as unknown as WebSocket

function latest(): FakeWebSocket {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1]
}

beforeEach(() => {
  FakeWebSocket.instances = []
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('FallbackPoller（01 §7.3：WS 不可用 → REST 轮询降级）', () => {
  it('WS 断开期间启动轮询，恢复后停止', async () => {
    const ws = new WSManager('ws://x/ws', factory)
    const poller = new FallbackPoller(ws)
    const runs = { quotes: 0, traders: 0 }
    poller.register({ key: 'quotes', intervalMs: 3000, run: () => void runs.quotes++ })
    poller.register({ key: 'traders', intervalMs: 5000, run: () => void runs.traders++ })
    poller.start()

    ws.connect()
    latest().open()
    expect(poller.active).toBe(false)

    latest().onclose?.()
    expect(poller.active).toBe(true)

    await vi.advanceTimersByTimeAsync(15000)
    expect(runs.quotes).toBe(5) // 3s × 5
    expect(runs.traders).toBe(3) // 5s × 3

    vi.advanceTimersByTime(1000)
    latest().open()
    expect(poller.active).toBe(false)

    await vi.advanceTimersByTimeAsync(10000)
    expect(runs.quotes).toBe(5)
    expect(runs.traders).toBe(3)
    ws.close()
  })

  it('运行中注册新轮询器立即启动其定时器', () => {
    const ws = new WSManager('ws://x/ws', factory)
    const poller = new FallbackPoller(ws)
    poller.start()
    ws.connect()
    latest().onclose?.()
    let n = 0
    const off = poller.register({ key: 'late', intervalMs: 1000, run: () => void n++ })
    vi.advanceTimersByTime(3000)
    expect(n).toBe(3)
    off()
    vi.advanceTimersByTime(3000)
    expect(n).toBe(3)
    ws.close()
  })

  it('注册注销幂等：注销后不再运行', () => {
    const ws = new WSManager('ws://x/ws', factory)
    const poller = new FallbackPoller(ws)
    poller.start()
    let n = 0
    const off = poller.register({ key: 'k', intervalMs: 1000, run: () => void n++ })
    ws.connect()
    latest().onclose?.()
    vi.advanceTimersByTime(2000)
    off()
    vi.advanceTimersByTime(5000)
    expect(n).toBe(2)
    ws.close()
  })
})
