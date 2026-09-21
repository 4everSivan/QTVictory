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
import { lsGet, lsSet } from '../../lib/storage'
import { KLineChart } from './KLineChart'
import { MinuteChart } from './MinuteChart'

type ChartTab = 'minute' | KlinePeriod
type OverlayId = 'ma' | 'ema' | 'boll'
type SubId = 'vol' | 'macd' | 'rsi' | 'kdj'

const TABS: ReadonlyArray<[ChartTab, string]> = [
  ['minute', '分时'],
  ['day', '日K'],
  ['week', '周K'],
  ['month', '月K'],
]
const OVERLAY_LABELS: ReadonlyArray<[OverlayId, string]> = [
  ['ma', 'MA'],
  ['ema', 'EMA'],
  ['boll', 'BOLL'],
]
const SUB_LABELS: ReadonlyArray<[SubId, string]> = [
  ['vol', 'VOL'],
  ['macd', 'MACD'],
  ['rsi', 'RSI'],
  ['kdj', 'KDJ'],
]

const OVERLAY_KEY = 'qtv_kline_overlays'
const SUB_KEY = 'qtv_kline_sub'

function isOverlayId(v: string | null): v is OverlayId {
  return v === 'ma' || v === 'ema' || v === 'boll'
}

function isSubId(v: string | null): v is SubId {
  return v === 'vol' || v === 'macd' || v === 'rsi' || v === 'kdj'
}

function loadOverlays(): OverlayId[] {
  const raw = lsGet(OVERLAY_KEY)
  if (raw === null) return ['ma']
  return raw.split(',').filter(isOverlayId)
}

function loadSub(): SubId {
  const stored = lsGet(SUB_KEY)
  return isSubId(stored) ? stored : 'vol'
}

interface ChartAreaProps {
  code: string | null
  quote: Quote | null
}

/**
 * 图表区（01 §4.5 v1 定稿 + §5.5 D1–D8，C021 布局修正）：
 * 顶栏 = 周期 Tab 四枚 + 叠加胶丸组（D4「顶栏第二胶丸组」）；
 * 底栏 = 副图胶丸组（用户拍板：与顶栏上下对称，修订 D2 口径）；
 * 数据直读 T17 预取缓存；周期/叠加/副图选择经 lib/storage 持久化。
 */
export function ChartArea({ code, quote }: ChartAreaProps) {
  const [tab, setTab] = useState<ChartTab>(loadKlinePeriod)
  const [overlays, setOverlays] = useState<OverlayId[]>(loadOverlays)
  const [sub, setSub] = useState<SubId>(loadSub)
  const period: KlinePeriod = tab === 'minute' ? 'day' : tab
  const klines = useCache<KlineRow[]>(code && tab !== 'minute' ? klineKey(code, period) : null)
  const minutes = useCache<MinuteRow[]>(code ? minuteKey(code) : null)
  const prevClose = quote && quote.prevClose > 0 ? quote.prevClose : 0

  useEffect(() => {
    if (code && tab !== 'minute') fetchKlinePeriod(code, period)
  }, [code, tab, period])

  const toggleOverlay = (id: OverlayId) => {
    setOverlays((cur) => {
      const next = cur.includes(id) ? cur.filter((v) => v !== id) : [...cur, id]
      lsSet(OVERLAY_KEY, next.join(','))
      return next
    })
  }

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
        {/* 顶栏第二胶丸组（D4）：主图叠加独立开关，可同开 */}
        <div className="ca-overlays" data-testid="kline-overlay-pills">
          {OVERLAY_LABELS.map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={`pill ${overlays.includes(id) ? 'active' : ''}`}
              aria-label={label}
              aria-pressed={overlays.includes(id)}
              onClick={() => toggleOverlay(id)}
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
          <KLineChart klines={klines ?? []} period={period} sub={sub} overlays={overlays} />
        )}
      </div>
      {/* 底部胶丸组（C021 用户拍板）：与顶栏叠加胶丸上下对称 */}
      <div className="ca-foot">
        <div className="ca-overlays" data-testid="kline-sub-pills">
          {SUB_LABELS.map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={`pill ${sub === id ? 'active' : ''}`}
              aria-label={label}
              aria-pressed={sub === id}
              onClick={() => {
                setSub(id)
                lsSet(SUB_KEY, id)
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="micro-label ca-sub-note">副图指标</span>
      </div>
    </div>
  )
}
