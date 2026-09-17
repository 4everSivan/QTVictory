import { useMemo, useState } from 'react'
import { api, ApiError } from '../../api/client'
import { orderFieldError } from '../../api/errors'
import { useTraders } from '../../state/traders'
import { toast } from '../panes/Toasts'
import type { Quote } from '../../api/types'
import {
  boardKind,
  boardLabel,
  calcFee,
  lotError,
  marketAmountEst,
  priceBandError,
} from '../../validate/order'
import { fmtPrice } from '../../lib/format'

interface OrderPanelProps {
  quote: Quote | null
}

/**
 * 下单面板（01 §4.7 纵向方案 A）：右栏 44% 分割、body 内滚动、
 * 方向钮/提交钮钉底；市价类型 seg 仅市价态出现；确认弹窗标注交易员身份；
 * 限价提示"可能分批部分成交"。作用于当前交易员（§2.1 v2 跟随语义）。
 */
export function OrderPanel({ quote }: OrderPanelProps) {
  const { currentId, current, account, detail, refresh } = useTraders()
  const [side, setSide] = useState<'buy' | 'sell'>('buy')
  const [orderType, setOrderType] = useState<'limit' | 'market'>('limit')
  const [marketType, setMarketType] = useState<'best5_cancel' | 'opponent_best'>('best5_cancel')
  const [price, setPrice] = useState('')
  const [qty, setQty] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)

  const disabled = currentId === null || current?.status !== 'running'

  const code = quote?.code ?? ''
  const prevClose = quote && quote.prevClose > 0 ? quote.prevClose : 0
  const last = quote && quote.last > 0 ? quote.last : 0
  const position = (account?.positions ?? detail?.positions ?? []).find((p) => p.code === code) ?? null
  const posQty = position?.qty ?? 0
  const t1Locked = position?.todayBought ?? 0
  const sellable = Math.max(0, posQty - t1Locked)

  const priceNum = Number(price)
  const qtyNum = Number(qty)
  const limitPrice = orderType === 'limit' ? priceNum : last

  // 输入层即时校验（§6.1 体验层）
  const qtyErr = qty ? lotError(code, qtyNum, posQty, side === 'sell') : null
  const priceErr =
    orderType === 'limit' && price && prevClose > 0
      ? priceBandError(priceNum, side, code, prevClose, last, quote?.bids ?? [], quote?.asks ?? [])
      : null

  const est = useMemo(() => {
    if (!qtyNum || qtyNum <= 0 || limitPrice <= 0) return null
    const amount =
      orderType === 'market'
        ? marketAmountEst(side, qtyNum, last, quote?.bids ?? [], quote?.asks ?? [], marketType)
        : null
    const estPrice = orderType === 'market' ? amount!.estPrice : limitPrice
    const gross = round2(estPrice * qtyNum)
    const fee = calcFee(gross, side === 'buy')
    const need = round2(gross + (side === 'buy' ? fee.total : 0))
    return { estPrice, gross, fee, need, note: orderType === 'market' ? amount!.note : '按限价估算，实际按成交回报' }
  }, [qtyNum, limitPrice, side, orderType, marketType, last, quote])

  const overCash = side === 'buy' && est !== null && account !== null && est.need > account.availableCash
  const overSell = side === 'sell' && qtyNum > 0 && qtyNum > sellable

  const quickBuy = (pct: number) => {
    if (!est || !account || last <= 0) return
    const budget = account.availableCash * pct
    const per = last * (1 + (side === 'buy' ? 0.00026 : 0))
    const q = side === 'buy' ? Math.floor(budget / per / 100) * 100 : 0
    setQty(String(Math.max(0, q)))
  }
  const quickSell = () => setQty(String(sellable))

  const submit = async () => {
    if (currentId === null || submitting) return
    setSubmitting(true)
    setServerError(null)
    try {
      await api.post(`/traders/${currentId}/orders`, {
        code,
        side,
        type: orderType,
        price: orderType === 'limit' ? priceNum : null,
        qty: qtyNum,
        marketType: orderType === 'market' ? marketType : null,
        clientOrderId: `ui-${Date.now()}`,
      })
      toast('success', `${side === 'buy' ? '买入' : '卖出'}委托已提交 ${code} ×${qtyNum}`)
      setConfirming(false)
      setQty('')
      refresh()
    } catch (e) {
      const err = e as ApiError
      const fieldText = orderFieldError(err)
      if (fieldText) {
        setServerError(fieldText)
      } else {
        toast('error', err.message)
      }
      setConfirming(false)
    } finally {
      setSubmitting(false)
    }
  }

  const clientValidation =
    qtyErr ??
    priceErr ??
    (overCash ? '超出可用资金（含费用预估）' : null) ??
    (overSell ? `超出可卖（持仓 ${posQty}，T+1 锁定 ${t1Locked}）` : null)
  const validationText = clientValidation ?? serverError

  return (
    <div className="order-panel" data-testid="order-panel">
      <div className="op-head">
        <span className="micro-label">下单 · ORDER</span>
        {disabled && (
          <span className="op-disabled-note">{currentId === null ? '未选中交易员' : '交易员非运行状态'}</span>
        )}
      </div>

      <div className="op-body">
        <div className="seg op-side-seg">
          {(
            [
              ['buy', '买入'],
              ['sell', '卖出'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={`${side === key ? 'active' : ''} op-side-${key}`}
              onClick={() => setSide(key)}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="seg">
          {(
            [
              ['limit', '限价'],
              ['market', '市价'],
            ] as const
          ).map(([key, label]) => (
            <button key={key} type="button" className={orderType === key ? 'active' : ''} onClick={() => setOrderType(key)}>
              {label}
            </button>
          ))}
        </div>

        {orderType === 'market' && (
          <div className="seg">
            {(
              [
                ['best5_cancel', '最优五档剩余撤销'],
                ['opponent_best', '对手方最优'],
              ] as const
            ).map(([key, label]) => (
              <button key={key} type="button" className={marketType === key ? 'active' : ''} onClick={() => setMarketType(key)}>
                {label}
              </button>
            ))}
          </div>
        )}

        {orderType === 'limit' && (
          <div className="op-row">
            <span className="micro-label">价格</span>
            <div className="op-stepper num">
              <button type="button" onClick={() => setPrice((prev) => (round2(Number(prev || last) - 0.01)).toFixed(2))}>−</button>
              <input value={price} placeholder={last ? last.toFixed(2) : '--'} onChange={(e) => setPrice(e.target.value)} />
              <button type="button" onClick={() => setPrice((prev) => (round2(Number(prev || last) + 0.01)).toFixed(2))}>＋</button>
            </div>
          </div>
        )}

        <div className="op-row">
          <span className="micro-label">数量（{boardLabel(boardKind(code))}）</span>
          <input className="num" value={qty} placeholder={code.startsWith('sh68') || code.startsWith('sz68') ? '≥200' : '100 的倍数'} onChange={(e) => setQty(e.target.value)} />
        </div>

        <div className="op-quick num">
          {side === 'buy' ? (
            <>
              <button type="button" onClick={() => quickBuy(0.25)}>1/4 仓</button>
              <button type="button" onClick={() => quickBuy(0.5)}>1/2 仓</button>
              <button type="button" onClick={() => quickBuy(0.95)}>满仓</button>
            </>
          ) : (
            <button type="button" onClick={quickSell}>全仓可卖 {sellable}</button>
          )}
        </div>

        <div className="op-avail num">
          <span className="micro-label">可用资金</span>
          <span>{fmtPrice(account?.availableCash ?? null)}</span>
          {account && account.frozenCash > 0 && (
            <span className="op-frozen">（冻结 {fmtPrice(account.frozenCash)}）</span>
          )}
          {side === 'sell' && (
            <>
              <span className="micro-label">可卖</span>
              <span>{sellable}</span>
              {t1Locked > 0 && <span className="op-frozen">（T+1 锁定 {t1Locked}）</span>}
            </>
          )}
        </div>

        {est && (
          <div className="op-fee num">
            <div><span className="micro-label">预估金额</span> {fmtPrice(est.gross)}</div>
            <div><span className="micro-label">佣金</span> {fmtPrice(est.fee.commission)}</div>
            <div><span className="micro-label">印花税</span> {fmtPrice(est.fee.stampTax)}</div>
            <div><span className="micro-label">过户费</span> {fmtPrice(est.fee.transferFee)}</div>
            <div className="op-fee-note micro-label">{est.note}</div>
          </div>
        )}

        {validationText && <p className="form-error op-error">{validationText}</p>}
      </div>

      <div className="op-footer">
        <button
          type="button"
          className={`op-submit op-submit-${side}`}
          disabled={disabled || !code || !qty || clientValidation !== null || submitting}
          onClick={() => setConfirming(true)}
        >
          {side === 'buy' ? '买入' : '卖出'} {code}
        </button>
      </div>

      {confirming && (
        <div className="dialog-overlay" onClick={() => setConfirming(false)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()} data-testid="order-confirm">
            <div className="dialog-title">
              确认下单 · <span className={side === 'buy' ? 'up' : 'down'}>{side === 'buy' ? '买入' : '卖出'} {code} ×{qtyNum}</span>
            </div>
            <p className="dialog-note">以 {current?.name ?? '--'}（交易员）身份下单</p>
            <p className="dialog-note">
              {orderType === 'limit' ? '限价单可能分批部分成交' : '市价单按五档加权近似，实际按成交回报'}
              {orderType === 'limit' && price ? ` · ${fmtPrice(priceNum)}` : ''}
            </p>
            <div className="dialog-actions">
              <button type="button" onClick={() => setConfirming(false)}>取消</button>
              <button type="button" className="btn-primary" onClick={() => void submit()} disabled={submitting}>
                {submitting ? '提交中…' : '确认'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function round2(n: number): number {
  return Math.round(n * 100) / 100
}
