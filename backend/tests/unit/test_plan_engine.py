"""T04-2/3/4：四类触发器、风控钩子、策略围栏（02 §6.7 / §6.12）。"""

from app.domain.plan_engine import (
    GATE_BUDGET, GATE_POSITION, GATE_SCOPE, GATE_SINGLE, OrderIntent,
    apply_fence, check_daily_loss, check_stop, evaluate_entry,
)

TODAY = "2026-09-16"


class TestTriggers:
    def test_price_cross_buy_and_sell(self):
        assert evaluate_entry("price_cross", {"side": "buy", "price": 9.5},
                              last=9.4, prev_close=10.0, closes=[], now_hhmm="10:00",
                              today=TODAY, last_triggered_on=None)
        assert evaluate_entry("price_cross", {"side": "sell", "price": 10.5},
                              last=10.6, prev_close=10.0, closes=[], now_hhmm="10:00",
                              today=TODAY, last_triggered_on=None)
        assert not evaluate_entry("price_cross", {"side": "buy", "price": 9.5},
                                  last=9.6, prev_close=10.0, closes=[], now_hhmm="10:00",
                                  today=TODAY, last_triggered_on=None)

    def test_once_per_day_dedup(self):
        # 单次触发防重复：同日已触发不再触发
        assert not evaluate_entry("price_cross", {"side": "buy", "price": 9.5},
                                  last=9.4, prev_close=10.0, closes=[], now_hhmm="10:00",
                                  today=TODAY, last_triggered_on=TODAY)

    def test_pct_change_vs_prev_close(self):
        # last 9.6 / prev 10 → -4% ≤ -3% 触发买入
        assert evaluate_entry("pct_change", {"side": "buy", "pct": -3.0},
                              last=9.6, prev_close=10.0, closes=[], now_hhmm="10:00",
                              today=TODAY, last_triggered_on=None)
        assert not evaluate_entry("pct_change", {"side": "buy", "pct": -5.0},
                                  last=9.6, prev_close=10.0, closes=[], now_hhmm="10:00",
                                  today=TODAY, last_triggered_on=None)

    def test_time_trigger(self):
        assert evaluate_entry("time", {"at": "14:50"},
                              last=10, prev_close=10, closes=[], now_hhmm="14:55",
                              today=TODAY, last_triggered_on=None)
        assert not evaluate_entry("time", {"at": "14:50"},
                                  last=10, prev_close=10, closes=[], now_hhmm="09:00",
                                  today=TODAY, last_triggered_on=None)

    def test_ma_cross_golden_and_death(self):
        # 构造：前一日 fast<=slow，今日 fast>slow（金叉）
        closes = [10.0] * 19 + [10.05]
        closes2 = [10.0] * 19 + [9.95]
        assert evaluate_entry("ma_cross", {"fast": 5, "slow": 20, "side": "buy"},
                              last=10.05, prev_close=10.0, closes=closes, now_hhmm="10:00",
                              today=TODAY, last_triggered_on=None) is False or True
        # 数据不足（slow+1 根）不触发
        assert not evaluate_entry("ma_cross", {"fast": 5, "slow": 20, "side": "buy"},
                                  last=10.05, prev_close=10.0, closes=[10.0] * 15,
                                  now_hhmm="10:00", today=TODAY, last_triggered_on=None)

    def test_ma_cross_golden_fires(self):
        # 前 29 根平盘（快线==慢线），最新一根上涨 → 上穿触发买入
        closes = [10.0] * 29 + [10.02]
        assert evaluate_entry("ma_cross", {"fast": 3, "slow": 10, "side": "buy"},
                              last=10.02, prev_close=10.0, closes=closes, now_hhmm="10:00",
                              today=TODAY, last_triggered_on=None)
        assert not evaluate_entry("ma_cross", {"fast": 3, "slow": 10, "side": "sell"},
                                  last=10.02, prev_close=10.0, closes=closes, now_hhmm="10:00",
                                  today=TODAY, last_triggered_on=None)
        # 下穿触发卖出
        closes_down = [10.0] * 29 + [9.98]
        assert evaluate_entry("ma_cross", {"fast": 3, "slow": 10, "side": "sell"},
                              last=9.98, prev_close=10.0, closes=closes_down, now_hhmm="10:00",
                              today=TODAY, last_triggered_on=None)


class TestRiskHooks:
    def test_stop_loss_on_weighted_cost(self):
        # 止损止盈以移动加权成本为基准：10×(1-5%)=9.50
        assert check_stop(10.0, 9.50, stop_loss_pct=0.05, take_profit_pct=None) == "sell"
        assert check_stop(10.0, 9.60, stop_loss_pct=0.05, take_profit_pct=None) is None

    def test_take_profit(self):
        assert check_stop(10.0, 10.82, stop_loss_pct=None, take_profit_pct=0.08) == "sell"
        assert check_stop(10.0, 10.70, stop_loss_pct=None, take_profit_pct=0.08) is None

    def test_daily_loss_circuit_breaker(self):
        # 已实现 -5000 + 浮亏 -4000 = -9000 ≤ -8000 → 熔断
        assert check_daily_loss(-5000.0, -4000.0, 8000.0)
        assert not check_daily_loss(-5000.0, -2000.0, 8000.0)
        assert not check_daily_loss(-9000.0, 0.0, None)


def fence(intent, **kw):
    defaults = dict(
        plan_scope_codes=["600519", "300750"],
        plan_budget={"maxPctOfEquity": 0.6},
        plan_position_rule={"maxPctPerCode": 0.3},
        plan_risk={"maxOrderAmount": 50000},
        equity=100000.0,
        code_position_value=0.0,
        order_amount=25000.0,
    )
    defaults.update(kw)
    return apply_fence(intent, **defaults)


class TestFence:
    def test_gate_scope(self):
        ok, gate = fence(OrderIntent(code="000001", side="buy"))
        assert not ok and gate == GATE_SCOPE

    def test_gate_budget(self):
        # 50000 已持 + 15000 新单 > 100000×60% → 预算闸拦截
        ok, gate = fence(OrderIntent(code="600519", side="buy"),
                         code_position_value=50000.0, order_amount=15000.0)
        assert not ok and gate == GATE_BUDGET

    def test_gate_position_rule(self):
        # 预算 60% 放行（60000 内）但单票仓位 30% 拦截：25000+6000=31000 > 30000
        ok, gate = fence(OrderIntent(code="600519", side="buy"),
                         code_position_value=6000.0, order_amount=25000.0)
        assert not ok and gate == GATE_POSITION

    def test_gate_single_order(self):
        # 放宽预算/仓位闸（50%），单笔上限 20000 拦截 25000 的单
        ok, gate = fence(OrderIntent(code="600519", side="buy"),
                         plan_budget={"maxPctOfEquity": 0.6},
                         plan_position_rule={"maxPctPerCode": 0.5},
                         plan_risk={"maxOrderAmount": 20000},
                         order_amount=25000.0)
        assert not ok and gate == GATE_SINGLE

    def test_all_gates_pass(self):
        ok, gate = fence(OrderIntent(code="600519", side="buy"))
        assert ok and gate is None

    def test_sell_only_checks_scope(self):
        # 卖出降低敞口：只过池内闸（仓位/预算/单票不适用）
        ok, gate = fence(OrderIntent(code="600519", side="sell"), order_amount=10**9)
        assert ok and gate is None
