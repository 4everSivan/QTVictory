/**
 * 输入层即时校验（01 §6.1 体验层，非安全边界——最终以后端校验为准）。
 * 口径与 backend app/domain/engine.py 逐行对齐（v1 前端 TRADE.* 废止后的等价纯函数）。
 */
import type { BookLevel } from '../api/types'

export type BoardKind = 'main' | 'gem' | 'star'

function stripPrefix(code: string): string {
  return code.slice(0, 2) in { sh: 1, sz: 1, bj: 1 } && code.length > 6 ? code.slice(2) : code
}

export function boardKind(code: string): BoardKind {
  const bare = stripPrefix(code)
  if (bare.startsWith('68')) return 'star'
  if (bare.startsWith('30')) return 'gem'
  return 'main'
}

export function boardLabel(kind: BoardKind): string {
  return kind === 'star' ? '科创板' : kind === 'gem' ? '创业板' : '主板'
}

export const LOT_RULE_TEXT = '主板/创业板 100 股整数倍；科创板 ≥200 股后 1 股递增，零股须一次卖出'

/** 申报单位校验（engine.lot_ok 等价） */
export function lotOk(code: string, qty: number, posQty = 0, isSell = false): boolean {
  if (!Number.isInteger(qty) || qty <= 0) return false
  if (stripPrefix(code).startsWith('68')) {
    if (isSell) {
      return posQty < 200 ? qty === posQty : qty >= 200
    }
    return qty >= 200
  }
  return qty % 100 === 0
}

export function lotError(code: string, qty: number, posQty = 0, isSell = false): string | null {
  if (lotOk(code, qty, posQty, isSell)) return null
  const kind = boardKind(code)
  if (kind === 'star') {
    if (isSell && posQty > 0 && posQty < 200 && qty !== posQty) {
      return `科创板零股须一次性卖出（当前持仓 ${posQty} 股）`
    }
    return `科创板申报数量须 ≥200 股（当前 ${qty || '--'}）`
  }
  return `${boardLabel(kind)}申报数量须为 100 股整数倍（当前 ${qty || '--'}）`
}

export function limitPct(code: string): number {
  const kind = boardKind(code)
  return kind === 'star' || kind === 'gem' ? 20 : 10
}

/** 涨跌停带 */
export function limitBand(prevClose: number, code: string): [number, number] {
  const k = limitPct(code) / 100
  return [round2(prevClose * (1 - k)), round2(prevClose * (1 + k))]
}

/**
 * 有效申报区间 = 涨跌停带 ∩ 连续竞价 ±2%（§6.1）；
 * 无档位时取最新价（engine.valid_band 等价）。
 */
export function effectiveBand(
  side: 'buy' | 'sell',
  code: string,
  prevClose: number,
  last: number,
  bids: BookLevel[],
  asks: BookLevel[],
): [number, number] {
  const [lo, hi] = limitBand(prevClose, code)
  if (side === 'buy') {
    const ref = asks[0] ? asks[0][0] : last
    return [lo, Math.min(hi, round2(ref * 1.02))]
  }
  const ref = bids[0] ? bids[0][0] : last
  return [Math.max(lo, round2(ref * 0.98)), hi]
}

export function priceBandError(
  price: number,
  side: 'buy' | 'sell',
  code: string,
  prevClose: number,
  last: number,
  bids: BookLevel[],
  asks: BookLevel[],
): string | null {
  const [lo, hi] = limitBand(prevClose, code)
  if (price < lo || price > hi) {
    return `超出涨跌停带 ${lo.toFixed(2)}–${hi.toFixed(2)}`
  }
  const [elo, ehi] = effectiveBand(side, code, prevClose, last, bids, asks)
  if (price < elo || price > ehi) {
    return `超出连续竞价 ±2% 有效申报区间 ${elo.toFixed(2)}–${ehi.toFixed(2)}；涨跌停带 ${lo.toFixed(2)}–${hi.toFixed(2)}`
  }
  return null
}

/* ---- 费用与市价预估（engine.calc_fee 等价） ------------------------- */

export interface FeeEst {
  commission: number
  stampTax: number
  transferFee: number
  total: number
}

export function calcFee(amount: number, isBuy: boolean): FeeEst {
  const commission = round2(Math.max(amount * 0.00025, 5.0))
  const stampTax = isBuy ? 0 : round2(amount * 0.0005)
  const transferFee = round2(amount * 0.00001)
  return { commission, stampTax, transferFee, total: round2(commission + stampTax + transferFee) }
}

/** 市价单金额预估：最优五档剩余撤销=逐档吃量加权；对手方最优=对手一档价（可能部分成交） */
export function marketAmountEst(
  side: 'buy' | 'sell',
  qty: number,
  last: number,
  bids: BookLevel[],
  asks: BookLevel[],
  marketType: 'best5_cancel' | 'opponent_best',
): { estPrice: number; fillableQty: number; note: string } {
  const book = side === 'buy' ? asks : bids
  if (marketType === 'opponent_best') {
    const l1 = book[0]
    return {
      estPrice: l1 ? l1[0] : last,
      fillableQty: l1 ? Math.min(qty, l1[1]) : 0,
      note: '按对手方最优价估算，实际按成交回报',
    }
  }
  let remain = qty
  let amount = 0
  for (const [p, v] of book) {
    if (remain <= 0) break
    const take = Math.min(remain, v)
    amount += take * p
    remain -= take
  }
  const filled = qty - remain
  return {
    estPrice: filled > 0 ? amount / filled : last,
    fillableQty: filled,
    note: '按五档加权近似，实际按成交回报',
  }
}

/* ---- 撤单禁用窗口（§4.8：集合竞价 9:20–9:25） ------------------------ */

export function cancelDisabled(nowHHMM: string, phase: string): boolean {
  if (phase !== 'auction') return false
  return nowHHMM >= '09:20' && nowHHMM <= '09:25'
}

function round2(n: number): number {
  return Math.round(n * 100) / 100
}
