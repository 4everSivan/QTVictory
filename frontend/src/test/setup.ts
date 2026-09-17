import '@testing-library/jest-dom/vitest'

// jsdom 无布局引擎：为图表组件提供固定视口尺寸（§5.4 测量的兜底值）
Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
  configurable: true,
  value: 800,
})
Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
  configurable: true,
  value: 400,
})

// jsdom 环境下 Node 22 内置 WebSocket 与 jsdom Event 不兼容且避免单测向真实端口发连接
class MockWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3

  url: string
  readyState = MockWebSocket.OPEN
  onopen: ((ev: any) => any) | null = null
  onclose: ((ev: any) => any) | null = null
  onmessage: ((ev: any) => any) | null = null
  onerror: ((ev: any) => any) | null = null

  constructor(url: string) {
    this.url = url
    setTimeout(() => {
      this.onopen?.(new Event('open'))
    }, 0)
  }
  send(_data: any) {}
  close() {
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.(new Event('close'))
  }
}
globalThis.WebSocket = MockWebSocket as any

