import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ServerFrame } from './types'
import { WSManager, type FrameHandler, type WSFactory } from './ws'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  readonly sent: string[] = []
  closed = false

  constructor(public readonly url: string) {
    FakeWebSocket.instances.push(this)
  }

  send(data: string): void {
    this.sent.push(data)
  }

  close(): void {
    this.closed = true
    this.onclose?.()
  }

  open(): void {
    this.onopen?.()
  }

  emit(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) })
  }

  emitRaw(raw: string): void {
    this.onmessage?.({ data: raw })
  }

  serverClose(): void {
    this.closed = true
    this.onclose?.()
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

describe('WS 订阅管理（02 §5.3 / 01 §7.3）', () => {
  it('connect 建立连接，订阅发送 sub 帧', () => {
    const m = new WSManager('ws://x/ws', factory)
    m.connect()
    latest().open()
    m.subscribe('quotes', () => {})
    expect(JSON.parse(latest().sent[0])).toEqual({ op: 'sub', topics: ['quotes'] })
    expect(m.state).toBe('open')
    m.close()
  })

  it('同 topic 多 handler 只发一次订阅帧，退订最后一个才发 unsub', () => {
    const m = new WSManager('ws://x/ws', factory)
    m.connect()
    latest().open()
    const off1 = m.subscribe('traders', () => {})
    const off2 = m.subscribe('traders', () => {})
    expect(latest().sent.filter((s) => s.includes('"traders"'))).toHaveLength(1)
    off1()
    expect(latest().sent.filter((s) => s.includes('unsub'))).toHaveLength(0)
    off2()
    const unsub = latest().sent.map((s) => JSON.parse(s)).find((x) => x.op === 'unsub')
    expect(unsub).toEqual({ op: 'unsub', topics: ['traders'] })
    m.close()
  })

  it('trader:{id} 按 id 订阅', () => {
    const m = new WSManager('ws://x/ws', factory)
    m.connect()
    latest().open()
    m.subscribe('trader:7', () => {})
    expect(JSON.parse(latest().sent[0])).toEqual({ op: 'sub', topics: ['trader:7'] })
    m.close()
  })

  it('推送帧按 topic 分发；ack 控制帧走 onControl 通道', () => {
    const m = new WSManager('ws://x/ws', factory)
    m.connect()
    const ws = latest()
    ws.open()
    const got: ServerFrame[] = []
    const control: ServerFrame[] = []
    m.subscribe('quotes', ((f: ServerFrame) => got.push(f)) as FrameHandler)
    m.onControl(((f: ServerFrame) => control.push(f)) as never)
    ws.emit({ topic: 'ack', data: { op: 'sub', topics: ['quotes'] } })
    ws.emit({
      topic: 'quotes',
      data: { source: 'anchor', live: false, ts: 't', quotes: [{ code: '600519', name: 'M', last: 1, prevClose: 1, open: 1, high: 1, low: 1, volume: 0, bids: [], asks: [] }] },
    })
    expect(got).toHaveLength(1)
    expect(got[0].topic).toBe('quotes')
    expect(control).toHaveLength(1)
    expect(control[0].topic).toBe('ack')
    m.close()
  })

  it('非法 JSON 与守卫失败帧被丢弃并 console 告警', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const m = new WSManager('ws://x/ws', factory)
    m.connect()
    const ws = latest()
    ws.open()
    const got: ServerFrame[] = []
    m.subscribe('quotes', ((f: ServerFrame) => got.push(f)) as FrameHandler)
    ws.emitRaw('not-json')
    ws.emit({ topic: 'quotes', data: { nope: true } })
    expect(got).toHaveLength(0)
    expect(spy).toHaveBeenCalledTimes(2)
    spy.mockRestore()
    m.close()
  })

  it('断线指数退避重连并在重连成功后自动重订', () => {
    const m = new WSManager('ws://x/ws', factory)
    m.connect()
    latest().open()
    m.subscribe('quotes', () => {})
    m.subscribe('trader:3', () => {})

    latest().serverClose()
    expect(m.state).toBe('reconnecting')
    expect(FakeWebSocket.instances).toHaveLength(1)

    vi.advanceTimersByTime(1000)
    expect(FakeWebSocket.instances).toHaveLength(2)
    expect(m.state).toBe('reconnecting')
    latest().open()
    expect(m.state).toBe('open')
    const subs = latest().sent.map((s) => JSON.parse(s))
    expect(subs).toContainEqual({ op: 'sub', topics: ['quotes'] })
    expect(subs).toContainEqual({ op: 'sub', topics: ['trader:3'] })
    m.close()
  })

  it('重连成功后触发 onReconnect（REST 全量拉回再续订，01 §7.3）', () => {
    const m = new WSManager('ws://x/ws', factory)
    const reconnected: string[] = []
    m.onReconnect(() => reconnected.push('yes'))
    m.connect()
    latest().open()
    expect(reconnected).toHaveLength(0)
    latest().serverClose()
    vi.advanceTimersByTime(1000)
    latest().open()
    expect(reconnected).toEqual(['yes'])
    m.close()
  })

  it('手动 close 不再重连', () => {
    const m = new WSManager('ws://x/ws', factory)
    m.connect()
    latest().open()
    m.close()
    expect(m.state).toBe('closed')
    vi.advanceTimersByTime(60000)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it('退避按 2^n 封顶 15s', () => {
    const m = new WSManager('ws://x/ws', factory)
    m.connect()
    latest().open()
    latest().serverClose()
    vi.advanceTimersByTime(1000) // 第 1 次重连：1s
    latest().serverClose()
    vi.advanceTimersByTime(2000) // 第 2 次：2s
    latest().serverClose()
    vi.advanceTimersByTime(4000) // 第 3 次：4s
    latest().serverClose()
    vi.advanceTimersByTime(15000) // 第 4 次起：封顶 15s
    latest().serverClose()
    expect(FakeWebSocket.instances).toHaveLength(5)
    vi.advanceTimersByTime(15000)
    expect(FakeWebSocket.instances).toHaveLength(6)
    m.close()
  })
})
