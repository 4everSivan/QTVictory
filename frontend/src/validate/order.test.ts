import { describe, expect, it } from 'vitest'
import type { BookLevel } from '../api/types'
import {
  boardKind,
  calcFee,
  cancelDisabled,
  effectiveBand,
  limitBand,
  limitPct,
  lotError,
  lotOk,
  marketAmountEst,
  priceBandError,
} from './order'

const bids: BookLevel[] = [[9.98, 300], [9.97, 500]]
const asks: BookLevel[] = [[10.02, 200], [10.03, 400]]

describe('申报单位（engine.lot_ok 等价）', () => {
  it('主板/创业板 100 股整数倍', () => {
    expect(lotOk('600519', 100)).toBe(true)
    expect(lotOk('600519', 150)).toBe(false)
    expect(lotOk('sz300001', 200)).toBe(true)
    expect(lotError('600519', 150)).toContain('100 股整数倍')
  })

  it('科创板：买入 ≥200；零股一次性卖出', () => {
    expect(lotOk('sh688001', 199)).toBe(false)
    expect(lotOk('sh688001', 200)).toBe(true)
    expect(lotOk('sh688001', 201)).toBe(true)
    expect(lotOk('sh688001', 50, 50, true)).toBe(true)
    expect(lotOk('sh688001', 30, 50, true)).toBe(false)
    expect(lotOk('sh688001', 300, 500, true)).toBe(true)
    expect(lotError('sh688001', 30, 50, true)).toContain('零股须一次性卖出')
  })

  it('正股数与整数校验', () => {
    expect(lotOk('600519', 0)).toBe(false)
    expect(lotOk('600519', -100)).toBe(false)
    expect(lotOk('600519', 100.5)).toBe(false)
  })
})

describe('涨跌停带与有效申报区间（§6.1）', () => {
  it('板块涨跌幅：主板 10% / 创业·科创 20%', () => {
    expect(limitPct('600519')).toBe(10)
    expect(limitPct('sz300001')).toBe(20)
    expect(limitPct('sh688001')).toBe(20)
  })

  it('涨跌停带按昨收对称', () => {
    expect(limitBand(10, '600519')).toEqual([9, 11])
    expect(limitBand(10, 'sh688001')).toEqual([8, 12])
  })

  it('有效区间 = 涨跌停带 ∩ ±2%（买取卖一、卖取买一，无档位取最新价）', () => {
    expect(effectiveBand('buy', '600519', 10, 10, bids, asks)).toEqual([9, 10.22])
    expect(effectiveBand('sell', '600519', 10, 10, bids, asks)).toEqual([9.78, 11])
    expect(effectiveBand('buy', '600519', 10, 10.5, [], [])).toEqual([9, 10.71])
  })

  it('越界文案给出两区间', () => {
    const err = priceBandError(10.5, 'buy', '600519', 10, 10, bids, asks)
    expect(err).toContain('±2%')
    expect(err).toContain('涨跌停带 9.00–11.00')
    const limitErr = priceBandError(11.5, 'buy', '600519', 10, 10, bids, asks)
    expect(limitErr).toContain('涨跌停带')
  })
})

describe('费用与市价预估（engine.calc_fee 等价）', () => {
  it('佣金 max(amt×0.00025, 5)；印花税卖出 0.0005；过户费 0.0001', () => {
    const buy = calcFee(10_000, true)
    expect(buy.commission).toBe(5)
    expect(buy.stampTax).toBe(0)
    expect(buy.transferFee).toBe(1)
    const sell = calcFee(100_000, false)
    expect(sell.commission).toBe(25)
    expect(sell.stampTax).toBe(50)
    expect(sell.transferFee).toBe(10)
    expect(sell.total).toBe(85)
  })

  it('最优五档剩余撤销：逐档吃量加权，不足标 fillableQty', () => {
    const est = marketAmountEst('buy', 500, 10, bids, asks, 'best5_cancel')
    expect(est.fillableQty).toBe(200 + 400 < 500 ? 600 : 500)
    expect(est.estPrice).toBeCloseTo((200 * 10.02 + 300 * 10.03) / 500)
    const small = marketAmountEst('buy', 100, 10, bids, asks, 'best5_cancel')
    expect(small.estPrice).toBe(10.02)
  })

  it('对手方最优：取对手一档价，量按一档约束', () => {
    const est = marketAmountEst('buy', 500, 10, bids, asks, 'opponent_best')
    expect(est.estPrice).toBe(10.02)
    expect(est.fillableQty).toBe(200)
  })
})

describe('撤单禁用窗口（§4.8）', () => {
  it('集合竞价 9:20–9:25 禁用，其余放行', () => {
    expect(cancelDisabled('09:19', 'auction')).toBe(false)
    expect(cancelDisabled('09:20', 'auction')).toBe(true)
    expect(cancelDisabled('09:25', 'auction')).toBe(true)
    expect(cancelDisabled('09:26', 'auction')).toBe(false)
    expect(cancelDisabled('09:21', 'continuous')).toBe(false)
  })
})

describe('板块判定', () => {
  it('带/不带市场前缀均可判定', () => {
    expect(boardKind('sh688001')).toBe('star')
    expect(boardKind('688001')).toBe('star')
    expect(boardKind('sz300750')).toBe('gem')
    expect(boardKind('600519')).toBe('main')
  })
})
