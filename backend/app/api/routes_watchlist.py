"""自选股路由（T23-2，02 §5.2 v6）：/watchlist 列表 / 单码增删（幂等）/ 批量回执。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from app.models.schemas import WatchlistBatchIn

router = APIRouter()


@router.get("/watchlist")
async def watchlist_list(request: Request):
    ctx = request.app.state.ctx
    return {"data": await asyncio.to_thread(ctx.watchlist.list)}


@router.put("/watchlist/{code}")
async def watchlist_add(request: Request, code: str):
    return await request.app.state.ctx.watchlist.add(code)


@router.delete("/watchlist/{code}")
async def watchlist_remove(request: Request, code: str):
    return await request.app.state.ctx.watchlist.remove(code)


@router.post("/watchlist/batch")
async def watchlist_batch(request: Request, body: WatchlistBatchIn):
    return await request.app.state.ctx.watchlist.batch(body.add, body.remove)
