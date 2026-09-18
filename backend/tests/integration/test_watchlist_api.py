"""T23 集成：watchlist 端点组 / 幂等重放 / 审计落库 / suggest 代理（§6.12）。

行情探测与联想外呼一律以注入替身离线完成，不触网。
"""

import pytest

from app.adapters.tencent import NormalizedQuote
from tests.harness import make_app
from tests.integration.test_api import client_for


def _quote(code: str, name: str, *, suspended: bool = False) -> NormalizedQuote:
    if suspended:
        return NormalizedQuote(code=code, name=name, last=0.0, prev_close=10.0,
                               open=0.0, high=0.0, low=0.0, cum_volume=0)
    return NormalizedQuote(code=code, name=name, last=10.0, prev_close=9.9,
                           open=10.0, high=10.1, low=9.9, cum_volume=1000)


class _Probe:
    def __init__(self, known: dict[str, str], suspended: set[str] | None = None):
        self.known, self.suspended = known, suspended or set()

    async def __call__(self, code: str) -> NormalizedQuote | None:
        if code in self.suspended:
            return _quote(code, "停牌标的", suspended=True)
        return _quote(code, self.known[code]) if code in self.known else None


@pytest.fixture
async def api():
    app, ctx = make_app()
    ctx.watchlist._probe = _Probe(
        {"sh600519": "贵州茅台", "sz000001": "平安银行", "sh000300": "沪深300"},
        suspended={"sz300750"},
    )
    async with client_for(app) as c:
        yield c, ctx


class TestWatchlistEndpoints:
    async def test_crud_flow_and_idempotency(self, api):
        c, ctx = api
        assert (await c.get("/api/watchlist")).json() == {"data": []}
        r1 = await c.put("/api/watchlist/600519")
        assert r1.status_code == 200
        assert r1.json()["created"] is True and r1.json()["code"] == "sh600519"
        assert r1.json()["name"] == "贵州茅台"
        ctx.clock.advance(seconds=3)
        await c.put("/api/watchlist/000001")
        rows = (await c.get("/api/watchlist")).json()["data"]
        assert [r["code"] for r in rows] == ["sz000001", "sh600519"]  # addedAt 倒序
        assert "sh600519" in ctx.market.watchlist()  # 并入关注集
        r2 = await c.put("/api/watchlist/SH600519")  # 写法变体归一：重复添加返回原态
        assert r2.json()["created"] is False
        assert r2.json()["addedAt"] == r1.json()["addedAt"]
        assert len((await c.get("/api/watchlist")).json()["data"]) == 2
        d1 = await c.delete("/api/watchlist/600519")  # 裸码删前缀行
        assert d1.json() == {"code": "sh600519", "removed": True}
        d2 = await c.delete("/api/watchlist/sh600519")  # 删除不存在视为成功
        assert d2.status_code == 200 and d2.json()["removed"] is False

    async def test_add_validation_errors(self, api):
        c, ctx = api
        bad = await c.put("/api/watchlist/abc")
        assert bad.status_code == 400
        body = bad.json()
        assert set(body) == {"code", "message", "details"}  # §5.1 错误模型
        assert body["code"] == "BAD_CODE" and body["details"]["reason"] == "BAD_FORMAT"
        unreachable = await c.put("/api/watchlist/999999")
        assert unreachable.json()["details"]["reason"] == "UNREACHABLE"
        suspended = await c.put("/api/watchlist/300750")
        assert suspended.json()["details"]["reason"] == "SUSPENDED"
        assert (await c.get("/api/watchlist")).json()["data"] == []  # 无脏数据

    async def test_batch_partial_apply_receipts(self, api):
        c, ctx = api
        r = await c.post("/api/watchlist/batch", json={
            "add": ["600519", "abc", "999999", "000001"],
            "remove": ["sh600519", "sh999999"],
        })
        assert r.status_code == 200
        receipts = r.json()["results"]
        assert [(x["code"], x["op"], x["ok"], x["error"]) for x in receipts] == [
            ("600519", "add", True, None),
            ("abc", "add", False, "BAD_FORMAT"),
            ("999999", "add", False, "UNREACHABLE"),
            ("000001", "add", True, None),
            ("sh600519", "remove", True, None),
            ("sh999999", "remove", True, None),
        ]
        rows = (await c.get("/api/watchlist")).json()["data"]
        assert [x["code"] for x in rows] == ["sz000001"]  # 部分应用

    async def test_batch_schema_validation(self, api):
        c, ctx = api
        r = await c.post("/api/watchlist/batch", json={"add": "600519"})
        assert r.status_code == 422 and r.json()["code"] == "BAD_REQUEST"


class TestWatchlistIdempotency:
    async def test_put_replay_returns_first(self, api):
        c, ctx = api
        h = {"Idempotency-Key": "wl-put-1"}
        r1 = await c.put("/api/watchlist/600519", headers=h)
        r2 = await c.put("/api/watchlist/600519", headers=h)
        assert r1.status_code == r2.status_code == 200
        assert r1.json() == r2.json() and r2.json()["created"] is True  # 重放返回首次
        assert ctx.store.watchlist_codes() == ["sh600519"]

    async def test_batch_replay_single_apply(self, api):
        c, ctx = api
        h = {"Idempotency-Key": "wl-batch-1"}
        body = {"add": ["600519", "000001"], "remove": []}
        r1 = await c.post("/api/watchlist/batch", json=body, headers=h)
        r2 = await c.post("/api/watchlist/batch", json=body, headers=h)
        assert r1.json() == r2.json()
        assert sorted(ctx.store.watchlist_codes()) == ["sh600519", "sz000001"]
        conflict = await c.post("/api/watchlist/batch",
                                json={"add": ["000300"], "remove": []}, headers=h)
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "DUPLICATE_REQUEST"


class TestWatchlistAudit:
    async def test_mutations_audited(self, api):
        c, ctx = api
        await c.put("/api/watchlist/600519")
        await c.delete("/api/watchlist/sh600519")
        await c.post("/api/watchlist/batch", json={"add": ["abc"], "remove": []})
        rows = [r for r in ctx.store.audit_feed()
                if r["path"].startswith("/api/watchlist")]
        assert [r["method"] for r in rows] == ["PUT", "DELETE", "POST"]
        assert all(r["actor"] == "observer" for r in rows)


class TestSuggestEndpoint:
    async def test_normalized_and_cached(self, api):
        c, ctx = api

        class _Suggest:
            def __init__(self):
                self.calls = 0

            async def fetch_suggest(self, q):
                self.calls += 1
                return [{"code": "sh600519", "name": "贵州茅台", "kind": "stock"}]

        fake = _Suggest()
        ctx.market._tencent = fake
        r1 = await c.get("/api/market/suggest", params={"q": "茅台"})
        assert r1.status_code == 200
        assert r1.json() == {"data": [
            {"code": "sh600519", "name": "贵州茅台", "kind": "stock"}]}
        r2 = await c.get("/api/market/suggest", params={"q": "茅台"})
        assert r2.json() == r1.json() and fake.calls == 1  # 缓存命中不重复外呼

    async def test_missing_query_param_422(self, api):
        c, ctx = api
        r = await c.get("/api/market/suggest")
        assert r.status_code == 422 and r.json()["code"] == "BAD_REQUEST"
