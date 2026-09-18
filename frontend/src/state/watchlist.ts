import { api } from '../api/client'
import type {
  Quote,
  SuggestItem,
  WatchAddResult,
  WatchBatchReceipt,
  WatchEntry,
  WatchRemoveResult,
} from '../api/types'

/**
 * 自选股数据层（T24-1，01 §4.2 v5 / §7.2）：
 * 端点封装 + 列表编排。码制与后端对齐：带市场前缀规范码（sh600519），
 * PUT/DELETE 接受裸码或大小写变体，后端归一后以前缀码回执。
 */
export const watchlistOps = {
  list: () => api.get<{ data: WatchEntry[] }>('/watchlist'),
  add: (code: string) => api.put<WatchAddResult>(`/watchlist/${encodeURIComponent(code)}`),
  remove: (code: string) => api.del<WatchRemoveResult>(`/watchlist/${encodeURIComponent(code)}`),
  batch: (add: string[], remove: string[]) =>
    api.post<{ results: WatchBatchReceipt[] }>('/watchlist/batch', { add, remove }),
  suggest: (q: string) =>
    api.get<{ data: SuggestItem[] }>(`/market/suggest?q=${encodeURIComponent(q)}`),
}

/**
 * 名称暂存：GET /watchlist 不回名称；添加回执（created 时带 name）缓存在此，
 * 供首个 quotes 包络到达前的占位行展示。
 */
const names = new Map<string, string>()

export function rememberName(code: string, name: string | undefined): void {
  if (name) names.set(code, name)
}

export interface WatchRow {
  code: string
  name: string
  quote: Quote | null
  /** true = 自选集成员（可删）；false = 动态项（持仓 ∪ 计划池 ∪ 指数，不可删） */
  pinned: boolean
}

/**
 * 列表编排（01 §4.2 v5 分组与排序）：
 * 自选集置顶，顺序取 GET /watchlist 回序（addedAt 倒序）；其下动态项保持
 * quotes 包络原顺序（后端关注集序）。删除自选后仍被持仓/计划引用的码随
 * entries 收缩自动回落动态区。自选项可能暂无行情快照（等下一轮轮询），
 * 以 quote=null 占位行置顶展示。
 */
export function arrangeWatchRows(quotes: Quote[], entries: WatchEntry[]): WatchRow[] {
  const byCode = new Map(quotes.map((q) => [q.code, q]))
  const pinnedCodes = new Set(entries.map((e) => e.code))
  const pinned: WatchRow[] = entries.map((e) => {
    const quote = byCode.get(e.code) ?? null
    return { code: e.code, name: quote?.name || names.get(e.code) || '', quote, pinned: true }
  })
  const dynamic: WatchRow[] = quotes
    .filter((q) => !pinnedCodes.has(q.code))
    .map((q) => ({ code: q.code, name: q.name, quote: q, pinned: false }))
  return [...pinned, ...dynamic]
}
