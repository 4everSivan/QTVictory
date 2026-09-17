import { vi } from 'vitest'
import type { AccountView, TraderListItem } from '../api/types'

export const t1: TraderListItem = {
  id: 1,
  name: 'Alpha',
  mode: 'strategy',
  strategyType: 'trend',
  status: 'running',
  initCash: 1_000_000,
  equity: 1_050_000,
  totalReturn: 0.05,
}

export const t2: TraderListItem = {
  id: 2,
  name: 'Beta',
  mode: 'manual',
  strategyType: null,
  status: 'paused',
  initCash: 500_000,
  equity: 480_000,
  totalReturn: -0.04,
}

export interface MockTradersState {
  list: TraderListItem[]
  currentId: number | null
  current: TraderListItem | null
  account: AccountView | null
  detail: null
  dayPnl: number | null
  events: Array<{ id: number; ts: string; text: string }>
  dialog: 'create' | 'edit' | 'none'
  editTarget: TraderListItem | null
  detailOpen: boolean
  openCreate: ReturnType<typeof vi.fn>
  openEdit: ReturnType<typeof vi.fn>
  openDetail: ReturnType<typeof vi.fn>
  closeDetail: ReturnType<typeof vi.fn>
  closeDialog: ReturnType<typeof vi.fn>
  setCurrent: ReturnType<typeof vi.fn>
  refresh: ReturnType<typeof vi.fn>
}

export const state: MockTradersState = {
  list: [t1, t2],
  currentId: 1,
  current: t1,
  account: null,
  detail: null,
  dayPnl: null,
  events: [{ id: 1, ts: '2026-09-17T09:31:00', text: '创建 · Alpha' }],
  dialog: 'none',
  editTarget: null,
  detailOpen: false,
  openCreate: vi.fn(),
  openEdit: vi.fn(),
  openDetail: vi.fn(),
  closeDetail: vi.fn(),
  closeDialog: vi.fn(),
  setCurrent: vi.fn(),
  refresh: vi.fn(),
}

export function useTraders() {
  return state
}

export const traderOps = {
  create: vi.fn((_payload?: unknown) => Promise.resolve({ id: 3 })),
  patch: vi.fn((_id?: number, _payload?: unknown) => Promise.resolve({})),
  inject: vi.fn((_id?: number, _amount?: number) => Promise.resolve({})),
  reset: vi.fn((_id?: number) => Promise.resolve({})),
  remove: vi.fn((_id?: number) => Promise.resolve({ id: 1, hard: false, deleted: true })),
}
