"""应用装配（T01-3/T01-6，02 §4.5 / §4.6）。

启动序（lifespan，失败即中止）：迁移 → 观察员初始化 → 串行基座 →
行情启动（offline 跳过）。CORS 白名单 = QTV_CORS；默认仅监听 127.0.0.1。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.middleware import (
    AuditMiddleware, AuthMiddleware, IdempotencyMiddleware, RateLimitMiddleware,
)
from app.api.routes_market import router as market_router
from app.api.routes_meta import router as meta_router
from app.api.routes_traders import router as traders_router
from app.api.ws import WSHub, ws_endpoint
from app.context import AppContext
from app.errors import BizError

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("qtv.main")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await app.state.ctx.start()
    yield
    await app.state.ctx.stop()


def create_app(settings=None, clock=None, offline: bool = False) -> FastAPI:
    app = FastAPI(title="QTVictory", version="0.1.0", lifespan=_lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    ctx = AppContext(settings=settings, clock=clock, offline=offline)
    app.state.ctx = ctx
    app.state.ws_hub = WSHub(ctx)

    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(AuditMiddleware)  # 最外层：失败请求同样审计
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ctx.settings.qtv_cors],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(BizError)
    async def biz_error_handler(request: Request, exc: BizError):
        return JSONResponse(
            {"code": exc.code, "message": exc.message, "details": exc.details},
            status_code=exc.status,
        )

    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            {"code": "BAD_REQUEST", "message": "请求参数校验失败",
             "details": exc.errors()[:5]},
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            {"code": f"HTTP_{exc.status_code}", "message": str(exc.detail),
             "details": None},
            status_code=exc.status_code,
        )

    @app.get("/health")
    async def health():
        return {"ok": True, "state": ctx.session.state_view()["state"]}

    app.include_router(meta_router, prefix="/api")
    app.include_router(market_router, prefix="/api")
    app.include_router(traders_router, prefix="/api")
    app.websocket("/ws")(ws_endpoint)
    return app


app = create_app()


def run() -> None:
    """uvicorn 入口：python -m app.main。"""
    import uvicorn

    from app.config import get_settings

    s = get_settings()
    uvicorn.run("app.main:app", host="127.0.0.1", port=s.qtv_port, log_level="info")


if __name__ == "__main__":
    run()
