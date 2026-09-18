import { useCallback, useEffect, useMemo, useState } from 'react'
import { Dock } from './components/panes/Dock'
import { OrderBook } from './components/panes/OrderBook'
import { OrderPanel } from './components/panes/OrderPanel'
import { QuoteHeader } from './components/panes/QuoteHeader'
import { Topbar } from './components/panes/Topbar'
import { WatchList } from './components/panes/WatchList'
import { ChartArea } from './components/charts/ChartArea'
import { TraderBoard } from './components/traders/TraderBoard'
import { TraderFormDialog } from './components/traders/TraderFormDialog'
import { TraderDetailDialog } from './components/traders/TraderDetailDialog'
import { Toasts, useToasts } from './components/panes/Toasts'
import { TradersProvider, useTraders } from './state/traders'
import { useFallbackPoll, useQuery, useSubscription } from './api/hooks'
import type {
  QuotesEnvelope,
  ServerFrame,
  SessionState,
  Quote,
  WatchEntry,
} from './api/types'
import { quoteQuality } from './api/types'
import {
  ingestQuotesEnvelope,
  useMarketSelection,
} from './state/marketData'
import { arrangeWatchRows } from './state/watchlist'
import { isIndexCode } from './lib/format'
import { cycleMode, getMode, type ThemeMode } from './theme'

const MODE_LABEL: Record<ThemeMode, string> = {
  light: '浅色',
  dark: '深色',
  system: '跟随系统',
}

type QuotesFrame = Extract<ServerFrame, { topic: 'quotes' }>

function pickDefault(quotes: Quote[]): string | null {
  const stock = quotes.find((q) => !isIndexCode(q.code))
  return stock ? stock.code : quotes[0] ? quotes[0].code : null
}

function Shell() {
  const [mode, setMode] = useState<ThemeMode>(() => getMode())
  const [selected, setSelected] = useState<string | null>(null)
  const { dialog, editTarget, closeDialog, detailOpen, closeDetail, detail } = useTraders()
  const toasts = useToasts()

  const sessionQuery = useQuery<SessionState>('/session')
  const quotesQuery = useQuery<QuotesEnvelope>('/market/quotes')
  const watchQuery = useQuery<{ data: WatchEntry[] }>('/watchlist')
  const quotesFrame = useSubscription<QuotesFrame>('quotes')

  const envelope = quotesFrame?.data ?? quotesQuery.data ?? null

  const reloadQuotes = useCallback(() => quotesQuery.reload(), [quotesQuery])
  useFallbackPoll('quotes', 3000, reloadQuotes)

  useEffect(() => {
    if (envelope) ingestQuotesEnvelope(envelope.quotes, envelope.ts)
  }, [envelope])

  useEffect(() => {
    if (selected === null && envelope) {
      setSelected(pickDefault(envelope.quotes))
    }
  }, [envelope, selected])

  useMarketSelection(selected)

  const quotes = envelope?.quotes ?? []
  const quote = quotes.find((q) => q.code === selected) ?? null
  const quality = envelope ? quoteQuality(envelope) : 'fallback'
  // 列表编排（T24-1）：自选集置顶（addedAt 倒序）+ 动态项保持关注集原序
  const watchEntries = watchQuery.data?.data ?? []
  const watchRows = useMemo(
    () => arrangeWatchRows(quotes, watchEntries),
    [quotes, watchEntries],
  )
  const reloadWatchlist = useCallback(() => void watchQuery.reload(), [watchQuery])

  return (
    <div className="app">
      <header className="topbar">
        <Topbar session={sessionQuery.data} envelope={envelope} />
        <button
          type="button"
          className="num theme-toggle"
          onClick={() => setMode(cycleMode())}
        >
          {MODE_LABEL[mode]}
        </button>
      </header>
      <aside className="leftcol">
        <section className="pane-watchlist">
          <WatchList rows={watchRows} selected={selected} onSelect={setSelected} onChanged={reloadWatchlist} />
        </section>
        <section className="pane-traders">
          <TraderBoard />
        </section>
      </aside>
      <main className="center">
        <QuoteHeader quote={quote} />
        <ChartArea code={selected} quote={quote} />
      </main>
      <aside className="rightcol">
        <section className="pane-orderbook">
          <OrderBook quote={quote} quality={quality} />
        </section>
        <section className="pane-order">
          <OrderPanel quote={quote} />
        </section>
      </aside>
      <footer className="dock">
        <Dock session={sessionQuery.data} clock={envelope?.ts.slice(11, 16) ?? ''} />
      </footer>

      {dialog !== 'none' && <TraderFormDialog mode={dialog} onClose={closeDialog} key={dialog + (editTarget?.id ?? 0)} />}
      {detailOpen && detail && <TraderDetailDialog detail={detail} onClose={closeDetail} />}
      <Toasts items={toasts} />
    </div>
  )
}

export default function App() {
  return (
    <TradersProvider>
      <Shell />
    </TradersProvider>
  )
}
