"""元路由（T09-2）：session / templates / events / audit。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request

from app.domain.strategies import templates_payload
from app.store.store import page_result

router = APIRouter()


@router.get("/session")
async def session_state(request: Request):
    return request.app.state.ctx.session.state_view()


@router.get("/templates")
async def list_templates():
    return {"data": templates_payload()}


@router.get("/traders/events")
async def trader_events(request: Request, cursor: int = 0, limit: int = Query(50, le=500)):
    ctx = request.app.state.ctx
    rows = await asyncio.to_thread(ctx.store.events_feed, cursor, limit)
    return page_result(rows, limit)


@router.get("/audit")
async def audit_feed(request: Request, cursor: int = 0, limit: int = Query(50, le=500)):
    ctx = request.app.state.ctx
    rows = await asyncio.to_thread(ctx.store.audit_feed, cursor, limit)
    return page_result(rows, limit)
