"""T03-5/6/7/10/11：市价五档/对手方、限价排队与部分成交、量约束、降级档（02 §6.1/§6.12）。"""

from app.domain.engine import (
    BookLevel, MatchOutcome, Tick, limit_match, market_match, tick_volume_cap,
)


def mk_tick(delta_volume=10**9, degraded=False, last=10.0, prev=10.0):
    return Tick(
        code="600519", last=last, prev_close=prev,
        bids=[BookLevel(9.99, 300), BookLevel(9.98, 300), BookLevel(9.97, 300),
              BookLevel(9.96, 300), BookLevel(9.95, 300)],
        asks=[BookLevel(10.00, 300), BookLevel(10.01, 300), BookLevel(10.02, 300),
              BookLevel(10.03, 300), BookLevel(10.04, 300)],
        delta_volume=delta_volume, degraded=degraded, ts="2026-09-16T10:00:00",
    )


BIG = 10**9


class TestMarketBest5:
    def test_walk_levels_weighted_avg(self):
        # 吃三档：300@10.00 + 300@10.01 + 100@10.02，加权均价 10.0071…→10.01
        out = market_match("buy", 700, mk_tick(), BIG)
        assert out.filled_qty == 700 and out.status == "filled"
        assert [f.qty for f in out.fills] == [300, 300, 100]
        assert [f.price for f in out.fills] == [10.00, 10.01, 10.02]
        assert abs(out.avg_price - 7005.0 / 700) < 0.001

    def test_remaining_cancelled_immediately(self):
        # 五档合计 1500，需求 2000 → 成交 1500，剩余 500 即时撤销
        out = market_match("buy", 2000, mk_tick(), BIG)
        assert out.filled_qty == 1500
        assert out.remaining_qty == 500
        assert out.status == "cancel"

    def test_level_and_cap_dual_constraint(self):
        # 档位挂量充足但限额 200 → 只成交 200
        out = market_match("buy", 700, mk_tick(), cap=200)
        assert out.filled_qty == 200
        assert out.fills == [BookLevel(10.00, 200)] or (
            out.fills[0].price == 10.00 and out.fills[0].qty == 200
        )

    def test_sell_side_eats_bids(self):
        out = market_match("sell", 400, mk_tick(), BIG)
        assert [f.price for f in out.fills] == [9.99, 9.98]
        assert [f.qty for f in out.fills] == [300, 100]


class TestMarketOpponentBest:
    def test_opponent_first_level(self):
        out = market_match("sell", 200, mk_tick(), BIG, market_type="opponent_best")
        assert out.filled_qty == 200 and out.avg_price == 9.99 and out.status == "filled"

    def test_opponent_partial_then_cancel(self):
        out = market_match("sell", 500, mk_tick(), BIG, market_type="opponent_best")
        assert out.filled_qty == 300 and out.avg_price == 9.99
        assert out.status == "cancel" and out.remaining_qty == 200


class TestVolumeCap:
    def test_cap_from_delta_volume(self):
        assert tick_volume_cap(mk_tick(delta_volume=1000), 0.25) == 250

    def test_degraded_has_no_cap(self):
        assert tick_volume_cap(mk_tick(degraded=True), 0.25) >= 10**9


class TestLimitQueue:
    def test_no_cross_waits(self):
        out = limit_match("buy", 9.99, 100, mk_tick(last=10.00), BIG)
        assert out.status == "wait" and out.filled_qty == 0

    def test_cross_fills_at_order_price(self):
        # 买：last ≤ price 触发；成交价 = 委托价
        out = limit_match("buy", 10.00, 100, mk_tick(last=10.00), BIG)
        assert out.status == "filled" and out.avg_price == 10.00

    def test_partial_accumulates_over_ticks(self):
        # §6.12：量约束分批与部分成交累计
        out1 = limit_match("buy", 10.00, 500, mk_tick(last=10.00), cap=200)
        assert out1.status == "partial" and out1.filled_qty == 200
        out2 = limit_match("buy", 10.00, 300, mk_tick(last=10.00), cap=300)
        assert out2.status == "filled" and out2.filled_qty == 300

    def test_sell_cross(self):
        out = limit_match("sell", 10.00, 100, mk_tick(last=10.01), BIG)
        assert out.status == "filled" and out.avg_price == 10.00


class TestFallbackFill:
    def test_fixed_slippage_full_fill(self):
        t = mk_tick(degraded=True, last=100.0)
        out = market_match("buy", 1000, t, 0)
        assert out.status == "filled" and out.filled_qty == 1000
        assert abs(out.avg_price - 100.05) < 0.006
        assert out.fill_model == "fallback"
        sell = market_match("sell", 1000, t, 0)
        assert abs(sell.avg_price - 99.95) < 0.006

    def test_limit_fallback_full_fill(self):
        t = mk_tick(degraded=True, last=100.0)
        out = limit_match("buy", 99.0, 500, t, cap=0)
        assert out.status == "filled" and out.filled_qty == 500
        assert out.fill_model == "fallback"


class TestPoolCompetition:
    def test_shared_pool_arrival_order(self):
        """§6.12：限额池多交易员竞争——先到先得，合计不穿透限额。"""
        t = mk_tick(delta_volume=1000)  # cap=250 @25%
        cap = tick_volume_cap(t, 0.25)
        first = market_match("buy", 200, t, cap)
        remaining_cap = cap - first.filled_qty
        second = market_match("buy", 200, t, remaining_cap)
        assert first.filled_qty == 200
        assert second.filled_qty == 50
        assert first.filled_qty + second.filled_qty == 250  # 不穿透真实流动性
