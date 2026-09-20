"""T09 集成：端点覆盖 / 鉴权矩阵 / 幂等重放 / 限速 / 审计 / 导出（§6.12）。

鉴权矩阵所用密钥随机生成：源码与测试不落任何可用凭据字面量。
"""

import httpx
import pytest
import secrets

from tests.harness import make_app, quote


def _gen_key() -> str:
    return secrets.token_urlsafe(24)


class Client:
    def __init__(self, app):
        self.app = app

    async def __aenter__(self):
        await self.app.state.ctx.start()
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://t"
        )
        return self._client

    async def __aexit__(self, *exc):
        await self._client.aclose()
        await self.app.state.ctx.stop()
        return False


def client_for(app):
    return Client(app)


@pytest.fixture
async def api():
    app, ctx = make_app()
    async with client_for(app) as c:
        yield c, ctx


class TestEndpoints:
    async def test_health_session_templates(self, api):
        c, ctx = api
        assert (await c.get("/health")).json()["ok"] is True
        sess = (await c.get("/api/session")).json()
        assert sess["state"] == "trading" and sess["tradingDate"]
        templates = (await c.get("/api/templates")).json()["data"]
        assert len(templates) == 8

    async def test_trader_crud_flow(self, api):
        c, ctx = api
        r = await c.post("/api/traders", json={
            "name": "手动", "mode": "manual", "initCash": 200000,
        })
        assert r.status_code == 201
        tid = r.json()["id"]
        detail = (await c.get(f"/api/traders/{tid}")).json()
        assert detail["equity"] == 200000
        patch = await c.patch(f"/api/traders/{tid}", json={"status": "paused"})
        assert patch.json()["status"] == "paused"
        cap = await c.post(f"/api/traders/{tid}/capital", json={"amount": 1000})
        assert cap.json()["initCash"] == 201000
        dele = await c.delete(f"/api/traders/{tid}")
        assert dele.json()["deleted"] is True
        assert (await c.get(f"/api/traders/{tid}")).status_code == 404

    async def test_order_flow_and_error_shape(self, api):
        c, ctx = api
        tid = (await c.post("/api/traders", json={
            "name": "t", "mode": "manual", "initCash": 200000})).json()["id"]
        ctx.market.inject([quote()])
        r = await c.post(f"/api/traders/{tid}/orders", json={
            "side": "buy", "type": "limit", "code": "sh600519",
            "price": 10.21, "qty": 100,
        })
        body = r.json()
        assert r.status_code == 400
        assert set(body) == {"code", "message", "details"}  # 统一错误模型
        assert body["code"] == "PRICE_BAND"
        ok = await c.post(f"/api/traders/{tid}/orders", json={
            "side": "buy", "type": "limit", "code": "sh600519", "price": 10.0, "qty": 100,
            "clientOrderId": "ext-1",
        })
        assert ok.status_code == 201
        oid = ok.json()["id"]
        cancel = await c.delete(f"/api/traders/{tid}/orders/{oid}")
        assert cancel.json()["status"] == "cancel"
        for path in ("orders", "trades", "positions", "equity", "metrics"):
            resp = await c.get(f"/api/traders/{tid}/{path}")
            assert resp.status_code == 200

    async def test_order_market_type_nullable_contract(self, api):
        """C016：限价单 marketType=null（前端口径）不再 422；市价单缺省回落 best5_cancel。"""
        c, ctx = api
        tid = (await c.post("/api/traders", json={
            "name": "t", "mode": "manual", "initCash": 200000})).json()["id"]
        ctx.market.inject([quote()])
        limit = await c.post(f"/api/traders/{tid}/orders", json={
            "side": "buy", "type": "limit", "code": "sh600519",
            "price": 10.0, "qty": 100, "marketType": None,
        })
        assert limit.status_code == 201
        assert limit.json()["market_type"] is None  # 限价单不落市价类型
        mkt = await c.post(f"/api/traders/{tid}/orders", json={
            "side": "buy", "type": "market", "code": "sh600519", "qty": 100,
        })
        assert mkt.status_code == 201
        assert mkt.json()["market_type"] == "best5_cancel"  # 缺省归一默认类型

    async def test_market_endpoints(self, api):
        c, ctx = api
        ctx.market.inject([quote()])
        q = (await c.get("/api/market/quotes")).json()
        assert q["source"] == "tencent" and q["quotes"]
        ctx.market.sync_klines([("sh600519", "2026-09-15", 10, 10.2, 10.3, 9.9, 123)])
        k = (await c.get("/api/market/kline", params={"code": "sh600519"})).json()
        # T25：冷热合成——完结冷 bar 在前，当日未完结合成热 bar（close = 快照 last）在后
        assert k["data"][-2]["close"] == 10.2
        assert k["data"][-1]["date"] == "2026-09-16" and k["data"][-1]["close"] == 10.0
        # C013：minute 假参数移除——校验拒放并指向 /market/minute（统一错误模型 400）
        bad = await c.get("/api/market/kline",
                          params={"code": "sh600519", "period": "minute"})
        assert bad.status_code == 400
        assert bad.json()["code"] == "BAD_REQUEST"
        bad3 = await c.get("/api/market/kline",
                           params={"code": "sh600519", "period": "year"})
        assert bad3.status_code == 400 and bad3.json()["code"] == "BAD_REQUEST"

    async def test_kline_endpoint_serves_cold_hot_view(self, api):
        """T25：/market/kline 读冷热合成序列——当日未完结合成热 bar。"""
        c, ctx = api
        ctx.market.sync_klines([("sh600519", "2026-09-15", 10, 10.2, 10.3, 9.9, 123)])
        ctx.market.inject([quote(last=10.6, prev=10.2, cum=300_000)])
        k = (await c.get("/api/market/kline", params={"code": "sh600519"})).json()
        assert [r["date"] for r in k["data"]][-1] == "2026-09-16"
        assert k["data"][-1]["close"] == 10.6

    async def test_kline_period_week_aggregation(self, api):
        """T26：period=week 离线注入聚合正确性（limit=聚合后根数）。"""
        c, ctx = api
        ctx.market.sync_klines([
            ("sh600519", "2026-09-14", 10, 11, 12, 9, 100),   # 周一
            ("sh600519", "2026-09-15", 11, 12, 13, 10, 200),
            ("sh600519", "2026-09-18", 12, 13, 14, 12, 300),  # 周五
            ("sh600519", "2026-09-21", 13, 14, 15, 13, 400),  # 次周一
        ])
        k = (await c.get("/api/market/kline",
                         params={"code": "sh600519", "period": "week"})).json()
        dates = [r["date"] for r in k["data"]]
        assert dates == ["2026-09-18", "2026-09-21"]
        assert k["data"][0]["volume"] == 600 and k["data"][0]["open"] == 10
        assert k["data"][0]["close"] == 13
        # limit = 聚合后根数：1 根 → 仅最近一周
        k1 = (await c.get("/api/market/kline",
                          params={"code": "sh600519", "period": "week", "limit": 1})).json()
        assert [r["date"] for r in k1["data"]] == ["2026-09-21"]

    async def test_minute_default_date_fallback(self, api):
        """C018：缺省 date 无行回退最近有数交易日；显式 date 不回退。"""
        c, ctx = api
        ctx.market.inject([quote(ts="15:35:00")])  # 推进 trading_date 至 09-16（槽外 ts 不落桶）
        ctx.store.upsert_minutes([("sh600519", "2026-09-15", "09:31", 10.0, 100)])
        r = (await c.get("/api/market/minute", params={"code": "sh600519"})).json()
        assert r["date"] == "2026-09-15" and len(r["data"]) == 1  # 回退到最近有数日
        r2 = (await c.get("/api/market/minute",
                          params={"code": "sh600519", "date": "2026-09-14"})).json()
        assert r2["date"] == "2026-09-14" and r2["data"] == []    # 显式精确查询

    async def test_minute_latest_bootstrap_on_empty(self, api):
        """C019：缺省回退仍空 → 在线触发最近交易日分时引导；显式 date 不触发。"""
        c, ctx = api

        class _FakeMinuteSource:
            def __init__(self):
                self.calls: list[str] = []

            async def fetch_latest_minutes(self, code):
                self.calls.append(code)
                return ("2026-09-18", [
                    (code, "2026-09-18", "09:30", 10.0, 1000),
                    (code, "2026-09-18", "09:31", 10.1, 2500),
                ])

        src = _FakeMinuteSource()
        ctx.market.inject([quote(ts="15:35:00")])   # trading_date=09-16，不落桶
        ctx.market._tencent = src
        r = (await c.get("/api/market/minute", params={"code": "sh600519"})).json()
        assert r["date"] == "2026-09-18" and len(r["data"]) == 2  # 引导后返回最近交易日
        assert src.calls == ["sh600519"]
        assert len(ctx.store.minutes_for("sh600519", "2026-09-18")) == 2  # 已落库
        # 显式 date 不触发引导
        r2 = (await c.get("/api/market/minute",
                          params={"code": "sz000001", "date": "2026-09-14"})).json()
        assert r2["data"] == [] and src.calls == ["sh600519"]
        # 无数据空结果 → 冷却，不连续打上游
        class _EmptySource(_FakeMinuteSource):
            async def fetch_latest_minutes(self, code):
                self.calls.append(code)
                return None
        empty = _EmptySource()
        ctx.market._tencent = empty
        for _ in range(2):
            r3 = (await c.get("/api/market/minute", params={"code": "sz000001"})).json()
            assert r3["data"] == []
        assert empty.calls == ["sz000001"]  # 第二次命中 10 分钟冷却

    async def test_plans_and_entries_crud(self, api):
        c, ctx = api
        tid = (await c.post("/api/traders", json={
            "name": "t", "mode": "manual", "initCash": 100000})).json()["id"]
        plan = (await c.post(f"/api/traders/{tid}/plans", json={
            "name": "p", "scope": {"codes": ["sh600519"]},
            "risk": {"stopLossPct": 0.05},
        })).json()
        pid = plan["id"]
        entry = (await c.post(f"/api/plans/{pid}/entries", json={
            "triggerType": "price_cross", "triggerParams": {"side": "buy", "price": 9.5},
            "action": {"side": "buy", "qty": 100, "type": "market"}, "tif": "day",
        }))
        assert entry.status_code == 201
        bad = await c.post(f"/api/plans/{pid}/entries", json={
            "triggerType": "nope", "triggerParams": {},
            "action": {"side": "buy", "qty": 100},
        })
        assert bad.status_code == 422 and bad.json()["code"] == "BAD_REQUEST"
        got = (await c.get(f"/api/traders/{tid}/plans")).json()["data"]
        assert got[0]["name"] == "p"
        assert (await c.delete(f"/api/plans/entries/{entry.json()['id']}")).json()["deleted"]

    async def test_events_and_audit_feeds(self, api):
        c, ctx = api
        await c.post("/api/traders", json={"name": "t", "mode": "manual", "initCash": 1000})
        events = (await c.get("/api/traders/events")).json()
        assert events["data"]
        audit = (await c.get("/api/audit")).json()
        assert audit["data"] and audit["data"][-1]["method"] == "POST"


