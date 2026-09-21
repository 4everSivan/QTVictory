import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { KlineRow } from '../../api/types'
import type { KlinePeriod } from '../../state/marketData'
import {
  boll,
  clampView,
  defaultView,
  ema,
  kdj,
  linearScale,
  macd,
  maSeries,
  pan,
  rsiWilder,
  zoom,
  type ViewWindow,
} from './math'
import { useChartSize } from './useChartSize'
import { useChartTheme } from './useChartTheme'

const PAD_L = 4
const PAD_R = 58
const PAD_T = 26
const DATE_AXIS = 16
const SUB_RATIO = 0.22 // D3：副图高度比例 0.20 → 0.22
const MA_STEPS = [5, 10, 20, 60] as const

/** D6 指标色阶（用户拍板）：ind1 白 / ind2 黄 / ind3 紫 / ind4 青 / ind5 橙；红绿专属涨跌 */
type OverlayId = 'ma' | 'ema' | 'boll'
type SubId = 'vol' | 'macd' | 'rsi' | 'kdj'

/** 图例周期标签（T27-1/D5） */
const PERIOD_LABELS: Record<KlinePeriod, string> = {
  day: '日K',
  week: '周K',
  month: '月K',
}

interface KLineChartProps {
  klines: KlineRow[]
  /** 周期（T27-1）：影响图例/日期轴口径与默认副图（分时态不渲染本组件） */
  period?: KlinePeriod
  /** 副图指标（C021：控件沉底 ca-foot，状态由 ChartArea 持有传入） */
  sub?: SubId
  /** 主图叠加集合（C021：控件归位顶栏 ca-bar，状态由 ChartArea 持有传入） */
  overlays?: OverlayId[]
}

/**
 * K 线图（01 §5.1 全交互定稿 + §5.5 D1–D8）：
 * 默认 90 根 / 滚轮缩放 ×1.18（30~N）/ 拖拽平移 / 双击复位 /
 * 单副图槽位（VOL｜MACD｜RSI｜KDJ，0.22）/ 主图叠加（MA｜EMA｜BOLL 独立开关可同开）/
 * 指标色阶令牌 / 图例（日期+OHLC+涨跌幅+叠加当前值）/ 十字光标 / 仅渲染可见区间。
 * MA 透明度阶梯废止改色相阶梯（§5.1 修订项，浅色对比度修复）。
 */
