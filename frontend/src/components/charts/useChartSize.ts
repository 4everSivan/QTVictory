import { useEffect, useRef, useState, type RefObject } from 'react'

export interface ChartSize {
  width: number
  height: number
}

/**
 * 图表尺寸测量（01 §5.4 三重测量）：
 * ① ResizeObserver；② 窗口 resize 直接测量；③ 定时兜底（嵌入式 WebView RO 可能不触发）。
 */
export function useChartSize<T extends HTMLElement>(): [RefObject<T | null>, ChartSize] {
  const ref = useRef<T | null>(null)
  const [size, setSize] = useState<ChartSize>({ width: 0, height: 0 })

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const measure = () => {
      const width = el.clientWidth
      const height = el.clientHeight
      setSize((prev) => (prev.width === width && prev.height === height ? prev : { width, height }))
    }

    measure()

    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    ro?.observe(el)
    window.addEventListener('resize', measure)
    const timer = setInterval(measure, 1000)

    return () => {
      ro?.disconnect()
      window.removeEventListener('resize', measure)
      clearInterval(timer)
    }
  }, [])

  return [ref, size]
}
