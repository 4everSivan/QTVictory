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

/* ---- 技术指标（01 §5.5 D8 口径钉死；null 语义对齐 maSeries，窗口不足 null） ---- */

/** EMA（种子=首值——与 TA-Lib 的 SMA 种子差异在 golden vectors 中显式钉死，D8） */
export function ema(values: number[], n: number): Array<number | null> {
  const out: Array<number | null> = values.map(() => null)
  if (n <= 0 || values.length < n) return out
  const k = 2 / (n + 1)
  let prev = values[0]
  for (let i = 1; i < values.length; i += 1) {
    prev = values[i] * k + prev * (1 - k)
    if (i >= n - 1) out[i] = prev
  }
  return out
}

export interface MacdPoint {
  dif: number | null
  dea: number | null
  hist: number | null
}

/** MACD(fast,slow,signal)：DIF=EMA(fast)−EMA(slow)；DEA=EMA(signal) of DIF（种子取首个非空 DIF）；柱=2×(DIF−DEA) */
export function macd(
  closes: number[],
  fast = 12,
  slow = 26,
  signal = 9,
): MacdPoint[] {
  const ef = ema(closes, fast)
  const es = ema(closes, slow)
  const dif: Array<number | null> = closes.map((_, i) =>
    ef[i] !== null && es[i] !== null ? (ef[i] as number) - (es[i] as number) : null,
  )
  const first = dif.findIndex((v) => v !== null)
  const dea: Array<number | null> = dif.map(() => null)
  if (first >= 0) {
    const k = 2 / (signal + 1)
    let prev = dif[first] as number
    dea[first] = prev
    for (let i = first + 1; i < dif.length; i += 1) {
      prev = (dif[i] as number) * k + prev * (1 - k)
      dea[i] = prev
    }
  }
  return dif.map((v, i) => ({
    dif: v,
    dea: dea[i],
    hist: v !== null && dea[i] !== null ? 2 * (v - (dea[i] as number)) : null,
  }))
}

/** RSI（Wilder 平滑，首值 SMA(n)：前 n 个变化的平均，此后 (prev×(n−1)+cur)/n） */
export function rsiWilder(closes: number[], n = 14): Array<number | null> {
  const out: Array<number | null> = closes.map(() => null)
  if (closes.length <= n) return out
  let gain = 0
  let loss = 0
  for (let i = 1; i <= n; i += 1) {
    const ch = closes[i] - closes[i - 1]
    if (ch > 0) gain += ch
    else loss -= ch
  }
  let avgGain = gain / n
  let avgLoss = loss / n
  out[n] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)
  for (let i = n + 1; i < closes.length; i += 1) {
    const ch = closes[i] - closes[i - 1]
    avgGain = (avgGain * (n - 1) + Math.max(ch, 0)) / n
    avgLoss = (avgLoss * (n - 1) + Math.max(-ch, 0)) / n
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)
  }
  return out
}

export interface BollPoint {
  mid: number | null
  upper: number | null
  lower: number | null
}

/** BOLL(n,k)：中轨 SMA(n)，上下轨 ±k×总体标准差 */
export function boll(closes: number[], n = 20, k = 2): BollPoint[] {
  return closes.map((_, i) => {
    if (i < n - 1) return { mid: null, upper: null, lower: null }
    const win = closes.slice(i - n + 1, i + 1)
    const mid = win.reduce((a, b) => a + b, 0) / n
    const sd = Math.sqrt(win.reduce((a, b) => a + (b - mid) ** 2, 0) / n)
    return { mid, upper: mid + k * sd, lower: mid - k * sd }
  })
}

export interface KdjPoint {
  k: number | null
  d: number | null
  j: number | null
}

/** KDJ(n,mv,sv)：RSV→K/D 递推（初值 50），J=3K−2D */
export function kdj(
  bars: Array<{ high: number; low: number; close: number }>,
  n = 9,
  mv = 3,
  sv = 3,
): KdjPoint[] {
  let prevK = 50
  let prevD = 50
  return bars.map((b, i) => {
    if (i < n - 1) return { k: null, d: null, j: null }
    const win = bars.slice(i - n + 1, i + 1)
    const hh = Math.max(...win.map((w) => w.high))
    const ll = Math.min(...win.map((w) => w.low))
    const rsv = hh === ll ? 50 : ((b.close - ll) / (hh - ll)) * 100
    const k = ((mv - 1) * prevK + rsv) / mv
    const d = ((sv - 1) * prevD + k) / sv
    prevK = k
    prevD = d
    return { k, d, j: 3 * k - 2 * d }
  })
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
