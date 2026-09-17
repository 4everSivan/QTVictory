"""T14-5 性能基准（02 §2.3，本机口径）：

① 64 交易员 × 2 计划 × 5 条件单，单 tick 评估 < 50ms；
② 导出 1 万行 < 2s（Q5 同步流式）；
③ tick → 撮合/计划评估 → 广播 < 200ms；
④ REST P95 < 50ms。

以断言固化阈值，报告数据由 -s 输出（T14-6 归档）。
"""

from __future__ import annotations

import statistics
import time

import httpx
import pytest

from tests.harness import make_app, quote

N_TRADERS, N_PLANS, N_ENTRIES = 64, 2, 5


async def _seed_scale(ctx):
    for i in range(N_TRADERS):
        t = await ctx.traders.create({"name": f"t{i}", "mode": "manual",
                                      "initCash": 1_000_000})
        for p in range(N_PLANS):
            plan = await ctx.plans.create_plan({
                "traderId": t["id"], "name": f"p{p}",
                "scope": {"codes": ["600519"]},
            })
            for e in range(N_ENTRIES):
                await ctx.plans.create_entry(plan["id"], {
                    "triggerType": "price_cross",
                    "triggerParams": {"side": "buy", "price": 9.5},
                    "action": {"side": "buy", "qty": 100, "type": "market"},
                    "tif": "gtc",
                })


class TestBenchmarks:
    async def test_bench_single_tick_under_50ms(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            await _seed_scale(ctx)
            ctx.market.inject([quote()])  # 预热
            # §6.12 口径：单 tick「评估」< 50ms —— 用不触发价（9.6 > 9.5）
            q = quote(last=9.6, cum=999_999_999)
            t0 = time.perf_counter()
            ctx.market.inject([q])
            for _ in range(2000):
                if ctx.serial._queue.empty():  # noqa: SLF001
                    break
                await __import__("asyncio").sleep(0)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            print(f"\n[bench] {N_TRADERS}×{N_PLANS}×{N_ENTRIES} single tick eval: "
                  f"{elapsed_ms:.1f}ms")
            assert elapsed_ms < 50, "单 tick 评估超时（§6.12：<50ms）"
            # 参考数据（非 §6.12 阈值）：全量触发洪峰（640 条件单齐发下单）
            q2 = quote(last=9.4, cum=999_999_999)
            t0 = time.perf_counter()
            ctx.market.inject([q2])
            for _ in range(5000):
                if ctx.serial._queue.empty():  # noqa: SLF001
                    break
                await __import__("asyncio").sleep(0)
            flood_ms = (time.perf_counter() - t0) * 1000
            print(f"[bench] (ref) full-trigger flood 640 entries: {flood_ms:.1f}ms")
        finally:
            await ctx.stop()

    async def test_bench_export_10k_rows_under_2s(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            t = await ctx.traders.create({"name": "t", "mode": "manual",
                                          "initCash": 10_000_000})
            tid = t["id"]
            now = "2026-09-16T10:00:00"
            rows = [{
                "order_id": 1, "trader_id": tid, "code": "600519", "side": "buy",
                "price": 10.0, "qty": 100, "amount": 1000.0, "commission": 5.0,
                "stamp_tax": 0.0, "transfer_fee": 0.1, "realized_pnl": None,
                "origin": "manual", "ts": now, "trading_date": "2026-09-16",
            } for _ in range(10_000)]
            t0 = time.perf_counter()
            for r in rows:
                ctx.store.insert_trade(r)
            seed_ms = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            n = 0
            for _chunk in ctx.exporter.csv_stream(tid, "trades"):
                n += 1
            elapsed_ms = (time.perf_counter() - t0) * 1000
            print(f"\n[bench] export 10k rows csv: {elapsed_ms:.1f}ms "
                  f"(seed {seed_ms:.0f}ms, {n} chunks)")
            assert elapsed_ms < 2000
        finally:
            await ctx.stop()

    async def test_bench_tick_to_broadcast_under_200ms(self):
        _, ctx = make_app()
        await ctx.start()
        try:
            received: list[float] = []
            t0 = time.perf_counter()

            def on_quote(_topic, _data):
                received.append(time.perf_counter())

            ctx.bus.subscribe("quotes", on_quote)
            q = quote()
            ctx.market.inject([q])
            await __import__("asyncio").sleep(0.05)
            assert received
            latency_ms = (received[0] - t0) * 1000
            print(f"\n[bench] tick -> quotes broadcast: {latency_ms:.2f}ms")
            assert latency_ms < 200
        finally:
            await ctx.stop()

    async def test_bench_rest_p95_under_50ms(self):
        app, ctx = make_app(qtv_rate_limit=100_000)  # 基准放开限速，测接口本身
        await ctx.start()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://t") as c:
                latencies = []
                for _ in range(100):
                    t0 = time.perf_counter()
                    resp = await c.get("/api/session")
                    assert resp.status_code == 200
                    latencies.append((time.perf_counter() - t0) * 1000)
            latencies.sort()
            p95 = latencies[int(len(latencies) * 0.95) - 1]
            print(f"\n[bench] REST P95 (n=100): {p95:.2f}ms, "
                  f"median {statistics.median(latencies):.2f}ms")
            assert p95 < 50
        finally:
            await ctx.stop()
