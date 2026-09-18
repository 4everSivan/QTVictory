"""交易员服务（T05，02 §3.5 / §3.1）。

生命周期：创建（任意初始资金/模板实例化/可选初始计划）→ running/paused/closed
→ 软删（默认）/ 硬删（?hard=true 二次审计事件）；注资/重置；账户从属视图；
动态流 trader_events。初始世界为空（Q2）：无演示播种。
"""

from __future__ import annotations

import json
from typing import Any

from app.domain.strategies import TEMPLATES
from app.errors import BizError


def trader_public(t: dict[str, Any]) -> dict[str, Any]:
    """交易员行的对外序列化（驼峰契约，§5.2）。"""
    import json as _json

    return {
        "id": t["id"], "name": t["name"], "mode": t["mode"],
        "strategyType": t["strategy_type"],
        "strategyParams": _json.loads(t["strategy_params"]) if t["strategy_params"] else None,
        "status": t["status"], "initCash": t["init_cash"], "cash": t["cash"],
        "createdAt": t["created_at"],
    }


class TraderService:
    def __init__(self, ctx):
        self.ctx = ctx

    # -- 创建（T05-1） ------------------------------------------------------

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        def _create() -> dict[str, Any]:
            store = self.ctx.store
            if store.count_active_traders() >= self.ctx.settings.qtv_max_traders:
                raise BizError("MAX_TRADERS", "交易员数量达到上限",
                               {"max": self.ctx.settings.qtv_max_traders}, 400)
            name = str(payload.get("name", "")).strip()
            if not name:
                raise BizError("BAD_REQUEST", "name 必填", None, 422)
            mode = payload.get("mode", "manual")
            if mode not in ("manual", "strategy"):
                raise BizError("BAD_REQUEST", "mode 必须为 manual | strategy", None, 422)
            init_cash = float(payload.get("initCash", 1_000_000))
            if init_cash <= 0:
                raise BizError("BAD_REQUEST", "initCash 必须为正数", None, 422)
            stype, params = None, None
            if mode == "strategy":
                template = payload.get("template")
                explicit = payload.get("strategy") or {}
                if template:
                    if template not in TEMPLATES:
                        raise BizError("BAD_REQUEST", f"未知模板 {template}", None, 422)
                    stype = template
                    params = {**TEMPLATES[template]["params"], **(payload.get("params") or {})}
                elif explicit.get("type"):
                    stype = explicit["type"]
                    if stype not in TEMPLATES:
                        raise BizError("BAD_REQUEST", f"未知策略 {stype}", None, 422)
                    params = {**TEMPLATES[stype]["params"], **(explicit.get("params") or {})}
                else:
                    raise BizError("BAD_REQUEST", "strategy 模式需指定 template 或 strategy.type",
                                   None, 422)
            now = self.ctx.clock.now().isoformat(timespec="seconds")
            tid = store.insert_trader(
                name, mode, stype, json.dumps(params) if params else None,
                init_cash, init_cash, now,
            )
            store.insert_event(tid, now, "created",
                               json.dumps({"name": name, "mode": mode, "initCash": init_cash}))
            plan_spec = payload.get("plan")
            if plan_spec:
                # 串行基座内直接调同步内核（嵌套 serial.run 会死锁）
                plan_spec = dict(plan_spec, traderId=tid)
                self.ctx.plans._create_plan_sync(plan_spec)
            trader = store.get_trader(tid)
            self.ctx.bus.publish("events", {"e": "trader_created", "traderId": tid, "name": name})
            return trader

        return await self.ctx.serial.run(_create)

    # -- 生命周期（T05-2） --------------------------------------------------

    def _require(self, trader_id: int, *, allow_deleted: bool = False) -> dict[str, Any]:
        trader = self.ctx.store.get_trader(trader_id)
        if trader is None or (trader["status"] == "deleted" and not allow_deleted):
            raise BizError("TRADER_NOT_FOUND", f"交易员 {trader_id} 不存在", None, 404)
        return trader

    async def patch(self, trader_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        def _patch() -> dict[str, Any]:
            trader = self._require(trader_id)
            store = self.ctx.store
            now = self.ctx.clock.now().isoformat(timespec="seconds")
            if "name" in payload:
                store.trader_set_name(trader_id, str(payload["name"]))
            status = payload.get("status")
            if status:
                self._transition(trader_id, trader["status"], status, now)
            if "strategy_params" in payload and trader["strategy_type"]:
                merged = json.loads(trader["strategy_params"] or "{}")
                merged.update(payload["strategy_params"] or {})
                store.trader_set_strategy(trader_id, trader["strategy_type"], json.dumps(merged))
            self.ctx.bus.publish("events", {"e": "trader_updated", "traderId": trader_id})
            return store.get_trader(trader_id)

        return await self.ctx.serial.run(_patch)

    def _transition(self, trader_id: int, current: str, target: str, now: str) -> None:
        store = self.ctx.store
        allowed = {
            "running": ("paused", "closed"),
            "paused": ("running", "closed"),
            "closed": (),
        }
        if target not in allowed.get(current, ()):
            raise BizError("BAD_REQUEST", f"不允许 {current} → {target}", None, 422)
        store.trader_set_status(trader_id, target)
        action = {"paused": "paused", "running": "resumed", "closed": "closed"}[target]
        store.insert_event(trader_id, now, action, None)
        self.ctx.bus.publish("events", {"e": f"trader_{action}", "traderId": trader_id})

    async def delete(self, trader_id: int, hard: bool = False) -> dict[str, Any]:
        def _delete() -> dict[str, Any]:
            trader = self._require(trader_id, allow_deleted=True)
            now = self.ctx.clock.now().isoformat(timespec="seconds")
            store = self.ctx.store
            if hard:
                store.trader_hard_delete(trader_id)
                # 硬删需二次审计（§3.5）：审计落点在 API 中间件，此处留痕
                store.insert_event(None, now, "trader_hard_deleted",
                                   json.dumps({"traderId": trader_id, "name": trader["name"]}))
            else:
                store.trader_soft_delete(trader_id, now)
                store.insert_event(trader_id, now, "deleted", None)
            self.ctx.bus.publish("events", {
                "e": "trader_deleted", "traderId": trader_id, "hard": hard,
            })
            return {"id": trader_id, "hard": hard, "deleted": True}

        return await self.ctx.serial.run(_delete)

    # -- 重置 / 注资（T05-4） ----------------------------------------------

    async def reset(self, trader_id: int) -> dict[str, Any]:
        def _reset() -> dict[str, Any]:
            trader = self._require(trader_id)
            now = self.ctx.clock.now().isoformat(timespec="seconds")
            self.ctx.store.trader_reset(trader_id, trader["init_cash"])
            self.ctx.store.insert_event(trader_id, now, "reset", None)
            # 当日未成交委托一并撤销（账户已回初始态）
            self.ctx.store.cancel_day_orders(now[:10])
            return self.ctx.store.get_trader(trader_id)

        return await self.ctx.serial.run(_reset)

    async def inject_capital(self, trader_id: int, amount: float) -> dict[str, Any]:
        def _inject() -> dict[str, Any]:
            trader = self._require(trader_id)
            if amount <= 0:
                raise BizError("BAD_REQUEST", "注资金额必须为正", None, 422)
            now = self.ctx.clock.now().isoformat(timespec="seconds")
            store = self.ctx.store
            # 注资调增 init_cash，保持收益率口径（§3.5）
            store.trader_set_capital(trader_id, trader["cash"] + amount,
                                     trader["init_cash"] + amount)
            store.insert_event(trader_id, now, "capital_injected", json.dumps({"amount": amount}))
            return store.get_trader(trader_id)

        return await self.ctx.serial.run(_inject)

    # -- 账户从属视图（T05-3） ---------------------------------------------

    def account_view(self, trader_id: int) -> dict[str, Any]:
        store = self.ctx.store
        trader = self._require(trader_id)
        positions = []
        market_value = 0.0
        for pos in store.positions_for_trader(trader_id):
            price = self.ctx.market.price(pos["code"])
            value = pos["qty"] * price
            market_value += value
            positions.append({
                "code": pos["code"], "qty": pos["qty"], "avgCost": pos["avg_cost"],
                "todayBought": pos["today_bought"],
                "price": price, "value": round(value, 2),
                "unrealizedPnl": round((price - pos["avg_cost"]) * pos["qty"], 2)
                if pos["qty"] else 0.0,
            })
        frozen = self._frozen_cash(trader_id)
        equity = trader["cash"] + market_value
        return {
            "traderId": trader_id, "name": trader["name"], "mode": trader["mode"],
            "status": trader["status"], "initCash": trader["init_cash"],
            "cash": round(trader["cash"], 2),
            "frozenCash": round(frozen, 2),
            "availableCash": round(trader["cash"] - frozen, 2),
            "marketValue": round(market_value, 2),
            "equity": round(equity, 2),
            "totalReturn": round(equity / trader["init_cash"] - 1, 6)
            if trader["init_cash"] else 0.0,
            "positions": positions,
        }

    def _frozen_cash(self, trader_id: int) -> float:
        """买入冻结 = Σ 活跃买单 frozen_amount（§6.1 派生口径）。"""
        total = 0.0
        for order in self.ctx.store.orders_feed(trader_id, limit=10**6):
            if order["status"] in ("wait", "partial") and order["side"] == "buy":
                total += order["frozen_amount"] or 0.0
        return total

    def frozen_shares(self, trader_id: int, code: str) -> int:
        """卖出冻结股数 = Σ 活跃卖单 frozen_amount。"""
        total = 0
        for order in self.ctx.store.orders_feed(trader_id, limit=10**6):
            if (order["status"] in ("wait", "partial") and order["side"] == "sell"
                    and order["code"] == code):
                total += int(order["frozen_amount"] or 0)
        return total

    # -- 列表 / 排行（供 T12 扩展） ----------------------------------------

    def list_view(self, *, status: str | None = None, include_closed: bool = False) -> list[dict]:
        rows = self.ctx.store.list_traders(include_deleted=False)
        out = []
        for t in rows:
            if status and t["status"] != status:
                continue
            if t["status"] == "closed" and not include_closed:
                continue
            equity = self._equity_of(t)
            out.append({
                "id": t["id"], "name": t["name"], "mode": t["mode"],
                "strategyType": t["strategy_type"], "status": t["status"],
                "initCash": t["init_cash"], "equity": round(equity, 2),
                "totalReturn": round(equity / t["init_cash"] - 1, 6) if t["init_cash"] else 0.0,
            })
        out.sort(key=lambda r: r["totalReturn"], reverse=True)
        return out

    def _equity_of(self, trader: dict[str, Any]) -> float:
        value = trader["cash"]
        for pos in self.ctx.store.positions_for_trader(trader["id"]):
            value += pos["qty"] * self.ctx.market.price(pos["code"])
        return value

    def detail_view(self, trader_id: int) -> dict[str, Any]:
        account = self.account_view(trader_id)
        store = self.ctx.store
        snapshots = store.snapshots_for_trader(trader_id)
        account["metrics"] = self.ctx.metrics.compute_metrics(trader_id)
        account["orders"] = store.orders_feed(trader_id, limit=50)
        account["trades"] = store.trades_feed(trader_id, limit=50)
        account["equitySeries"] = snapshots
        account["plans"] = [
            self.ctx.plans.plan_view(p) for p in store.plans_for_trader(trader_id)
        ]
        # C003：编辑态回填——详情响应增补当前生效 strategyParams（manual 为 null）
        import json as _json
        trader = store.get_trader(trader_id)
        account["strategyParams"] = (
            _json.loads(trader["strategy_params"]) if trader and trader["strategy_params"] else None
        )
        return account
