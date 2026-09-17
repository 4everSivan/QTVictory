/** 图表纯函数（01 §5 交互数学）：全部可单测 */

export const MIN_CANDLES = 30
export const ZOOM_FACTOR = 1.18
export const MINUTE_SLOTS = 242

export interface ViewWindow {
  /** 可见窗口右端（exclusive）索引 */
  end: number
  count: number
}

export function clampCount(count: number, total: number): number {
  return Math.max(MIN_CANDLES, Math.min(Math.round(count), Math.max(total, MIN_CANDLES)))
}

export function clampView(view: ViewWindow, total: number): ViewWindow {
  const count = clampCount(view.count, total)
  const end = Math.max(count, Math.min(view.end, total))
  return { end, count }
}

/** 滚轮缩放（§5.1：×1.18，30~N，右端锚定） */
export function zoom(view: ViewWindow, dir: 1 | -1, total: number): ViewWindow {
  const next = dir > 0 ? view.count / ZOOM_FACTOR : view.count * ZOOM_FACTOR
  return clampView({ end: view.end, count: next }, total)
}

/** 拖拽平移：dx 像素 → 索引位移 */
export function pan(view: ViewWindow, dxPixels: number, stepPixels: number, total: number): ViewWindow {
  const shift = Math.round(dxPixels / Math.max(stepPixels, 1e-6))
  return clampView({ end: view.end - shift, count: view.count }, total)
}

export function defaultView(total: number): ViewWindow {
  return clampView({ end: total, count: Math.min(90, total) }, total)
}

/** 移动平均：i 处前 n 项（含 i）均值，不足返回 null */
export function ma(values: Array<number | null>, n: number, i: number): number | null {
  if (i < n - 1) return null
  let sum = 0
  for (let k = i - n + 1; k <= i; k += 1) {
    const v = values[k]
    if (typeof v !== 'number') return null
    sum += v
  }
  return sum / n
}

export function maSeries(values: Array<number | null>, n: number): Array<number | null> {
  return values.map((_, i) => ma(values, n, i))
}

export interface CumPoint {
  price: number
  cumVolume: number
}

/** VWAP：累计量差分加权均价（backend minute_klines.volume 为累计量） */
export function vwapFromCumulative(points: CumPoint[]): Array<number | null> {
  let pv = 0
  let vv = 0
  return points.map((p, i) => {
    if (p.price <= 0) return null
    const prev = i > 0 ? points[i - 1] : null
    const dv = prev && p.cumVolume >= prev.cumVolume ? p.cumVolume - prev.cumVolume : 0
    if (dv > 0) {
      pv += p.price * dv
      vv += dv
    }
    return vv > 0 ? pv / vv : null
  })
}

/** 归一化百分比序列（§5.3：净值曲线，首日=0） */
export function normalizePercent(series: number[]): number[] {
  if (series.length === 0) return []
  const base = series[0]
  if (!base) return series.map(() => 0)
  return series.map((v) => (v / base - 1) * 100)
}

/* ---- 分时槽位（§5.2：242 槽 = 上午 121 + 下午 121） ---------------- */

const MORNING_BASE = 9 * 60 + 30 // 09:30
const AFTERNOON_BASE = 13 * 60 // 13:00

/** "HH:MM" → 槽位；午休时段返回 null */
export function slotIndexFor(minute: string): number | null {
  const [h, m] = minute.split(':').map(Number)
  const t = h * 60 + m
  if (t < MORNING_BASE || t > 15 * 60) return null
  if (t <= 11 * 60 + 30) return t - MORNING_BASE
  if (t >= AFTERNOON_BASE) return 120 + (t - AFTERNOON_BASE) + 1
  return null
}

export function slotTime(index: number): string {
  const t = index <= 120 ? MORNING_BASE + index : AFTERNOON_BASE + (index - 121)
  return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`
}

export function linearScale(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain
  const [r0, r1] = range
  const span = d1 - d0 || 1e-9
  const f = (v: number) => r0 + ((v - d0) / span) * (r1 - r0)
  f.invert = (r: number) => d0 + ((r - r0) / (r1 - r0)) * span
  return f
}
