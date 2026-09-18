"""计划服务（T11，02 §3.7 / §6.7 集成侧）。

- 计划与条件单 CRUD（级联撤单）；
- PlanEngine 每 tick 调度（串行基座内，先于撮合）；
- 触发执行链：条件单 → 下单（origin=plan）→ 事件；
- 策略调度：status/frequency 驱动 Strategies → 围栏 → 下单（origin=strategy）；
- 风控钩子：止损止盈 / 日亏损熔断（risk_halt）；
- 日切联动：day 条件单过期、gtc 续期、计划到期。
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

from app.domain.engine import board_code
from app.domain.plan_engine import (
    OrderIntent, apply_fence, check_daily_loss, check_stop, evaluate_entry,
)
from app.domain.strategies import run_template
from app.errors import BizError
from app.services.watchlist import normalize_codes

TRIGGERS = ("price_cross", "pct_change", "time", "ma_cross")


def _round_lot(code: str, qty: int) -> int:
    if qty <= 0:
        return 0
    if board_code(code).startswith("68"):
        return qty if qty >= 200 else 0
    return qty // 100 * 100


class PlanService:
    def __init__(self, ctx):
        self.ctx = ctx

    # -- CRUD（T11-1） ------------------------------------------------------

    async def create_plan(self, spec: dict[str, Any]) -> dict[str, Any]:
        return await self.ctx.serial.run(lambda: self._create_plan_sync(spec))

    def _create_plan_sync(self, spec: dict[str, Any]) -> dict[str, Any]:
        store = self.ctx.store
        trader_id = int(spec.get("traderId", 0))
        if store.get_trader(trader_id) is None:
            raise BizError("TRADER_NOT_FOUND", f"交易员 {trader_id} 不存在", None, 404)
        scope = dict(spec.get("scope") or {"codes": []})
        codes = scope.get("codes", [])
        if not codes:
            raise BizError("BAD_REQUEST", "计划标的池不能为空", None, 422)
        # C011：标的码归一落库（裸码静默落空修复）——裸 6 位按板块规则推导
        # 主市场前缀，非法码显式 422 拒绝；保序去重
        normalized, invalid = normalize_codes([str(c) for c in codes])
        if invalid:
            raise BizError("BAD_CODE", f"标的码格式非法：{', '.join(invalid)}",
                           {"codes": invalid, "reason": "BAD_FORMAT"}, 422)
        scope["codes"] = normalized
        plan_id = store.insert_plan(
            trader_id, str(spec.get("name", "计划")),
            json.dumps(scope),
            json.dumps(spec.get("budget") or {}),
            json.dumps(spec.get("positionRule") or {}),
            json.dumps(spec.get("risk") or {}),
            json.dumps(spec.get("schedule") or {"frequency": "daily"}),
            self.ctx.clock.now().isoformat(timespec="seconds"),
        )
        return self.plan_view(store.get_plan(plan_id))

    def plan_view(self, plan: dict[str, Any]) -> dict[str, Any]:
        def loads(s):
            try:
                return json.loads(s) if s else {}
            except ValueError:
                return {}

        view_scope = loads(plan["scope"])
        # C011：读取边界归一——存量裸码行惰性愈合，视图回显规范码
        view_scope["codes"] = normalize_codes(view_scope.get("codes", []))[0]
        return {
            "id": plan["id"], "traderId": plan["trader_id"], "name": plan["name"],
            "status": plan["status"], "scope": view_scope,
            "budget": loads(plan["budget"]), "positionRule": loads(plan["position_rule"]),
            "risk": loads(plan["risk"]), "schedule": loads(plan["schedule"]),
            "createdAt": plan["created_at"],
        }

    async def patch_plan(self, plan_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            store = self.ctx.store
            plan = store.get_plan(plan_id)
            if plan is None:
                raise BizError("PLAN_NOT_FOUND", f"计划 {plan_id} 不存在", None, 404)
            if "name" in payload:
                store.insert_event(plan["trader_id"], self._now_s(), "plan_renamed", None)
            status = payload.get("status")
            if status:
                if status not in ("active", "paused", "done"):
                    raise BizError("BAD_REQUEST", "计划状态非法", None, 422)
                store.plan_set_status(plan_id, status)
                self.ctx.bus.publish("plans", {"e": "plan_status", "planId": plan_id,
                                               "status": status})
            if "risk" in payload:
                merged = json.loads(plan["risk"] or "{}")
                merged.update(payload["risk"] or {})
                store.update_plan_risk(plan_id, json.dumps(merged))
            return self.plan_view(store.get_plan(plan_id))

        return await self.ctx.serial.run(_run)

    async def delete_plan(self, plan_id: int) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            store = self.ctx.store
            plan = store.get_plan(plan_id)
            if plan is None:
                raise BizError("PLAN_NOT_FOUND", f"计划 {plan_id} 不存在", None, 404)
            n = 0
            for order in store.active_orders_by_plan(plan_id):
                store.order_set_status(order["id"], "cancel", frozen_amount=0.0)
                n += 1
            store.plan_delete(plan_id)
            store.insert_event(plan["trader_id"], self._now_s(), "plan_deleted",
                               json.dumps({"planId": plan_id, "cancelledOrders": n}))
            return {"id": plan_id, "deleted": True, "cancelledOrders": n}

        return await self.ctx.serial.run(_run)

    # -- 条件单 CRUD --------------------------------------------------------

    async def create_entry(self, plan_id: int, spec: dict[str, Any]) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            store = self.ctx.store
            plan = store.get_plan(plan_id)
            if plan is None:
                raise BizError("PLAN_NOT_FOUND", f"计划 {plan_id} 不存在", None, 404)
            ttype = spec.get("trigger", {}).get("type") or spec.get("triggerType")
            params = spec.get("trigger", {}).get("params") or spec.get("triggerParams") or {}
            action = spec.get("action") or {}
            if ttype not in TRIGGERS:
                raise BizError("BAD_TRIGGER", f"触发器类型必须为 {TRIGGERS}", None, 422)
            if action.get("side") not in ("buy", "sell"):
                raise BizError("BAD_TRIGGER", "action.side 必须为 buy | sell", None, 422)
            if not (action.get("qty") or action.get("pctOfPosition")):
                raise BizError("BAD_TRIGGER", "action 需指定 qty 或 pctOfPosition", None, 422)
            tif = spec.get("tif", "day")
            if tif not in ("day", "gtc"):
                raise BizError("BAD_TRIGGER", "tif 必须为 day | gtc", None, 422)
            entry_id = store.insert_entry(
                plan_id, ttype, json.dumps(params), json.dumps(action), tif,
                self._now_s(),
            )
            return store.get_entry(entry_id)

        return await self.ctx.serial.run(_run)

    async def delete_entry(self, entry_id: int) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            entry = self.ctx.store.get_entry(entry_id)
            if entry is None:
                raise BizError("PLAN_NOT_FOUND", f"条件单 {entry_id} 不存在", None, 404)
            self.ctx.store.entry_delete(entry_id)
            return {"id": entry_id, "deleted": True}

        return await self.ctx.serial.run(_run)

    # -- 校验链接入点（T11-5） ---------------------------------------------

    def enforce_fence(self, trader_id: int, code: str, side: str, amount: float) -> None:
        """manual/operator 下单的计划约束（§3.6 校验链一环）。"""
        store = self.ctx.store
        plans = [self.plan_view(p) for p in store.plans_for_trader(trader_id, active_only=False)]
        plans = [p for p in plans if p["status"] != "done"]
        if not plans:
            return
        if all(p["status"] == "paused" for p in plans):
            raise BizError("PLAN_PAUSED", "全部计划已暂停", None, 409)
        scoped = [p for p in plans if code in p["scope"].get("codes", [])]
        if not scoped:
            raise BizError("PLAN_CONSTRAINT", f"{code} 不在计划标的池内", {"gate": "scope"})
        account = self.ctx.traders.account_view(trader_id)
        pos = store.get_position(trader_id, code)
        price = self.ctx.market.price(code)
        pos_value = (pos["qty"] if pos else 0) * price
        for plan in scoped:
            if plan["status"] == "paused":
                continue
            ok, gate = apply_fence(
                OrderIntent(code=code, side=side), 
                plan_scope_codes=plan["scope"].get("codes", []),
                plan_budget=plan["budget"], plan_position_rule=plan["positionRule"],
                plan_risk=plan["risk"], equity=account["equity"],
                code_position_value=pos_value, order_amount=amount,
            )
            if not ok:
                raise BizError("PLAN_CONSTRAINT", f"未通过策略围栏（{gate}）", {"gate": gate})

    # -- tick 调度（T11-2/T11-3/T11-4） ------------------------------------

    async def on_ticks(self, ticks: list) -> None:
        if not ticks:
            return
        store = self.ctx.store
        today = store.get_state("trading_date") or self._now_s()[:10]
        now_hhmm = self.ctx.clock.now().strftime("%H:%M")
        # 调用内缓存（T14-5 基准优化：64×2×5 场景避免逐条目重复查询）
        closes_cache: dict[str, list[float]] = {}
        for tick in ticks:
            closes_cache[tick.code] = [k["close"] for k in store.klines_for(tick.code, 120)]
        plan_cache: dict[int, dict | None] = {}
        trader_cache: dict[int, dict | None] = {}
        scope_cache: dict[int, list[str]] = {}
        for entry in store.active_entries():
            plan = plan_cache.get(entry["plan_id"])
            if entry["plan_id"] not in plan_cache:
                plan = store.get_plan(entry["plan_id"])
                plan_cache[entry["plan_id"]] = plan
                scope_cache[entry["plan_id"]] = (
                    # C011：裸行读取边界归一（存量裸码计划惰性愈合）
                    normalize_codes(json.loads(plan["scope"] or "{}").get("codes", []))[0]
                    if plan else []
                )
            if plan is None or plan["status"] != "active":
                continue
            for tick in ticks:
                if tick.code not in scope_cache[entry["plan_id"]]:
                    continue
                if plan["trader_id"] not in trader_cache:
                    trader_cache[plan["trader_id"]] = store.get_trader(plan["trader_id"])
                trader = trader_cache[plan["trader_id"]]
                if trader is None or trader["status"] != "running":
                    continue
                params = json.loads(entry["trigger_params"] or "{}")
                try:
                    triggered = evaluate_entry(
                        entry["trigger_type"], params,
                        last=tick.last, prev_close=tick.prev_close,
                        closes=closes_cache.get(tick.code, []),
                        now_hhmm=now_hhmm, today=today,
                        last_triggered_on=entry["last_triggered_on"],
                    )
                except (KeyError, ValueError):
                    continue
                if triggered:
                    self._fire_entry(plan, entry, tick, today)
        self._run_risk_hooks()
        self._run_strategies()

    def _fire_entry(self, plan: dict, entry: dict, tick, today: str) -> None:
        store = self.ctx.store
        action = json.loads(entry["action"] or "{}")
        trader_id = plan["trader_id"]
        qty = int(action.get("qty") or 0)
        if not qty and action.get("pctOfPosition"):
            pos = store.get_position(trader_id, tick.code)
            qty = _round_lot(tick.code, int((pos["qty"] if pos else 0)
                                            * float(action["pctOfPosition"])))
        payload = {
            "side": action["side"], "type": action.get("type", "market"),
            "code": tick.code, "qty": qty,
            "clientOrderId": f"entry-{entry['id']}-{today}",
            "planEntryId": entry["id"],
        }
        if action.get("type") == "limit" and action.get("price"):
            payload["price"] = action["price"]
        try:
            order = self.ctx.trading._submit(trader_id, payload, origin="plan")
            store.entry_set_triggered(entry["id"], today, "triggered")
            store.insert_event(trader_id, self._now_s(), "plan_entry_triggered",
                               json.dumps({"entryId": entry["id"], "orderId": order["id"]}))
            self.ctx.bus.publish("plans", {
                "e": "entry_triggered", "planId": plan["id"], "entryId": entry["id"],
                "orderId": order["id"], "code": tick.code, "side": action["side"],
            })
        except BizError as exc:
            store.insert_event(trader_id, self._now_s(), "plan_entry_failed",
                               json.dumps({"entryId": entry["id"], "code": exc.code,
                                           "message": exc.message}))
            if exc.code in ("TRADER_CLOSED", "SESSION_CLOSED"):
                store.entry_set_triggered(entry["id"], today, "triggered")

    def _run_risk_hooks(self) -> None:
        store = self.ctx.store
        today = store.get_state("trading_date") or self._now_s()[:10]
        for trader in store.list_traders():
            if trader["status"] != "running":
                continue
            plans = store.plans_for_trader(trader["id"], active_only=True)
            if not plans:
                continue
            positions = store.positions_for_trader(trader["id"])
            realized_cache: float | None = None  # 每交易员仅算一次当日已实现
            for plan in plans:
                pv = self.plan_view(plan)
                risk = pv["risk"] or {}
                scope = pv["scope"].get("codes", [])
                # 止损/止盈（去重：每计划每标的每动作每日一次）
                for pos in positions:
                    if pos["code"] not in scope or pos["qty"] <= 0:
                        continue
                    price = self.ctx.market.price(pos["code"])
                    action = check_stop(pos["avg_cost"], price,
                                        risk.get("stopLossPct"), risk.get("takeProfitPct"))
                    if action and not self._risk_done(plan["id"], pos["code"], today):
                        payload = {"side": "sell", "type": "market", "code": pos["code"],
                                   "qty": pos["qty"],
                                   "clientOrderId": f"risk-{plan['id']}-{pos['code']}-{today}"}
                        try:
                            self.ctx.trading._submit(trader["id"], payload, origin="plan")
                            self._mark_risk_done(plan["id"], pos["code"], today)
                            store.insert_event(trader["id"], self._now_s(), "risk_stop",
                                               json.dumps({"code": pos["code"], "price": price}))
                        except BizError:
                            pass
                # 日亏损熔断
                if risk.get("dailyMaxLoss"):
                    if realized_cache is None:
                        realized_cache = sum(
                            t["realized_pnl"] or 0.0
                            for t in store.trades_feed(trader["id"], limit=10**6)
                            if t["trading_date"] == today
                        )
                    unrealized = sum(
                        (self.ctx.market.price(p["code"]) - p["avg_cost"]) * p["qty"]
                        for p in positions
                    )
                    if check_daily_loss(realized_cache, unrealized, float(risk["dailyMaxLoss"])):
                        store.plan_set_status(plan["id"], "paused")
                        store.insert_event(trader["id"], self._now_s(), "risk_halt",
                                           json.dumps({"planId": plan["id"],
                                                       "realized": realized_cache,
                                                       "unrealized": unrealized}))
                        self.ctx.bus.publish("plans", {
                            "e": "risk_halt", "planId": plan["id"],
                            "traderId": trader["id"],
                        })

    def _risk_done(self, plan_id: int, code: str, today: str) -> bool:
        return self.ctx.store.get_state(f"risk:{plan_id}:{code}:{today}") == "done"

    def _mark_risk_done(self, plan_id: int, code: str, today: str) -> None:
        self.ctx.store.set_state(f"risk:{plan_id}:{code}:{today}", "done")

    def _run_strategies(self) -> None:
        store = self.ctx.store
        today = store.get_state("trading_date") or self._now_s()[:10]
        now_hhmm = self.ctx.clock.now().strftime("%H:%M")
        for trader in store.list_traders():
            if trader["mode"] != "strategy" or trader["status"] != "running":
                continue
            plans = [self.plan_view(p) for p in store.plans_for_trader(trader["id"],
                                                                       active_only=True)]
            if not plans:
                continue
            for plan in plans:
                freq = (plan["schedule"] or {}).get("frequency", "daily")
                if freq == "daily":
                    if now_hhmm < "09:35":
                        continue
                    if store.get_state(f"strat:{trader['id']}:{today}") == "done":
                        continue
                self._run_one_strategy(trader, plan, today)
                if freq == "daily":
                    store.set_state(f"strat:{trader['id']}:{today}", "done")

    def _run_one_strategy(self, trader: dict, plan: dict, today: str) -> None:
        store = self.ctx.store
        params = json.loads(trader["strategy_params"] or "{}")
        account = self.ctx.traders.account_view(trader["id"])
        positions = {
            p["code"]: {"qty": p["qty"], "avg_cost": p["avg_cost"]}
            for p in store.positions_for_trader(trader["id"])
        }
        for code in plan["scope"].get("codes", []):
            price = self.ctx.market.price(code)
            quote = self.ctx.market.quote(code)
            if price <= 0:
                continue
            mview = {
                "code": code, "last": price,
                "prev_close": quote.prev_close if quote else price,
                "closes": [k["close"] for k in store.klines_for(code, limit=120)],
            }
            try:
                intents = run_template(trader["strategy_type"], params, mview,
                                       {"cash": account["cash"], "equity": account["equity"],
                                        "positions": positions})
            except (KeyError, ValueError):
                continue
            for intent in intents:
                self._execute_intent(trader, plan, intent, today)

    def _execute_intent(self, trader: dict, plan: dict, intent: OrderIntent, today: str) -> None:
        store = self.ctx.store
        account = self.ctx.traders.account_view(trader["id"])
        price = self.ctx.market.price(intent.code)
        qty = intent.qty
        if intent.side == "buy" and intent.pct_of_cash:
            amount = account["availableCash"] * intent.pct_of_cash
            qty = _round_lot(intent.code, int(amount / price)) if price > 0 else 0
        if intent.side == "sell" and intent.pct_of_position:
            pos = store.get_position(trader["id"], intent.code)
            qty = _round_lot(intent.code, int((pos["qty"] if pos else 0)
                                              * intent.pct_of_position))
        if qty <= 0:
            return
        order_amount = qty * (intent.price or price)
        pos = store.get_position(trader["id"], intent.code)
        pos_value = (pos["qty"] if pos else 0) * price
        ok, gate = apply_fence(
            intent,
            plan_scope_codes=plan["scope"].get("codes", []),
            plan_budget=plan["budget"], plan_position_rule=plan["positionRule"],
            plan_risk=plan["risk"], equity=account["equity"],
            code_position_value=pos_value, order_amount=order_amount,
        )
        if not ok:
            store.insert_event(trader["id"], self._now_s(), "strategy_fenced",
                               json.dumps({"code": intent.code, "gate": gate}))
            return
        payload = {
            "side": intent.side, "type": intent.type, "code": intent.code, "qty": qty,
            "clientOrderId": f"strat-{trader['id']}-{intent.code}-{today}",
        }
        if intent.type == "limit" and intent.price:
            payload["price"] = intent.price
        try:
            self.ctx.trading._submit(trader["id"], payload, origin="strategy")
        except BizError:
            pass

    # -- 日切联动（T11-6） --------------------------------------------------

    def day_rollover(self, date_str: str) -> int:
        """计划到期检查（day 条件单过期已在日切步骤 1）。"""
        store = self.ctx.store
        n = 0
        for trader in store.list_traders():
            for plan in store.plans_for_trader(trader["id"]):
                pv = self.plan_view(plan)
                valid_until = (pv["risk"] or {}).get("validUntil")
                if plan["status"] == "active" and valid_until and valid_until <= date_str:
                    store.plan_set_status(plan["id"], "done")
                    store.insert_event(trader["id"], self._now_s(), "plan_done",
                                       json.dumps({"planId": plan["id"]}))
                    self.ctx.bus.publish("plans", {"e": "plan_done", "planId": plan["id"]})
                    n += 1
        return n

    def _now_s(self) -> str:
        return self.ctx.clock.now().isoformat(timespec="seconds")
