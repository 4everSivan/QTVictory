import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { KlineRow } from '../../api/types'
import {
  clampView,
  defaultView,
  linearScale,
  maSeries,
  pan,
  zoom,
  type ViewWindow,
} from './math'
import { useChartSize } from './useChartSize'
import { useChartTheme } from './useChartTheme'

const PAD_L = 4
const PAD_R = 58
const PAD_T = 26
const DATE_AXIS = 16
const VOL_RATIO = 0.2
const MA_STEPS = [5, 10, 20, 60] as const
const MA_ALPHA: Record<number, number> = { 5: 1, 10: 0.55, 20: 0.32, 60: 1 }

interface KLineChartProps {
  klines: KlineRow[]
}

/**
 * 日 K（01 §5.1 全交互定稿）：
 * 默认 90 根 / 滚轮缩放 ×1.18（30~N）/ 拖拽平移 / 双击复位 /
 * 成交量子图 20% / MA5·10·20·60 透明度阶梯（MA60 灰虚线）/
 * 最新价虚线 + 右轴色块标签 / 十字光标 + OHLC 信息条 / 仅渲染可见区间。
 */
export function KLineChart({ klines }: KLineChartProps) {
  const [wrapRef, { width, height }] = useChartSize<HTMLDivElement>()
  const theme = useChartTheme()
  const total = klines.length
  const [view, setView] = useState<ViewWindow>(() => defaultView(total))
  const [cross, setCross] = useState<number | null>(null)
  const drag = useRef<{ x: number; end: number; moved: boolean } | null>(null)

  useEffect(() => {
    setView(defaultView(total))
    setCross(null)
  }, [total])

  const step = width > 0 ? (width - PAD_L - PAD_R) / view.count : 1

  const onWheel = useCallback(
    (e: WheelEvent) => {
      e.preventDefault()
      setView((v) => zoom(v, e.deltaY < 0 ? 1 : -1, total))
    },
    [total],
  )

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [wrapRef, onWheel])

  const closes = useMemo(() => klines.map((k) => k.close), [klines])
  const mas = useMemo(
    () => Object.fromEntries(MA_STEPS.map((n) => [n, maSeries(closes, n)])) as Record<number, Array<number | null>>,
    [closes],
  )

  const start = Math.max(0, view.end - view.count)
  const visible = klines.slice(start, view.end)
  const lo = Math.min(...visible.map((k) => k.low))
  const hi = Math.max(...visible.map((k) => k.high))
  const maxVol = Math.max(...visible.map((k) => k.volume), 1)

  const plotH = height - PAD_T - DATE_AXIS
  const volH = plotH * VOL_RATIO
  const priceH = plotH - volH
  const y = linearScale([lo, hi], [PAD_T + priceH, PAD_T])
  const yVol = linearScale([0, maxVol], [PAD_T + plotH, PAD_T + priceH + 2])

  const x = (i: number) => PAD_L + (i + 0.5) * step
  const candleW = Math.max(1, Math.min(step * 0.62, 40))

  const last = total > 1 ? klines[total - 1] : null
  const prevClose = total > 1 ? klines[total - 2].close : null
  const lastCls =
    last && prevClose !== null
      ? last.close > prevClose
        ? theme.up
        : last.close < prevClose
          ? theme.down
          : theme.flat
      : theme.flat

  const toIndex = (clientX: number): number => {
    const rect = wrapRef.current?.getBoundingClientRect()
    if (!rect) return start
    return Math.max(start, Math.min(view.end - 1, start + Math.floor((clientX - rect.left - PAD_L) / step)))
  }

  return (
    <div
      ref={wrapRef}
      className="chart-wrap"
      data-testid="kline-chart"
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture?.(e.pointerId)
        drag.current = { x: e.clientX, end: view.end, moved: false }
      }}
      onPointerMove={(e) => {
        if (drag.current && e.buttons === 1) {
          const dx = e.clientX - drag.current.x
          if (Math.abs(dx) > 3) drag.current.moved = true
          if (drag.current.moved) {
            setView(clampView(pan({ end: drag.current.end, count: view.count }, dx, step, total), total))
            setCross(null)
            return
          }
        }
        setCross(toIndex(e.clientX))
      }}
      onPointerUp={() => {
        drag.current = null
      }}
      onPointerLeave={() => setCross(null)}
      onDoubleClick={() => {
        setView(defaultView(total))
        setCross(null)
      }}
    >
      {width > 0 && height > 0 && (
        <svg width={width} height={height} className="chart-svg">
          {/* 最新价虚线 + 右轴色块 */}
          {last && (
            <g>
              <line
                x1={PAD_L}
                x2={width - PAD_R}
                y1={y(last.close)}
                y2={y(last.close)}
                stroke={lastCls}
                strokeWidth={1}
                strokeDasharray="4 4"
                opacity={0.7}
              />
              <rect
                x={width - PAD_R + 2}
                y={y(last.close) - 8}
                width={PAD_R - 4}
                height={16}
                fill={lastCls}
                rx={2}
              />
              <text x={width - PAD_R + 6} y={y(last.close) + 3.5} fontSize={10} fill={theme.txt}>
                {last.close.toFixed(2)}
              </text>
            </g>
          )}

          {/* 蜡烛与量柱：仅可见区间 */}
          {visible.map((k, i) => {
            const up = k.close >= k.open
            const color = up ? theme.up : theme.down
            return (
              <g key={k.date}>
                <line
                  x1={x(i)}
                  x2={x(i)}
                  y1={y(k.high)}
                  y2={y(k.low)}
                  stroke={color}
                  strokeWidth={1}
                />
                <rect
                  x={x(i) - candleW / 2}
                  y={y(Math.max(k.open, k.close))}
                  width={candleW}
                  height={Math.max(1, Math.abs(y(k.open) - y(k.close)))}
                  fill={up ? 'transparent' : color}
                  stroke={color}
                  strokeWidth={1}
                />
                <rect
                  x={x(i) - candleW / 2}
                  y={yVol(k.volume)}
                  width={candleW}
                  height={Math.max(0, yVol(0) - yVol(k.volume))}
                  fill={color}
                  opacity={0.35}
                />
              </g>
            )
          })}

          {/* MA5/10/20/60：透明度阶梯，MA60 灰虚线 */}
          {MA_STEPS.map((n) => {
            const series = mas[n]
            const pts: string[] = []
            for (let i = 0; i < visible.length; i += 1) {
              const v = series[start + i]
              if (typeof v === 'number') pts.push(`${x(i)},${y(v)}`)
            }
            if (pts.length < 2) return null
            return (
              <polyline
                key={n}
                points={pts.join(' ')}
                fill="none"
                stroke={n === 60 ? theme.txt3 : theme.txt2}
                strokeWidth={1}
                opacity={n === 60 ? 1 : MA_ALPHA[n]}
                strokeDasharray={n === 60 ? '5 4' : undefined}
              />
            )
          })}

          {/* 日期轴 */}
          {(() => {
            const every = Math.max(1, Math.ceil(view.count / 6))
            const labels: Array<{ i: number; date: string }> = []
            for (let i = 0; i < visible.length; i += every) {
              labels.push({ i, date: visible[i].date.slice(5) })
            }
            return labels.map(({ i, date }) => (
              <text key={`${date}-${i}`} x={x(i)} y={height - 4} fontSize={9} fill={theme.txt3} textAnchor="middle">
                {date}
              </text>
            ))
          })()}

          {/* 十字光标 + OHLC 信息条 */}
          {cross !== null && cross >= start && cross < view.end && (
            <g>
              <line x1={x(cross - start)} x2={x(cross - start)} y1={PAD_T} y2={PAD_T + plotH} stroke={theme.crosshair} strokeDasharray="3 3" />
              <line x1={PAD_L} x2={width - PAD_R} y1={y(klines[cross].close)} y2={y(klines[cross].close)} stroke={theme.crosshair} strokeDasharray="3 3" />
              <text x={PAD_L + 4} y={14} fontSize={10} fill={theme.txt2}>
                {`${klines[cross].date}  开 ${klines[cross].open.toFixed(2)}  高 ${klines[cross].high.toFixed(2)}  低 ${klines[cross].low.toFixed(2)}  收 ${klines[cross].close.toFixed(2)}`}
              </text>
            </g>
          )}
        </svg>
      )}
    </div>
  )
}
