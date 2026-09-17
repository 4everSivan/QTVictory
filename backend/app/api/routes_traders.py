"""交易员路由（T09-2）：traders 全家 / orders / plans / entries / export。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    CapitalIn, EntryCreate, OrderIn, PlanCreate, PlanPatch, TraderCreate, TraderPatch,
)
from app.services.trader import trader_public
from app.store.store import page_result

router = APIRouter()


@router.get("/traders")
async def list_traders(
    request: Request,
    status: str | None = None,
    include: str | None = None,
    sort: str = "ret",
):
    ctx = request.app.state.ctx
    include_closed = include == "closed"
    rows = await asyncio.to_thread(
        ctx.metrics.leaderboard, include_closed=include_closed
    )
    if status:
        rows = [r for r in rows if r["status"] == status]
    return {"data": rows, "sort": sort}


@router.post("/traders", status_code=201)
async def create_trader(request: Request, body: TraderCreate):
    ctx = request.app.state.ctx
    trader = await ctx.traders.create(body.model_dump())
    return trader_public(trader)


@router.get("/traders/{trader_id}")
async def trader_detail(request: Request, trader_id: int):
    return await _view(request.app.state.ctx, trader_id)


@router.patch("/traders/{trader_id}")
async def patch_trader(request: Request, trader_id: int, body: TraderPatch):
    updated = await request.app.state.ctx.traders.patch(
        trader_id, body.model_dump(exclude_none=True))
    return trader_public(updated)


@router.delete("/traders/{trader_id}")
async def delete_trader(request: Request, trader_id: int, hard: bool = False):
    return await request.app.state.ctx.traders.delete(trader_id, hard=hard)


@router.post("/traders/{trader_id}/reset")
async def reset_trader(request: Request, trader_id: int):
    return trader_public(await request.app.state.ctx.traders.reset(trader_id))


@router.post("/traders/{trader_id}/capital")
async def inject_capital(request: Request, trader_id: int, body: CapitalIn):
    return trader_public(await request.app.state.ctx.traders.inject_capital(trader_id, body.amount))


# -- 订单 ----------------------------------------------------------------


@router.post("/traders/{trader_id}/orders", status_code=201)
async def submit_order(request: Request, trader_id: int, body: OrderIn):
    """代交易员下单（UI 与外部程序同用此端点；origin=manual/operator 见 §3.1）。"""
    ctx = request.app.state.ctx
    origin = "operator" if request.headers.get("X-Origin") == "operator" else "manual"
    return await ctx.trading.submit_order(trader_id, body.model_dump(), origin=origin)


@router.delete("/traders/{trader_id}/orders/{order_id}")
async def cancel_order(request: Request, trader_id: int, order_id: int):
    return await request.app.state.ctx.trading.cancel(trader_id, order_id)


@router.get("/traders/{trader_id}/orders")
async def orders_feed(request: Request, trader_id: int, cursor: int = 0,
                      limit: int = Query(50, le=500), active: bool = False):
    ctx = request.app.state.ctx
    rows = await asyncio.to_thread(ctx.store.orders_feed, trader_id, cursor, limit, active)
    return page_result(rows, limit)


@router.get("/traders/{trader_id}/trades")
async def trades_feed(request: Request, trader_id: int, cursor: int = 0,
                      limit: int = Query(50, le=500)):
    ctx = request.app.state.ctx
    rows = await asyncio.to_thread(ctx.store.trades_feed, trader_id, cursor, limit)
    return page_result(rows, limit)


@router.get("/traders/{trader_id}/positions")
async def positions_view(request: Request, trader_id: int):
    ctx = request.app.state.ctx
    account = await asyncio.to_thread(ctx.traders.account_view, trader_id)
    return {"data": account["positions"]}


@router.get("/traders/{trader_id}/equity")
async def equity_series(request: Request, trader_id: int):
    ctx = request.app.state.ctx
    rows = await asyncio.to_thread(ctx.store.snapshots_for_trader, trader_id)
    return {"data": rows}


@router.get("/traders/{trader_id}/metrics")
async def trader_metrics(request: Request, trader_id: int):
    ctx = request.app.state.ctx
    return await asyncio.to_thread(ctx.metrics.compute_metrics, trader_id)


# -- 计划 ----------------------------------------------------------------


@router.get("/traders/{trader_id}/plans")
async def list_plans(request: Request, trader_id: int):
    ctx = request.app.state.ctx

    def _rows():
        return [ctx.plans.plan_view(p)
                for p in ctx.store.plans_for_trader(trader_id)]

    return {"data": await asyncio.to_thread(_rows)}


@router.post("/traders/{trader_id}/plans", status_code=201)
async def create_plan(request: Request, trader_id: int, body: PlanCreate):
    spec = body.model_dump()
    spec["traderId"] = trader_id
    return await request.app.state.ctx.plans.create_plan(spec)


@router.get("/plans/{plan_id}")
async def get_plan(request: Request, plan_id: int):
    ctx = request.app.state.ctx

    def _get():
        plan = ctx.store.get_plan(plan_id)
        if plan is None:
            from app.errors import BizError
            raise BizError("PLAN_NOT_FOUND", f"计划 {plan_id} 不存在", None, 404)
        return ctx.plans.plan_view(plan)

    return await asyncio.to_thread(_get)


@router.patch("/plans/{plan_id}")
async def patch_plan(request: Request, plan_id: int, body: PlanPatch):
    return await request.app.state.ctx.plans.patch_plan(plan_id, body.model_dump(exclude_none=True))


@router.delete("/plans/{plan_id}")
async def delete_plan(request: Request, plan_id: int):
    return await request.app.state.ctx.plans.delete_plan(plan_id)


@router.get("/plans/{plan_id}/entries")
async def list_entries(request: Request, plan_id: int):
    ctx = request.app.state.ctx
    rows = await asyncio.to_thread(ctx.store.entries_for_plan, plan_id)
    return {"data": rows}


@router.post("/plans/{plan_id}/entries", status_code=201)
async def create_entry(request: Request, plan_id: int, body: EntryCreate):
    spec = {"triggerType": body.triggerType, "triggerParams": body.triggerParams,
            "action": body.action, "tif": body.tif}
    return await request.app.state.ctx.plans.create_entry(plan_id, spec)


@router.delete("/plans/entries/{entry_id}")
async def delete_entry(request: Request, entry_id: int):
    return await request.app.state.ctx.plans.delete_entry(entry_id)


# -- 导出（T13-1 入口） ---------------------------------------------------


@router.get("/traders/{trader_id}/export")
async def export_data(
    request: Request, trader_id: int,
    type: str = "trades", format: str = "csv",
    from_: str | None = Query(None, alias="from"), to: str | None = None,
    stream: bool = False,
):
    ctx = request.app.state.ctx

    def _check():
        trader = ctx.store.get_trader(trader_id)
        if trader is None or trader["status"] == "deleted":
            from app.errors import BizError
            raise BizError("TRADER_NOT_FOUND", f"交易员 {trader_id} 不存在", None, 404)
        ctx.exporter.validate(type, format, from_, to)

    await asyncio.to_thread(_check)
    filename = f"qtv_{type}_{trader_id}.{format}"
    if format == "csv":
        return StreamingResponse(
            ctx.exporter.csv_stream(trader_id, type, from_, to),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    media = "application/x-ndjson" if stream else "application/json"
    return StreamingResponse(
        ctx.exporter.json_stream(trader_id, type, from_, to, ndjson=stream),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _view(ctx, trader_id: int):
    return await asyncio.to_thread(ctx.traders.detail_view, trader_id)
