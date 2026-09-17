"""T05：交易员生命周期 / 模板实例化 / 上限 / 注资重置 / 账户视图（02 §6.12 生命周期项）。"""

import pytest

from app.errors import BizError
from tests.harness import inject, make_app, quote


async def test_full_lifecycle():
    _, ctx = make_app()
    await ctx.start()
    try:
        t = await ctx.traders.create({"name": "手动", "mode": "manual", "initCash": 500000})
        assert t["status"] == "running" and t["cash"] == 500000
        tid = t["id"]
        # 暂停 → 恢复 → 关闭
        await ctx.traders.patch(tid, {"status": "paused"})
        assert ctx.store.get_trader(tid)["status"] == "paused"
        await ctx.traders.patch(tid, {"status": "running"})
        await ctx.traders.patch(tid, {"status": "closed"})
        closed_view = ctx.traders.list_view()
        assert closed_view == []  # closed 退出排行
        assert ctx.traders.list_view(include_closed=True)[0]["status"] == "closed"
        # 非法流转
        with pytest.raises(BizError):
            await ctx.traders.patch(tid, {"status": "running"})
        # 软删 → 硬删
        await ctx.traders.delete(tid, hard=False)
        assert ctx.store.get_trader(tid)["status"] == "deleted"
        await ctx.traders.delete(tid, hard=True)
        assert ctx.store.get_trader(tid) is None
    finally:
        await ctx.stop()


async def test_template_instantiation_and_max():
    _, ctx = make_app(qtv_max_traders=2)
    await ctx.start()
    try:
        t = await ctx.traders.create({
            "name": "动量", "mode": "strategy", "template": "momentum", "initCash": 300000,
        })
        assert t["strategy_type"] == "momentum"
        assert t["strategy_params"]  # 默认参数已实例化
        await ctx.traders.create({"name": "b", "mode": "manual", "initCash": 1})
        with pytest.raises(BizError) as ei:
            await ctx.traders.create({"name": "c", "mode": "manual", "initCash": 1})
        assert ei.value.code == "MAX_TRADERS"
        with pytest.raises(BizError):
            await ctx.traders.create({"name": "d", "mode": "strategy", "initCash": 1})  # 缺模板
        with pytest.raises(BizError):
            await ctx.traders.create({"name": "e", "mode": "manual", "initCash": -1})
    finally:
        await ctx.stop()


async def test_capital_injection_and_reset():
    _, ctx = make_app()
    await ctx.start()
    try:
        t = await ctx.traders.create({"name": "t", "mode": "manual", "initCash": 100000})
        tid = t["id"]
        # 注资：调增 init_cash，收益率口径保持（§3.5）
        t2 = await ctx.traders.inject_capital(tid, 50000)
        assert t2["cash"] == 150000 and t2["init_cash"] == 150000
        account = ctx.traders.account_view(tid)
        assert account["equity"] == 150000 and account["totalReturn"] == 0.0
        # 建仓后重置：回初始资金，净值断点保留
        await inject(ctx, quote())
        await ctx.trading.submit_order(tid, {
            "side": "buy", "type": "market", "code": "600519", "qty": 100,
        })
        await inject(ctx, quote())
        assert ctx.store.positions_for_trader(tid)
        ctx.store.upsert_snapshot(tid, "2026-09-15", 100000, 100000)  # 历史快照
        t3 = await ctx.traders.reset(tid)
        assert t3["cash"] == 150000 and ctx.store.positions_for_trader(tid) == []
        assert ctx.store.snapshots_for_trader(tid)  # 断点保留
    finally:
        await ctx.stop()


async def test_account_view_positions():
    _, ctx = make_app()
    await ctx.start()
    try:
        t = await ctx.traders.create({"name": "t", "mode": "manual", "initCash": 100000})
        tid = t["id"]
        await inject(ctx, quote())
        await ctx.trading.submit_order(tid, {
            "side": "buy", "type": "market", "code": "600519", "qty": 1000,
        })
        await inject(ctx, quote())
        account = ctx.traders.account_view(tid)
        assert len(account["positions"]) == 1
        pos = account["positions"][0]
        assert pos["qty"] == 1000 and pos["todayBought"] == 1000
        assert account["marketValue"] == 10000.0
        assert account["cash"] < 100000  # 已扣款
        # 动态流有 created / order / fill 事件
        actions = [e["action"] for e in ctx.store.events_feed()]
        assert "created" in actions and "order" in actions and "fill" in actions
    finally:
        await ctx.stop()
