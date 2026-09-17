import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import { useFallbackPoll, useQuery, useSubscription } from '../api/hooks'
import type {
  AccountView,
  PlanPush,
  ServerFrame,
  TraderDetail,
  TraderEventPush,
  TraderListItem,
} from '../api/types'
import { getStoredTraderId, setStoredTraderId } from './ui'
import { toast } from '../components/panes/Toasts'

type TradersFrame = Extract<ServerFrame, { topic: 'traders' }>
type AccountFrame = Extract<ServerFrame, { topic: `trader:${number}` }>

export interface TraderEventItem {
  id: number
  ts: string
  text: string
}

const EVENT_TEXT: Record<string, string> = {
  created: '创建',
  trader_created: '创建',
  deleted: '删除',
  paused: '暂停',
  resumed: '恢复',
  closed: '关闭',
  order: '委托',
  order_cancelled: '撤单',
  fill: '成交',
  reset: '重置',
  capital_injected: '注资',
  plan_renamed: '计划改名',
  plan_deleted: '计划删除',
  plan_entry_triggered: '条件单触发',
  plan_entry_failed: '条件单失败',
  risk_stop: '风控止损',
  risk_halt: '风控熔断',
  plan_done: '计划完成',
  strategy_fenced: '策略围栏拦截',
}

let eventSeq = 0

export interface TradersState {
  list: TraderListItem[]
  currentId: number | null
  current: TraderListItem | null
  account: AccountView | null
  detail: TraderDetail | null
  dayPnl: number | null
  events: TraderEventItem[]
  dialog: 'create' | 'edit' | 'none'
  editTarget: TraderListItem | null
  detailOpen: boolean
  openCreate: () => void
  openEdit: (trader: TraderListItem) => void
  openDetail: () => void
  closeDetail: () => void
  closeDialog: () => void
  setCurrent: (id: number | null) => void
  refresh: () => void
}

const Ctx = createContext<TradersState | null>(null)

/**
 * 交易员上下文（01 §2.1 v2 跟随语义 + §8 展示层）：
 * 当前交易员决定顶栏指标 / Dock / 下单面板 / 计划的作用对象；
 * list 由 traders topic（2s 节流）+ REST 兜底轮询维护，账户由 trader:{id} topic 增量维护。
 */
export function TradersProvider({ children }: { children: ReactNode }) {
  const listQuery = useQuery<{ data: TraderListItem[]; sort: string }>('/traders')
  const listFrame = useSubscription<TradersFrame>('traders')
  const list = useMemo(
    () => listFrame?.data ?? listQuery.data?.data ?? [],
    [listFrame, listQuery.data],
  )

  const [currentId, setCurrentIdState] = useState<number | null>(() => getStoredTraderId())
  const [dialog, setDialog] = useState<'create' | 'edit' | 'none'>('none')
  const [editTarget, setEditTarget] = useState<TraderListItem | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [liveEvents, setLiveEvents] = useState<TraderEventItem[]>([])

  const detailQuery = useQuery<TraderDetail>(currentId === null ? null : `/traders/${currentId}`)
  const accountFrame = useSubscription<AccountFrame>(
    currentId === null ? null : (`trader:${currentId}` as const),
  )
  const eventsQuery = useQuery<{ data: Array<{ id: number; ts: string; action: string; detail: string | null }> }>(
    '/traders/events?limit=20',
  )
  const eventsFrame = useSubscription<Extract<ServerFrame, { topic: 'events' }>>('events')
  const plansFrame = useSubscription<Extract<ServerFrame, { topic: 'plans' }>>('plans')

  useEffect(() => {
    if (!plansFrame) return
    const push = plansFrame.data as PlanPush
    if (push.e === 'risk_halt') toast('error', `风控熔断：计划 #${push.planId ?? '--'}`)
    if (push.e === 'plan_done') toast('info', `计划完成 #${push.planId ?? '--'}`)
    if (push.e === 'entry_triggered') toast('info', `条件单触发 #${push.orderId ?? '--'} ${push.code ?? ''}`)
  }, [plansFrame])

  useEffect(() => {
    if (list.length === 0) return
    if (currentId === null || !list.some((t) => t.id === currentId)) {
      setCurrentIdState(list[0].id)
    }
  }, [list, currentId])

  useEffect(() => {
    if (!eventsFrame) return
    const push = eventsFrame.data as TraderEventPush
    const text = EVENT_TEXT[push.e] ?? push.e
    const name = push.name ? ` · ${push.name}` : ''
    eventSeq += 1
    setLiveEvents((prev) =>
      [{ id: -eventSeq, ts: new Date().toISOString(), text: `${text}${name}` }, ...prev].slice(0, 20),
    )
  }, [eventsFrame])

  const setCurrent = useCallback((id: number | null) => {
    setStoredTraderId(id)
    setCurrentIdState(id)
  }, [])

  const openCreate = useCallback(() => {
    setEditTarget(null)
    setDialog('create')
  }, [])

  const openEdit = useCallback((trader: TraderListItem) => {
    setEditTarget(trader)
    setDialog('edit')
  }, [])

  const openDetail = useCallback(() => setDetailOpen(true), [])
  const closeDetail = useCallback(() => setDetailOpen(false), [])

  const closeDialog = useCallback(() => setDialog('none'), [])

  const refreshList = useCallback(() => void listQuery.reload(), [listQuery])
  useFallbackPoll('traders', 5000, refreshList)

  const detail = detailQuery.data
  const account = accountFrame?.data ?? detail ?? null
  const dayPnl = useMemo(() => {
    if (!account || !detail?.equitySeries?.length) return null
    const last = detail.equitySeries[detail.equitySeries.length - 1]
    return account.equity - last.total_equity
  }, [account, detail])

  const events = useMemo<TraderEventItem[]>(() => {
    const rest = (eventsQuery.data?.data ?? []).map((e) => ({
      id: e.id,
      ts: e.ts,
      text: EVENT_TEXT[e.action] ?? e.action,
    }))
    return [...liveEvents, ...rest].slice(0, 20)
  }, [liveEvents, eventsQuery.data])

  const value: TradersState = {
    list,
    currentId,
    current: list.find((t) => t.id === currentId) ?? null,
    account,
    detail,
    dayPnl,
    events,
    dialog,
    editTarget,
    detailOpen,
    openCreate,
    openEdit,
    openDetail,
    closeDetail,
    closeDialog,
    setCurrent,
    refresh: () => {
      refreshList()
      void detailQuery.reload()
    },
  }

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useTraders(): TradersState {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useTraders 必须在 TradersProvider 内使用')
  return ctx
}

/* ---- 生命周期操作（T19-5，接 API；失败抛 ApiError 由调用方转 Toast） ---- */

export const traderOps = {
  create: (payload: Record<string, unknown>) =>
    api.post<TraderListItem>('/traders', payload),
  patch: (id: number, payload: Record<string, unknown>) =>
    api.patch<TraderListItem>(`/traders/${id}`, payload),
  inject: (id: number, amount: number) =>
    api.post<TraderListItem>(`/traders/${id}/capital`, { amount }),
  reset: (id: number) => api.post<TraderListItem>(`/traders/${id}/reset`),
  remove: (id: number) => api.del<{ id: number; hard: boolean; deleted: boolean }>(`/traders/${id}`),
}
