"""统计服务（T12，02 §3.8 统计侧 / §6.9）。

收盘结算快照 + 指标计算（总收益率 / 年化 252 / 最大回撤 / 夏普 /
胜率取卖出成交 / 超额 vs 沪深300）；快照不足 2 日返回 null。
指标计算为纯函数（可单测，T14 断言依据）。
"""

from __future__ import annotations

from typing import Any

BENCHMARK = "sh000300"


def compute_from_snapshots(
    snapshots: list[dict[str, Any]], sell_trades: list[dict[str, Any]],
    benchmark_closes: dict[str, float] | None = None,
) -> dict[str, Any]:
    """纯函数：由 equity 快照序列计算指标（§6.9 口径）。"""
    if len(snapshots) < 2:
        return {"insufficient": True, "totalReturn": None, "annualized": None,
                "maxDrawdown": None, "maxDrawdownDays": None, "sharpe": None,
                "winRate": None, "excess": None, "days": len(snapshots)}
    equities = [float(s["total_equity"]) for s in snapshots]
    dates = [s["date"] for s in snapshots]
    total_return = equities[-1] / equities[0] - 1.0 if equities[0] > 0 else 0.0
    n = len(equities) - 1
    annualized = (1.0 + total_return) ** (252.0 / n) - 1.0 if n > 0 else 0.0

    peak = equities[0]
    peak_idx = 0
    max_dd = 0.0
    dd_days = 0
    for i, eq in enumerate(equities):
        if eq > peak:
            peak = eq
            peak_idx = i
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            dd_days = i - peak_idx  # 谷底距峰顶的交易日数

    rets = [equities[i] / equities[i - 1] - 1.0 for i in range(1, len(equities))
            if equities[i - 1] > 0]
    sharpe = None
    if len(rets) >= 2:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        std = var ** 0.5
        if std > 0:
            sharpe = mean / std * (252.0 ** 0.5)

    sells = [t for t in sell_trades if t.get("realized_pnl") is not None]
    win_rate = (
        sum(1 for t in sells if t["realized_pnl"] > 0) / len(sells) if sells else None
    )

    excess = None
    if benchmark_closes:
        bench = [benchmark_closes.get(d) for d in (dates[0], dates[-1])]
        if all(b is not None and b > 0 for b in bench):
            excess = total_return - (bench[1] / bench[0] - 1.0)

    return {
        "insufficient": False,
        "days": len(snapshots),
        "totalReturn": round(total_return, 6),
        "annualized": round(annualized, 6),
        "maxDrawdown": round(max_dd, 6),
        "maxDrawdownDays": dd_days,
        "sharpe": round(sharpe, 4) if sharpe is not None else None,
        "winRate": round(win_rate, 4) if win_rate is not None else None,
        "excess": round(excess, 6) if excess is not None else None,
    }


class MetricsService:
    def __init__(self, ctx):
        self.ctx = ctx

    # -- 收盘结算（T12-1） --------------------------------------------------

    def close_snapshots(self, date_str: str) -> int:
        """对全体未关闭（running/paused）交易员落净值快照。"""
        store = self.ctx.store
        n = 0
        for trader in store.list_traders():
            if trader["status"] in ("closed", "deleted"):
                continue
            equity = trader["cash"]
            for pos in store.positions_for_trader(trader["id"]):
                equity += pos["qty"] * self.ctx.market.price(pos["code"])
            store.upsert_snapshot(trader["id"], date_str, round(equity, 2),
                                  round(trader["cash"], 2))
            n += 1
        return n

    # -- 指标（T12-2） ------------------------------------------------------

    def compute_metrics(self, trader_id: int) -> dict[str, Any] | None:
        store = self.ctx.store
        snapshots = store.snapshots_for_trader(trader_id)
        sells = [t for t in store.trades_feed(trader_id, limit=10**6)
                 if t["side"] == "sell"]
        bench = {k["date"]: k["close"] for k in store.klines_for(BENCHMARK, limit=10**4)}
        return compute_from_snapshots(snapshots, sells, bench or None)

    # -- 排行榜（T12-3） ----------------------------------------------------

    def leaderboard(self, *, include_closed: bool = False) -> list[dict[str, Any]]:
        rows = self.ctx.traders.list_view(include_closed=include_closed)
        for row in rows:
            row["metrics"] = self.compute_metrics(row["id"])
        return rows
