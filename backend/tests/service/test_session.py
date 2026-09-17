"""T08：时段状态机 / 日切幂等 / 公司行动（02 §6.4 / §6.6 / §6.12）。"""

from datetime import datetime

from tests.harness import inject, make_app, quote


class TestPhaseMachine:
    def test_phase_boundaries(self):
        _, ctx = make_app()
        cases = [
            ("09:14", "closed"), ("09:15", "call_auction"), ("09:24", "call_auction"),
            ("09:25", "continuous"), ("11:29", "continuous"), ("11:30", "closed"),
            ("12:59", "closed"), ("13:00", "continuous"), ("14:56", "continuous"),
            ("14:57", "closing_auction"), ("14:59", "closing_auction"), ("15:00", "closed"),
        ]
        for hhmm, expected in cases:
            ctx.clock.set(datetime.fromisoformat(f"2026-09-16T{hhmm}:00"))
            assert ctx.session.phase_at(ctx.clock.now()) == expected, hhmm

    async def test_state_view(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            assert ctx.session.state_view()["state"] == "trading"  # 09:30
            ctx.clock.set(datetime.fromisoformat("2026-09-16T15:05:00"))
            assert ctx.session.state_view()["state"] == "closed"
        finally:
            await ctx.stop()


async def _seed_day(ctx):
    """准备一个有持仓、挂单、分红送转场景的交易日 2026-09-16。"""
    t = await ctx.traders.create({"name": "t", "mode": "manual", "initCash": 100000})
    tid = t["id"]
    ctx.store.set_state("trading_date", "2026-09-16")
    await inject(ctx, quote())
    # 建仓 1000 股 @10
    await ctx.trading.submit_order(tid, {
        "side": "buy", "type": "market", "code": "600519", "qty": 1000,
    })
    await inject(ctx, quote())
    # 挂一笔未成交买单（日终应撤）
    await ctx.trading.submit_order(tid, {
        "side": "buy", "type": "limit", "code": "600519", "price": 9.90, "qty": 100,
    })
    # 次日（09-17）除权：每股派息 0.50，10 送 1 转增 0.5
    ctx.store.upsert_actions([("600519", "2026-09-17", 0.50, 0.1, 0.5, "2026-09-16", "test")])
    return tid


class TestDayCut:
    async def test_full_sequence_and_idempotency(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            tid = await _seed_day(ctx)
            pos = ctx.store.get_position(tid, "600519")
            assert pos["qty"] == 1000 and pos["today_bought"] == 1000

            report = await ctx.session.day_cut("2026-09-16")
            steps = report["steps"]
            assert steps["eol_cancel"]["orders"] == 1        # 日终撤单（挂单被撤）
            assert steps["snapshot"] == 1                     # 收盘快照
            assert steps["corporate_actions"] == 1            # 公司行动处理（1 交易员）
            assert steps["minute_persist"] >= 1
            assert steps["advance_date"] == "2026-09-17"

            trader = ctx.store.get_trader(tid)
            # 分红：1000 × 0.50 × (1−10%) = 450
            assert trader["cash"] == pytest_approx(
                100000 - (10000 + 6.0) + 450)
            # 送转：1000 × (1 + 0.1 + 0.5) = 1600 股，成本摊薄
            pos = ctx.store.get_position(tid, "600519")
            assert pos["qty"] == 1600
            assert pos["avg_cost"] == pytest_approx((10000 + 6.0) / 1600)
            # T+1 重置 + 到账股份不占 today_bought（除权日即可卖）
            assert pos["today_bought"] == 0
            # 快照 = 除权前口径（§6.4：收盘快照先于公司行动）
            snap = ctx.store.snapshots_for_trader(tid)[-1]
            assert snap["total_equity"] == pytest_approx(
                100000 - (10000 + 6.0) + 1000 * 10)
            # 事件留痕
            actions = [e["action"] for e in ctx.store.events_feed()]
            assert "dividend" in actions and "transfer" in actions

            # 幂等重入：全部步骤跳过，金额不变
            cash_before = ctx.store.get_trader(tid)["cash"]
            qty_before = ctx.store.get_position(tid, "600519")["qty"]
            report2 = await ctx.session.day_cut("2026-09-16")
            assert all(v == "skipped" for v in report2["steps"].values())
            assert ctx.store.get_trader(tid)["cash"] == cash_before
            assert ctx.store.get_position(tid, "600519")["qty"] == qty_before
        finally:
            await ctx.stop()

    async def test_day_entry_expiry_and_plan_done(self):
        from app.errors import BizError

        _, ctx = make_app()
        await ctx.start()
        try:
            tid = await _seed_day(ctx)
            plan = await ctx.plans.create_plan({
                "traderId": tid, "name": "p", "scope": {"codes": ["600519"]},
                "risk": {"validUntil": "2026-09-16"},
            })
            pid = plan["id"]
            await ctx.plans.create_entry(pid, {
                "triggerType": "price_cross", "triggerParams": {"side": "buy", "price": 9.5},
                "action": {"side": "buy", "qty": 100, "type": "market"}, "tif": "day",
            })
            await ctx.plans.create_entry(pid, {
                "triggerType": "price_cross", "triggerParams": {"side": "buy", "price": 9.5},
                "action": {"side": "buy", "qty": 100, "type": "market"}, "tif": "gtc",
            })
            await ctx.session.day_cut("2026-09-16")
            entries = ctx.store.entries_for_plan(pid)
            statuses = {e["tif"]: e["status"] for e in entries}
            assert statuses["day"] == "expired"    # day 条件单日终过期
            assert statuses["gtc"] == "waiting"    # gtc 续期
            assert ctx.store.get_plan(pid)["status"] == "done"  # 计划到期（validUntil）
        finally:
            await ctx.stop()

    async def test_dividend_tax_free(self):
        _, ctx = make_app(qtv_dividend_tax=0.0)
        await ctx.start()
        try:
            tid = await _seed_day(ctx)
            await ctx.session.day_cut("2026-09-16")
            trader = ctx.store.get_trader(tid)
            assert trader["cash"] == pytest_approx(100000 - (10000 + 6.0) + 1000 * 0.50)
        finally:
            await ctx.stop()


def pytest_approx(value, rel=1e-6):
    import pytest

    return pytest.approx(value, rel=rel)
