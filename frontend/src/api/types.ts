/**
 * 领域类型：与后端真实载荷逐字段对齐（T16-1）。
 * 手工维护：REST 200 响应多为 unknown（后端视图手工组包），
 * 本文件以线上实测载荷 + backend store schema 为准。
 */

export type Side = 'buy' | 'sell'
export type OrderType = 'limit' | 'market'
export type MarketType = 'best5_cancel' | 'opponent_best'
export type TraderMode = 'manual' | 'strategy'
export type TraderStatus = 'running' | 'paused' | 'closed' | 'deleted'
export type OrderStatus = 'wait' | 'partial' | 'filled' | 'cancel'
export type PlanEntryStatus = 'waiting' | 'triggered' | 'filled'
export type Tif = 'day' | 'gtc'

/* ---- 会话 / 行情 ---------------------------------------------- */

export interface SessionState {
  state: 'trading' | 'closed' | 'auction' | 'degraded'
  phase: string
  tradingDate: string
}

export interface MarketStatus {
  source: 'tencent' | 'sina' | 'eastmoney' | 'anchor'
  live: boolean
  ageSec: number | null
}

/** 五档价位：[价格, 量]（backend BookLevel 序列化为二元数组） */
export type BookLevel = [number, number]

export interface Quote {
  code: string
  name: string
  last: number
  prevClose: number
  open: number
  high: number
  low: number
  volume: number
  bids: BookLevel[]
  asks: BookLevel[]
}

export interface QuotesEnvelope {
  source: MarketStatus['source']
  live: boolean
  ts: string
  quotes: Quote[]
}

/** 行情质量：live=true 且源为完整档（tencent/sina，含五档与增量量）视为实时，否则降级 */
export type QuoteQuality = 'live' | 'fallback'

const FULL_SOURCES: ReadonlySet<MarketStatus['source']> = new Set(['tencent', 'sina'])

export function quoteQuality(env: Pick<QuotesEnvelope, 'source' | 'live'>): QuoteQuality {
  return env.live && FULL_SOURCES.has(env.source) ? 'live' : 'fallback'
}

export interface KlineRow {
  code: string
  date: string
  open: number
  close: number
  high: number
  low: number
  volume: number
}

export interface MinuteRow {
  code: string
  date: string
  minute: string
  price: number
  volume: number
}

/* ---- 交易员（驼峰视图） ---------------------------------------- */

export interface Metrics {
  insufficient: boolean
  totalReturn: number | null
  annualized: number | null
  maxDrawdown: number | null
  maxDrawdownDays: number | null
  sharpe: number | null
  winRate: number | null
  excess: number | null
  days: number
}

export interface TraderPublic {
  id: number
  name: string
  mode: TraderMode
  strategyType: string | null
  strategyParams: Record<string, unknown> | null
  status: TraderStatus
  initCash: number
  cash: number
  createdAt: string
}

export interface TraderListItem {
  id: number
  name: string
  mode: TraderMode
  strategyType: string | null
  status: TraderStatus
  initCash: number
  equity: number
  totalReturn: number
  metrics?: Metrics
}

export interface PositionView {
  code: string
  qty: number
  avgCost: number
  todayBought: number
  price: number
  value: number
  unrealizedPnl: number
}

export interface AccountView {
  traderId: number
  name: string
  mode: TraderMode
  status: TraderStatus
  initCash: number
  cash: number
  frozenCash: number
  availableCash: number
  marketValue: number
  equity: number
  totalReturn: number
  positions: PositionView[]
}

export interface TraderDetail extends AccountView {
  metrics: Metrics
  orders: OrderRow[]
  trades: TradeRow[]
  equitySeries: EquityPoint[]
  plans: PlanView[]
  /** C003：当前生效策略参数（编辑态回填依据；manual 为 null） */
  strategyParams: Record<string, number> | null
}

/* ---- 订单 / 成交 / 持仓 / 净值（snake_case DB 行，page_result 包壳） ---- */

export interface OrderRow {
  id: number
  trader_id: number
  origin: 'manual' | 'operator' | 'plan' | 'strategy'
  plan_entry_id: number | null
  client_order_id: string | null
  side: Side
  type: OrderType
  market_type: MarketType | null
  code: string
  price: number | null
  qty: number
  filled_qty: number
  avg_filled_price: number | null
  frozen_amount: number | null
  fill_model: 'real' | 'fallback' | null
  status: OrderStatus
  created_at: string
  trading_date: string
  filled_at: string | null
}

export interface TradeRow {
  id: number
  order_id: number
  trader_id: number
  code: string
  side: Side
  price: number
  qty: number
  amount: number
  commission: number
  stamp_tax: number
  transfer_fee: number
  realized_pnl: number | null
  origin: string
  ts: string
  trading_date: string
}

export interface EquityPoint {
  trader_id: number
  date: string
  total_equity: number
  cash: number
}

export interface Page<T> {
  data: T[]
  nextCursor: number | null
}

/* ---- 事件流（snake_case DB 行） ---------------------------------- */

