import { lsGet, lsSet } from '../lib/storage'

const KEY_CURRENT_TRADER = 'qtv_current_trader'

/** UI 态白名单（01 §9）：localStorage 仅主题与此处"上次选中交易员" */
export function getStoredTraderId(): number | null {
  const raw = lsGet(KEY_CURRENT_TRADER)
  if (raw === null) return null
  const id = Number(raw)
  return Number.isInteger(id) && id > 0 ? id : null
}

export function setStoredTraderId(id: number | null): void {
  lsSet(KEY_CURRENT_TRADER, id === null ? '' : String(id))
}
