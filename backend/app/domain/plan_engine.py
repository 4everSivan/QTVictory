"""计划引擎内核（T04，02 §6.7）——纯函数，零 I/O。

- 四类触发器：price_cross（last 与阈值，单次触发防重复）/ pct_change（当日
  相对昨收）/ time（每交易日一次）/ ma_cross（日K收盘口径）；
- 风控钩子：止损止盈以移动加权成本为基准；日亏损（已实现+浮亏）达
  daily_max_loss → 计划转 paused + risk_halt；
- 策略围栏四道闸：池内 → 预算 → 仓位 → 单笔。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class OrderIntent:
    """策略/触发器的下单意图（经围栏过滤后才执行）。"""

    code: str
    side: str                      # buy | sell
    qty: int = 0                   # 股数（>0 时直接生效）
    pct_of_cash: float | None = None    # 按可用资金比例估算股数
    pct_of_position: float | None = None  # 按持仓比例卖出
    type: str = "market"           # limit | market
    price: float | None = None
    reason: str = ""


def _ma(values: list[float], n: int) -> float | None:
    if len(values) < n or n <= 0:
        return None
    return sum(values[-n:]) / n


def evaluate_entry(
    trigger_type: str,
    params: dict[str, Any],
    *,
    last: float,
    prev_close: float,
    closes: list[float],
    now_hhmm: str,
    today: str,
    last_triggered_on: str | None,
) -> bool:
    """条件单触发评估（单次触发防重复：同日已触发不再触发）。"""
    if last_triggered_on == today:
        return False
    side = params.get("side", "buy")
    if trigger_type == "price_cross":
        price = float(params["price"])
        return last <= price if side == "buy" else last >= price
    if trigger_type == "pct_change":
        pct = float(params["pct"])
        day_pct = (last / prev_close - 1.0) * 100.0 if prev_close else 0.0
        return day_pct <= pct if side == "buy" else day_pct >= pct
    if trigger_type == "time":
        return now_hhmm >= str(params.get("at", "14:50"))
    if trigger_type == "ma_cross":
        fast = _ma(closes, int(params.get("fast", 5)))
        slow = _ma(closes, int(params.get("slow", 20)))
        if fast is None or slow is None or len(closes) < int(params.get("slow", 20)) + 1:
            return False
        prev_fast = _ma(closes[:-1], int(params.get("fast", 5)))
        prev_slow = _ma(closes[:-1], int(params.get("slow", 20)))
        if prev_fast is None or prev_slow is None:
            return False
        golden = prev_fast <= prev_slow and fast > slow
        death = prev_fast >= prev_slow and fast < slow
        return golden if side == "buy" else death
    raise ValueError(f"unknown trigger_type: {trigger_type}")


def check_stop(
    avg_cost: float, last: float,
    stop_loss_pct: float | None, take_profit_pct: float | None,
) -> str | None:
    """止损/止盈（以移动加权成本为基准）；返回 'sell' 或 None。"""
    if avg_cost <= 0:
        return None
    if stop_loss_pct and last <= avg_cost * (1 - stop_loss_pct):
        return "sell"
    if take_profit_pct and last >= avg_cost * (1 + take_profit_pct):
        return "sell"
    return None


def check_daily_loss(realized_today: float, unrealized_today: float, daily_max_loss: float | None) -> bool:
    """日亏损（已实现 + 浮亏）达上限 → 熔断。"""
    if daily_max_loss is None or daily_max_loss <= 0:
        return False
    return (realized_today + unrealized_today) <= -daily_max_loss


GATE_SCOPE = "scope"
GATE_BUDGET = "budget"
GATE_POSITION = "position_rule"
GATE_SINGLE = "single_order"


def apply_fence(
    intent: OrderIntent,
    *,
    plan_scope_codes: list[str],
    plan_budget: dict[str, Any] | None,
    plan_position_rule: dict[str, Any] | None,
    plan_risk: dict[str, Any] | None,
    equity: float,
    code_position_value: float,
    order_amount: float,
) -> tuple[bool, str | None]:
    """策略围栏四道闸（02 §6.7）：池内 → 预算 → 仓位 → 单笔。

    卖出意图只过池内闸（卖出降低风险敞口）。
    """
    if intent.code not in plan_scope_codes:
        return False, GATE_SCOPE
    if intent.side == "sell":
        return True, None
    budget = plan_budget or {}
    max_pct_equity = budget.get("maxPctOfEquity")
    if max_pct_equity is not None:
        if code_position_value + order_amount > equity * float(max_pct_equity):
            return False, GATE_BUDGET
    max_amount = budget.get("maxAmount")
    if max_amount is not None and code_position_value + order_amount > float(max_amount):
        return False, GATE_BUDGET
    rule = plan_position_rule or {}
    max_pct_code = rule.get("maxPctPerCode")
    if max_pct_code is not None:
        if code_position_value + order_amount > equity * float(max_pct_code):
            return False, GATE_POSITION
    risk = plan_risk or {}
    max_order = risk.get("maxOrderAmount")
    if max_order is not None and order_amount > float(max_order):
        return False, GATE_SINGLE
    return True, None
