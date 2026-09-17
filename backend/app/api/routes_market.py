"""行情路由（T09-2）：/market/quotes|kline|minute。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request

router = APIRouter()


@router.get("/market/quotes")
async def market_quotes(request: Request, codes: str | None = None):
    ctx = request.app.state.ctx
    payload = await asyncio.to_thread(ctx.market.quotes_payload)
    if codes:
        wanted = {c.strip() for c in codes.split(",") if c.strip()}
        payload["quotes"] = [q for q in payload["quotes"] if q["code"] in wanted]
    return payload


@router.get("/market/kline")
async def market_kline(
    request: Request,
    code: str = Query(min_length=3),
    period: str = "day",
    limit: int = Query(250, ge=1, le=5000),
):
    if period not in ("day", "minute"):
        return {"code": "BAD_REQUEST", "message": "period 必须为 day | minute",
                "details": None}
    ctx = request.app.state.ctx
    rows = await asyncio.to_thread(ctx.store.klines_for, code, limit)
    return {"code": code, "period": period, "data": rows}


@router.get("/market/minute")
async def market_minute(
    request: Request,
    code: str = Query(min_length=3),
    date: str | None = None,
):
    ctx = request.app.state.ctx
    day = date or ctx.store.get_state("trading_date") or ""
    rows = await asyncio.to_thread(ctx.store.minutes_for, code, day)
    return {"code": code, "date": day, "data": rows}
