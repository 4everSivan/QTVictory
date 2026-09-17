"""T03-2/3/4/8：费用、涨跌停带、±2% 有效申报范围、板块申报单位、冻结（02 §6.1）。"""

from app.domain.engine import (
    BookLevel, Tick, buy_freeze, calc_fee, limit_pct, lot_ok,
    price_limits, release_freeze, valid_band,
)


def mk_tick(code="600519", last=10.0, prev=10.0, bid=10.0, ask=10.0):
    return Tick(
        code=code, last=last, prev_close=prev,
        bids=[BookLevel(bid, 10000)], asks=[BookLevel(ask, 10000)],
    )


class TestFee:
    def test_commission_stamp_transfer(self):
        # 10 万买入：佣金 25 / 印花 0 / 过户 10
        fee = calc_fee(100000.0, is_buy=True)
        assert fee.commission == 25.0 and fee.stamp_tax == 0.0 and fee.transfer_fee == 10.0
        assert fee.total == 35.0
        # 10 万卖出：印花税 50
        fee = calc_fee(100000.0, is_buy=False)
        assert fee.stamp_tax == 50.0

    def test_min_commission_5(self):
        fee = calc_fee(1000.0, is_buy=True)
        assert fee.commission == 5.0  # 1000×0.00025=0.25 → 最低 5 元
        assert fee.transfer_fee == 0.1


class TestLimits:
    def test_main_board_10pct(self):
        lo, hi = price_limits(10.0, "600519")
        assert (lo, hi) == (9.0, 11.0)
        assert limit_pct("600519") == 10.0

    def test_gem_star_20pct(self):
        lo, hi = price_limits(10.0, "300750")
        assert (lo, hi) == (8.0, 12.0)
        lo, hi = price_limits(50.0, "688981")
        assert (lo, hi) == (40.0, 60.0)


class TestValidBand:
    def test_buy_band_takes_tighter(self):
        # 涨跌停 9~11，卖一 10.00 → 买 ≤ min(11, 10.20) = 10.20
        lo, hi = valid_band(mk_tick(ask=10.0), "buy", "600519")
        assert (lo, hi) == (9.0, 10.2)

    def test_sell_band(self):
        # 买一 10.00 → 卖 ≥ max(9, 9.80) = 9.80
        lo, hi = valid_band(mk_tick(bid=10.0), "sell", "600519")
        assert (lo, hi) == (9.8, 11.0)

    def test_no_level_falls_back_to_last(self):
        t = mk_tick()
        t.asks = []
        lo, hi = valid_band(t, "buy", "600519")
        assert hi == 10.2  # last 10.0 × 1.02


class TestLotSize:
    def test_main_board(self):
        assert lot_ok("600519", 100)
        assert lot_ok("600519", 300)
        assert not lot_ok("600519", 150)
        assert not lot_ok("600519", 0)

    def test_gem_board(self):
        assert lot_ok("300750", 200)
        assert not lot_ok("300750", 150)

    def test_star_board_increment(self):
        # 科创板：首购 ≥200，此后 1 股递增（02 §6.12 断言）
        assert not lot_ok("688981", 150)
        assert lot_ok("688981", 200)
        assert lot_ok("688981", 201)
        # 余额 <200 的零股须一次性卖出
        assert lot_ok("688981", 150, pos_qty=150, is_sell=True)
        assert not lot_ok("688981", 100, pos_qty=150, is_sell=True)
        assert lot_ok("688981", 250, pos_qty=300, is_sell=True)


class TestFreeze:
    def test_buy_freeze_with_margin(self):
        assert buy_freeze(10.0, 100) == 1002.0  # price×qty×1.002

    def test_proportional_release(self):
        # 冻结 1002，成交 40/100 → 剩余冻结 601.2
        assert release_freeze("buy", 1002.0, 100, 40) == 601.2

    def test_full_release(self):
        assert release_freeze("buy", 1002.0, 100, 100) == 0.0
