#!/usr/bin/env node
/**
 * 数据层冒烟（T16 DoD）：对真实后端验证 REST 全量 → WS 订阅增量 → 协议契约。
 * 运行：node scripts/smoke.mjs（需后端 127.0.0.1:8787 已启动）
 */
const BASE = process.env.VITE_API_BASE ?? 'http://127.0.0.1:8787/api'
const WS = BASE.replace(/^http/, 'ws').replace(/\/api\/?$/, '/ws')

let passed = 0
let failed = 0

function check(name, cond, extra = '') {
  if (cond) {
    passed += 1
    console.log(`  ✓ ${name}`)
  } else {
    failed += 1
    console.error(`  ✗ ${name} ${extra}`)
  }
}

async function get(path) {
  const res = await fetch(`${BASE}${path}`)
  const body = await res.json().catch(() => null)
  return { status: res.status, body }
}

function wsOpen(url) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url)
    const timer = setTimeout(() => reject(new Error('ws connect timeout')), 5000)
    ws.onopen = () => {
      clearTimeout(timer)
      resolve(ws)
    }
    ws.onerror = () => {
      clearTimeout(timer)
      reject(new Error('ws connect error'))
    }
  })
}

function nextFrame(ws, predicate, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('frame timeout')), timeoutMs)
    const handler = (event) => {
      const frame = JSON.parse(event.data)
      if (predicate(frame)) {
        clearTimeout(timer)
        ws.removeEventListener('message', handler)
        resolve(frame)
      }
    }
    ws.addEventListener('message', handler)
  })
}

const session = await get('/session')
check('GET /api/session 200', session.status === 200)
check(
  'session 载荷键（state/phase/tradingDate）',
  session.body && ['state', 'phase', 'tradingDate'].every((k) => k in session.body),
  JSON.stringify(session.body),
)

const quotes = await get('/market/quotes')
check('GET /api/market/quotes 200', quotes.status === 200)
check(
  'quotes 包络键（source/live/ts/quotes）',
  quotes.body && ['source', 'live', 'ts', 'quotes'].every((k) => k in quotes.body),
)
const q0 = quotes.body?.quotes?.[0]
check(
  'quote 字段（code/name/last/prevClose/bids/asks）',
  q0 && ['code', 'name', 'last', 'prevClose', 'bids', 'asks'].every((k) => k in q0),
  JSON.stringify(q0)?.slice(0, 160),
)

const traders = await get('/traders')
check('GET /api/traders 200', traders.status === 200)
check('traders 包络键（data/sort）', traders.body && Array.isArray(traders.body.data))

const templates = await get('/templates')
check(
  'templates 为 8 个策略模板',
  templates.body?.data?.length === 8,
  `got ${templates.body?.data?.length}`,
)

console.log('--- WS 协议（02 §5.3） ---')
const ws = await wsOpen(WS)
const ack = nextFrame(ws, (f) => f.topic === 'ack')
ws.send(JSON.stringify({ op: 'sub', topics: ['quotes', 'events'] }))
const ackFrame = await ack
check('ack 帧回执当前订阅集', ackFrame.data.op === 'sub' && ackFrame.data.topics.includes('quotes'))

const quotesPush = nextFrame(ws, (f) => f.topic === 'quotes', 75000)
const fill = nextFrame(ws, (f) => f.topic === 'events', 8000).catch(() => null)
ws.send(JSON.stringify({ op: 'unsub', topics: ['events'] }))
const push = await quotesPush
check(
  'quotes 推送为全量包络（行情降级时为 anchor/live=false）',
  push.data && ['source', 'live', 'ts', 'quotes'].every((k) => k in push.data),
)
const evt = await fill
check('events topic 订阅/退订无异常（60s 内无事件亦可）', evt === null || evt.topic === 'events')

ws.close()
console.log(`\nsmoke: ${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
