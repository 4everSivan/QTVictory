import { useSyncExternalStore } from 'react'
import { CHART_THEMES, getMode, onThemeChange, resolveTheme, type ChartTheme } from '../../theme'

/** 图表主题（01 §3.1，C002）：window.__THEME 由 theme.ts 单一写入口维护，主题切换实时刷新 */
export function useChartTheme(): ChartTheme {
  return useSyncExternalStore(
    (onStoreChange) => onThemeChange(() => onStoreChange()),
    () => CHART_THEMES[resolveTheme(getMode())],
  )
}