export interface EventRow {
  id: number
  trader_id: number | null
  ts: string
  action: string
  detail: string | null
}

/* ---- 计划（plan_view 驼峰；entries 为 snake_case 行） -------------- */

export interface PlanView {
  id: number
  traderId: number
  name: string
  status: 'active' | 'halted' | 'done' | 'deleted'
  scope: Record<string, unknown>
  budget: Record<string, unknown>
  positionRule: Record<string, unknown>
  risk: Record<string, unknown>
  schedule: Record<string, unknown>
  createdAt: string
}

export type TriggerType = 'price_cross' | 'pct_change' | 'time' | 'ma_cross'

export interface EntryRow {
  id: number
  plan_id: number
  trigger_type: TriggerType
  trigger_params: string
  action: string
  tif: Tif
  status: PlanEntryStatus
  last_triggered_on: string | null
  created_at: string
}

/* ---- 策略模板 / 审计 -------------------------------------------- */

export interface TemplateParam {
  default: number
}

export interface Template {
  template: string
  name: string
  params: Record<string, TemplateParam>
}

/* ---- 自选股（T23/T24，02 §5.2 v6：码制为带市场前缀规范码） ------------ */

export interface WatchEntry {
  code: string
  addedAt: string
}

export interface WatchAddResult {
  code: string
  addedAt: string
  created: boolean
  name?: string
}

export interface WatchRemoveResult {
  code: string
  removed: boolean
}

export interface WatchBatchReceipt {
  code: string
  op: 'add' | 'remove'
  ok: boolean
  error: string | null
}

export interface SuggestItem {
  code: string
  name: string
  kind: string
}

/* ---- 请求体（与 backend models.schemas 对齐） --------------------- */

export interface TraderCreate {
  name: string
  mode: TraderMode
  strategyType?: string | null
  strategyParams?: Record<string, unknown> | null
  initialCash: number
  plan?: Record<string, unknown> | null
}

export interface OrderCreate {
  code: string
  side: Side
  orderType: OrderType
  price?: number | null
  qty: number
  marketType?: MarketType | null
  clientOrderId?: string | null
}

/* ---- 统一错误模型（02 §5.1） -------------------------------------- */

export interface ApiErrorBody {
  code: string
  message: string
  details: unknown
}

/* ---- WS（02 §5.3 / backend app/api/ws.py） ------------------------ */

export type StaticTopic = 'quotes' | 'traders' | 'plans' | 'events'
export type Topic = StaticTopic | `trader:${number}`

export interface PlanPush {
  e: 'entry_triggered' | 'entry_filled' | 'risk_halt' | 'plan_done' | 'plan_status'
  planId?: number
  entryId?: number
  orderId?: number
  traderId?: number
  code?: string
  side?: Side
}

export interface TraderEventPush {
  e: string
  traderId?: number
  name?: string
  hard?: boolean
}

export interface AckFrame {
  topic: 'ack'
  data: { op: 'sub' | 'unsub'; topics: string[] }
}

export interface WsErrorFrame {
  topic: 'error'
  data: { message: string }
}

export type ServerFrame =
  | { topic: 'quotes'; data: QuotesEnvelope }
  | { topic: 'traders'; data: TraderListItem[] }
  | { topic: `trader:${number}`; data: AccountView }
  | { topic: 'plans'; data: PlanPush }
  | { topic: 'events'; data: TraderEventPush }
  | AckFrame
  | WsErrorFrame

export interface SubMessage {
  op: 'sub' | 'unsub'
  topics: string[]
}

/* ---- 运行时守卫（T16-1：WS 帧边界校验） --------------------------- */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export function isQuotesEnvelope(value: unknown): value is QuotesEnvelope {
  if (!isRecord(value) || !Array.isArray(value.quotes)) return false
  return value.quotes.every(
    (q) =>
      isRecord(q) &&
      typeof q.code === 'string' &&
      typeof q.last === 'number' &&
      Array.isArray(q.bids) &&
      Array.isArray(q.asks),
  )
}

export function isTraderList(value: unknown): value is TraderListItem[] {
  return (
    Array.isArray(value) &&
    value.every((t) => isRecord(t) && typeof t.id === 'number' && typeof t.name === 'string')
  )
}

export function isAccountView(value: unknown): value is AccountView {
  return (
    isRecord(value) &&
    typeof value.traderId === 'number' &&
    typeof value.cash === 'number' &&
    Array.isArray(value.positions)
  )
}

export function isServerFrame(value: unknown): value is ServerFrame {
  if (!isRecord(value) || typeof value.topic !== 'string') return false
  switch (value.topic) {
    case 'quotes':
      return isQuotesEnvelope(value.data)
    case 'traders':
      return isTraderList(value.data)
    case 'plans':
    case 'events':
      return isRecord(value.data)
    case 'ack':
      return isRecord(value.data) && typeof (value.data as AckFrame['data']).op === 'string'
    case 'error':
      return isRecord(value.data) && typeof (value.data as WsErrorFrame['data']).message === 'string'
    default:
      return value.topic.startsWith('trader:') && isAccountView(value.data)
  }
}
