export type ThemeName = 'nothing' | 'terminal'

export const THEMES: readonly ThemeName[] = ['nothing', 'terminal']

export const DEFAULT_THEME: ThemeName = 'nothing'

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
}

export const CHART_THEMES: Record<ThemeName, ChartTheme> = {
  nothing: {
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
  },
  terminal: {
    up: '#f04752',
    down: '#2ebd85',
    flat: '#8b98a9',
    line: '#222a38',
    line2: '#3a4a63',
    txt: '#e6edf3',
    txt2: '#8b98a9',
    txt3: '#5c6b7f',
    grid: '#222a38',
    crosshair: '#3a4a63',
    areaUp: 'rgba(240, 71, 82, 0.05)',
    areaDown: 'rgba(46, 189, 133, 0.05)',
  },
}

import { lsGet, lsSet } from './lib/storage'

const STORAGE_KEY = 'qtv_theme'

declare global {
  interface Window {
    __THEME: ChartTheme
  }
}

function isThemeName(value: string | null): value is ThemeName {
  return value === 'nothing' || value === 'terminal'
}

export function getTheme(): ThemeName {
  const stored = lsGet(STORAGE_KEY)
  return isThemeName(stored) ? stored : DEFAULT_THEME
}

export function applyTheme(theme: ThemeName): ThemeName {
  document.documentElement.dataset.theme = theme
  window.__THEME = CHART_THEMES[theme]
  lsSet(STORAGE_KEY, theme)
  for (const listener of themeListeners) listener(theme)
  return theme
}

type ThemeListener = (theme: ThemeName) => void
const themeListeners = new Set<ThemeListener>()

export function onThemeChange(listener: ThemeListener): () => void {
  themeListeners.add(listener)
  return () => {
    themeListeners.delete(listener)
  }
}

export function toggleTheme(): ThemeName {
  const next: ThemeName = getTheme() === 'nothing' ? 'terminal' : 'nothing'
  return applyTheme(next)
}

export function initTheme(): ThemeName {
  return applyTheme(getTheme())
}
