"""T06：腾讯解析 / ΔV 差分 / 降级状态 / 分钟累积 / 交易日历推定。"""

import asyncio
import json

from app.adapters.sina import parse_sina_payload
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

    def test_compact_timestamp_normalized(self):
        """C010：真实字段 30 为 YYYYMMDDHHMMSS（实测 20260918150018），
        归一为 HH:MM:SS；带冒号旧口径原样通过。"""
        f = [str(i) for i in range(40)]
        f[1] = "贵州茅台"; f[2] = "600519"; f[3] = "1688.00"; f[4] = "1680.00"
        f[5] = "1685.00"; f[6] = "12345"
        f[30] = "20260918093105"
        [q] = parse_quote_payload(f'v_sh600519="{"~".join(f)}";')
        assert q.ts == "09:31:05"
        f[30] = "09:30:03"
        [q] = parse_quote_payload(f'v_sh600519="{"~".join(f)}";')
        assert q.ts == "09:30:03"


def _sina_line(code: str = "sh600519", *, zero_book: bool = False) -> str:
    """构造一条合法的新浪快照响应（字段位与真实接口一致，量纲：股）。"""
    f = ["0"] * 33
    f[0] = "贵州茅台"
    f[1] = "1262.990"   # 今开
    f[2] = "1266.980"   # 昨收
    f[3] = "1258.880"   # 现价
    f[4] = "1265.880"   # 最高
    f[5] = "1258.200"   # 最低
    f[8] = "957073"     # 成交量（股）
    f[9] = "1206982486.000"  # 成交额（元）
    if not zero_book:
        # 10–19 买五档（量/价交替，量：股）
        for i, (p, v) in enumerate(
            [(1258.87, 100), (1258.86, 100), (1258.85, 400), (1258.82, 100), (1258.81, 200)]
        ):
            f[10 + i * 2] = str(v)
            f[11 + i * 2] = f"{p:.2f}"
        # 20–29 卖五档
        for i, (p, v) in enumerate(
            [(1259.00, 200), (1259.17, 1200), (1259.18, 200), (1259.23, 100), (1259.38, 100)]
        ):
            f[20 + i * 2] = str(v)
            f[21 + i * 2] = f"{p:.2f}"
    f[30] = "2026-09-18"
    f[31] = "10:59:57"
    return f'var hq_str_{code}="{",".join(f)}";'


class TestSinaParse:
    """C008：新浪快照解析（字段位 / 五档量纲 / 成交额归一）。"""

    def test_fields_and_five_levels(self):
        [q] = parse_sina_payload(_sina_line())
        assert q.code == "sh600519" and q.name == "贵州茅台"
        assert q.last == 1258.88 and q.prev_close == 1266.98
        assert q.open == 1262.99 and q.high == 1265.88 and q.low == 1258.20
        assert len(q.bids) == 5 and len(q.asks) == 5
        assert q.bids[0] == (1258.87, 100)   # 量纲已是股，无手换算
        assert q.asks[0] == (1259.00, 200)
        assert q.cum_volume == 957073
        assert q.amount_wan == 120698.25     # 元 → 万
        assert q.ts == "10:59:57"

    def test_index_zero_book_skipped(self):
        [q] = parse_sina_payload(_sina_line("sh000300", zero_book=True))
        assert q.code == "sh000300"
        assert q.bids == [] and q.asks == []  # 指数无盘口：价量非正自然跳过

    def test_suspended_detected(self):
        line = _sina_line()
        line = line.replace("1262.990", "0.000", 1).replace("1258.880", "0.000", 1)
        [q] = parse_sina_payload(line)
        assert q.last == 0.0  # 现价与今开均 ≤0 判停牌


class _FakeAdapter:
    """离线替身：可控返回快照或抛错。"""

    def __init__(self, quotes: list[NormalizedQuote] | None = None, dead: bool = False):
        self._quotes = quotes or []
        self._dead = dead

    async def fetch_quotes(self, codes):
        if self._dead:
            raise RuntimeError("source dead")
        return self._quotes


