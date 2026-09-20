"""T07：下单校验链（§5.4 全码）/ 撮合集成 / 冻结解冻 / 撤单窗口 / 集合竞价 / 限额池竞争。"""

import pytest

from app.errors import BizError
from tests.harness import inject, make_app, quote


async def setup_ctx(**kw):
    _, ctx = make_app(**kw)
    await ctx.start()
    return ctx


@pytest.fixture
async def ctx():
    c = await setup_ctx()
    try:
        yield c
    finally:
        await c.stop()


async def _mk_trader(ctx, cash=2_000_000):
    t = await ctx.traders.create({"name": "t", "mode": "manual", "initCash": cash})
    return t["id"]


class TestValidationChain:
    async def test_lot_size(self, ctx):
        tid = await _mk_trader(ctx)
        await inject(ctx, quote())
        with pytest.raises(BizError) as ei:
            await ctx.trading.submit_order(tid, {
                "side": "buy", "type": "limit", "code": "sh600519",
                "price": 10.0, "qty": 150,
            })
        assert ei.value.code == "LOT_SIZE"

    async def test_price_band_with_dual_ranges(self, ctx):
        tid = await _mk_trader(ctx)
        await inject(ctx, quote())  # 卖一 10.00 → 买上限 10.20
        with pytest.raises(BizError) as ei:
            await ctx.trading.submit_order(tid, {
                "side": "buy", "type": "limit", "code": "sh600519",
                "price": 10.21, "qty": 100,
            })
        assert ei.value.code == "PRICE_BAND"
        d = ei.value.details
        assert d["limitBand"] == [9.0, 11.0] and d["effectiveBand"] == [9.0, 10.2]

    async def test_insufficient_funds(self, ctx):
        tid = await _mk_trader(ctx, cash=5000)
        await inject(ctx, quote())
        with pytest.raises(BizError) as ei:
            await ctx.trading.submit_order(tid, {
                "side": "buy", "type": "limit", "code": "sh600519",
                "price": 10.0, "qty": 1000,  # 需 10020 > 5000
            })
        assert ei.value.code == "INSUFFICIENT_FUNDS"

    async def test_t1_locked(self, ctx):
        tid = await _mk_trader(ctx)
        await inject(ctx, quote())
        await ctx.trading.submit_order(tid, {
            "side": "buy", "type": "market", "code": "sh600519", "qty": 1000,
        })
        await inject(ctx, quote())
        assert ctx.store.get_position(tid, "sh600519")["today_bought"] == 1000
        with pytest.raises(BizError) as ei:
            await ctx.trading.submit_order(tid, {
                "side": "sell", "type": "market", "code": "sh600519", "qty": 200,
            })
        assert ei.value.code == "T1_LOCKED"

    async def test_session_closed(self, ctx):
        tid = await _mk_trader(ctx)
        await inject(ctx, quote())
        ctx.clock.set(__import__("datetime").datetime.fromisoformat("2026-09-16T15:30:00"))
        with pytest.raises(BizError) as ei:
            await ctx.trading.submit_order(tid, {
                "side": "buy", "type": "limit", "code": "sh600519",
                "price": 10.0, "qty": 100,
            })
        assert ei.value.code == "SESSION_CLOSED"

    async def test_stale_quote_rejects_market_order(self, ctx):
        tid = await _mk_trader(ctx)
        await inject(ctx, quote())
        ctx.clock.advance(seconds=31)
        with pytest.raises(BizError) as ei:
            await ctx.trading.submit_order(tid, {
                "side": "buy", "type": "market", "code": "sh600519", "qty": 100,
            })
        assert ei.value.code == "STALE_QUOTE"

    async def test_suspended(self, ctx):
        tid = await _mk_trader(ctx)
        await inject(ctx, quote(last=0.0))
        with pytest.raises(BizError) as ei:
            await ctx.trading.submit_order(tid, {
                "side": "buy", "type": "limit", "code": "sh600519",
                "price": 10.0, "qty": 100,
            })
        assert ei.value.code == "SUSPENDED"

    async def test_unsupported_board_rejects_quoted_exotics(self, ctx):
        """C015：指数/ETF/北交所行情可及但规则未覆盖 → UNSUPPORTED_BOARD。"""
        tid = await _mk_trader(ctx)
        await inject(ctx, quote(code="sh000300"), quote(code="sh510300"),
                     quote(code="bj430047"))
        for code in ("sh000300", "sh510300", "bj430047"):
            with pytest.raises(BizError) as ei:
                await ctx.trading.submit_order(tid, {
                    "side": "buy", "type": "limit", "code": code,
                    "price": 10.0, "qty": 100,
                })
            assert ei.value.code == "UNSUPPORTED_BOARD", code

    async def test_bare_code_keeps_suspended_semantics(self, ctx):
        """C015：裸码无行情快照，维持原有 SUSPENDED 语义（白名单在行情检查之后）。"""
        tid = await _mk_trader(ctx)
        await inject(ctx, quote())
        with pytest.raises(BizError) as ei:
            await ctx.trading.submit_order(tid, {
                "side": "buy", "type": "limit", "code": "600519",
                "price": 10.0, "qty": 100,
            })
        assert ei.value.code == "SUSPENDED"

    async def test_trader_status_rejects(self, ctx):
        tid = await _mk_trader(ctx)
        await inject(ctx, quote())
        await ctx.traders.patch(tid, {"status": "paused"})
        with pytest.raises(BizError) as ei:
            await ctx.trading.submit_order(tid, {
                "side": "buy", "type": "limit", "code": "sh600519",
                "price": 10.0, "qty": 100,
            })
        assert ei.value.code == "TRADER_CLOSED"

    async def test_client_order_id_idempotent(self, ctx):
        tid = await _mk_trader(ctx)
        await inject(ctx, quote())
        payload = {"side": "buy", "type": "limit", "code": "sh600519",
                   "price": 10.0, "qty": 100, "clientOrderId": "ext-0001"}
        o1 = await ctx.trading.submit_order(tid, payload)
        o2 = await ctx.trading.submit_order(tid, dict(payload, price=10.0))
        assert o1["id"] == o2["id"]  # 重复提交返回首次结果
        assert len(ctx.store.orders_feed(tid)) == 1


