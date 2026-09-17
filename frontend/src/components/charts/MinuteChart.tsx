import { useMemo, useState } from 'react'
import type { MinuteRow } from '../../api/types'
import { linearScale, MINUTE_SLOTS, slotIndexFor, slotTime, vwapFromCumulative } from './math'
import { useChartSize } from './useChartSize'
import { useChartTheme } from './useChartTheme'

const PAD_L = 4
const PAD_R = 58
const PAD_T = 12
const VOL_RATIO = 0.22

interface MinuteChartProps {
  minutes: MinuteRow[]
  prevClose: number
}

/**
 * 分时图（01 §5.2 定稿）：242 槽 / 左右双轴（价格/百分比，相对昨收着色）/
 * 价格线涨跌色 + 5% 面积 / VWAP 灰虚线（累计量差分）/ 昨收基准线 / 量柱 22%。
 */
export function MinuteChart({ minutes, prevClose }: MinuteChartProps) {
  const [wrapRef, { width, height }] = useChartSize<HTMLDivElement>()
  const theme = useChartTheme()
  const [hover, setHover] = useState<number | null>(null)

  const slots = useMemo(() => {
    const prices: Array<number | null> = Array(MINUTE_SLOTS).fill(null)
    const cums: number[] = Array(MINUTE_SLOTS).fill(0)
    for (const m of minutes) {
      const idx = slotIndexFor(m.minute)
      if (idx === null) continue
      prices[idx] = m.price
      cums[idx] = m.volume
    }
    // 前向填充价格与累计量（缺口沿用前值，保证差分非负）
    let lastPrice: number | null = null
    let lastCum = 0
    const filled = prices.map((p, i) => {
      if (p !== null && p > 0) lastPrice = p
      if (cums[i] > 0) lastCum = cums[i]
      cums[i] = lastCum
      return lastPrice
    })
    const points = filled.map((price, i) => ({ price: price ?? 0, cumVolume: cums[i] }))
    return { prices: filled, cums, vwap: vwapFromCumulative(points) }
  }, [minutes])

  const defined = slots.prices.filter((p): p is number => p !== null)
  if (defined.length === 0 || prevClose <= 0) {
    return (
      <div ref={wrapRef} className="chart-wrap" data-testid="minute-chart">
        <div className="chart-empty micro-label">分时数据积累中</div>
      </div>
    )
  }

  const lastPrice = defined[defined.length - 1]
  const up = lastPrice >= prevClose
  const lineColor = up ? theme.up : theme.down
  const lo = Math.min(...defined, prevClose)
  const hi = Math.max(...defined, prevClose)
  const span = Math.max(hi - lo, prevClose * 0.002)

  const plotH = height - PAD_T * 2
  const volH = plotH * VOL_RATIO
  const priceH = plotH - volH
  const y = linearScale([lo - span * 0.05, hi + span * 0.05], [PAD_T + priceH, PAD_T])
  const x = (i: number) => PAD_L + (i / (MINUTE_SLOTS - 1)) * (width - PAD_L - PAD_R)

  const linePts: string[] = []
  const areaPts: string[] = []
  const vwapPts: string[] = []
  for (let i = 0; i < MINUTE_SLOTS; i += 1) {
    const p = slots.prices[i]
    if (p !== null) {
      linePts.push(`${x(i)},${y(p)}`)
      areaPts.push(`${x(i)},${y(p)}`)
    }
    const v = slots.vwap[i]
    if (typeof v === 'number') vwapPts.push(`${x(i)},${y(v)}`)
  }
  areaPts.push(`${x(MINUTE_SLOTS - 1)},${y(lo)}`, `${x(0)},${y(lo)}`)

  // 量柱：相邻槽累计量差分
  const vols = slots.cums.map((c, i) => (i === 0 ? c : Math.max(0, c - slots.cums[i - 1])))
  const maxVol = Math.max(...vols, 1)
  const yVol = linearScale([0, maxVol], [PAD_T + plotH, PAD_T + priceH + 2])

  const pctTicks = [-1, -0.5, 0, 0.5, 1].map((r) => prevClose * (1 + r * 0.01))

  return (
    <div
      ref={wrapRef}
      className="chart-wrap"
      data-testid="minute-chart"
      onPointerMove={(e) => {
        const rect = e.currentTarget.getBoundingClientRect()
        const i = Math.round(((e.clientX - rect.left - PAD_L) / (width - PAD_L - PAD_R)) * (MINUTE_SLOTS - 1))
        setHover(Math.max(0, Math.min(MINUTE_SLOTS - 1, i)))
      }}
      onPointerLeave={() => setHover(null)}
    >
      {width > 0 && height > 0 && (
        <svg width={width} height={height} className="chart-svg">
          {/* 昨收基准线 */}
          <line x1={PAD_L} x2={width - PAD_R} y1={y(prevClose)} y2={y(prevClose)} stroke={theme.flat} strokeDasharray="4 4" opacity={0.7} />

          {/* 5% 面积 */}
          <polygon points={areaPts.join(' ')} fill={up ? theme.areaUp : theme.areaDown} />

          {/* 量柱 */}
          {vols.map((v, i) =>
            v > 0 ? (
              <rect key={i} x={x(i) - 1.5} y={yVol(v)} width={3} height={Math.max(0, yVol(0) - yVol(v))} fill={lineColor} opacity={0.3} />
            ) : null,
          )}

          {/* VWAP 灰虚线 */}
          {vwapPts.length > 1 && (
            <polyline points={vwapPts.join(' ')} fill="none" stroke={theme.txt3} strokeWidth={1} strokeDasharray="5 4" />
          )}

          {/* 价格线 */}
          {linePts.length > 1 && <polyline points={linePts.join(' ')} fill="none" stroke={lineColor} strokeWidth={1.4} />}

          {/* 左轴价格 / 右轴百分比 */}
          {pctTicks.map((p) => (
            <g key={p}>
              <text x={PAD_L + 2} y={y(p) - 2} fontSize={9} fill={theme.txt3}>
                {p.toFixed(2)}
              </text>
              <text x={width - PAD_R + 4} y={y(p) - 2} fontSize={9} fill={p === prevClose ? theme.txt3 : p > prevClose ? theme.up : theme.down}>
                {`${((p / prevClose - 1) * 100).toFixed(2)}%`}
              </text>
              <line x1={PAD_L} x2={width - PAD_R} y1={y(p)} y2={y(p)} stroke={theme.grid} strokeWidth={p === prevClose ? 0 : 0.5} opacity={0.5} />
            </g>
          ))}

          {/* 时间轴 */}
          {[0, 60, 121, 181, 241].map((i) => (
            <text key={i} x={x(i)} y={height - 3} fontSize={9} fill={theme.txt3} textAnchor="middle">
              {slotTime(i)}
            </text>
          ))}

          {/* 悬停十字与读数 */}
          {hover !== null && slots.prices[hover] !== null && (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={PAD_T} y2={PAD_T + plotH} stroke={theme.crosshair} strokeDasharray="3 3" />
              <text x={PAD_L + 4} y={12} fontSize={10} fill={theme.txt2}>
                {`${slotTime(hover)}  ${slots.prices[hover]?.toFixed(2) ?? '--'}  ${(((slots.prices[hover] ?? prevClose) / prevClose - 1) * 100).toFixed(2)}%`}
              </text>
            </g>
          )}
        </svg>
      )}
    </div>
  )
}