class TestAuthMatrix:
    async def test_key_required_when_configured(self):
        key = _gen_key()
        app, ctx = make_app(qtv_api_key=key)
        async with client_for(app) as c:
            assert (await c.get("/api/session")).status_code == 401
            ok = await c.get("/api/session", headers={"X-API-Key": key})
            assert ok.status_code == 200

    async def test_public_read_allows_get_only(self):
        key = _gen_key()
        app, ctx = make_app(qtv_api_key=key, qtv_public_read=True)
        async with client_for(app) as c:
            assert (await c.get("/api/session")).status_code == 200  # 只读放行
            r = await c.post("/api/traders", json={"name": "t", "mode": "manual"})
            assert r.status_code == 401
            r = await c.post("/api/traders", json={"name": "t", "mode": "manual"},
                             headers={"X-API-Key": key})
            assert r.status_code == 201


class TestIdempotency:
    async def test_replay_returns_first_and_conflict(self):
        app, ctx = make_app()
        async with client_for(app) as c:
            body = {"name": "t", "mode": "manual", "initCash": 1000}
            h = {"Idempotency-Key": "op-1"}
            r1 = await c.post("/api/traders", json=body, headers=h)
            r2 = await c.post("/api/traders", json=body, headers=h)
            assert r1.status_code == r2.status_code == 201
            assert r1.json()["id"] == r2.json()["id"]  # 返回首次结果
            r3 = await c.post("/api/traders", json=dict(body, name="other"), headers=h)
            assert r3.status_code == 409 and r3.json()["code"] == "DUPLICATE_REQUEST"


