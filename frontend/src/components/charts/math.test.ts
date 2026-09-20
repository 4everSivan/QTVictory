import { describe, expect, it } from 'vitest'
import {
  boll,
  clampView,
  defaultView,
  ema,
  kdj,
  linearScale,
  ma,
  macd,
  maSeries,
  MIN_CANDLES,
  normalizePercent,
  pan,
  rsiWilder,
  slotIndexFor,
  slotTime,
  vwapFromCumulative,
  zoom,
} from './math'

describe('日K 交互数学（01 §5.1）', () => {
  it('缩放 ×1.18 且钳制 30~N（右端锚定）', () => {
    const v0 = defaultView(300) // 90 根
    const v1 = zoom(v0, 1, 300)
    expect(Math.round(v1.count)).toBe(Math.round(90 / 1.18))
    expect(v1.end).toBe(v0.end)
    const vOut = zoom({ end: 300, count: 31 }, 1, 300)
    expect(vOut.count).toBe(MIN_CANDLES)
    const vMax = zoom({ end: 300, count: 299 }, -1, 300)
    expect(vMax.count).toBe(300)
  })

  it('平移按像素位移换算索引并钳制窗口', () => {
    const v = pan({ end: 300, count: 90 }, 50, 10, 300) // 右拖 50px → 看更早 5 根
    expect(v.end).toBe(295)
    const toNewest = pan({ end: 300, count: 90 }, -9999, 10, 300) // 左拖极限 → 最新
    expect(toNewest.end).toBe(300)
    const toOldest = pan({ end: 300, count: 90 }, 9999, 10, 300) // 右拖极限 → 最旧
    expect(toOldest.end).toBe(90)
  })

  it('MA：不足 n 返回 null，恰好 n 为均值', () => {
    const values = [1, 2, 3, 4, 5]
    expect(ma(values, 5, 3)).toBeNull()
    expect(ma(values, 5, 4)).toBe(3)
    const series = maSeries(values, 2)
    expect(series[0]).toBeNull()
    expect(series[1]).toBe(1.5)
  })

  it('clampView 边界安全', () => {
    expect(clampView({ end: 10, count: 90 }, 300)).toEqual({ end: 90, count: 90 })
  })
})

describe('分时数学（01 §5.2）', () => {
  it('槽位映射：09:30→0，11:30→120，13:00→121，15:00→241，午休为 null', () => {
    expect(slotIndexFor('09:30')).toBe(0)
    expect(slotIndexFor('11:30')).toBe(120)
    expect(slotIndexFor('13:00')).toBe(121)
    expect(slotIndexFor('15:00')).toBe(241)
    expect(slotIndexFor('12:00')).toBeNull()
    expect(slotIndexFor('09:25')).toBeNull()
  })

  it('槽位时间往返一致', () => {
    expect(slotTime(0)).toBe('09:30')
    expect(slotTime(120)).toBe('11:30')
    expect(slotTime(121)).toBe('13:00')
    expect(slotTime(241)).toBe('15:00')
  })

  it('VWAP：累计量差分加权（首样本前的量不可知，从第二样本起算）', () => {
    const vwap = vwapFromCumulative([
      { price: 10, cumVolume: 100 },
      { price: 12, cumVolume: 300 },
      { price: 11, cumVolume: 600 },
    ])
    expect(vwap[0]).toBeNull()
    expect(vwap[1]).toBe(12) // (12×200)/200
    expect(vwap[2]).toBeCloseTo((12 * 200 + 11 * 300) / 500)
  })
})

describe('净值归一化（01 §5.3）', () => {
  it('首日 = 0，其余为百分比', () => {
    const out = normalizePercent([100, 110, 90])
    expect(out[0]).toBe(0)
    expect(out[1]).toBeCloseTo(10)
    expect(out[2]).toBeCloseTo(-10)
    expect(normalizePercent([])).toEqual([])
    expect(normalizePercent([0, 5])).toEqual([0, 0])
  })
})

