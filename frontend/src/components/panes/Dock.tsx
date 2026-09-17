import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../../api/client'
import { presentError } from '../../api/errors'
import { useQuery } from '../../api/hooks'
import { useTraders } from '../../state/traders'
import { toast } from './Toasts'
import { AnalyticsTab } from './AnalyticsTab'
import { ExportMenuDialog } from '../traders/ExportMenuDialog'
import type { OrderRow, Page, SessionState, TradeRow } from '../../api/types'
import { cancelDisabled } from '../../validate/order'
import { fmtPrice } from '../../lib/format'

const TABS = [
  ['positions', '持仓'],
  ['orders', '当日委托'],
  ['trades', '成交记录'],
  ['analytics', '收益分析'],
] as const

type TabKey = (typeof TABS)[number][0]

const ORDER_STATUS: Record<OrderRow['status'], string> = {
  wait: 'WAIT',
  partial: 'PARTIAL',
  filled: 'FILLED',
  cancel: 'CANCEL',
}

export function orderShortId(id: number): string {
  return id.toString(16).toUpperCase().padStart(4, '0').slice(-4)
}

/**
 * 底部 Dock（01 §4.8，236px）：持仓/当日委托/成交记录/收益分析四 Tab，
 * 全部跟随当前交易员；委托表 partial 列与撤单（集合竞价 9:20–9:25 禁用）；
 * 成交按 order_id 分组（ORD 微标签组头，组间 1px 深线，v2.1 结构分组）。
 */