class TestMatchingIntegration:
    async def test_market_buy_multi_fill_and_costs(self, ctx):
        """市价单五档成交、一单多笔、费用与加权成本（§6.12）。"""
        tid = await _mk_trader(ctx)
        # 五档各 300 股 → 700 股吃三档
        def book_quote(cum):
            q = quote(cum=cum)
            q.asks = [(10.00, 300), (10.01, 300), (10.02, 300), (10.03, 300), (10.04, 300)]
            q.bids = [(9.99, 300), (9.98, 300), (9.97, 300), (9.96, 300), (9.95, 300)]
            return q

        await inject(ctx, book_quote(1_000_000))
        order = await ctx.trading.submit_order(tid, {
            "side": "buy", "type": "market", "code": "sh600519", "qty": 700,
        })
        await inject(ctx, book_quote(2_000_000))
        order = ctx.store.get_order(order["id"])
        assert order["status"] == "filled" and order["filled_qty"] == 700
        assert abs(order["avg_filled_price"] - 7005.0 / 700) < 0.0001
        trades = ctx.store.trades_for_order(order["id"])
        assert [t["qty"] for t in trades] == [300, 300, 100]  # 一单多笔
        pos = ctx.store.get_position(tid, "sh600519")
        assert pos["qty"] == 700 and pos["today_bought"] == 700
        # 移动加权成本含费用：成交额 7005 + 三笔费用（5.3+5.3+5.1）
        fees = sum(t["commission"] + t["stamp_tax"] + t["transfer_fee"] for t in trades)
        assert abs(pos["avg_cost"] - (7005.0 + fees) / 700) < 1e-9
        assert ctx.store.get_trader(tid)["cash"] == pytest.approx(2_000_000 - 7005.0 - fees)

    async def test_limit_partial_accumulates(self, ctx):
        """限价单跨 tick 部分成交累计（量约束分批）。"""
        tid = await _mk_trader(ctx, cash=1_000_000)
        await inject(ctx, quote(cum=100_000))  # 基线
        order = await ctx.trading.submit_order(tid, {
            "side": "buy", "type": "limit", "code": "sh600519",
            "price": 10.0, "qty": 50000,
        })
        await inject(ctx, quote(cum=200_000))  # ΔV=100000 → cap 25000
        order = ctx.store.get_order(order["id"])
        assert order["status"] == "partial" and order["filled_qty"] == 25000
        frozen = order["frozen_amount"]
        assert frozen == pytest.approx(50000 * 10 * 1.002 * 25000 / 50000)  # 按比例剩余
        await inject(ctx, quote(cum=200_600))  # ΔV=600 → cap 150
        order = ctx.store.get_order(order["id"])
        assert order["filled_qty"] == 25150 and order["status"] == "partial"

    async def test_sell_realized_pnl(self, ctx):
        tid = await _mk_trader(ctx)
        await inject(ctx, quote())
        await ctx.trading.submit_order(tid, {
            "side": "buy", "type": "market", "code": "sh600519", "qty": 1000,
        })
        await inject(ctx, quote())
        buy_fee = 5.0 + 10000 * 0.0001  # 佣金 5 + 过户 1
        avg = (10000.0 + buy_fee) / 1000
        # T+1：改交易日解锁
        ctx.clock.set(__import__("datetime").datetime.fromisoformat("2026-09-17T09:30:00"))
        await inject(ctx, quote(last=11.0, cum=3_000_000))
        ctx.store.t1_reset_all()
        await ctx.trading.submit_order(tid, {
            "side": "sell", "type": "limit", "code": "sh600519", "price": 11.0, "qty": 1000,
        })
        await inject(ctx, quote(last=11.0, cum=3_010_000))
        trades = [t for t in ctx.store.trades_feed(tid) if t["side"] == "sell"]
        assert trades and trades[0]["realized_pnl"] == pytest.approx(
            (11.0 - avg) * 1000 - (5 + 11000 * 0.0005 + 11000 * 0.0001)
        )

    async def test_pool_competition_arrival_order(self, ctx):
        """限额池多交易员竞争：先到先得、合计不穿透（§6.12 集成）。"""
        t1 = await _mk_trader(ctx)
        t2 = await _mk_trader(ctx)
        await inject(ctx, quote(cum=1000))  # 基线
        await ctx.trading.submit_order(t1, {
            "side": "buy", "type": "limit", "code": "sh600519", "price": 10.0, "qty": 200,
        })
        await ctx.trading.submit_order(t2, {
            "side": "buy", "type": "limit", "code": "sh600519", "price": 10.0, "qty": 200,
        })
        await inject(ctx, quote(cum=2000))  # ΔV=1000 → cap 250
        p1 = ctx.store.get_position(t1, "sh600519")
        p2 = ctx.store.get_position(t2, "sh600519")
        assert p1["qty"] == 200          # 先到先得
        assert p2["qty"] == 50           # 剩余额度
        assert p1["qty"] + p2["qty"] == 250  # 合计 ≤ ΔV×25%


