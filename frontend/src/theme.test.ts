import { describe, expect, it, beforeEach } from 'vitest'
import { lsClear, lsGet, lsSet } from './lib/storage'
import {
  applyTheme,
  CHART_THEMES,
  getTheme,
  initTheme,
  THEMES,
  toggleTheme,
} from './theme'

describe('theme 模块（01 §3.1/§3.3 双主题）', () => {
  beforeEach(() => {
    lsClear()
    document.documentElement.removeAttribute('data-theme')
  })

  it('默认主题为 nothing 基线', () => {
    expect(getTheme()).toBe('nothing')
  })

  it('非法持久化值回落默认主题', () => {
    lsSet('qtv_theme', 'bogus')
    expect(getTheme()).toBe('nothing')
  })

  it('applyTheme 同步 data-theme、window.__THEME 与持久化', () => {
    applyTheme('terminal')
    expect(document.documentElement.dataset.theme).toBe('terminal')
    expect(window.__THEME).toBe(CHART_THEMES.terminal)
    expect(lsGet('qtv_theme')).toBe('terminal')
  })

  it('toggleTheme 在两套皮肤间往返', () => {
    expect(toggleTheme()).toBe('terminal')
    expect(toggleTheme()).toBe('nothing')
  })

  it('initTheme 恢复持久化主题并写入 __THEME', () => {
    lsSet('qtv_theme', 'terminal')
    expect(initTheme()).toBe('terminal')
    expect(window.__THEME).toBe(CHART_THEMES.terminal)
  })

  it('主题集合与设计定稿一致（基线 + 备选）', () => {
    expect(THEMES).toEqual(['nothing', 'terminal'])
  })
})
