"""导出服务（T13，02 §3.8 导出侧 / §6.8 / Q5 同步流式）。

五类（trades/orders/positions/equity/plans）× csv/json × 区间过滤；
CSV：UTF-8 BOM、金额两位小数无千分位、流式生成；
JSON：数组（?stream=true 可选 NDJSON）。
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Iterator

from app.errors import BizError

EXPORT_TYPES = ("trades", "orders", "positions", "equity", "plans")
EXPORT_FORMATS = ("csv", "json")

TRADE_COLUMNS = ["ts", "code", "name", "side", "price", "qty", "amount",
                 "commission", "stampTax", "transferFee", "realizedPnl", "origin"]
ORDER_COLUMNS = ["id", "createdAt", "code", "side", "type", "marketType", "price",
                 "qty", "filledQty", "avgFilledPrice", "status", "origin", "planEntryId"]
POSITION_COLUMNS = ["code", "qty", "todayBought", "avgCost", "price", "value",
                    "unrealizedPnl", "availableSell"]
EQUITY_COLUMNS = ["date", "totalEquity", "cash"]
PLAN_COLUMNS = ["planId", "name", "status", "scope", "budget", "risk", "entries"]


def _in_range(day: str | None, from_: str | None, to: str | None) -> bool:
    if day is None:
        return True
    if from_ and day < from_:
        return False
    if to and day > to:
        return False
    return True


def _money(v: Any) -> str:
    return f"{float(v):.2f}" if v is not None else ""


class ExportService:
    def __init__(self, ctx):
        self.ctx = ctx

    def validate(self, type_: str, format_: str, from_: str | None, to: str | None) -> None:
        if type_ not in EXPORT_TYPES:
            raise BizError("EXPORT_RANGE_INVALID", f"type 必须为 {EXPORT_TYPES}", None, 422)
        if format_ not in EXPORT_FORMATS:
            raise BizError("EXPORT_RANGE_INVALID", f"format 必须为 {EXPORT_FORMATS}", None, 422)
        if from_ and to and from_ > to:
            raise BizError("EXPORT_RANGE_INVALID", "from 不能晚于 to", None, 422)

    # -- 行生成（T13-4 区间过滤口径） ---------------------------------------

    def rows(self, trader_id: int, type_: str,
             from_: str | None = None, to: str | None = None) -> tuple[list[str], Iterator[list]]:
        store = self.ctx.store
        if type_ == "trades":
            return TRADE_COLUMNS, (
                [t["ts"], t["code"], self._name(t["code"]), t["side"], _money(t["price"]),
                 t["qty"], _money(t["amount"]), _money(t["commission"]), _money(t["stamp_tax"]),
                 _money(t["transfer_fee"]), _money(t["realized_pnl"]), t["origin"]]
                for t in store.trades_feed(trader_id, limit=10**7)
                if _in_range(t["ts"][:10], from_, to)
            )
        if type_ == "orders":
            return ORDER_COLUMNS, (
                [o["id"], o["created_at"], o["code"], o["side"], o["type"],
                 o["market_type"] or "", _money(o["price"]), o["qty"], o["filled_qty"],
                 _money(o["avg_filled_price"]), o["status"], o["origin"],
                 o["plan_entry_id"] or ""]
                for o in store.orders_feed(trader_id, limit=10**7)
                if _in_range(o["created_at"][:10], from_, to)
            )
        if type_ == "positions":
            account = self.ctx.traders.account_view(trader_id)
            frozen_map: dict[str, int] = {}
            for o in store.orders_feed(trader_id, limit=10**6):
                if o["status"] in ("wait", "partial") and o["side"] == "sell":
                    frozen_map[o["code"]] = frozen_map.get(o["code"], 0) + int(o["frozen_amount"] or 0)
            return POSITION_COLUMNS, (
                [p["code"], p["qty"], p["todayBought"], _money(p["avgCost"]),
                 _money(p["price"]), _money(p["value"]), _money(p["unrealizedPnl"]),
                 p["qty"] - p["todayBought"] - frozen_map.get(p["code"], 0)]
                for p in account["positions"]
            )
        if type_ == "equity":
            return EQUITY_COLUMNS, (
                [s["date"], _money(s["total_equity"]), _money(s["cash"])]
                for s in store.snapshots_for_trader(trader_id)
                if _in_range(s["date"], from_, to)
            )
        # plans：计划与条件单（含状态与触发记录），当前时点快照
        def _plan_rows():
            for plan in store.plans_for_trader(trader_id):
                pv = self.ctx.plans.plan_view(plan)
                entries = [
                    {"id": e["id"], "triggerType": e["trigger_type"],
                     "triggerParams": json.loads(e["trigger_params"] or "{}"),
                     "action": json.loads(e["action"] or "{}"), "tif": e["tif"],
                     "status": e["status"], "lastTriggeredOn": e["last_triggered_on"]}
                    for e in store.entries_for_plan(plan["id"])
                ]
                yield [plan["id"], pv["name"], pv["status"], json.dumps(pv["scope"],
                       ensure_ascii=False), json.dumps(pv["budget"], ensure_ascii=False),
                       json.dumps(pv["risk"], ensure_ascii=False),
                       json.dumps(entries, ensure_ascii=False)]
        return PLAN_COLUMNS, _plan_rows()

    def _name(self, code: str) -> str:
        q = self.ctx.market.quote(code)
        return q.name if q else ""

    # -- 流式输出（T13-1/2/3） ---------------------------------------------

    def csv_stream(self, trader_id: int, type_: str,
                   from_: str | None = None, to: str | None = None) -> Iterator[str]:
        headers, row_iter = self.rows(trader_id, type_, from_, to)
        buf = io.StringIO()
        buf.write("﻿")  # UTF-8 BOM（Excel 兼容，§6.8）
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(headers)
        yield buf.getvalue()
        for row in row_iter:
            chunk = io.StringIO()
            writer = csv.writer(chunk, lineterminator="\n")
            writer.writerow(row)
            yield chunk.getvalue()

    def json_stream(self, trader_id: int, type_: str,
                    from_: str | None = None, to: str | None = None,
                    ndjson: bool = False) -> Iterator[str]:
        headers, row_iter = self.rows(trader_id, type_, from_, to)
        if ndjson:
            for row in row_iter:
                yield json.dumps(dict(zip(headers, row)), ensure_ascii=False) + "\n"
            return
        yield "["
        first = True
        for row in row_iter:
            yield ("" if first else ",") + json.dumps(dict(zip(headers, row)),
                                                      ensure_ascii=False)
            first = False
        yield "]"
