"""8 个策略模板（T04-5，02 §3.5 / §6.7）——纯函数。

定位：平台功能验证与绩效基线参照，非产品内容。
参数 schema 与前端 v1 §8 一致；输出下单意图（OrderIntent），
须经 PlanEngine.apply_fence 围栏过滤后才执行。
"""

from __future__ import annotations

from typing import Any, Callable

from app.domain.plan_engine import OrderIntent


def _ma(values: list[float], n: int) -> float | None:
    if len(values) < n or n <= 0:
        return None
    return sum(values[-n:]) / n


def _std(values: list[float], n: int) -> float | None:
    if len(values) < n or n <= 0:
        return None
    tail = values[-n:]
    m = sum(tail) / n
    return (sum((v - m) ** 2 for v in tail) / n) ** 0.5


def _intent_buy_pct(code: str, pct: float, reason: str) -> OrderIntent:
    return OrderIntent(code=code, side="buy", pct_of_cash=pct, type="market", reason=reason)


def _intent_sell_pct(code: str, pct: float, reason: str) -> OrderIntent:
    return OrderIntent(code=code, side="sell", pct_of_position=pct, type="market", reason=reason)


def _ctx(mview: dict[str, Any]) -> tuple[float, float, list[float]]:
    return mview["last"], mview["prev_close"], list(mview.get("closes", []))


# ---- 8 模板 ------------------------------------------------------------


def strat_trend(mview: dict[str, Any], account: dict[str, Any], p: dict[str, Any]) -> list[OrderIntent]:
    """趋势跟踪：MA5 上穿 MA20 买入、下穿卖出。"""
    last, _, closes = _ctx(mview)
    fast_n, slow_n = int(p.get("fast", 5)), int(p.get("slow", 20))
    fast, slow = _ma(closes, fast_n), _ma(closes, slow_n)
    if fast is None or slow is None:
        return []
    if fast > slow and (len(closes) < slow_n + 1 or
                        (_ma(closes[:-1], fast_n) or 0) <= (_ma(closes[:-1], slow_n) or 0)):
        return [_intent_buy_pct(mview["code"], float(p.get("pctOfCash", 0.2)), "ma_golden")]
    if fast < slow:
        return [_intent_sell_pct(mview["code"], float(p.get("pctSell", 1.0)), "ma_death")]
    return []


def strat_mean_reversion(mview: dict[str, Any], account: dict[str, Any], p: dict[str, Any]) -> list[OrderIntent]:
    """均值回归：z 值超 ±threshold 反向操作。"""
    last, _, closes = _ctx(mview)
    n = int(p.get("window", 20))
    m, s = _ma(closes, n), _std(closes, n)
    if m is None or s is None or s == 0:
        return []
    z = (last - m) / s
    if z <= -float(p.get("threshold", 1.5)):
        return [_intent_buy_pct(mview["code"], float(p.get("pctOfCash", 0.15)), f"z={z:.2f}")]
    if z >= float(p.get("threshold", 1.5)):
        return [_intent_sell_pct(mview["code"], float(p.get("pctSell", 0.5)), f"z={z:.2f}")]
    return []


def strat_grid(mview: dict[str, Any], account: dict[str, Any], p: dict[str, Any]) -> list[OrderIntent]:
    """网格：价格落在 mid±k×step 的格点带内低买高卖。"""
    last, _, closes = _ctx(mview)
    m = _ma(closes, int(p.get("window", 20)))
    if m is None:
        return []
    step = m * float(p.get("gridPct", 0.02))
    offset = (last - m) / step if step > 0 else 0.0
    if offset <= -1:
        return [_intent_buy_pct(mview["code"], float(p.get("pctOfCash", 0.1)), f"grid_off={offset:.2f}")]
    if offset >= 1:
        return [_intent_sell_pct(mview["code"], float(p.get("pctSell", 0.3)), f"grid_off={offset:.2f}")]
    return []


def strat_momentum_breakout(mview: dict[str, Any], account: dict[str, Any], p: dict[str, Any]) -> list[OrderIntent]:
    """动量突破：突破 N 日高点买入（×buffer），跌破 N 日低点卖出。"""
    last, _, closes = _ctx(mview)
    n = int(p.get("lookback", 20))
    if len(closes) < n:
        return []
    hi, lo = max(closes[-n:]), min(closes[-n:])
    buf = float(p.get("buffer", 1.01))
    if last >= hi * buf:
        return [_intent_buy_pct(mview["code"], float(p.get("pctOfCash", 0.25)), "break_high")]
    if last <= lo * (2 - buf):
        return [_intent_sell_pct(mview["code"], float(p.get("pctSell", 1.0)), "break_low")]
    return []


def strat_long_value(mview: dict[str, Any], account: dict[str, Any], p: dict[str, Any]) -> list[OrderIntent]:
    """长线价值：价格相对长期均值（MA60）偏离带外反向。"""
    last, _, closes = _ctx(mview)
    m = _ma(closes, int(p.get("window", 60)))
    if m is None:
        return []
    band = float(p.get("band", 0.1))
    if last <= m * (1 - band):
        return [_intent_buy_pct(mview["code"], float(p.get("pctOfCash", 0.3)), "below_band")]
    if last >= m * (1 + band):
        return [_intent_sell_pct(mview["code"], float(p.get("pctSell", 0.3)), "above_band")]
    return []


