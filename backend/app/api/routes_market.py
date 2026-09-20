"""行情路由（T09-2）：/market/quotes|kline|minute。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request

from app.errors import BizError

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
    # C013：minute 假参数移除（原校验放行但恒返回日K行）；分时统一走
    # /market/minute，week/month 待 §3.11 多周期落地后放行
    if period != "day":
        raise BizError(
            "BAD_REQUEST",
            "period 当前仅支持 day；分时数据请用 /market/minute", None, 400)
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
    if date is not None:
        # 显式 date：精确查询，不回退
        rows = await asyncio.to_thread(ctx.store.minutes_for, code, date)
        return {"code": code, "date": date, "data": rows}
    # C018：缺省 date = trading_date；该日无行（非交易时段/尚未出数）时
    # 回退该码最近有分时数据的交易日，响应 date 如实标识实际日期
    day = ctx.store.get_state("trading_date") or ""
    rows = await asyncio.to_thread(ctx.store.minutes_for, code, day)
    if not rows:
        fallback = await asyncio.to_thread(ctx.store.latest_minute_date, code)
        if fallback and fallback != day:
            day = fallback
            rows = await asyncio.to_thread(ctx.store.minutes_for, code, day)
    if not rows:
        # C019：回退仍空 → 最近交易日分时引导（单日全量，幂等落库后返回）
        boot_day = await ctx.market.bootstrap_latest_minutes(code)
        if boot_day:
            day = boot_day
            rows = await asyncio.to_thread(ctx.store.minutes_for, code, day)
    return {"code": code, "date": day, "data": rows}


@router.get("/market/suggest")
async def market_suggest(request: Request, q: str = Query(min_length=1, max_length=32)):
    """名称联想（T23-4）：腾讯 smartbox 代理，规范化 [{code, name, kind}]，
    服务端短缓存 + 全局限速；上游故障返回空列表。"""
    return {"data": await request.app.state.ctx.market.suggest(q)}
