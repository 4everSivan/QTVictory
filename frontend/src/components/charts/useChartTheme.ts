import { useSyncExternalStore } from 'react'
import { CHART_THEMES, onThemeChange, DEFAULT_THEME, getTheme, type ChartTheme } from '../../theme'

/** 图表主题（01 §3.1）：window.__THEME 由 theme.ts 单一写入口维护，主题切换实时刷新 */
export function useChartTheme(): ChartTheme {
  return useSyncExternalStore(
    (onStoreChange) => onThemeChange(() => onStoreChange()),
    () => CHART_THEMES[getTheme()] ?? CHART_THEMES[DEFAULT_THEME],
  )
}
