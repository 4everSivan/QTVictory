/** 数值格式化：全部数字走 Space Mono（.num）+ tabular-nums（01 §3.2） */

export function fmtPrice(n: number | null | undefined): string {
  return typeof n === 'number' && Number.isFinite(n) ? n.toFixed(2) : '--'
}

export function fmtPct(r: number | null | undefined): string {
  if (typeof r !== 'number' || !Number.isFinite(r)) return '--'
  return `${r >= 0 ? '+' : ''}${(r * 100).toFixed(2)}%`
}

export function fmtSigned(n: number | null | undefined): string {
  if (typeof n !== 'number' || !Number.isFinite(n)) return '--'
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}`
}

/** 成交量：股 → 手 */
export function fmtVol(shares: number | null | undefined): string {
  if (typeof shares !== 'number' || !Number.isFinite(shares)) return '--'
  return `${Math.floor(shares / 100)}`
}

export function pctChange(last: number, prevClose: number): number | null {
  if (!prevClose) return null
  return last / prevClose - 1
}

export function trendClass(value: number | null | undefined): 'up' | 'down' | 'flat' {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) return 'flat'
  return value > 0 ? 'up' : 'down'
}

export function isIndexCode(code: string): boolean {
  return /^(sh000|sz399)/.test(code)
}