describe('线性比例尺', () => {
  it('正逆映射一致', () => {
    const s = linearScale([0, 100], [0, 500])
    expect(s(50)).toBe(250)
    expect(s.invert(250)).toBeCloseTo(50)
  })
})

/* ---- 指标纯函数（01 §5.5 D8 口径钉死 + golden vectors，T27-4） ---------- */

const GV_CLOSES = [
  9.1, 10.37, 10.74, 10.21, 11.48, 11.85, 11.32, 12.59, 12.96, 12.43, 13.7, 14.07,
  13.54, 14.81, 15.18, 14.65, 15.92, 16.29, 15.76, 17.03, 17.4, 16.87, 18.14, 18.51,
  17.98, 19.25, 19.62, 19.09, 20.36, 20.73, 20.2, 21.47, 21.84, 21.31, 22.58, 22.95,
  22.42, 23.69, 24.06, 23.53, 24.8, 25.17, 24.64, 25.91, 26.28,
]

describe('EMA（种子=首值，D8 钉死——与 TA-Lib SMA 种子差异显式声明）', () => {
  it('窗口不足返回 null；起点为 n-1', () => {
    const r = ema(GV_CLOSES, 12)
    expect(r[10]).toBeNull()
    expect(r[11]).not.toBeNull()
  })

  it('golden vector：ema12[15] / ema26[44]', () => {
    expect(ema(GV_CLOSES, 12)[15]).toBeCloseTo(13.285023, 6)
    expect(ema(GV_CLOSES, 26)[44]).toBeCloseTo(21.514743, 6)
  })
})

describe('MACD(12,26,9)', () => {
  it('DIF 自 slow-1 起非空（slow=26 → idx 25），此前为 null', () => {
    const m = macd(GV_CLOSES)
    expect(m[24].dif).toBeNull()
    expect(m[25].dif).not.toBeNull()
  })

  it('golden vector：dif/dea/hist[44]，柱=2×(DIF−DEA)', () => {
    const m = macd(GV_CLOSES)[44]
    expect(m.dif).toBeCloseTo(2.479711, 6)
    expect(m.dea).toBeCloseTo(2.399194, 6)
    expect(m.hist).toBeCloseTo(0.161033, 6)
  })
})

describe('RSI（Wilder 平滑 14）', () => {
  it('首值 SMA14 于 idx 14，此前 null', () => {
    const r = rsiWilder(GV_CLOSES)
    expect(r[13]).toBeNull()
    expect(r[14]).not.toBeNull()
  })

  it('golden vector：rsi[29] / rsi[44]', () => {
    const r = rsiWilder(GV_CLOSES)
    expect(r[29]).toBeCloseTo(77.96991, 4)
    expect(r[44]).toBeCloseTo(77.469446, 4)
  })

  it('单边上涨无下跌 → 100', () => {
    expect(rsiWilder([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15])[14]).toBe(100)
  })
})

describe('BOLL(20,2) 总体标准差', () => {
  it('golden vector：mid/upper/lower[44]', () => {
    const b = boll(GV_CLOSES)[44]
    expect(b.mid).toBeCloseTo(22.495, 6)
    expect(b.upper).toBeCloseTo(26.841044, 6)
    expect(b.lower).toBeCloseTo(18.148956, 6)
  })
})

describe('KDJ(9,3,3) 递推初值 50', () => {
  const bars = Array.from({ length: 45 }, (_, i) => ({
    high: 10.8 + 0.3 * i,
    low: 10.0 + 0.3 * i,
    close: 10.15 + 0.3 * i,
  }))

  it('首值于 idx 8，此前 null', () => {
    expect(kdj(bars)[7].k).toBeNull()
    expect(kdj(bars)[8].k).not.toBeNull()
  })

  it('golden vector：k/d/j[44]，J=3K−2D', () => {
    const p = kdj(bars)[44]
    expect(p.k).toBeCloseTo(79.687491, 6)
    expect(p.d).toBeCloseTo(79.687379, 6)
    expect(p.j).toBeCloseTo(79.687714, 6)
  })
})
