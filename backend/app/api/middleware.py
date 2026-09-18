"""API 横切中间件（T09-4/5/6/7，02 §5.1 / §6.3）。

挂载顺序（外 → 内）：Audit → RateLimit → Auth → Idempotency → 路由。
- Audit：全部非 GET 落 audit_log（失败请求与免鉴权模式同样生效，不含密钥）；
- RateLimit：令牌桶 QTV_RATE_LIMIT/s，429 + Retry-After；
- Auth：QTV_API_KEY 启用后校验 X-API-Key（常量时间比较），
  QTV_PUBLIC_READ 放行只读；默认免鉴权（仅 127.0.0.1 + 启动告警）；
- Idempotency：写操作 Idempotency-Key 重放返回首次结果，
  键冲突且请求体不一致 → 409 DUPLICATE_REQUEST。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.errors import BizError


def _ctx(request: Request):
    return request.app.state.ctx


def _error_body(code: str, message: str, details: Any = None) -> dict:
    return {"code": code, "message": message, "details": details}


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        body = await request.body() if request.method != "GET" else b""
        response = await call_next(request)
        if request.method != "GET":
            ctx = _ctx(request)
            digest = hashlib.sha256(body).hexdigest() if body else None
            path = request.url.path
            target = None
            parts = [p for p in path.split("/") if p]
            if parts and parts[-1].isdigit():
                target = parts[-1]
            ts = ctx.clock.now().isoformat(timespec="seconds")
            method, status = request.method, response.status_code
            await asyncio.to_thread(
                ctx.store.insert_audit, ts, method, path, target, digest, status
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """令牌桶：容量 = 每秒限额，按客户端地址独立计量。"""

    def __init__(self, app):
        super().__init__(app)
        self._buckets: dict[str, tuple[float, float]] = {}  # ip -> (tokens, last)

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        ctx = _ctx(request)
        rate = ctx.settings.qtv_rate_limit
        key = request.client.host if request.client else "anon"
        now = time.monotonic()
        tokens, last = self._buckets.get(key, (float(rate), now))
        tokens = min(float(rate), tokens + (now - last) * rate)
        if tokens < 1.0:
            return JSONResponse(
                _error_body("RATE_LIMITED", "请求超限", {"limitPerSec": rate}),
                status_code=429,
                headers={"Retry-After": "1"},
            )
        self._buckets[key] = (tokens - 1.0, now)
        return await call_next(request)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ctx = _ctx(request)
        api_key = ctx.settings.qtv_api_key
        if not api_key:  # Q4：默认免鉴权（仅本机 + 启动告警）
            return await call_next(request)
        provided = request.headers.get("X-API-Key", "")
        if hmac.compare_digest(provided.encode(), api_key.encode()):
            return await call_next(request)
        if request.method in ("GET", "HEAD") and ctx.settings.qtv_public_read:
            return await call_next(request)
        return JSONResponse(
            _error_body("UNAUTHORIZED", "缺少或错误的 X-API-Key"), status_code=401
        )


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return await call_next(request)
        idem_key = request.headers.get("Idempotency-Key")
        if not idem_key:
            return await call_next(request)
        ctx = _ctx(request)
        body = await request.body()
        digest = hashlib.sha256(body).hexdigest()
        existing = await asyncio.to_thread(ctx.store.idem_get, idem_key)
        if existing is not None:
            if existing["request_digest"] != digest:
                return JSONResponse(
                    _error_body("DUPLICATE_REQUEST",
                                "幂等键冲突且请求体不一致",
                                {"key": idem_key}),
                    status_code=409,
                )
            return Response(
                content=existing["response_body"],
                status_code=existing["status_code"] or 200,
                media_type="application/json",
            )
        response = await call_next(request)
        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        payload = b"".join(chunks)
        if 200 <= response.status_code < 500:
            ts = ctx.clock.now().isoformat(timespec="seconds")
            await asyncio.to_thread(
                ctx.store.idem_put, idem_key, request.url.path, digest,
                response.status_code, payload.decode("utf-8", errors="replace"), ts,
            )
        return Response(
            content=payload,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
