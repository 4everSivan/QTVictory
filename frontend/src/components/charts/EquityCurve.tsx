import { useState } from 'react'
import { normalizePercent } from './math'
import { useChartSize } from './useChartSize'
import { useChartTheme } from './useChartTheme'

export interface EquityPoint {
  date: string
  value: number
}

interface EquityCurveProps {
  account: EquityPoint[]
  benchmark?: EquityPoint[]
  heightRatio?: number
}

const PAD = { l: 8, r: 8, t: 14, b: 18 }

function align(series: EquityPoint[], dates: string[]): Array<number | null> {
  const map = new Map(series.map((p) => [p.date, p.value]))
  return dates.map((d) => map.get(d) ?? null)
}

/**
 * 净值曲线（01 §5.3）：归一化百分比、双线（账户/基准）、
 * 悬停浮签（日期/账户/基准/超额）。快照 <2 日由调用方空态（§4.9）。
 */
export function EquityCurve({ account, benchmark, heightRatio = 1 }: EquityCurveProps) {
  const [wrapRef, { width, height }] = useChartSize<HTMLDivElement>()
  const theme = useChartTheme()
  const [hover, setHover] = useState<number | null>(null)

  const dates = [...new Set([...account, ...(benchmark ?? [])].map((p) => p.date))].sort()
  const n = dates.length
  const h = Math.max(120, height * heightRatio)

  if (n < 2 || width <= 0) {
    return (
      <div ref={wrapRef} className="chart-wrap equity" data-testid="equity-curve">
        <div className="chart-empty micro-label">净值数据积累中（≥2 个交易日）</div>
      </div>
    )
  }

  const acc = normalizePercent(align(account, dates).map((v) => v ?? account[0].value) as number[])
  const bench = benchmark
    ? normalizePercent(align(benchmark, dates).map((v) => v ?? benchmark[0].value) as number[])
    : null
  const all = bench ? [...acc, ...bench] : acc
  const lo = Math.min(...all)
  const hi = Math.max(...all)
  const span = Math.max(hi - lo, 1e-9)

  const x = (i: number) => PAD.l + (i / (n - 1)) * (width - PAD.l - PAD.r)
  const y = (v: number) => PAD.t + (1 - (v - lo) / span) * (h - PAD.t - PAD.b)

  const line = (vals: number[]) => vals.map((v, i) => `${x(i)},${y(v)}`).join(' ')
  const ticks = [0, Math.floor((n - 1) / 2), n - 1]

  return (
    <div
      ref={wrapRef}
      className="chart-wrap equity"
      data-testid="equity-curve"
      onPointerMove={(e) => {
        const rect = e.currentTarget.getBoundingClientRect()
        const i = Math.round(((e.clientX - rect.left - PAD.l) / (width - PAD.l - PAD.r)) * (n - 1))
        setHover(Math.max(0, Math.min(n - 1, i)))
      }}
      onPointerLeave={() => setHover(null)}
    >
      {height > 0 && (
        <svg width={width} height={h} className="chart-svg">
          <line x1={PAD.l} x2={width - PAD.r} y1={y(0)} y2={y(0)} stroke={theme.grid} strokeDasharray="3 3" />
          <polyline points={line(acc)} fill="none" stroke={theme.txt} strokeWidth={1.4} data-testid="eq-account" />
          {bench && (
            <polyline points={line(bench)} fill="none" stroke={theme.txt3} strokeWidth={1.2} strokeDasharray="5 4" data-testid="eq-benchmark" />
          )}
          {ticks.map((i) => (
            <text key={i} x={x(i)} y={h - 4} fontSize={9} fill={theme.txt3} textAnchor="middle">
              {dates[i].slice(5)}
            </text>
          ))}
          {hover !== null && (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={h - PAD.b} stroke={theme.crosshair} strokeDasharray="3 3" />
              <text x={PAD.l + 4} y={12} fontSize={10} fill={theme.txt2} data-testid="eq-tip">
                {`${dates[hover]}  账户 ${acc[hover].toFixed(2)}%${bench ? `  基准 ${bench[hover].toFixed(2)}%  超额 ${(acc[hover] - bench[hover]).toFixed(2)}%` : ''}`}
              </text>
            </g>
          )}
        </svg>
      )}
    </div>
  )
}

export interface TraderSeries {
  name: string
  points: EquityPoint[]
}

/** 多交易员对比（§5.3 可选组件 TradersCurve）：单色系内靠线型/透明度区分（§3 纪律） */
export function TradersCurve({ series }: { series: TraderSeries[] }) {
  const [wrapRef, { width, height }] = useChartSize<HTMLDivElement>()
  const theme = useChartTheme()

  const dates = [...new Set(series.flatMap((s) => s.points.map((p) => p.date)))].sort()
  const n = dates.length
  if (n < 2 || series.length === 0 || width <= 0) {
    return (
      <div ref={wrapRef} className="chart-wrap equity" data-testid="traders-curve">
        <div className="chart-empty micro-label">净值数据积累中（≥2 个交易日）</div>
      </div>
    )
  }

  const all: number[] = []
  const lines = series.map((s) => {
    const vals = normalizePercent(align(s.points, dates).map((v) => v ?? s.points[0].value) as number[])
    all.push(...vals)
    return vals
  })
  const lo = Math.min(...all)
  const hi = Math.max(...all)
  const span = Math.max(hi - lo, 1e-9)
  const h = Math.max(160, height)
  const x = (i: number) => PAD.l + (i / (n - 1)) * (width - PAD.l - PAD.r)
  const y = (v: number) => PAD.t + (1 - (v - lo) / span) * (h - PAD.t - PAD.b)
  const dash = (i: number) => (i % 3 === 1 ? '6 4' : i % 3 === 2 ? '2 3' : undefined)

  return (
    <div ref={wrapRef} className="chart-wrap equity" data-testid="traders-curve">
      {height > 0 && (
        <svg width={width} height={h} className="chart-svg">
          {lines.map((vals, i) => (
            <polyline
              key={series[i].name}
              points={vals.map((v, k) => `${x(k)},${y(v)}`).join(' ')}
              fill="none"
              stroke={theme.txt}
              strokeWidth={1.2}
              opacity={1 - (i / Math.max(series.length, 1)) * 0.55}
              strokeDasharray={dash(i)}
            />
          ))}
        </svg>
      )}
      <div className="tc-legend">
        {series.map((s) => (
          <span key={s.name} className="micro-label">
            {s.name}
          </span>
        ))}
      </div>
    </div>
  )
}
