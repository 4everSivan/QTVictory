import { useState } from 'react'
import type { Quote } from '../../api/types'
import { klineKey, minuteKey, useCache } from '../../state/marketData'
import type { KlineRow, MinuteRow } from '../../api/types'
import { KLineChart } from './KLineChart'
import { MinuteChart } from './MinuteChart'

interface ChartAreaProps {
  code: string | null
  quote: Quote | null
}

/**
 * 图表区（01 §4.5 v1 定稿）：Tab 胶丸（分时/日K）+ 点阵底图表框 + 右上操作提示。
 * 数据直读 T17 预取缓存（kline/minute）。
 */
export function ChartArea({ code, quote }: ChartAreaProps) {
  const [tab, setTab] = useState<'minute' | 'day'>('minute')
  const klines = useCache<KlineRow[]>(code ? klineKey(code) : null)
  const minutes = useCache<MinuteRow[]>(code ? minuteKey(code) : null)
  const prevClose = quote && quote.prevClose > 0 ? quote.prevClose : 0

  return (
    <div className="chart-area" data-testid="chart-area">
      <div className="ca-bar">
        <div className="ca-tabs" role="tablist">
          {(
            [
              ['minute', '分时'],
              ['day', '日K'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              className={`ca-tab ${tab === key ? 'active' : ''}`}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="micro-label ca-hint">滚轮缩放 · 拖拽平移 · 双击复位</span>
      </div>
      <div className="ca-body">
        {tab === 'minute' ? (
          <MinuteChart minutes={minutes ?? []} prevClose={prevClose} />
        ) : (
          <KLineChart klines={klines ?? []} />
        )}
      </div>
    </div>
  )
}