class TestRateLimit:
    async def test_token_bucket_429(self):
        app, ctx = make_app(qtv_rate_limit=5)
        async with client_for(app) as c:
            codes = [(await c.get("/api/session")).status_code for _ in range(12)]
            assert 429 in codes
            assert codes.index(429) >= 4  # 容量 5：第 6 个请求起限流
            assert (await c.get("/health")).status_code == 200  # 健康检查豁免


class TestAudit:
    async def test_writes_audited_with_status(self):
        app, ctx = make_app()
        async with client_for(app) as c:
            await c.post("/api/traders", json={"name": "ok", "mode": "manual"})
            await c.post("/api/traders", json={"name": "", "mode": "manual"})  # 失败请求
            rows = ctx.store.audit_feed()
            posts = [r for r in rows if r["method"] == "POST"]
            assert len(posts) == 2  # 失败请求同样记录
            assert any(r["status_code"] == 422 for r in posts)


class TestExportEndpoint:
    async def test_csv_download_headers(self):
        app, ctx = make_app()
        async with client_for(app) as c:
            tid = (await c.post("/api/traders", json={
                "name": "t", "mode": "manual", "initCash": 100000})).json()["id"]
            ctx.market.inject([quote()])
            await c.post(f"/api/traders/{tid}/orders", json={
                "side": "buy", "type": "market", "code": "sh600519", "qty": 100})
            r = await c.get(f"/api/traders/{tid}/export",
                            params={"type": "trades", "format": "csv"})
            assert r.status_code == 200
            assert r.headers["content-disposition"].startswith("attachment")
            assert r.text.startswith("﻿")  # UTF-8 BOM
            bad = await c.get(f"/api/traders/{tid}/export", params={"type": "nope"})
            assert bad.status_code == 422