export function Dock({ session, clock }: { session: SessionState | null; clock: string }) {
  const { currentId, current, account, detail, refresh } = useTraders()
  const [tab, setTab] = useState<TabKey>('positions')
  const [exportOpen, setExportOpen] = useState(false)

  const ordersQuery = useQuery<Page<OrderRow>>(
    currentId === null ? null : `/traders/${currentId}/orders?limit=100`,
  )
  const tradesQuery = useQuery<Page<TradeRow>>(
    currentId === null ? null : `/traders/${currentId}/trades?limit=100`,
  )

  const orders = useMemo(() => ordersQuery.data?.data ?? [], [ordersQuery.data])
  const trades = useMemo(() => tradesQuery.data?.data ?? [], [tradesQuery.data])

  // 成交/部分成交 Toast：以委托 filled_qty 快照差分派生（T20-5）
  const filledSnap = useRef(new Map<number, number>())
  useEffect(() => {
    const seen = new Map<number, number>()
    for (const o of orders) {
      seen.set(o.id, o.filled_qty)
      const before = filledSnap.current.get(o.id)
      if (before !== undefined && o.filled_qty > before) {
        const delta = o.filled_qty - before
        if (o.status === 'filled') {
          toast('success', `成交回报 #${orderShortId(o.id)} ${o.code} ×${o.filled_qty}`)
        } else {
          toast('info', `部分成交 #${orderShortId(o.id)} ${o.code} +${delta}（${o.filled_qty}/${o.qty}）`)
        }
      } else if (before === undefined && o.filled_qty > 0) {
        if (o.status === 'filled') {
          toast('success', `成交回报 #${orderShortId(o.id)} ${o.code} ×${o.filled_qty}`)
        } else {
          toast('info', `部分成交 #${orderShortId(o.id)} ${o.code}（${o.filled_qty}/${o.qty}）`)
        }
      }
    }
    filledSnap.current = seen
  }, [orders])

  const cancel = async (order: OrderRow) => {
    if (currentId === null) return
    try {
      await api.del(`/traders/${currentId}/orders/${order.id}`)
      toast('success', `撤单已提交 #${orderShortId(order.id)}`)
      refresh()
      void ordersQuery.reload()
    } catch (e) {
      toast('error', presentError(e as ApiError).text)
    }
  }

  const cancelBan = cancelDisabled(clock, session?.phase ?? '')

  return (
    <div className="dock-inner" data-testid="dock">
      <div className="dock-tabs">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={`dock-tab ${tab === key ? 'active' : ''}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
        <span className="dock-follow micro-label" data-testid="dock-follow">
          跟随 当前交易员{current ? ` · ${current.name}` : ''}
        </span>
        {current && (
          <button type="button" className="dock-export num" onClick={() => setExportOpen(true)}>
            导出
          </button>
        )}
      </div>

      <div className="dock-body num">
        {currentId === null && <div className="wl-empty">未选中交易员</div>}

        {currentId !== null && tab === 'positions' && (
          <table className="dtable" data-testid="dock-positions">
            <thead>
              <tr><th>代码</th><th>持仓</th><th>成本</th><th>现价</th><th>市值</th><th>浮动盈亏</th></tr>
            </thead>
            <tbody>
              {(account?.positions ?? []).length === 0 && (
                <tr><td colSpan={6} className="flat">无持仓</td></tr>
              )}
              {(account?.positions ?? []).map((p) => (
                <tr key={p.code}>
                  <td>{p.code}</td>
                  <td>{p.qty}</td>
                  <td>{fmtPrice(p.avgCost)}</td>
                  <td>{fmtPrice(p.price)}</td>
                  <td>{fmtPrice(p.value)}</td>
                  <td className={p.unrealizedPnl > 0 ? 'up' : p.unrealizedPnl < 0 ? 'down' : 'flat'}>
                    {fmtPrice(p.unrealizedPnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {currentId !== null && tab === 'orders' && (
          <table className="dtable" data-testid="dock-orders">
            <thead>
              <tr>
                <th>时间</th><th>代码</th><th>方向</th><th>类型</th><th>价格</th>
                <th>委托量</th><th>已成交/委托量</th><th>状态</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {orders.length === 0 && <tr><td colSpan={9} className="flat">当日无委托</td></tr>}
              {[...orders].reverse().map((o) => (
                <tr key={o.id} className={o.status === 'wait' || o.status === 'partial' ? '' : 'dock-done'}>
                  <td>{o.created_at.slice(11, 19)}</td>
                  <td>{o.code}</td>
                  <td className={o.side === 'buy' ? 'up' : 'down'}>{o.side === 'buy' ? '买入' : '卖出'}</td>
                  <td className="flat">
                    {o.type === 'market'
                      ? `市价·${o.market_type === 'opponent_best' ? '对手方最优' : '最优五档'}`
                      : '限价'}
                  </td>
                  <td>{o.price !== null ? fmtPrice(o.price) : '--'}</td>
                  <td>{o.qty}</td>
                  <td>{`${o.filled_qty}/${o.qty}`}</td>
                  <td>
                    <span className={`status-pill st-${o.status}`}>
                      {o.status === 'partial' ? `PARTIAL ${o.filled_qty}/${o.qty}` : ORDER_STATUS[o.status]}
                    </span>
                  </td>
                  <td>
                    {(o.status === 'wait' || o.status === 'partial') && (
                      <button
                        type="button"
                        className="dock-cancel"
                        disabled={cancelBan}
                        title={cancelBan ? '集合竞价 9:20–9:25 不可撤单' : '撤单'}
                        onClick={() => void cancel(o)}
                      >
                        撤单
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {currentId !== null && tab === 'trades' && (
          <div className="dock-trades" data-testid="dock-trades">
            {trades.length === 0 && <div className="wl-empty">暂无成交</div>}
            {groupByOrder(trades).map(([orderId, group]) => {
              const first = group[0]
              const order = orders.find((o) => o.id === orderId)
              const filledQty = order?.filled_qty ?? group.reduce((s, t) => s + t.qty, 0)
              const totalQty = order?.qty ?? filledQty
              const status = order ? ORDER_STATUS[order.status] : 'FILLED'
              return (
                <div key={orderId} className="trade-group">
                  <div className="trade-group-head micro-label">
                    {`ORD #${orderShortId(orderId)} · ${order?.type === 'market' ? '市价' : '限价'}${first.side === 'buy' ? '买入' : '卖出'} ${fmtPrice(first.price)} ×${totalQty} · ${status === 'PARTIAL' ? `PARTIAL ${filledQty}/${totalQty}` : status}`}
                  </div>
                  <table className="dtable">
                    <tbody>
                      {group.map((t) => (
                        <tr key={t.id}>
                          <td className="flat">{t.ts.slice(11, 19)}</td>
                          <td>{t.code}</td>
                          <td className={t.side === 'buy' ? 'up' : 'down'}>{t.side === 'buy' ? '买入' : '卖出'}</td>
                          <td>{fmtPrice(t.price)}</td>
                          <td>{t.qty}</td>
                          <td>{fmtPrice(t.amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            })}
          </div>
        )}

        {currentId !== null && tab === 'analytics' && (
          <div data-testid="dock-analytics">
            {detail ? (
              <AnalyticsTab detail={detail} />
            ) : (
              <div className="detail-plans-placeholder">
                <span className="flat">收益数据加载中…</span>
              </div>
            )}
          </div>
        )}
      </div>
      {exportOpen && current && <ExportMenuDialog trader={current} onClose={() => setExportOpen(false)} />}
    </div>
  )
}

function groupByOrder(trades: TradeRow[]): Array<[number, TradeRow[]]> {
  const map = new Map<number, TradeRow[]>()
  for (const t of trades) {
    const list = map.get(t.order_id) ?? []
    list.push(t)
    map.set(t.order_id, list)
  }
  return [...map.entries()].sort((a, b) => b[0] - a[0])
}
