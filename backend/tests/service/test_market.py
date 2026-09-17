"""T06：腾讯解析 / ΔV 差分 / 降级状态 / 分钟累积 / 交易日历推定。"""

from app.adapters.tencent import NormalizedQuote, TencentAdapter, parse_quote_payload
from tests.harness import inject, make_app, quote


def _sample_line() -> str:
    """构造一条合法的腾讯快照响应（字段位与真实接口一致）。"""
    f = [str(i) for i in range(40)]
    f[1] = "贵州茅台"
    f[2] = "600519"
    f[3] = "1688.00"   # 现价
    f[4] = "1680.00"   # 昨收
    f[5] = "1685.00"   # 今开
    f[6] = "12345"     # 成交量（手）
    f[30] = "09:30:03"
    f[33] = "1690.00"
    f[34] = "1681.00"
    # 9–18 买五档（价/量交替，量：手）
    for i, (p, v) in enumerate([(1687.0, 12), (1686.0, 8), (1685.0, 6), (1684.0, 4), (1683.0, 2)]):
        f[9 + i * 2] = f"{p:.2f}"
        f[10 + i * 2] = str(v)
    # 19–28 卖五档
    for i, (p, v) in enumerate([(1688.0, 10), (1689.0, 9), (1690.0, 7), (1691.0, 5), (1692.0, 3)]):
        f[19 + i * 2] = f"{p:.2f}"
        f[20 + i * 2] = str(v)
    f[37] = "50000.00"
    return f'v_sh600519="{"~".join(f)}";'


class TestParse:
    def test_fields_and_five_levels(self):
        [q] = parse_quote_payload(_sample_line())
        assert q.code == "sh600519" and q.name == "贵州茅台"
        assert q.last == 1688.0 and q.prev_close == 1680.0
        assert len(q.bids) == 5 and len(q.asks) == 5
        assert q.bids[0] == (1687.0, 1200)   # 手 → 股
        assert q.asks[0] == (1688.0, 1000)
        assert q.cum_volume == 12345 * 100

    def test_star_688_volume_normalized(self):
        f = [str(i) for i in range(40)]
        f[1] = "中芯国际"; f[2] = "688981"; f[3] = "50.00"; f[4] = "49.00"
        f[5] = "49.50"; f[6] = "200000"  # 688 字段为股
        [q] = parse_quote_payload(f'v_sh688981="{"~".join(f)}";')
        assert q.cum_volume == 200000  # ÷100 归一后再 ×100 还原为股

    def test_suspended_detected(self):
        f = [str(i) for i in range(40)]
        f[3] = "0.00"; f[5] = "0.00"
        [q] = parse_quote_payload(f'v_sh600519="{"~".join(f)}";')
        assert q.last == 0.0  # 停牌


class TestMarketRuntime:
    async def test_delta_volume_diff(self):
        _, ctx = make_app()
        captured: list = []
        orig = ctx.trading.on_ticks

        async def spy(ticks):
            captured.extend(ticks)

        ctx.trading.on_ticks = spy
        await ctx.start()
        try:
            await inject(ctx, quote(cum=1_000_000, ts="09:30:00"))
            await inject(ctx, quote(cum=1_006_000, ts="09:30:03"))
            assert captured[0].delta_volume == 1_000_000  # 首个 tick：全部累计量
            assert captured[1].delta_volume == 6_000      # 差分 = 周期增量
        finally:
            ctx.trading.on_ticks = orig
            await ctx.stop()

    async def test_stale_and_status(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            assert ctx.market.stale()  # 从未更新
            await inject(ctx, quote())
            assert not ctx.market.stale()
            ctx.clock.advance(seconds=31)
            assert ctx.market.stale()  # >30s 拒市价单口径
            assert ctx.market.status()["source"] == "tencent"
        finally:
            await ctx.stop()

    async def test_degraded_state_view(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            await inject(ctx, quote())
            ctx.market.source = "anchor"
            view = ctx.session.state_view()
            assert view["state"] == "degraded"
        finally:
            await ctx.stop()

    async def test_minute_accumulation_and_persist(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            await inject(ctx, quote(ts="09:31:00"), quote(cum=1_100_000, ts="09:31:30"))
            n = ctx.market.persist_minutes("2026-09-16")
            assert n >= 1
            rows = ctx.store.minutes_for("600519", "2026-09-16")
            assert any(r["minute"] == "09:31" for r in rows)
        finally:
            await ctx.stop()

    async def test_watchlist_dynamic(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            assert "sh000300" in ctx.market.watchlist()  # 指数恒在
            await ctx.traders.create({"name": "t", "mode": "manual", "initCash": 100000})
            await inject(ctx, quote())
            await ctx.trading.submit_order(1, {
                "side": "buy", "type": "limit", "code": "600519",
                "price": 10.0, "qty": 100,
            })
            await inject(ctx, quote())
            assert "600519" in ctx.market.watchlist()  # 持仓并入关注集
        finally:
            await ctx.stop()


class TestKlineBootstrapContract:
    """C001 回归：适配器输出 → upsert_klines → klines_for 全链路契约。"""

    class _Resp:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    class _Client:
        def __init__(self, body):
            self._body = body

        async def get(self, url, params=None):
            return TestKlineBootstrapContract._Resp(self._body)

    async def _fetch(self, code: str, body) -> list:
        return await TencentAdapter(self._Client(body)).fetch_daily_klines(code)

    async def test_rows_roundtrip_into_store(self):
        """股票源 qfqday 7 元组落库后可读回（元组维度漂移即在此暴露）。"""
        body = {"data": {"sh600519": {"qfqday": [
            ["2026-09-15", "1680.00", "1685.00", "1690.00", "1675.00", "25000.00"],
            ["2026-09-16", "1685.00", "1678.00", "1691.00", "1670.00", "26235.00"],
        ]}}}
        rows = await self._fetch("sh600519", body)
        _, ctx = make_app()
        await ctx.start()
        try:
            ctx.market.sync_klines(rows)
            got = ctx.store.klines_for("sh600519", limit=10)
        finally:
            await ctx.stop()
        assert [r["date"] for r in got] == ["2026-09-15", "2026-09-16"]
        assert got[-1]["close"] == 1678.0 and got[-1]["volume"] == 26235

    async def test_index_day_key_fallback(self):
        """指数无 qfqday 键，day 键同样按 7 元组契约落库。"""
        body = {"data": {"sh000300": {"day": [
            ["2026-09-16", "4449.880", "4480.270", "4483.360", "4417.600", "142000000.000"],
        ]}}}
        rows = await self._fetch("sh000300", body)
        assert rows == [("sh000300", "2026-09-16", 4449.88, 4480.27, 4483.36, 4417.6, 142000000)]
        _, ctx = make_app()
        await ctx.start()
        try:
            ctx.market.sync_klines(rows)
            got = ctx.store.klines_for("sh000300", limit=1)
        finally:
            await ctx.stop()
        assert len(got) == 1
