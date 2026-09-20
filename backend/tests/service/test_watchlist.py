"""T23：自选股服务——规范化/校验/幂等/批量回执/关注集并入/日K 引导/联想。"""

import asyncio

import pytest

from app.adapters.tencent import NormalizedQuote, parse_suggest_payload
from app.errors import BizError
from app.services.watchlist import code_candidates
from tests.harness import inject, make_app, quote


def _probe_quote(code: str, name: str = "探测标的", *, suspended: bool = False) -> NormalizedQuote:
    if suspended:
        return NormalizedQuote(code=code, name=name, last=0.0, prev_close=10.0,
                               open=0.0, high=0.0, low=0.0, cum_volume=0)
    return NormalizedQuote(code=code, name=name, last=10.0, prev_close=9.9,
                           open=10.0, high=10.1, low=9.9, cum_volume=1000)


class FakeProbe:
    """行情源快照探测替身：known 命中、unknown None、suspended 停牌、dead 抛错。"""

    def __init__(self, known: dict[str, str] | None = None,
                 suspended: set[str] | None = None, dead: bool = False):
        self.known = known or {}
        self.suspended = suspended or set()
        self.dead = dead
        self.calls: list[str] = []

    async def __call__(self, code: str) -> NormalizedQuote | None:
        self.calls.append(code)
        if self.dead:
            raise RuntimeError("quote source dead")
        if code in self.suspended:
            return _probe_quote(code, suspended=True)
        if code in self.known:
            return _probe_quote(code, self.known[code])
        return None


class TestCodeCandidates:
    def test_bare_rules_and_fallback(self):
        assert code_candidates("600519") == ["sh600519", "sz600519", "bj600519"]
        assert code_candidates("300750")[0] == "sz300750"
        assert code_candidates("920001")[0] == "bj920001"
        assert code_candidates("510050")[0] == "sh510050"
        assert code_candidates("000300") == ["sz000300", "sh000300", "bj000300"]

    def test_prefixed_passthrough_normalized(self):
        assert code_candidates("sh000300") == ["sh000300"]
        assert code_candidates(" SH600519 ") == ["sh600519"]

    def test_bad_format(self):
        for raw in ("", "abc", "60051", "6005191", "hk600519", "600 519"):
            assert code_candidates(raw) == []


