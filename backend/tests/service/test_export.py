"""T13：导出五类 × 双格式 × 区间过滤 / CSV BOM / NDJSON（02 §6.8）。"""

import csv
import io
import json

from tests.harness import inject, make_app, quote


async def _seed(ctx):
    t = await ctx.traders.create({"name": "t", "mode": "manual", "initCash": 100000})
    tid = t["id"]
    await inject(ctx, quote())
    await ctx.trading.submit_order(tid, {
        "side": "buy", "type": "market", "code": "600519", "qty": 1000,
    })
    await inject(ctx, quote())
    await ctx.plans.create_plan({"traderId": tid, "name": "p", "scope": {"codes": ["600519"]}})
    ctx.store.upsert_snapshot(tid, "2026-09-15", 100000, 100000)
    ctx.store.upsert_snapshot(tid, "2026-09-16", 100500, 100500)
    return tid


def _drain(gen) -> str:
    return "".join(gen)


class TestCsv:
    async def test_trades_csv_bom_and_columns(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            tid = await _seed(ctx)
            text = _drain(ctx.exporter.csv_stream(tid, "trades"))
            assert text.startswith("﻿")  # UTF-8 BOM
            rows = list(csv.reader(io.StringIO(text.lstrip("﻿"), newline="")))
            header = rows[0]
            assert header[:6] == ["ts", "code", "name", "side", "price", "qty"]
            assert len(rows) >= 2
            money_cols = [header.index("price"), header.index("amount")]
            for r in rows[1:]:
                for c in money_cols:
                    assert r[c] == f"{float(r[c]):.2f}"  # 两位小数、无千分位
        finally:
            await ctx.stop()

    async def test_positions_snapshot(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            tid = await _seed(ctx)
            rows = list(csv.reader(io.StringIO(_drain(
                ctx.exporter.csv_stream(tid, "positions")).lstrip("﻿"), newline="")))
            assert rows[0][0] == "code"
            assert rows[1][0] == "600519" and int(rows[1][1]) == 1000
        finally:
            await ctx.stop()

    async def test_plans_export_with_entries(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            tid = await _seed(ctx)
            rows = list(csv.reader(io.StringIO(_drain(
                ctx.exporter.csv_stream(tid, "plans")).lstrip("﻿"), newline="")))
            assert "planId" in rows[0] and "entries" in rows[0]
            assert rows[1][1] == "p"
        finally:
            await ctx.stop()


class TestJson:
    async def test_json_array(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            tid = await _seed(ctx)
            data = json.loads(_drain(ctx.exporter.json_stream(tid, "trades")))
            assert isinstance(data, list) and data and data[0]["side"] == "buy"
        finally:
            await ctx.stop()

    async def test_ndjson(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            tid = await _seed(ctx)
            lines = [l for l in _drain(
                ctx.exporter.json_stream(tid, "equity", ndjson=True)).splitlines() if l]
            assert len(lines) == 2
            assert json.loads(lines[0])["date"] == "2026-09-15"
        finally:
            await ctx.stop()

    async def test_range_filter(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            tid = await _seed(ctx)
            rows = list(csv.reader(io.StringIO(_drain(
                ctx.exporter.csv_stream(tid, "equity", "2026-09-16", None)).lstrip("﻿"), newline="")))
            assert len(rows) == 2  # header + 1 行（from 过滤）
        finally:
            await ctx.stop()

    async def test_invalid_params(self):
        from app.errors import BizError

        _, ctx = make_app()
        await ctx.start()
        try:
            tid = await _seed(ctx)
            for bad in (("nope", "csv", None, None), ("trades", "xml", None, None),
                        ("trades", "csv", "2026-09-16", "2026-09-15")):
                try:
                    ctx.exporter.validate(*bad)
                    raise AssertionError(f"should reject {bad}")
                except BizError as e:
                    assert e.code == "EXPORT_RANGE_INVALID"
        finally:
            await ctx.stop()