export function KLineChart({
  klines,
  period = 'day',
  sub = 'vol',
  overlays = ['ma'],
}: KLineChartProps) {
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
  const emas = useMemo(
    () => ({ 12: ema(closes, 12), 26: ema(closes, 26) }),
    [closes],
  )
  const bolls = useMemo(() => boll(closes, 20, 2), [closes])
  const macdSeries = useMemo(() => (sub === 'macd' ? macd(closes) : null), [sub, closes])
  const rsiSeries = useMemo(() => (sub === 'rsi' ? rsiWilder(closes) : null), [sub, closes])
  const kdjSeries = useMemo(
    () => (sub === 'kdj' ? kdj(klines.map((k) => ({ high: k.high, low: k.low, close: k.close }))) : null),
    [sub, klines],
  )

  const start = Math.max(0, view.end - view.count)
  const visible = klines.slice(start, view.end)

  const plotH = height - PAD_T - DATE_AXIS
  const subH = plotH * SUB_RATIO
  const priceH = plotH - subH
  const lo = Math.min(...visible.map((k) => k.low))
  const hi = Math.max(...visible.map((k) => k.high))
  const y = linearScale([lo, hi], [PAD_T + priceH, PAD_T])

  // 副图纵轴（按指标各自口径）
  const subRange = useMemo<[number, number]>(() => {
    if (sub === 'rsi' || sub === 'kdj') return [0, 100]
    if (sub === 'macd') {
      const vals: number[] = []
      for (let i = start; i < view.end; i += 1) {
        const p = macdSeries?.[i]
        if (!p) continue
        if (p.dif !== null) vals.push(p.dif)
        if (p.dea !== null) vals.push(p.dea)
        if (p.hist !== null) vals.push(p.hist)
      }
      if (vals.length === 0) return [-1, 1]
      const m = Math.max(...vals.map(Math.abs), 1e-9)
      return [-m, m]
    }
    const maxVol = Math.max(...visible.map((k) => k.volume), 1)
    return [0, maxVol]
  }, [sub, macdSeries, start, view.end, visible])
  const ySub = linearScale(subRange, [PAD_T + plotH, PAD_T + priceH + 2])

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

  // 光标根（无光标显最新根，D5；C021⑤：cross < total 守卫防空数据越界）
  const focusIdx =
    cross !== null && cross >= start && cross < view.end && cross < total
      ? cross
      : total - 1
  const focus = total > 0 ? klines[focusIdx] : null
  const focusPrev = focusIdx > 0 ? klines[focusIdx - 1].close : null
  const focusPct =
    focus && focusPrev && focusPrev > 0 ? ((focus.close - focusPrev) / focusPrev) * 100 : null

  const maColor = (n: number): string =>
    n === 5 ? theme.ind1 : n === 10 ? theme.ind2 : n === 20 ? theme.ind3 : theme.ind5

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
          {/* 图例（D5）：主图左上 = 日期 + OHLC + 涨跌幅 + 叠加当前值；无光标显最新根 */}
          {focus && (
            <g data-testid="kline-legend">
              <text x={PAD_L + 4} y={12} fontSize={10} fill={theme.txt2}>
                <tspan fill={theme.txt2}>{`${PERIOD_LABELS[period]} ${focus.date} `}</tspan>
                <tspan fill={theme.txt2}>{`开 ${focus.open.toFixed(2)}  高 ${focus.high.toFixed(2)}  低 ${focus.low.toFixed(2)}  收 ${focus.close.toFixed(2)}`}</tspan>
                {focusPct !== null && (
                  <tspan fill={focusPct >= 0 ? theme.up : theme.down}>{`  ${focusPct >= 0 ? '+' : ''}${focusPct.toFixed(2)}%`}</tspan>
                )}
              </text>
              <text x={PAD_L + 4} y={22} fontSize={9}>
                {overlays.includes('ma') &&
                  MA_STEPS.map((n) => {
                    const v = mas[n][focusIdx]
                    return v === null ? null : (
                      <tspan key={`ma${n}`} fill={maColor(n)}>{`MA${n} ${v.toFixed(2)}  `}</tspan>
                    )
                  })}
                {overlays.includes('ema') && (
                  <>
                    <tspan fill={theme.ind4}>{`EMA12 ${(emas[12][focusIdx] ?? 0).toFixed(2)}  `}</tspan>
                    <tspan fill={theme.ind4}>{`EMA26 ${(emas[26][focusIdx] ?? 0).toFixed(2)}  `}</tspan>
                  </>
                )}
                {overlays.includes('boll') && bolls[focusIdx].mid !== null && (
                  <tspan fill={theme.txt3}>{`BOLL ${(bolls[focusIdx].upper ?? 0).toFixed(2)}/${(bolls[focusIdx].mid ?? 0).toFixed(2)}/${(bolls[focusIdx].lower ?? 0).toFixed(2)}`}</tspan>
                )}
              </text>
            </g>
          )}

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

          {/* BOLL 填充（先画底，再画蜡烛） */}
          {overlays.includes('boll') && (() => {
            const top: string[] = []
            const bottom: string[] = []
            for (let i = 0; i < visible.length; i += 1) {
              const p = bolls[start + i]
              if (p.mid === null || p.upper === null || p.lower === null) continue
              top.push(`${x(i)},${y(p.upper)}`)
              bottom.push(`${x(i)},${y(p.lower)}`)
            }
            if (top.length < 2) return null
            return (
              <polygon
                points={`${top.join(' ')} ${bottom.reverse().join(' ')}`}
                fill={theme.txt3}
                opacity={0.06}
              />
            )
          })()}

          {/* 蜡烛：仅可见区间 */}
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
              </g>
            )
          })}

          {/* MA：色相阶梯（透明度阶梯废止，§5.1 修订项）；MA60 ind5 虚线 */}
          {overlays.includes('ma') &&
            MA_STEPS.map((n) => {
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
                  stroke={maColor(n)}
                  strokeWidth={1}
                  strokeDasharray={n === 60 ? '5 4' : undefined}
                />
              )
            })}

          {/* EMA：族内同色（ind4 青），EMA26 虚线 */}
          {overlays.includes('ema') &&
            ([12, 26] as const).map((n) => {
              const series = n === 12 ? emas[12] : emas[26]
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
                  stroke={theme.ind4}
                  strokeWidth={1}
                  strokeDasharray={n === 26 ? '5 4' : undefined}
                />
              )
            })}

          {/* BOLL 轨道：上下轨 txt3 细线，中轨 ind1 白虚线 */}
          {overlays.includes('boll') &&
            (['upper', 'mid', 'lower'] as const).map((band) => {
              const pts: string[] = []
              for (let i = 0; i < visible.length; i += 1) {
                const p = bolls[start + i]
                const v = band === 'upper' ? p.upper : band === 'lower' ? p.lower : p.mid
                if (typeof v === 'number') pts.push(`${x(i)},${y(v)}`)
              }
              if (pts.length < 2) return null
              return (
                <polyline
                  key={band}
                  points={pts.join(' ')}
                  fill="none"
                  stroke={band === 'mid' ? theme.ind1 : theme.txt3}
                  strokeWidth={1}
                  strokeDasharray={band === 'mid' ? '4 4' : undefined}
                  opacity={band === 'mid' ? 0.9 : 0.7}
                />
              )
            })}

          {/* 副图（单槽位 0.22）：VOL｜MACD｜RSI｜KDJ */}
          <g data-testid="kline-sub">
            <line
              x1={PAD_L}
              x2={width - PAD_R}
              y1={PAD_T + priceH + 2}
              y2={PAD_T + priceH + 2}
              stroke={theme.line}
              strokeWidth={1}
            />
            {sub === 'rsi' &&
              ([30, 70] as const).map((t) => (
                <line
                  key={t}
                  x1={PAD_L}
                  x2={width - PAD_R}
                  y1={ySub(t)}
                  y2={ySub(t)}
                  stroke={theme.txt3}
                  strokeWidth={1}
                  strokeDasharray="3 3"
                  opacity={0.5}
                />
              ))}
            {sub === 'kdj' &&
              ([20, 80] as const).map((t) => (
                <line
                  key={t}
                  x1={PAD_L}
                  x2={width - PAD_R}
                  y1={ySub(t)}
                  y2={ySub(t)}
                  stroke={theme.txt3}
                  strokeWidth={1}
                  strokeDasharray="3 3"
                  opacity={0.5}
                />
              ))}
            {sub === 'macd' && (
              <line
                x1={PAD_L}
                x2={width - PAD_R}
                y1={ySub(0)}
                y2={ySub(0)}
                stroke={theme.txt3}
                strokeWidth={1}
                strokeDasharray="3 3"
                opacity={0.5}
              />
            )}

            {sub === 'vol' &&
              visible.map((k, i) => {
                const up = k.close >= k.open
                return (
                  <rect
                    key={`v-${k.date}`}
                    x={x(i) - candleW / 2}
                    y={ySub(k.volume)}
                    width={candleW}
                    height={Math.max(0, ySub(0) - ySub(k.volume))}
                    fill={up ? theme.up : theme.down}
                    opacity={0.35}
                  />
                )
              })}

            {sub === 'macd' &&
              macdSeries &&
              visible.map((k, i) => {
                const p = macdSeries[start + i]
                if (!p || p.hist === null) return null
                const up = p.hist >= 0
                return (
                  <rect
                    key={`m-${k.date}`}
                    x={x(i) - candleW / 2}
                    y={ySub(Math.max(p.hist, 0))}
                    width={candleW}
                    height={Math.max(1, Math.abs(ySub(p.hist) - ySub(0)))}
                    fill={up ? theme.up : theme.down}
                    opacity={0.7}
                  />
                )
              })}
            {sub === 'macd' &&
              (['dif', 'dea'] as const).map((band, bi) => {
                const pts: string[] = []
                for (let i = 0; i < visible.length; i += 1) {
                  const v = macdSeries?.[start + i]?.[band] ?? null
                  if (typeof v === 'number') pts.push(`${x(i)},${ySub(v)}`)
                }
                if (pts.length < 2) return null
                return (
                  <polyline
                    key={band}
                    points={pts.join(' ')}
                    fill="none"
                    stroke={bi === 0 ? theme.ind1 : theme.ind2}
                    strokeWidth={1}
                  />
                )
              })}

            {sub === 'rsi' &&
              (() => {
                const pts: string[] = []
                for (let i = 0; i < visible.length; i += 1) {
                  const v = rsiSeries?.[start + i] ?? null
                  if (typeof v === 'number') pts.push(`${x(i)},${ySub(v)}`)
                }
                if (pts.length < 2) return null
                return <polyline points={pts.join(' ')} fill="none" stroke={theme.ind3} strokeWidth={1} />
              })()}

            {sub === 'kdj' &&
              (['k', 'd', 'j'] as const).map((band) => {
                const pts: string[] = []
                for (let i = 0; i < visible.length; i += 1) {
                  const v = kdjSeries?.[start + i]?.[band] ?? null
                  if (typeof v === 'number') pts.push(`${x(i)},${ySub(v)}`)
                }
                if (pts.length < 2) return null
                return (
                  <polyline
                    key={band}
                    points={pts.join(' ')}
                    fill="none"
                    stroke={band === 'k' ? theme.ind1 : band === 'd' ? theme.ind2 : theme.ind3}
                    strokeWidth={band === 'j' ? 1 : 1.2}
                  />
                )
              })}
          </g>

          {/* 副图图例（左上 = 指标名(参数) + 当前值） */}
          <g data-testid="kline-legend-sub">
            <text x={PAD_L + 4} y={PAD_T + priceH + 12} fontSize={9}>
              {sub === 'vol' && <tspan fill={theme.txt3}>VOL</tspan>}
              {sub === 'macd' && (
                <>
                  <tspan fill={theme.txt2}>MACD(12,26,9) </tspan>
                  <tspan fill={theme.ind1}>{`DIF ${(macdSeries?.[focusIdx]?.dif ?? 0).toFixed(2)} `}</tspan>
                  <tspan fill={theme.ind2}>{`DEA ${(macdSeries?.[focusIdx]?.dea ?? 0).toFixed(2)} `}</tspan>
                  <tspan fill={theme.txt3}>{`柱 ${(macdSeries?.[focusIdx]?.hist ?? 0).toFixed(2)}`}</tspan>
                </>
              )}
              {sub === 'rsi' && (
                <>
                  <tspan fill={theme.txt2}>RSI(14) </tspan>
                  <tspan fill={theme.ind3}>{(rsiSeries?.[focusIdx] ?? 0).toFixed(2)}</tspan>
                </>
              )}
              {sub === 'kdj' && (
                <>
                  <tspan fill={theme.txt2}>KDJ(9,3,3) </tspan>
                  <tspan fill={theme.ind1}>{`K ${(kdjSeries?.[focusIdx]?.k ?? 0).toFixed(2)} `}</tspan>
                  <tspan fill={theme.ind2}>{`D ${(kdjSeries?.[focusIdx]?.d ?? 0).toFixed(2)} `}</tspan>
                  <tspan fill={theme.ind3}>{`J ${(kdjSeries?.[focusIdx]?.j ?? 0).toFixed(2)}`}</tspan>
                </>
              )}
            </text>
          </g>

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

          {/* 十字光标（C021⑤：空数据越界守卫——cross < total） */}
          {cross !== null && cross >= start && cross < view.end && cross < total && (
            <g>
              <line x1={x(cross - start)} x2={x(cross - start)} y1={PAD_T} y2={PAD_T + plotH} stroke={theme.crosshair} strokeDasharray="3 3" />
              <line x1={PAD_L} x2={width - PAD_R} y1={y(klines[cross].close)} y2={y(klines[cross].close)} stroke={theme.crosshair} strokeDasharray="3 3" />
            </g>
          )}
        </svg>
      )}
    </div>
  )
}