class TestWatchlistService:
    async def test_add_list_order_and_idempotent_repeat(self):
        _, ctx = make_app()
        ctx.watchlist._probe = FakeProbe({"sh600519": "贵州茅台", "sz000001": "平安银行"})
        await ctx.start()
        try:
            r1 = await ctx.watchlist.add("600519")
            assert r1["created"] is True and r1["code"] == "sh600519"
            assert r1["name"] == "贵州茅台"
            ctx.clock.advance(seconds=5)
            await ctx.watchlist.add("000001")
            rows = ctx.watchlist.list()
            assert [r["code"] for r in rows] == ["sz000001", "sh600519"]  # addedAt 倒序
            # 重复添加（含写法变体）返回原态且不再探测
            calls_before = len(ctx.watchlist._probe.calls)
            r2 = await ctx.watchlist.add("SH600519")
            assert r2["created"] is False and r2["code"] == "sh600519"
            assert r2["addedAt"] == r1["addedAt"] and "name" not in r2
            assert len(ctx.watchlist._probe.calls) == calls_before
            assert len(ctx.watchlist.list()) == 2
        finally:
            await ctx.stop()

    async def test_remove_idempotent_and_variant(self):
        _, ctx = make_app()
        ctx.watchlist._probe = FakeProbe({"sh600519": "贵州茅台"})
        await ctx.start()
        try:
            await ctx.watchlist.add("600519")
            gone = await ctx.watchlist.remove("600519")  # 裸码删前缀行
            assert gone == {"code": "sh600519", "removed": True}
            again = await ctx.watchlist.remove("sh600519")  # 删除不存在视为成功
            assert again == {"code": "sh600519", "removed": False}
            assert ctx.watchlist.list() == []
        finally:
            await ctx.stop()

    async def test_validation_bad_format_unreachable_suspended(self):
        _, ctx = make_app()
        ctx.watchlist._probe = FakeProbe({"sh600519": "贵州茅台"},
                                         suspended={"sz300750"})
        await ctx.start()
        try:
            with pytest.raises(BizError) as e:
                await ctx.watchlist.add("abc")
            assert e.value.code == "BAD_CODE" and e.value.details["reason"] == "BAD_FORMAT"
            with pytest.raises(BizError) as e:
                await ctx.watchlist.add("999999")  # 三个候选均不可达
            assert e.value.details["reason"] == "UNREACHABLE"
            assert ctx.watchlist._probe.calls == ["sh999999", "sz999999", "bj999999"]
            with pytest.raises(BizError) as e:
                await ctx.watchlist.add("300750")
            assert e.value.details["reason"] == "SUSPENDED"  # 停牌码跳过（§6.12）
            with pytest.raises(BizError) as e:
                await ctx.watchlist.remove("abc")
            assert e.value.details["reason"] == "BAD_FORMAT"
            assert ctx.watchlist.list() == []  # 部分应用之外无脏数据
        finally:
            await ctx.stop()

    async def test_probe_source_error_503(self):
        _, ctx = make_app()
        ctx.watchlist._probe = FakeProbe(dead=True)
        await ctx.start()
        try:
            with pytest.raises(BizError) as e:
                await ctx.watchlist.add("600519")
            assert e.value.code == "QUOTE_SOURCE_ERROR" and e.value.status == 503
        finally:
            await ctx.stop()

    async def test_fallback_prefix_probe_order(self):
        """000300：sz 候选不可达 → 命中 sh 指数（兜底链按候选序）。"""
        _, ctx = make_app()
        ctx.watchlist._probe = FakeProbe({"sh000300": "沪深300"})
        await ctx.start()
        try:
            r = await ctx.watchlist.add("000300")
            assert r["code"] == "sh000300" and r["created"] is True
            assert ctx.watchlist._probe.calls == ["sz000300", "sh000300"]
        finally:
            await ctx.stop()

    async def test_batch_partial_apply_and_receipts(self):
        _, ctx = make_app()
        ctx.watchlist._probe = FakeProbe({"sh600519": "贵州茅台", "sz000001": "平安银行"})
        await ctx.start()
        try:
            out = await ctx.watchlist.batch(
                add=["600519", "abc", "999999", "000001"],
                remove=["sh600519", "sh999999"],
            )
            receipts = out["results"]
            assert [(r["code"], r["op"], r["ok"], r["error"]) for r in receipts] == [
                ("600519", "add", True, None),
                ("abc", "add", False, "BAD_FORMAT"),
                ("999999", "add", False, "UNREACHABLE"),
                ("000001", "add", True, None),
                ("sh600519", "remove", True, None),
                ("sh999999", "remove", True, None),   # 删除不存在视为成功
            ]
            assert [r["code"] for r in ctx.watchlist.list()] == ["sz000001"]  # 部分应用
        finally:
            await ctx.stop()


