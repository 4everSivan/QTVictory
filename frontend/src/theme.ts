import { lsGet, lsSet } from './lib/storage'

/** 主题模式（01 §3.1，C002）：浅色 / 深色 / 跟随系统，三态循环 */
export type ThemeMode = 'light' | 'dark' | 'system'
/** 已解析主题：system 经 prefers-color-scheme 解析为 light/dark 之一 */
export type ResolvedTheme = 'light' | 'dark'

export const THEME_MODES: readonly ThemeMode[] = ['light', 'dark', 'system']
export const DEFAULT_MODE: ThemeMode = 'dark'

export interface ChartTheme {
  up: string
  down: string
  flat: string
  line: string
  line2: string
  txt: string
  txt2: string
  txt3: string
  grid: string
  crosshair: string
  areaUp: string
  areaDown: string
  /** 指标色阶（01 §5.5 D6 用户拍板）：ind1=txt、ind2=warn 复用既有；ind3/4/5 新增令牌 */
  ind1: string
  ind2: string
  ind3: string
  ind4: string
  ind5: string
}

export const CHART_THEMES: Record<ResolvedTheme, ChartTheme> = {
  dark: {
    up: '#d71921',
    down: '#4a9e5c',
    flat: '#999999',
    line: '#1c1c1c',
    line2: '#333333',
    txt: '#e8e8e8',
    txt2: '#999999',
    txt3: '#666666',
    grid: '#1c1c1c',
    crosshair: '#333333',
    areaUp: 'rgba(215, 25, 33, 0.05)',
    areaDown: 'rgba(74, 158, 92, 0.05)',
    ind1: '#e8e8e8',
    ind2: '#d4a843',
    ind3: '#9d7cd8',
    ind4: '#4db8c4',
    ind5: '#e08a3c',
  },
  light: {
    up: '#d71921',
    down: '#2e7d42',
    flat: '#777777',
    line: '#e5e5e5',
    line2: '#cccccc',
    txt: '#1a1a1a',
    txt2: '#666666',
    txt3: '#999999',
    grid: '#ececec',
    crosshair: '#cccccc',
    areaUp: 'rgba(215, 25, 33, 0.08)',
    areaDown: 'rgba(46, 125, 66, 0.08)',
    ind1: '#1a1a1a',
    ind2: '#96700e',
    ind3: '#7c5cbf',
    ind4: '#2e8b96',
    ind5: '#c26a1a',
  },
}

const STORAGE_KEY = 'qtv_theme'

declare global {
  interface Window {
    __THEME: ChartTheme
  }
}

function isThemeMode(value: string | null): value is ThemeMode {
  return value === 'light' || value === 'dark' || value === 'system'
}

function systemTheme(): ResolvedTheme {
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return 'dark'
}

export function resolveTheme(mode: ThemeMode): ResolvedTheme {
  return mode === 'system' ? systemTheme() : mode
}

export function getMode(): ThemeMode {
  const stored = lsGet(STORAGE_KEY)
  return isThemeMode(stored) ? stored : DEFAULT_MODE
}

type ThemeListener = (theme: ResolvedTheme) => void
const themeListeners = new Set<ThemeListener>()

export function onThemeChange(listener: ThemeListener): () => void {
  themeListeners.add(listener)
  return () => {
    themeListeners.delete(listener)
  }
}

export function applyMode(mode: ThemeMode): ThemeMode {
  const resolved = resolveTheme(mode)
  document.documentElement.dataset.theme = resolved
  window.__THEME = CHART_THEMES[resolved]
  lsSet(STORAGE_KEY, mode)
  for (const listener of themeListeners) listener(resolved)
  return mode
}

export function cycleMode(): ThemeMode {
  const current = getMode()
  const next = THEME_MODES[(THEME_MODES.indexOf(current) + 1) % THEME_MODES.length]
  return applyMode(next)
}

export function initTheme(): ThemeMode {
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (getMode() === 'system') applyMode('system')
    })
  }
  return applyMode(getMode())
}