def strat_quick_trade(mview: dict[str, Any], account: dict[str, Any], p: dict[str, Any]) -> list[OrderIntent]:
    """短线快进：日内动量追涨 / 止损。"""
    last, prev_close, _ = _ctx(mview)
    day_pct = (last / prev_close - 1.0) * 100 if prev_close else 0.0
    if day_pct >= float(p.get("chasePct", 3.0)):
        return [_intent_buy_pct(mview["code"], float(p.get("pctOfCash", 0.2)), f"day%={day_pct:.1f}")]
    if day_pct <= -float(p.get("stopPct", 2.0)):
        return [_intent_sell_pct(mview["code"], float(p.get("pctSell", 1.0)), f"day%={day_pct:.1f}")]
    return []


def strat_event_driven(mview: dict[str, Any], account: dict[str, Any], p: dict[str, Any]) -> list[OrderIntent]:
    """事件驱动：放量 + 同向涨幅视为事件信号。"""
    last, prev_close, _ = _ctx(mview)
    vol_ratio = mview.get("volumeRatio")
    if vol_ratio is None:
        return []
    day_pct = (last / prev_close - 1.0) * 100 if prev_close else 0.0
    if vol_ratio >= float(p.get("volumeRatio", 2.0)) and day_pct >= float(p.get("minPct", 1.0)):
        return [_intent_buy_pct(mview["code"], float(p.get("pctOfCash", 0.15)), f"vol_x{vol_ratio:.1f}")]
    return []


def strat_conservative(mview: dict[str, Any], account: dict[str, Any], p: dict[str, Any]) -> list[OrderIntent]:
    """保守配置：目标权重再平衡（偏离 > threshold 时调仓）。"""
    code = mview["code"]
    last, _, _ = _ctx(mview)
    equity = float(account.get("equity", 0))
    positions = account.get("positions", {})
    pos_value = positions.get(code, {}).get("qty", 0) * last
    target_pct = float(p.get("targetPct", 0.25))
    threshold = float(p.get("threshold", 0.05))
    if equity <= 0:
        return []
    current = pos_value / equity
    if current < target_pct - threshold:
        gap = (target_pct - current) * equity
        return [OrderIntent(code=code, side="buy", qty=max(100, int(gap / last / 100) * 100),
                            type="market", reason="rebalance_under")]
    if current > target_pct + threshold:
        gap = (current - target_pct) * equity
        return [OrderIntent(code=code, side="sell", qty=max(100, int(gap / last / 100) * 100),
                            type="market", reason="rebalance_over")]
    return []


# ---- 注册表（GET /api/templates 数据源） -------------------------------

TEMPLATES: dict[str, dict[str, Any]] = {
    "trend": {
        "name": "趋势跟踪", "fn": strat_trend,
        "params": {"fast": 5, "slow": 20, "pctOfCash": 0.2, "pctSell": 1.0},
    },
    "mean_reversion": {
        "name": "均值回归", "fn": strat_mean_reversion,
        "params": {"window": 20, "threshold": 1.5, "pctOfCash": 0.15, "pctSell": 0.5},
    },
    "grid": {
        "name": "网格", "fn": strat_grid,
        "params": {"window": 20, "gridPct": 0.02, "pctOfCash": 0.1, "pctSell": 0.3},
    },
    "momentum": {
        "name": "动量突破", "fn": strat_momentum_breakout,
        "params": {"lookback": 20, "buffer": 1.01, "pctOfCash": 0.25, "pctSell": 1.0},
    },
    "long_value": {
        "name": "长线价值", "fn": strat_long_value,
        "params": {"window": 60, "band": 0.1, "pctOfCash": 0.3, "pctSell": 0.3},
    },
    "quick_trade": {
        "name": "短线快进", "fn": strat_quick_trade,
        "params": {"chasePct": 3.0, "stopPct": 2.0, "pctOfCash": 0.2, "pctSell": 1.0},
    },
    "event_driven": {
        "name": "事件驱动", "fn": strat_event_driven,
        "params": {"volumeRatio": 2.0, "minPct": 1.0, "pctOfCash": 0.15},
    },
    "conservative": {
        "name": "保守配置", "fn": strat_conservative,
        "params": {"targetPct": 0.25, "threshold": 0.05},
    },
}


def run_template(
    template: str, params: dict[str, Any],
    mview: dict[str, Any], account: dict[str, Any],
) -> list[OrderIntent]:
    """执行模板：用户参数覆盖默认参数后求值。"""
    tpl = TEMPLATES[template]
    merged = {**tpl["params"], **(params or {})}
    return tpl["fn"](mview, account, merged)


def templates_payload() -> list[dict[str, Any]]:
    """GET /api/templates 响应体（02 §5.2：8 种，含参数 schema）。"""
    return [
        {"template": key, "name": tpl["name"],
         "params": {k: {"default": v} for k, v in tpl["params"].items()}}
        for key, tpl in TEMPLATES.items()
    ]
