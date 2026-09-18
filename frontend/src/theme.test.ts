import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  applyMode,
  CHART_THEMES,
  cycleMode,
  getMode,
  initTheme,
  onThemeChange,
  resolveTheme,
} from './theme'
import { lsClear } from './lib/storage'

beforeEach(() => {
  lsClear()
  delete document.documentElement.dataset.theme
  vi.unstubAllGlobals()
})

describe('theme 模块（01 §3.1 三态切换，C002）', () => {
  it('默认模式为深色（Nothing 纯黑基线），initTheme 写入 data-theme 与 window.__THEME', () => {
    expect(getMode()).toBe('dark')
    initTheme()
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(window.__THEME).toBe(CHART_THEMES.dark)
    expect(CHART_THEMES.dark.up).toBe('#d71921')
    expect(CHART_THEMES.dark.txt).toBe('#e8e8e8')
  })

  it('cycleMode 按 浅色→深色→跟随系统 循环并持久化模式', () => {
    applyMode('light')
    expect(cycleMode()).toBe('dark')
    expect(cycleMode()).toBe('system')
    expect(cycleMode()).toBe('light')
    expect(getMode()).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(window.__THEME).toBe(CHART_THEMES.light)
  })

  it('浅色套系语义色色相不变、按浅色背景调校（涨色同值，跌/警示加深保对比）', () => {
    expect(CHART_THEMES.light.up).toBe(CHART_THEMES.dark.up)
    expect(CHART_THEMES.light.down).toBe('#2e7d42')
    expect(CHART_THEMES.light.txt).toBe('#1a1a1a')
  })

  it('system 模式经 prefers-color-scheme 解析（无 matchMedia 环境回退深色）', () => {
    expect(resolveTheme('system')).toBe('dark')
    const listener: { current: (() => void) | null } = { current: null }
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: false,
      media: query,
      addEventListener: (_: string, cb: () => void) => {
        listener.current = cb
      },
    }))
    expect(resolveTheme('system')).toBe('light')
    initTheme()
    applyMode('system')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(window.__THEME).toBe(CHART_THEMES.light)
    expect(typeof listener.current).toBe('function')
  })

  it('主题切换通知订阅者（图表主题实时刷新入口）', () => {
    const seen: string[] = []
    const off = onThemeChange((t) => seen.push(t))
    applyMode('light')
    applyMode('dark')
    off()
    applyMode('light')
    expect(seen).toEqual(['light', 'dark'])
  })
})