class TestCancelAndAuction:
    async def test_cancel_releases_freeze(self, ctx):
        tid = await _mk_trader(ctx)
        await inject(ctx, quote())
        order = await ctx.trading.submit_order(tid, {
            "side": "buy", "type": "limit", "code": "sh600519",
            "price": 9.95, "qty": 1000,  # 不穿越 → wait
        })
        assert ctx.traders.account_view(tid)["availableCash"] == pytest.approx(
            2_000_000 - 9.95 * 1000 * 1.002)
        cancelled = await ctx.trading.cancel(tid, order["id"])
        assert cancelled["status"] == "cancel"
        assert ctx.traders.account_view(tid)["availableCash"] == 2_000_000  # 解冻

    async def test_cancel_window_in_auction(self, ctx):
        """可撤窗口：9:15–9:20 可撤，9:20–9:25 禁撤（§6.1）。"""
        tid = await _mk_trader(ctx)
        await inject(ctx, quote(), now=__import__("datetime").datetime.fromisoformat(
            "2026-09-16T09:16:00"))
        order = await ctx.trading.submit_order(tid, {
            "side": "buy", "type": "limit", "code": "sh600519", "price": 9.95, "qty": 100,
        })
        ctx.clock.set(__import__("datetime").datetime.fromisoformat("2026-09-16T09:21:00"))
        with pytest.raises(BizError) as ei:
            await ctx.trading.cancel(tid, order["id"])
        assert ei.value.code == "SESSION_CLOSED"

    async def test_auction_settlement(self, ctx):
        """集合竞价：买单价 ≥ 集合竞价价即成交、成交价 = 集合竞价价（§6.12）。"""
        tid = await _mk_trader(ctx)
        await inject(ctx, quote(), now=__import__("datetime").datetime.fromisoformat(
            "2026-09-16T09:16:00"))
        order = await ctx.trading.submit_order(tid, {
            "side": "buy", "type": "limit", "code": "sh600519", "price": 10.00, "qty": 100,
        })
        ctx.trading.settle_auction("sh600519", auction_price=9.90, auction_volume=100000)
        order = ctx.store.get_order(order["id"])
        assert order["status"] == "filled" and order["avg_filled_price"] == 9.90
        assert ctx.store.get_position(tid, "sh600519")["qty"] == 100
