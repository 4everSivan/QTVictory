import { useEffect, useState } from 'react'
import type { Quote } from '../../api/types'
import {
  fetchKlinePeriod,
  klineKey,
  loadKlinePeriod,
  minuteKey,
  saveKlinePeriod,
  useCache,
  type KlinePeriod,
} from '../../state/marketData'
import type { KlineRow, MinuteRow } from '../../api/types'
import { KLineChart } from './KLineChart'
import { MinuteChart } from './MinuteChart'

type ChartTab = 'minute' | KlinePeriod

const TABS: ReadonlyArray<[ChartTab, string]> = [
  ['minute', '分时'],
  ['day', '日K'],
  ['week', '周K'],
  ['month', '月K'],
]

interface ChartAreaProps {
  code: string | null
  quote: Quote | null
}

/**
 * 图表区（01 §4.5 v1 定稿 + §5.5 D1）：Tab 胶丸四枚（分时｜日K｜周K｜月K）+
 * 点阵底图表框 + 右上操作提示。数据直读 T17 预取缓存；周期选择经
 * lib/storage 持久化，切换缺键时按 period 拉取（T27-1）。
 */
export function ChartArea({ code, quote }: ChartAreaProps) {
  const [tab, setTab] = useState<ChartTab>(loadKlinePeriod)
  const period: KlinePeriod = tab === 'minute' ? 'day' : tab
  const klines = useCache<KlineRow[]>(code && tab !== 'minute' ? klineKey(code, period) : null)
  const minutes = useCache<MinuteRow[]>(code ? minuteKey(code) : null)
  const prevClose = quote && quote.prevClose > 0 ? quote.prevClose : 0

  useEffect(() => {
    if (code && tab !== 'minute') fetchKlinePeriod(code, period)
  }, [code, tab, period])

  return (
    <div className="chart-area" data-testid="chart-area">
      <div className="ca-bar">
        <div className="ca-tabs" role="tablist">
          {TABS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              className={`ca-tab ${tab === key ? 'active' : ''}`}
              onClick={() => {
                setTab(key)
                if (key !== 'minute') saveKlinePeriod(key)
              }}
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
          <KLineChart klines={klines ?? []} period={period} />
        )}
      </div>
    </div>
  )
}
