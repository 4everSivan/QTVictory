import { describe, expect, it } from 'vitest'
import type { Quote } from '../api/types'
import { arrangeWatchRows, rememberName } from './watchlist'

function q(code: string, name = code): Quote {
  return { code, name, last: 10, prevClose: 9.9, open: 10, high: 10.1, low: 9.9, volume: 1000, bids: [], asks: [] }
}

function entry(code: string, addedAt: string) {
  return { code, addedAt }
}

describe('自选股列表编排（T24-1，01 §4.2 v5 分组与排序）', () => {
  it('自选集置顶且保持 addedAt 倒序，动态项保持 quotes 包络原顺序', () => {
    const rows = arrangeWatchRows(
      [q('sh600519'), q('sz000001'), q('sh000300'), q('sh601318')],
      [entry('sh601318', '2026-09-18T14:00:00'), entry('sz000001', '2026-09-18T13:00:00')],
    )
    expect(rows.map((r) => r.code)).toEqual(['sh601318', 'sz000001', 'sh600519', 'sh000300'])
    expect(rows.map((r) => r.pinned)).toEqual([true, true, false, false])
  })

  it('自选项暂无行情快照时以占位行置顶（名称取添加回执缓存）', () => {
    rememberName('sh601318', '中国平安')
    const rows = arrangeWatchRows([q('sh600519')], [entry('sh601318', '2026-09-18T14:00:00')])
    expect(rows[0]).toMatchObject({ code: 'sh601318', name: '中国平安', quote: null, pinned: true })
    expect(rows[1]).toMatchObject({ code: 'sh600519', pinned: false })
  })

  it('占位行无名称缓存时回落代码展示', () => {
    const rows = arrangeWatchRows([], [entry('sz000002', '2026-09-18T14:00:00')])
    expect(rows[0]).toMatchObject({ code: 'sz000002', name: '', quote: null, pinned: true })
  })

  it('删除自选后仍被持仓/计划引用的码回落动态项区保留展示', () => {
    const quotes = [q('sh600519'), q('sz000001')]
    const before = arrangeWatchRows(quotes, [entry('sz000001', '2026-09-18T13:00:00')])
    expect(before.map((r) => r.code)).toEqual(['sz000001', 'sh600519'])
    const after = arrangeWatchRows(quotes, [])
    expect(after.find((r) => r.code === 'sz000001')).toMatchObject({ pinned: false })
    expect(after.map((r) => r.code)).toEqual(['sh600519', 'sz000001'])
  })

  it('行情快照名称优先于名称缓存', () => {
    rememberName('sh601318', '缓存名')
    const rows = arrangeWatchRows([q('sh601318', '中国平安')], [entry('sh601318', '2026-09-18T14:00:00')])
    expect(rows[0].name).toBe('中国平安')
    expect(rows[0].quote?.last).toBe(10)
  })
})
