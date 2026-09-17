import { WS_URL } from './config'
import {
  isServerFrame,
  type AckFrame,
  type ServerFrame,
  type Topic,
  type WsErrorFrame,
} from './types'

export type ConnectionState =
  | 'idle'
  | 'connecting'
  | 'open'
  | 'reconnecting'
  | 'closed'

export type FrameHandler = (frame: ServerFrame) => void
export type StateHandler = (state: ConnectionState) => void
export type ReconnectHandler = () => void
export type ControlHandler = (frame: AckFrame | WsErrorFrame) => void

export interface WSFactory {
  (url: string): WebSocket
}

const BACKOFF_BASE_MS = 1000
const BACKOFF_MAX_MS = 15000

/**
 * 订阅式 WS 管理（02 §5.3）：
 * - 订阅注册/退订按 topic 去重，多组件共享单连接与单订阅帧；
 * - 断线指数退避重连，重连成功后自动重订，并触发 onReconnect（REST 全量拉回再续订，01 §7.3）；
 * - 服务端 ack/error 控制帧原样分发，非法 payload 经守卫拦截并 console 告警。
 */
export class WSManager {
  private ws: WebSocket | null = null
  private readonly handlers = new Map<string, Set<FrameHandler>>()
  private readonly stateHandlers = new Set<StateHandler>()
  private readonly reconnectHandlers = new Set<ReconnectHandler>()
  private readonly controlHandlers = new Set<ControlHandler>()
  private attempts = 0
  private manualClose = false
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private _state: ConnectionState = 'idle'

  constructor(
    private readonly url: string = WS_URL,
    private readonly factory: WSFactory = (u) => new WebSocket(u),
  ) {}

  get state(): ConnectionState {
    return this._state
  }

  get subscribedTopics(): Topic[] {
    return [...this.handlers.keys()] as Topic[]
  }

  onState(handler: StateHandler): () => void {
    this.stateHandlers.add(handler)
    return () => this.stateHandlers.delete(handler)
  }

  onReconnect(handler: ReconnectHandler): () => void {
    this.reconnectHandlers.add(handler)
    return () => this.reconnectHandlers.delete(handler)
  }

  /** ack / error 控制帧监听（诊断与联调用，按主题分发的推送不含控制帧） */
  onControl(handler: ControlHandler): () => void {
    this.controlHandlers.add(handler)
    return () => this.controlHandlers.delete(handler)
  }

  subscribe(topic: Topic, handler: FrameHandler): () => void {
    let set = this.handlers.get(topic)
    const first = !set || set.size === 0
    if (!set) {
      set = new Set()
      this.handlers.set(topic, set)
    }
    set.add(handler)
    if (first) this.sendSub('sub', [topic])
    return () => {
      const current = this.handlers.get(topic)
      if (!current) return
      current.delete(handler)
      if (current.size === 0) {
        this.handlers.delete(topic)
        this.sendSub('unsub', [topic])
      }
    }
  }

  connect(): void {
    if (this.ws && (this._state === 'open' || this._state === 'connecting')) return
    this.manualClose = false
    this.setState(this.attempts === 0 ? 'connecting' : 'reconnecting')
    const ws = this.factory(this.url)
    this.ws = ws
    ws.onopen = () => {
      this.attempts = 0
      this.setState('open')
      for (const topic of this.handlers.keys()) this.sendRaw({ op: 'sub', topics: [topic] })
      if (this.reconnectHandlers.size && this._hadConnected) {
        for (const h of this.reconnectHandlers) h()
      }
      this._hadConnected = true
    }
    ws.onmessage = (event) => this.handleMessage(event)
    ws.onclose = () => {
      this.ws = null
      if (this.manualClose) {
        this.setState('closed')
        return
      }
      this.scheduleReconnect()
    }
    ws.onerror = () => {
      // 错误后必然跟随 onclose，统一在 onclose 处理重连
    }
  }

  private _hadConnected = false

  close(): void {
    this.manualClose = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.ws?.close()
    if (!this.ws) this.setState('closed')
  }

  private scheduleReconnect(): void {
    this.setState('reconnecting')
    const delay = Math.min(BACKOFF_BASE_MS * 2 ** this.attempts, BACKOFF_MAX_MS)
    this.attempts += 1
    this.reconnectTimer = setTimeout(() => this.connect(), delay)
  }

  private handleMessage(event: MessageEvent): void {
    let payload: unknown
    try {
      payload = JSON.parse(String(event.data))
    } catch {
      console.error('[ws] invalid json frame', event.data)
      return
    }
    if (!isServerFrame(payload)) {
      console.error('[ws] frame failed guard, dropped', payload)
      return
    }
    if (payload.topic === 'ack' || payload.topic === 'error') {
      for (const handler of this.controlHandlers) handler(payload)
      return
    }
    const set = this.handlers.get(payload.topic)
    if (!set) return
    for (const handler of set) handler(payload)
  }

  private sendSub(op: 'sub' | 'unsub', topics: Topic[]): void {
    if (this._state !== 'open') return
    this.sendRaw({ op, topics })
  }

  private sendRaw(message: { op: 'sub' | 'unsub'; topics: string[] }): void {
    this.ws?.send(JSON.stringify(message))
  }

  private setState(state: ConnectionState): void {
    this._state = state
    for (const h of this.stateHandlers) h(state)
  }
}

export const wsManager = new WSManager()
