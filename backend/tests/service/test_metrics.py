"""T12：指标计算纯函数（§6.9 口径）与收盘快照。"""

from app.services.metrics import compute_from_snapshots
from tests.harness import inject, make_app, quote


def snap(date, total, cash=0.0):
    return {"date": date, "total_equity": total, "cash": cash}


class TestPure:
    def test_insufficient_snapshots_null(self):
        out = compute_from_snapshots([snap("2026-09-15", 100)], [])
        assert out["insufficient"] and out["totalReturn"] is None

    def test_basic_series(self):
        out = compute_from_snapshots(
            [snap("09-15", 100.0), snap("09-16", 120.0), snap("09-17", 90.0)], [],
        )
        assert out["totalReturn"] == round(90 / 100 - 1, 6)  # -10%
        assert out["maxDrawdown"] == round((120 - 90) / 120, 6)  # 25%
        assert out["maxDrawdownDays"] == 1  # 谷底距峰顶 1 个交易日
        assert out["annualized"] == round((1 - 0.1) ** (252 / 2) - 1, 6)
        assert out["sharpe"] is not None

    def test_win_rate_from_sells_only(self):
        sells = [
            {"side": "sell", "realized_pnl": 100},
            {"side": "sell", "realized_pnl": -50},
            {"side": "sell", "realized_pnl": 30},
            {"side": "buy", "realized_pnl": None},
        ]
        out = compute_from_snapshots([snap("d1", 100), snap("d2", 110)], sells)
        assert out["winRate"] == round(2 / 3, 4)

    def test_excess_vs_benchmark(self):
        bench = {"2026-09-15": 100.0, "2026-09-16": 105.0}
        out = compute_from_snapshots(
            [snap("2026-09-15", 100.0), snap("2026-09-16", 110.0)], [], bench,
        )
        assert out["excess"] == round(0.10 - 0.05, 6)

    def test_flat_series_sharpe_none(self):
        out = compute_from_snapshots([snap("d1", 100.0), snap("d2", 100.0)], [])
        assert out["sharpe"] is None and out["maxDrawdown"] == 0.0


async def test_close_snapshots_and_leaderboard():
    _, ctx = make_app()
    await ctx.start()
    try:
        t = await ctx.traders.create({"name": "t", "mode": "manual", "initCash": 100000})
        tid = t["id"]
        await inject(ctx, quote())
        await ctx.trading.submit_order(tid, {
            "side": "buy", "type": "market", "code": "sh600519", "qty": 1000,
        })
        await inject(ctx, quote())
        n = ctx.metrics.close_snapshots("2026-09-16")
        assert n == 1
        s = ctx.store.snapshots_for_trader(tid)[-1]
        assert s["total_equity"] == round(ctx.store.get_trader(tid)["cash"] + 10000, 2)
        # 指标：单快照 → 不足 2 日 null
        assert ctx.metrics.compute_metrics(tid)["insufficient"]
        # 排行榜
        board = ctx.metrics.leaderboard()
        assert board[0]["id"] == tid and "totalReturn" in board[0]
    finally:
        await ctx.stop()
