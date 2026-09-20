"""交易服务（T07，02 §3.6 / §6.1 集成侧 / §5.4）。

- 下单校验链（§3.6 顺序）：会话 → 交易员 → 停牌 → 品种准入（C015 白名单）→
  申报单位 → 价格范围 → 市价类型 → 冻结 → 可用 → 计划约束 → 生成订单（origin）；
- 撮合 tick 集成：限额池按到达顺序分配，一单多笔成交落库；
- 撤单与解冻（可撤窗口 = 连续竞价与 9:15–9:20）；
- clientOrderId 服务端幂等兜底（与 API 幂等中间件双层）。

错误码（§5.4，另加 SUSPENDED：停牌拒单（F4），02 未指定码、登记于 T07-5）。
"""

from __future__ import annotations

import json
from typing import Any

from app.domain.engine import (
    Tick, auction_match, buy_freeze, calc_fee, limit_match, lot_ok,
    market_match, release_freeze, tick_volume_cap, tradable_ok, valid_band,
)
from app.errors import BizError

ACTIVE = ("wait", "partial")


class TradingService:
    def __init__(self, ctx):
        self.ctx = ctx

    # -- 下单（T07-1） ------------------------------------------------------

    async def submit_order(
        self, trader_id: int, payload: dict[str, Any], origin: str = "manual",
    ) -> dict[str, Any]:
        return await self.ctx.serial.run(lambda: self._submit(trader_id, payload, origin))

    def _submit(self, trader_id: int, payload: dict[str, Any], origin: str) -> dict[str, Any]:
        if origin not in ("manual", "operator", "plan", "strategy"):
            raise BizError("BAD_REQUEST", f"非法 origin: {origin}", None, 422)
        store = self.ctx.store

        trader = store.get_trader(trader_id)
        if trader is None or trader["status"] == "deleted":
            raise BizError("TRADER_NOT_FOUND", f"交易员 {trader_id} 不存在", None, 404)
        if trader["status"] != "running":
            raise BizError("TRADER_CLOSED", f"交易员状态 {trader['status']}，不接受委托", None, 409)

        phase = self.ctx.session.phase_at(self.ctx.clock.now())
        if phase not in ("call_auction", "continuous", "closing_auction"):
            raise BizError("SESSION_CLOSED", "当前非交易时段", {"phase": phase}, 409)

        side = payload.get("side")
        otype = payload.get("type", "limit")
        code = str(payload.get("code", ""))
        qty = int(payload.get("qty", 0))
        if side not in ("buy", "sell"):
            raise BizError("BAD_REQUEST", "side 必须为 buy | sell", None, 422)
        if otype not in ("limit", "market"):
            raise BizError("BAD_REQUEST", "type 必须为 limit | market", None, 422)

        quote = self.ctx.market.quote(code)
        if quote is None or quote.last <= 0:
            raise BizError("SUSPENDED", f"{code} 无有效行情（停牌或未关注）", {"code": code}, 409)
        # C015：品种准入白名单——指数/基金/债券/北交所等行情可及但撮合规则未覆盖
        # （02 §6.1 规则适用范围），拒单防错规则误用；裸码无前缀同样不在白名单
        if not tradable_ok(code):
            raise BizError(
                "UNSUPPORTED_BOARD",
                "品种不在可交易白名单（仅沪深主板/创业板/科创板个股）",
                {"code": code},
            )

        # C016：marketType 契约容忍 null/缺省（前端限价单发 null），归一为默认类型
        market_type = payload.get("marketType") or "best5_cancel"
        if otype == "market" and market_type not in ("best5_cancel", "opponent_best"):
            raise BizError("BAD_REQUEST", "marketType 必须为 best5_cancel | opponent_best", None, 422)

        pos = store.get_position(trader_id, code)
        pos_qty = pos["qty"] if pos else 0
        if not lot_ok(code, qty, pos_qty=pos_qty, is_sell=(side == "sell")):
            raise BizError(
                "LOT_SIZE", "申报数量不符合板块申报单位",
                {"code": code, "qty": qty,
                 "rule": "主板/创业板 100 股整数倍；科创板 ≥200 股后 1 股递增，零股须一次卖出"},
            )

        price = payload.get("price")
        if otype == "limit":
            price = round(float(price), 2)  # type: ignore[arg-type]
            lo, hi = valid_band(self._tick_of(quote), side, code)
            if not lo <= price <= hi:  # type: ignore[operator]
                lim_lo, lim_hi = self._limit_pair(quote, code)
                raise BizError(
                    "PRICE_BAND", "申报价格超出有效申报范围",
                    {"limitBand": [lim_lo, lim_hi], "effectiveBand": [lo, hi]},
                )
        else:
            if self.ctx.market.stale():
                raise BizError("STALE_QUOTE", "行情过期，拒市价单",
                               {"ageSec": self.ctx.market.status()["ageSec"]}, 409)
            price = quote.last  # 冻结估算价

        # 冻结与可用（§6.1）
        if side == "buy":
            need = buy_freeze(price, qty)  # type: ignore[arg-type]
            frozen_now = self.ctx.traders._frozen_cash(trader_id)
            if trader["cash"] - frozen_now < need:
                raise BizError(
                    "INSUFFICIENT_FUNDS", "可用资金不足",
                    {"cash": trader["cash"], "frozen": frozen_now, "need": need},
                )
            frozen_amount: float | None = need
        else:
            frozen_shares = self.ctx.traders.frozen_shares(trader_id, code)
            locked = (pos["today_bought"] if pos else 0) + frozen_shares
            if pos_qty - locked < qty:
                raise BizError(
                    "T1_LOCKED", "可卖不足（T+1 锁定或卖出冻结）",
                    {"position": pos_qty, "locked": locked, "need": qty},
                )
            frozen_amount = float(qty)

        # 计划约束（manual/operator 下单；plan/strategy 已在上游过围栏）
        amount = price * qty  # type: ignore[operator]
        if origin in ("manual", "operator"):
            self.ctx.plans.enforce_fence(trader_id, code, side, amount)

        # clientOrderId 幂等兜底（T07-4）
        client_order_id = payload.get("clientOrderId")
        if client_order_id:
            existed = store.get_order_by_client_id(trader_id, str(client_order_id))
            if existed is not None:
                return existed

        now = self.ctx.clock.now()
        now_s = now.isoformat(timespec="seconds")
        trading_date = self.ctx.store.get_state("trading_date") or now.strftime("%Y-%m-%d")
        order_id = store.insert_order({
            "trader_id": trader_id, "origin": origin,
            "plan_entry_id": payload.get("planEntryId"),
            "client_order_id": client_order_id,
            "side": side, "type": otype,
            "market_type": market_type if otype == "market" else None,
            "code": code, "price": price if otype == "limit" else None,
            "qty": qty, "status": "wait", "frozen_amount": frozen_amount,
            "created_at": now_s, "trading_date": trading_date,
        })
        store.insert_event(trader_id, now_s, "order",
                           json.dumps({"orderId": order_id, "side": side, "code": code,
                                       "qty": qty, "origin": origin}))
        self._push_account(trader_id)
        return store.get_order(order_id)

    def _tick_of(self, quote) -> Tick:
        from app.domain.engine import BookLevel

        return Tick(
            code=quote.code, last=quote.last, prev_close=quote.prev_close,
            bids=[BookLevel(p, v) for p, v in quote.bids],
            asks=[BookLevel(p, v) for p, v in quote.asks],
        )

    def _limit_pair(self, quote, code: str) -> tuple[float, float]:
        from app.domain.engine import price_limits

        return price_limits(quote.prev_close, code)

    # -- 撤单（T07-3） ------------------------------------------------------

    async def cancel(self, trader_id: int, order_id: int) -> dict[str, Any]:
        return await self.ctx.serial.run(lambda: self._cancel(trader_id, order_id))

    def _cancel(self, trader_id: int, order_id: int) -> dict[str, Any]:
        store = self.ctx.store
        order = store.get_order(order_id)
        if order is None or order["trader_id"] != trader_id:
            raise BizError("TRADER_NOT_FOUND", "订单不存在", {"orderId": order_id}, 404)
        if order["status"] not in ACTIVE:
            raise BizError("BAD_REQUEST", f"订单状态 {order['status']}，不可撤", None, 409)
        now = self.ctx.clock.now()
        phase = self.ctx.session.phase_at(now)
        # 可撤窗口：连续竞价与 9:15–9:20（§6.1）
        cancelable = phase == "continuous" or (
            phase == "call_auction" and now.strftime("%H:%M") < "09:20"
        )
        if not cancelable:
            raise BizError("SESSION_CLOSED", "当前时段不可撤单", {"phase": phase}, 409)
        store.order_set_status(order_id, "cancel", frozen_amount=0.0)
        now_s = now.isoformat(timespec="seconds")
        store.insert_event(trader_id, now_s, "order_cancelled",
                           json.dumps({"orderId": order_id}))
        self._push_account(trader_id)
        return store.get_order(order_id)

    async def cancel_by_plan(self, plan_id: int) -> int:
        """计划删除级联撤单（§6.1 cancel 来源之一）。"""
        def _run() -> int:
            store = self.ctx.store
            n = 0
            for order in store.active_orders_by_plan(plan_id):
                store.order_set_status(order["id"], "cancel", frozen_amount=0.0)
                store.insert_event(order["trader_id"], self._now_s(), "order_cancelled",
                                   json.dumps({"orderId": order["id"], "byPlan": plan_id}))
                self._push_account(order["trader_id"])
                n += 1
            return n
        return await self.ctx.serial.run(_run)

    # -- 撮合 tick 集成（T07-2） -------------------------------------------

    async def on_ticks(self, ticks: list[Tick]) -> None:
        for tick in ticks:
            self._match_tick(tick)

    def _match_tick(self, tick: Tick) -> None:
        if tick.suspended:
            return
        phase = self.ctx.session.phase_at(self.ctx.clock.now())
        if phase in ("call_auction", "closing_auction"):
            return  # 集合竞价时段累积委托，待集合竞价价产生后结算
        store = self.ctx.store
        cap = tick_volume_cap(tick, self.ctx.settings.qtv_volume_participation)
        for order in store.active_orders_for_code(tick.code):  # 到达顺序（created_at, id）
            waiting = order["qty"] - order["filled_qty"]
            if waiting <= 0:
                continue
            if order["type"] == "market":
                out = market_match(order["side"], waiting, tick, cap,
                                   order["market_type"] or "best5_cancel")
            else:
                out = limit_match(order["side"], order["price"], waiting, tick, cap)
            if out.filled_qty > 0:
                for fill in out.fills:
                    self._apply_fill(order, fill, tick)
                cap -= out.filled_qty
            new_filled = order["filled_qty"] + out.filled_qty
            if out.filled_qty > 0 or out.status in ("cancel",):
                frozen = self._remaining_freeze(order, new_filled)
                store.order_apply_fill(
                    order["id"], new_filled,
                    self._avg_price(order, out),
                    frozen, out.fill_model, out.status, self._now_s() if out.status != "wait" else None,
                )
                if out.status in ("filled", "cancel"):
                    self._on_order_final(order)
            self._push_account(order["trader_id"])

    def settle_auction(self, code: str, auction_price: float, auction_volume: int) -> None:
        """集合竞价结算（9:25 / 15:00）：由 SessionService/测试触发。"""
        store = self.ctx.store
        part = self.ctx.settings.qtv_volume_participation
        for order in store.active_orders_for_code(code):
            waiting = order["qty"] - order["filled_qty"]
            out = auction_match(
                order["side"], order["type"], order["price"], waiting,
                auction_price, auction_volume, part,
            )
            if out.filled_qty > 0:
                for fill in out.fills:
                    self._apply_fill(order, fill, None)
            new_filled = order["filled_qty"] + out.filled_qty
            if out.filled_qty > 0 or out.status != "wait":
                store.order_apply_fill(
                    order["id"], new_filled, self._avg_price(order, out),
                    self._remaining_freeze(order, new_filled), out.fill_model,
                    out.status, self._now_s(),
                )
                if out.status in ("filled", "cancel"):
                    self._on_order_final(order)

    # -- 成交落账 ----------------------------------------------------------

    def _apply_fill(self, order: dict[str, Any], fill, tick: Tick | None) -> None:
        store = self.ctx.store
        trader = store.get_trader(order["trader_id"])
        if trader is None:
            return
        amount = fill.price * fill.qty
        fee = calc_fee(amount, order["side"] == "buy")
        pos = store.get_position(order["trader_id"], order["code"])
        realized = None
        if order["side"] == "buy":
            cost = amount + fee.total
            old_qty = pos["qty"] if pos else 0
            old_cost_total = old_qty * (pos["avg_cost"] if pos else 0.0)
            new_qty = old_qty + fill.qty
            avg = (old_cost_total + amount + fee.total) / new_qty if new_qty else 0.0
            store.upsert_position(
                order["trader_id"], order["code"], new_qty, avg,
                (pos["today_bought"] if pos else 0) + fill.qty,
            )
            store.trader_set_cash(order["trader_id"], trader["cash"] - cost)
        else:
            proceeds = amount - fee.total
            avg_cost = pos["avg_cost"] if pos else 0.0
            realized = round((fill.price - avg_cost) * fill.qty - fee.total, 2)
            new_qty = (pos["qty"] if pos else 0) - fill.qty
            if new_qty > 0:
                store.upsert_position(
                    order["trader_id"], order["code"], new_qty, avg_cost,
                    pos["today_bought"] if pos else 0,
                )
            else:
                store.delete_position(order["trader_id"], order["code"])
            store.trader_set_cash(order["trader_id"], trader["cash"] + proceeds)
        store.insert_trade({
            "order_id": order["id"], "trader_id": order["trader_id"], "code": order["code"],
            "side": order["side"], "price": fill.price, "qty": fill.qty,
            "amount": round(amount, 2), "commission": fee.commission,
            "stamp_tax": fee.stamp_tax, "transfer_fee": fee.transfer_fee,
            "realized_pnl": realized, "origin": order["origin"],
            "ts": self._now_s(), "trading_date": order["trading_date"],
        })
        store.insert_event(order["trader_id"], self._now_s(), "fill",
                           json.dumps({"orderId": order["id"], "price": fill.price,
                                       "qty": fill.qty, "side": order["side"]}))

    def _remaining_freeze(self, order: dict[str, Any], new_filled: int) -> float | None:
        if order["side"] == "buy":
            return release_freeze("buy", order["frozen_amount"] or 0.0,
                                  order["qty"], new_filled)
        remaining = order["qty"] - new_filled
        return float(remaining) if remaining > 0 else 0.0

    def _avg_price(self, order: dict[str, Any], out) -> float | None:
        trades = self.ctx.store.trades_for_order(order["id"])
        total_qty = sum(t["qty"] for t in trades)
        if total_qty <= 0:
            return None
        return round(sum(t["price"] * t["qty"] for t in trades) / total_qty, 4)

    def _on_order_final(self, order: dict[str, Any]) -> None:
        if order["plan_entry_id"]:
            entry = self.ctx.store.get_entry(order["plan_entry_id"])
            if entry is not None and entry["status"] == "triggered":
                self.ctx.store.entry_set_status(order["plan_entry_id"], "filled")
                self.ctx.bus.publish("plans", {
                    "e": "entry_filled", "entryId": order["plan_entry_id"],
                    "orderId": order["id"],
                })

    def _now_s(self) -> str:
        return self.ctx.clock.now().isoformat(timespec="seconds")

    def _push_account(self, trader_id: int) -> None:
        try:
            account = self.ctx.traders.account_view(trader_id)
            self.ctx.bus.publish(f"trader:{trader_id}", {
                "e": "account", "account": account,
            })
        except BizError:
            pass