class TestFallbackChain:
    """C008：腾讯(https/http) → 新浪 → 东财 → 锚点 降级次序与档位语义。"""

    async def _drive(self, ctx, times: int = 1):
        for _ in range(times):
            await ctx.market.poll_once()
        for _ in range(200):  # 等串行基座跑完（同 harness.inject 口径）
            if ctx.serial._queue.empty():  # noqa: SLF001
                await asyncio.sleep(0)
                break
            await asyncio.sleep(0.005)

    async def test_tencent_primary_unchanged(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            ctx.market._tencent = _FakeAdapter([quote()])
            ctx.market._sina = _FakeAdapter(dead=True)
            await self._drive(ctx)
            assert ctx.market.status()["source"] == "tencent"
            assert ctx.market.live
        finally:
            await ctx.stop()

    async def test_sina_full_grade_with_delta_volume(self):
        """新浪档非 degraded：ΔV 差分正常，source=sina。"""
        _, ctx = make_app()
        captured: list = []
        orig = ctx.trading.on_ticks

        async def spy(ticks):
            captured.extend(ticks)

        ctx.trading.on_ticks = spy
        await ctx.start()
        try:
            ctx.market._tencent = _FakeAdapter(dead=True)
            ctx.market._sina = _FakeAdapter([quote(cum=2_000_000)])
            ctx.market._eastmoney = _FakeAdapter(dead=True)
            await self._drive(ctx, 3)          # 3 败熔断 → 落到新浪
            assert ctx.market.status()["source"] == "sina"
            assert ctx.market.live
            ctx.market._sina = _FakeAdapter([quote(cum=2_006_000)])
            await self._drive(ctx)             # 熔断态直接走备源链
            assert captured[-1].delta_volume == 6_000  # 完整档：差分增量
        finally:
            ctx.trading.on_ticks = orig
            await ctx.stop()

    async def test_eastmoney_degraded_zero_delta(self):
        """东财档 degraded：无增量量（撮合回落 fallback 模型）。"""
        _, ctx = make_app()
        captured: list = []
        orig = ctx.trading.on_ticks

        async def spy(ticks):
            captured.extend(ticks)

        ctx.trading.on_ticks = spy
        await ctx.start()
        try:
            ctx.market._tencent = _FakeAdapter(dead=True)
            ctx.market._sina = _FakeAdapter(dead=True)
            ctx.market._eastmoney = _FakeAdapter([quote(cum=3_000_000)])
            await self._drive(ctx, 3)
            assert ctx.market.status()["source"] == "eastmoney"
            assert ctx.market.live
            assert captured[-1].delta_volume == 0
        finally:
            ctx.trading.on_ticks = orig
            await ctx.stop()

    async def test_all_dead_anchor_circuit(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            await inject(ctx, quote())         # 种子锚点
            ctx.market._tencent = _FakeAdapter(dead=True)
            ctx.market._sina = _FakeAdapter(dead=True)
            ctx.market._eastmoney = _FakeAdapter(dead=True)
            await self._drive(ctx, 3)
            assert ctx.market.status()["source"] == "anchor"
            assert not ctx.market.live
            assert ctx.market._circuit_until is not None  # 60s 闭锁
        finally:
            await ctx.stop()


class TestKlineBootstrapFallback:
    """C008：日K 引导 腾讯 ifzq → 东财 push2his 兜底。"""

    class _DeadTencent:
        async def fetch_daily_klines(self, code, limit=320):
            raise RuntimeError("kline source dead")

    class _EastKline:
        def __init__(self):
            self.called: list[str] = []

        async def fetch_daily_klines(self, code, limit=320):
            self.called.append(code)
            return [(code, "2026-09-17", 4460.0, 4486.0, 4490.0, 4450.0, 142000)]

    async def test_falls_back_to_eastmoney(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            east = self._EastKline()
            ctx.market._tencent = self._DeadTencent()
            ctx.market._eastmoney = east
            await ctx.market._bootstrap_klines()
            assert east.called == ["sh000300"]  # 关注集（离线）= 指数
            got = ctx.store.klines_for("sh000300", limit=1)
            assert len(got) == 1 and got[0]["close"] == 4486.0
        finally:
            await ctx.stop()


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
            rows = ctx.store.minutes_for("sh600519", "2026-09-16")
            assert any(r["minute"] == "09:31" for r in rows)
        finally:
            await ctx.stop()

    async def test_minute_buckets_split_and_unparseable_skipped(self):
        """C010：跨分钟分桶正确；不可解析 ts（降级档空串）不落桶。"""
        _, ctx = make_app()
        await ctx.start()
        try:
            await inject(ctx, quote(ts="09:30:05"))
            await inject(ctx, quote(cum=1_100_000, ts="09:31:05"))
            await inject(ctx, quote(cum=1_200_000, ts=""))
            bars = ctx.market._minute_bars
            assert sorted(m for _, m in bars) == ["09:30", "09:31"]
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
                "side": "buy", "type": "limit", "code": "sh600519",
                "price": 10.0, "qty": 100,
            })
            await inject(ctx, quote())
            assert "sh600519" in ctx.market.watchlist()  # 持仓并入关注集
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