class TestWatchSetUnion:
    async def test_watchlist_merged_and_removed(self):
        _, ctx = make_app()
        ctx.watchlist._probe = FakeProbe({"sh600519": "贵州茅台"})
        await ctx.start()
        try:
            assert "sh600519" not in ctx.market.watchlist()
            await ctx.watchlist.add("600519")
            assert "sh600519" in ctx.market.watchlist()  # 自选并入关注集
            await ctx.watchlist.remove("sh600519")
            assert "sh600519" not in ctx.market.watchlist()
        finally:
            await ctx.stop()

    async def test_removed_code_retained_by_position_and_plan(self):
        """自选删除后仍被持仓/计划引用的码保留关注集（§3.4 / §3.10）。"""
        _, ctx = make_app()
        ctx.watchlist._probe = FakeProbe({"sh600519": "贵州茅台", "sz300750": "宁德时代"})
        await ctx.start()
        try:
            await ctx.traders.create({"name": "t", "mode": "manual", "initCash": 100000})
            await ctx.traders.create({"name": "p", "mode": "manual", "initCash": 100000})
            await ctx.plans.create_plan({"traderId": 2, "name": "p",
                                         "scope": {"codes": ["300750"]}})
            # 裸码持仓（历史行形态）：C015 起下单链路拒收裸码（UNSUPPORTED_BOARD），
            # 存量行改为直接落库模拟，本用例关注集语义不变
            ctx.store.upsert_position(1, "600519", 100, 10.0, 0)
            await ctx.watchlist.add("600519")
            await ctx.watchlist.add("300750")
            watch = ctx.market.watchlist()
            assert {"sh600519", "sz300750", "600519"} <= set(watch)
            await ctx.watchlist.remove("sh600519")
            await ctx.watchlist.remove("sz300750")
            watch = ctx.market.watchlist()
            assert "sh600519" not in watch  # 自选行已删
            assert "sz300750" in watch       # 计划引用保留（C011 归一码）
            assert "600519" in watch         # 裸码持仓引用保留
        finally:
            await ctx.stop()

    async def test_watch_override_semantics_kept(self):
        _, ctx = make_app()
        ctx.watchlist._probe = FakeProbe({"sh600519": "贵州茅台"})
        await ctx.start()
        try:
            await ctx.watchlist.add("600519")
            ctx.market.set_watch_override(["sz000001"])
            assert ctx.market.watchlist() == ["sh000300", "sz000001"]  # 注入覆盖动态集
            ctx.market.set_watch_override(None)
            assert "sh600519" in ctx.market.watchlist()  # 恢复动态计算
        finally:
            await ctx.stop()


class _KlineSrc:
    def __init__(self, rows: list[tuple] | None = None, dead: bool = False):
        self.rows = rows
        self.dead = dead
        self.called: list[str] = []

    async def fetch_daily_klines(self, code: str, limit: int = 320):
        self.called.append(code)
        if self.dead:
            raise RuntimeError("kline source dead")
        await asyncio.sleep(0.01)  # 让排队可观测
        return self.rows or [(code, "2026-09-17", 10.0, 10.5, 10.6, 9.9, 12345)]


