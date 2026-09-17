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
            "side": "buy", "type": "limit", "code": "600519",
            "price": 10.21, "qty": 100,
        })
        body = r.json()
        assert r.status_code == 400
        assert set(body) == {"code", "message", "details"}  # 统一错误模型
        assert body["code"] == "PRICE_BAND"
        ok = await c.post(f"/api/traders/{tid}/orders", json={
            "side": "buy", "type": "limit", "code": "600519", "price": 10.0, "qty": 100,
            "clientOrderId": "ext-1",
        })
        assert ok.status_code == 201
        oid = ok.json()["id"]
        cancel = await c.delete(f"/api/traders/{tid}/orders/{oid}")
        assert cancel.json()["status"] == "cancel"
        for path in ("orders", "trades", "positions", "equity", "metrics"):
            resp = await c.get(f"/api/traders/{tid}/{path}")
            assert resp.status_code == 200

    async def test_market_endpoints(self, api):
        c, ctx = api
        ctx.market.inject([quote()])
        q = (await c.get("/api/market/quotes")).json()
        assert q["source"] == "tencent" and q["quotes"]
        ctx.market.sync_klines([("600519", "2026-09-15", 10, 10.2, 10.3, 9.9, 123)])
        k = (await c.get("/api/market/kline", params={"code": "600519"})).json()
        assert k["data"][-1]["close"] == 10.2

    async def test_plans_and_entries_crud(self, api):
        c, ctx = api
        tid = (await c.post("/api/traders", json={
            "name": "t", "mode": "manual", "initCash": 100000})).json()["id"]
        plan = (await c.post(f"/api/traders/{tid}/plans", json={
            "name": "p", "scope": {"codes": ["600519"]},
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
                "side": "buy", "type": "market", "code": "600519", "qty": 100})
            r = await c.get(f"/api/traders/{tid}/export",
                            params={"type": "trades", "format": "csv"})
            assert r.status_code == 200
            assert r.headers["content-disposition"].startswith("attachment")
            assert r.text.startswith("﻿")  # UTF-8 BOM
            bad = await c.get(f"/api/traders/{tid}/export", params={"type": "nope"})
            assert bad.status_code == 422
