"""T11 运行时：条件单触发→下单→成交→事件 / 策略调度 / 围栏 / 风控熔断。"""

import json
from datetime import datetime

from tests.harness import inject, make_app, quote


class TestScopeNormalization:
    """C011：计划标的池裸码归一（创建校验 + 读取边界愈合）。"""

    async def test_create_normalizes_bare_and_dedupes(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            t = await ctx.traders.create({"name": "t", "mode": "manual", "initCash": 100000})
            plan = await ctx.plans.create_plan({
                "traderId": t["id"], "scope": {"codes": ["601318", "sh600519", "601318", "SZ000001"]},
            })
            assert plan["scope"]["codes"] == ["sh601318", "sh600519", "sz000001"]
        finally:
            await ctx.stop()

    async def test_create_rejects_invalid_code(self):
        from app.errors import BizError

        _, ctx = make_app()
        await ctx.start()
        try:
            t = await ctx.traders.create({"name": "t", "mode": "manual", "initCash": 100000})
            try:
                await ctx.plans.create_plan({
                    "traderId": t["id"], "scope": {"codes": ["601318", "abc"]},
                })
                raise AssertionError("should reject invalid code")
            except BizError as e:
                assert e.code == "BAD_CODE" and e.status == 422
        finally:
            await ctx.stop()

    async def test_legacy_bare_scope_healed_on_view_and_fence(self):
        """存量裸码行：视图回显规范码；围栏按归一码放行（下单码为规范码）。"""
        _, ctx = make_app()
        await ctx.start()
        try:
            t = await ctx.traders.create({"name": "t", "mode": "manual", "initCash": 1000000})
            pid = ctx.store.insert_plan(
                t["id"], "裸码存量", json.dumps({"codes": ["600519"]}),
                "{}", "{}", "{}", "{}", "2026-09-16 09:00:00")
            view = ctx.plans.plan_view(ctx.store.get_plan(pid))
            assert view["scope"]["codes"] == ["sh600519"]
            await inject(ctx, quote())
            order = await ctx.trading.submit_order(t["id"], {
                "side": "buy", "type": "limit", "code": "sh600519",
                "price": 9.99, "qty": 100,
            })
            assert order["status"] in ("wait", "submitted", "filled", "partial")
        finally:
            await ctx.stop()

    async def test_bare_scope_plan_triggers_on_prefixed_tick(self):
        """端到端语义：裸码创建的计划对前缀码 tick 正常触发（BG-0006 场景）。"""
        _, ctx = make_app()
        await ctx.start()
        try:
            t = await ctx.traders.create({"name": "t", "mode": "manual", "initCash": 100000})
            plan = await ctx.plans.create_plan({
                "traderId": t["id"], "scope": {"codes": ["600519"]},
            })
            await ctx.plans.create_entry(plan["id"], {
                "triggerType": "price_cross",
                "triggerParams": {"side": "buy", "price": 9.5},
                "action": {"side": "buy", "qty": 200, "type": "market"},
                "tif": "day",
            })
            await inject(ctx, quote(last=9.4))  # 生产口径前缀码 tick → 触发
            orders = ctx.store.orders_feed(t["id"])
            assert len(orders) == 1 and orders[0]["code"] == "sh600519"
        finally:
            await ctx.stop()


class TestEntryRuntime:
    async def test_trigger_to_fill_to_event(self):
        """触发 → 下单（origin=plan）→ 成交 → 事件全链路（§6.12）。"""
        _, ctx = make_app()
        await ctx.start()
        try:
            t = await ctx.traders.create({"name": "t", "mode": "manual", "initCash": 100000})
            tid = t["id"]
            plan = await ctx.plans.create_plan({
                "traderId": tid, "name": "低吸", "scope": {"codes": ["sh600519"]},
            })
            await ctx.plans.create_entry(plan["id"], {
                "triggerType": "price_cross",
                "triggerParams": {"side": "buy", "price": 9.5},
                "action": {"side": "buy", "qty": 200, "type": "market"},
                "tif": "day",
            })
            published = []
            ctx.bus.subscribe("plans", lambda _t, d: published.append(d))
            await inject(ctx, quote(last=9.4))  # 穿越 9.5 → 触发
            orders = ctx.store.orders_feed(tid)
            assert len(orders) == 1 and orders[0]["origin"] == "plan"
            assert orders[0]["status"] in ("filled", "partial")
            assert orders[0]["plan_entry_id"] is not None
            entries = ctx.store.entries_for_plan(plan["id"])
            assert entries[0]["status"] in ("triggered", "filled")
            assert any(p.get("e") == "entry_triggered" for p in published)
            # 防重复：再注入不产生新订单
            await inject(ctx, quote(last=9.3))
            assert len(ctx.store.orders_feed(tid)) == 1
        finally:
            await ctx.stop()

    async def test_manual_order_fence(self):
        from app.errors import BizError

        _, ctx = make_app()
        await ctx.start()
        try:
            t = await ctx.traders.create({"name": "t", "mode": "manual", "initCash": 100000})
            tid = t["id"]
            await ctx.plans.create_plan({
                "traderId": tid, "scope": {"codes": ["sh600519"]},
                "budget": {"maxPctOfEquity": 0.5},
            })
            await inject(ctx, quote())
            # 池外标的 → PLAN_CONSTRAINT(scope)
            await inject(ctx, quote(code="sz000001", last=5.0, prev=5.0, cum=100000))
            with pytest_ctx(BizError, "PLAN_CONSTRAINT"):
                await ctx.trading.submit_order(tid, {
                    "side": "buy", "type": "limit", "code": "sz000001",
                    "price": 5.0, "qty": 100,
                })
            # 预算闸：0.5×100000=50000，已有持仓 0，单 60000 → 拦截
            with pytest_ctx(BizError, "PLAN_CONSTRAINT"):
                await ctx.trading.submit_order(tid, {
                    "side": "buy", "type": "limit", "code": "sh600519",
                    "price": 10.0, "qty": 6000,
                })
            # 计划全部暂停 → PLAN_PAUSED
            await ctx.plans.patch_plan(1, {"status": "paused"})
            with pytest_ctx(BizError, "PLAN_PAUSED"):
                await ctx.trading.submit_order(tid, {
                    "side": "buy", "type": "limit", "code": "sh600519",
                    "price": 10.0, "qty": 100,
                })
        finally:
            await ctx.stop()


class TestStrategyRuntime:
    async def test_daily_schedule_fires_once(self):
        _, ctx = make_app(clock_start="2026-09-16T09:40:00")
        await ctx.start()
        try:
            t = await ctx.traders.create({
                "name": "动量", "mode": "strategy", "template": "momentum",
                "initCash": 1000000,
            })
            tid = t["id"]
            # 突破形态日K + 现价突破
            ctx.market.sync_klines([
                ("sh600519", f"2026-08-{d:02d}", 10.0, 10.0, 10.1, 9.9, 10000)
                for d in range(1, 29)
            ] + [("sh600519", f"2026-09-{d:02d}", 10.2, 10.4, 10.5, 10.1, 12000)
                 for d in range(1, 16)])
            await ctx.plans.create_plan({
                "traderId": tid, "scope": {"codes": ["sh600519"]},
                "schedule": {"frequency": "daily"},
            })
            await inject(ctx, quote(last=10.6))
            orders = [o for o in ctx.store.orders_feed(tid) if o["origin"] == "strategy"]
            assert len(orders) == 1
            # 当日不重复
            await inject(ctx, quote(last=10.7))
            orders = [o for o in ctx.store.orders_feed(tid) if o["origin"] == "strategy"]
            assert len(orders) == 1
        finally:
            await ctx.stop()

    async def test_paused_trader_produces_nothing(self):
        _, ctx = make_app(clock_start="2026-09-16T09:40:00")
        await ctx.start()
        try:
            t = await ctx.traders.create({
                "name": "动量", "mode": "strategy", "template": "momentum",
                "initCash": 1000000,
            })
            tid = t["id"]
            await ctx.plans.create_plan({"traderId": tid, "scope": {"codes": ["sh600519"]}})
            await ctx.traders.patch(tid, {"status": "paused"})
            await inject(ctx, quote(last=10.6))
            assert ctx.store.orders_feed(tid) == []
        finally:
            await ctx.stop()


class TestRiskHooks:
    async def test_stop_loss_and_daily_halt(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            t = await ctx.traders.create({"name": "t", "mode": "manual", "initCash": 100000})
            tid = t["id"]
            plan = await ctx.plans.create_plan({
                "traderId": tid, "scope": {"codes": ["sh600519"]},
                "risk": {"stopLossPct": 0.03, "dailyMaxLoss": 300},
            })
            published = []
            ctx.bus.subscribe("plans", lambda _t, d: published.append(d))
            await inject(ctx, quote())
            await ctx.trading.submit_order(tid, {
                "side": "buy", "type": "market", "code": "sh600519", "qty": 1000,
            })
            await inject(ctx, quote())  # 建仓完成 @10
            # 价格跌至 9.6（-4% > 3% 止损）→ 自动卖出（origin=plan）
            ctx.store.t1_reset_all()
            await inject(ctx, quote(last=9.6, cum=5_000_000))
            sells = [o for o in ctx.store.orders_feed(tid) if o["side"] == "sell"]
            assert sells and sells[0]["origin"] == "plan"
            # 浮亏扩大触发日亏损熔断：计划转 paused + risk_halt
            await inject(ctx, quote(last=8.0, cum=5_100_000))
            assert ctx.store.get_plan(plan["id"])["status"] == "paused"
            assert any(p.get("e") == "risk_halt" for p in published)
        finally:
            await ctx.stop()


class TestGtcRollover:
    async def test_day_cut_gtc_and_day(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            t = await ctx.traders.create({"name": "t", "mode": "manual", "initCash": 100000})
            tid = t["id"]
            plan = await ctx.plans.create_plan({
                "traderId": tid, "scope": {"codes": ["sh600519"]},
            })
            for tif in ("day", "gtc"):
                await ctx.plans.create_entry(plan["id"], {
                    "triggerType": "time", "triggerParams": {"at": "09:00"},
                    "action": {"side": "buy", "qty": 100, "type": "market"}, "tif": tif,
                })
            await ctx.session.day_cut("2026-09-16")
            statuses = {e["tif"]: e["status"] for e in ctx.store.entries_for_plan(plan["id"])}
            assert statuses["day"] == "expired" and statuses["gtc"] == "waiting"
        finally:
            await ctx.stop()


def pytest_ctx(exc_type, code):
    import contextlib

    @contextlib.contextmanager
    def _cm():
        try:
            yield
            raise AssertionError(f"expected {exc_type.__name__}({code})")
        except exc_type as e:
            assert getattr(e, "code", None) == code or code is None

    return _cm()