class TestKlineBootstrap:
    async def test_add_triggers_single_code_bootstrap(self):
        _, ctx = make_app()
        ctx.watchlist._probe = FakeProbe({"sh600519": "贵州茅台"})
        await ctx.start()
        try:
            src = _KlineSrc()
            ctx.market._tencent = src
            await ctx.watchlist.add("600519")
            await asyncio.gather(*list(ctx.market._kline_boot_tasks))
            assert src.called == ["sh600519"]
            got = ctx.store.klines_for("sh600519", limit=1)
            assert len(got) == 1 and got[0]["close"] == 10.5
            # 重复添加不再触发引导
            await ctx.watchlist.add("600519")
            await asyncio.sleep(0)
            assert src.called == ["sh600519"]
        finally:
            await ctx.stop()

    async def test_bootstrap_falls_back_to_eastmoney(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            east = _KlineSrc()
            ctx.market._tencent = _KlineSrc(dead=True)
            ctx.market._eastmoney = east
            task = ctx.market.trigger_kline_bootstrap("sh600519")
            await task
            assert east.called == ["sh600519"]  # ifzq 失败落东财（C008 链同款）
            assert ctx.store.klines_for("sh600519", limit=1)
        finally:
            await ctx.stop()

    async def test_bootstrap_failure_does_not_propagate(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            ctx.market._tencent = _KlineSrc(dead=True)
            ctx.market._eastmoney = _KlineSrc(dead=True)
            task = ctx.market.trigger_kline_bootstrap("sh600519")
            await task  # 引导失败不抛出、不阻塞
            assert task.exception() is None
            assert ctx.store.klines_for("sh600519", limit=1) == []
        finally:
            await ctx.stop()

    async def test_batch_bootstrap_serial_queue(self):
        """批量添加的引导串行排队：按触发次序依次执行、互不并发。"""
        _, ctx = make_app()
        ctx.watchlist._probe = FakeProbe({"sh600519": "贵州茅台", "sz000001": "平安银行"})
        await ctx.start()
        try:
            east = _KlineSrc()
            ctx.market._tencent = _KlineSrc(dead=True)
            ctx.market._eastmoney = east
            await ctx.watchlist.batch(add=["600519", "000001"], remove=[])
            await asyncio.gather(*list(ctx.market._kline_boot_tasks))
            assert east.called == ["sh600519", "sz000001"]  # 串行按序
            assert ctx.store.klines_for("sz000001", limit=1)
        finally:
            await ctx.stop()

    async def test_offline_trigger_noop(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            assert ctx.market._tencent is None
            assert ctx.market.trigger_kline_bootstrap("sh600519") is None
        finally:
            await ctx.stop()


class TestSuggest:
    def test_parse_real_payload_multi(self):
        text = ('v_hint="sz~000001~平安银行~payh~GP-A^sh~601318~中国平安~zgpa~GP-A'
                '^sh~512930~AI人工智能ETF平安~airgznetfpa~ETF";')
        rows = parse_suggest_payload(text)
        assert rows == [
            {"code": "sz000001", "name": "平安银行", "kind": "stock"},
            {"code": "sh601318", "name": "中国平安", "kind": "stock"},
            {"code": "sh512930", "name": "AI人工智能ETF平安", "kind": "etf"},
        ]

    def test_parse_index_and_none(self):
        assert parse_suggest_payload('v_hint="sh~000300~沪深300~hs300~ZS";') == [
            {"code": "sh000300", "name": "沪深300", "kind": "index"},
        ]
        assert parse_suggest_payload('v_hint="N";') == []
        assert parse_suggest_payload('v_hint="";') == []
        assert parse_suggest_payload("garbage") == []

    def test_parse_unicode_escaped_name(self):
        # C009：smartbox hint 名称字段为字面 \uXXXX 转义文本，须还原为 Unicode
        text = 'v_hint="sh~601318~\\u4e2d\\u56fd\\u5e73\\u5b89~zgpa~GP-A";'
        assert parse_suggest_payload(text) == [
            {"code": "sh601318", "name": "中国平安", "kind": "stock"},
        ]
        # 混合载荷：转义与直编码中文并存
        mixed = ('v_hint="sz~000001~平安银行~payh~GP-A'
                 '^sh~600519~\\u8d35\\u5dde\\u8305\\u53f0~gzmt~GP-A";')
        rows = parse_suggest_payload(mixed)
        assert rows[0]["name"] == "平安银行"
        assert rows[1]["name"] == "贵州茅台"

    async def test_suggest_cache_and_upstream_failure(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            class _Suggest:
                def __init__(self):
                    self.calls = 0

                async def fetch_suggest(self, q):
                    self.calls += 1
                    return [{"code": "sh600519", "name": "贵州茅台", "kind": "stock"}]

            fake = _Suggest()
            ctx.market._tencent = fake
            first = await ctx.market.suggest("茅台")
            second = await ctx.market.suggest("茅台")
            assert first == second and fake.calls == 1  # 缓存命中不重复外呼
            await ctx.market.suggest("平安")
            assert fake.calls == 2

            class _Dead:
                async def fetch_suggest(self, q):
                    raise RuntimeError("upstream dead")

            ctx.market._tencent = _Dead()
            assert await ctx.market.suggest("招商银行") == []  # 上游故障返回空列表
        finally:
            await ctx.stop()

    async def test_suggest_offline_empty(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            assert await ctx.market.suggest("茅台") == []  # offline 无外呼
        finally:
            await ctx.stop()
