import { ApiError } from './client'

export type ErrorLevel = 'field' | 'toast'

export interface ErrorPresentation {
  /** 就地校验文案（下单面板）或 Toast 文案 */
  text: string
  level: ErrorLevel
}

interface BandDetails {
  limitBand?: [number, number]
  effectiveBand?: [number, number]
}

function fmt(n: number): string {
  return n.toFixed(2)
}

function bandText(details: unknown): string | null {
  const d = details as BandDetails | null
  if (!d || (!d.limitBand && !d.effectiveBand)) return null
  const parts: string[] = []
  if (d.effectiveBand) parts.push(`有效申报区间 ${fmt(d.effectiveBand[0])}–${fmt(d.effectiveBand[1])}`)
  if (d.limitBand) parts.push(`涨跌停带 ${fmt(d.limitBand[0])}–${fmt(d.limitBand[1])}`)
  return parts.join('；')
}

export interface ErrorSpec {
  level: ErrorLevel
  text: (message: string, details: unknown) => string
}

/** 01 §6 错误码 → 文案映射表（随 OpenAPI 对齐；未识别码回落通用文案） */
export const ERROR_MAP: Record<string, ErrorSpec> = {
  LOT_SIZE: {
    level: 'field',
    text: (_m, d) =>
      `申报数量不合规：${(d as { rule?: string } | null)?.rule ?? '主板/创业板 100 股整数倍；科创板 ≥200 股后 1 股递增'}`,
  },
  PRICE_BAND: {
    level: 'field',
    text: (_m, d) => bandText(d) ?? '申报价格超出有效申报范围',
  },
  INSUFFICIENT_FUNDS: {
    level: 'field',
    text: (_m, d) => {
      const v = d as { cash?: number; frozen?: number; need?: number } | null
      return v && typeof v.need === 'number'
        ? `可用资金不足：需要 ${fmt(v.need)}，可用 ${fmt((v.cash ?? 0) - (v.frozen ?? 0))}`
        : '可用资金不足'
    },
  },
  T1_LOCKED: {
    level: 'field',
    text: (_m, d) => {
      const v = d as { position?: number; locked?: number; need?: number } | null
      return v && typeof v.position === 'number'
        ? `可卖不足：持仓 ${v.position}，锁定/冻结 ${v.locked ?? 0}（T+1 或卖出冻结）`
        : '可卖不足（T+1 锁定或卖出冻结）'
    },
  },
  SESSION_CLOSED: { level: 'toast', text: () => '当前时段不可交易（已收盘或非交易时段）' },
  STALE_QUOTE: {
    level: 'toast',
    text: (_m, d) => {
      const age = (d as { ageSec?: number } | null)?.ageSec
      return typeof age === 'number' ? `行情过期（${Math.round(age)}s 未更新），拒市价单` : '行情过期，拒市价单'
    },
  },
  PLAN_CONSTRAINT: { level: 'toast', text: (m) => m || '计划约束拒绝（围栏过滤）' },
  RATE_LIMITED: { level: 'toast', text: () => '请求超限，请稍后再试' },
  SUSPENDED: { level: 'field', text: (m) => m || '标的无有效行情（停牌或未关注）' },
  UNSUPPORTED_BOARD: { level: 'field', text: (m) => m || '品种不可交易（仅沪深主板/创业板/科创板个股）' },
  TRADER_NOT_FOUND: { level: 'toast', text: () => '交易员不存在' },
  TRADER_CLOSED: { level: 'toast', text: () => '交易员已关闭' },
  PLAN_NOT_FOUND: { level: 'toast', text: () => '计划不存在' },
  ENTRY_NOT_FOUND: { level: 'toast', text: () => '条件单不存在' },
  ORDER_NOT_FOUND: { level: 'toast', text: () => '委托不存在' },
  NOT_ACTIVE: { level: 'toast', text: () => '委托非活动状态，无法撤单' },
  UNAUTHORIZED: { level: 'toast', text: () => '缺少或错误的 X-API-Key' },
  DUPLICATE_REQUEST: { level: 'toast', text: () => '重复请求（幂等键冲突）' },
  BAD_CODE: { level: 'toast', text: (m) => m || '代码非法或行情源不可达' },
  QUOTE_SOURCE_ERROR: { level: 'toast', text: (m) => m || '行情源校验不可用，稍后重试' },
}

export function presentError(error: ApiError): ErrorPresentation {
  const spec = ERROR_MAP[error.code]
  if (!spec) {
    console.warn(`[errors] unmapped error code: ${error.code}`)
    return { text: `${error.message}（${error.code}）`, level: 'toast' }
  }
  return { text: spec.text(error.message, error.details), level: spec.level }
}

/** 提交订单类错误的就地呈现：field 级返回文案，其余 undefined（由调用方转 Toast） */
export function orderFieldError(error: ApiError): string | null {
  const p = presentError(error)
  return p.level === 'field' ? p.text : null
}
