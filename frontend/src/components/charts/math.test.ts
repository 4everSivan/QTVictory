import { describe, expect, it } from 'vitest'
import {
  clampView,
  defaultView,
  linearScale,
  ma,
  maSeries,
  MIN_CANDLES,
  normalizePercent,
  pan,
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
