import { describe, expect, it, vi } from 'vitest'
import { ApiError } from './client'
import { ERROR_MAP, orderFieldError, presentError } from './errors'

function err(code: string, details: unknown = null, message = '后端消息'): ApiError {
  return new ApiError(400, { code, message, details })
}

describe('错误码 → 文案映射（01 §6 全表）', () => {
  it.each(Object.keys(ERROR_MAP))('码 %s 有非空文案与合法级别', (code) => {
    const p = presentError(err(code))
    expect(p.text.length).toBeGreaterThan(0)
    expect(['field', 'toast']).toContain(p.level)
  })

  it('PRICE_BAND：details 含两区间时文案同时给出', () => {
    const p = presentError(
      err('PRICE_BAND', { limitBand: [9.8, 11.2], effectiveBand: [10.5, 11.2] }),
    )
    expect(p.level).toBe('field')
    expect(p.text).toContain('10.50–11.20')
    expect(p.text).toContain('9.80–11.20')
  })

  it('PRICE_BAND：details 缺失时回落通用文案', () => {
    expect(presentError(err('PRICE_BAND')).text).toContain('有效申报范围')
  })

  it('INSUFFICIENT_FUNDS：按 details 算术渲染可用额', () => {
    const p = presentError(err('INSUFFICIENT_FUNDS', { cash: 1000, frozen: 200, need: 900 }))
    expect(p.text).toContain('900.00')
    expect(p.text).toContain('800.00')
  })

  it('T1_LOCKED：渲染持仓与锁定量', () => {
    const p = presentError(err('T1_LOCKED', { position: 500, locked: 100, need: 500 }))
    expect(p.text).toContain('500')
    expect(p.text).toContain('100')
  })

  it('STALE_QUOTE：渲染行情年龄', () => {
    expect(presentError(err('STALE_QUOTE', { ageSec: 42 })).text).toContain('42')
  })

  it('SESSION_CLOSED / RATE_LIMITED / UNAUTHORIZED 为 toast 级', () => {
    for (const code of ['SESSION_CLOSED', 'RATE_LIMITED', 'UNAUTHORIZED']) {
      expect(presentError(err(code)).level).toBe('toast')
    }
  })

  it('UNSUPPORTED_BOARD：field 级呈现白名单口径（C015）', () => {
    const p = presentError(err('UNSUPPORTED_BOARD', { code: 'sh000300' }, '品种不在可交易白名单'))
    expect(p.level).toBe('field')
    expect(p.text).toContain('白名单')
  })

  it('未识别码：回落通用文案并 console 告警（不白屏）', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const p = presentError(err('FUTURE_CODE_X'))
    expect(p.text).toContain('FUTURE_CODE_X')
    expect(warn).toHaveBeenCalledOnce()
    warn.mockRestore()
  })

  it('orderFieldError：field 级返回文案，toast 级返回 null', () => {
    expect(orderFieldError(err('LOT_SIZE'))).toContain('申报数量')
    expect(orderFieldError(err('SESSION_CLOSED'))).toBeNull()
  })
})
