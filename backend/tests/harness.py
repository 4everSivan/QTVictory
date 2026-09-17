"""测试装配（离线）：内存库 + FakeClock + 行情注入。"""

from __future__ import annotations

import asyncio
import importlib
from datetime import datetime

from app.adapters.tencent import NormalizedQuote
from app.config import Settings
from app.main import create_app


def make_app(clock_start: str = "2026-09-16T09:30:00", **settings_overrides):
    overrides = {"qtv_db": ":memory:", **settings_overrides}
    clock_mod = importlib.import_module("app.clock")
    clock = clock_mod.FakeClock(datetime.fromisoformat(clock_start))
    app = create_app(settings=Settings(**overrides), clock=clock, offline=True)
    return app, app.state.ctx


def quote(code="600519", last=10.0, prev=10.0, cum=None, *,
          bid_p=9.99, ask_p=10.00, vol=30000, ts="09:30:00", name="测试标的"):
    """默认 cum_volume 自动递增：连续注入天然形成正的周期增量 ΔV。"""
    global _CUM_SEQ
    if cum is None:
        _CUM_SEQ += 100_000
        cum = _CUM_SEQ
    return NormalizedQuote(
        code=code, name=name, last=last, prev_close=prev, open=last, high=last,
        low=last, cum_volume=cum,
        bids=[(bid_p, vol)] * 5, asks=[(ask_p, vol)] * 5, ts=ts,
    )


_CUM_SEQ = 1_000_000


async def inject(ctx, *quotes, now: datetime | None = None):
    """注入快照并等待串行基座跑完（撮合/计划已落库）。"""
    ctx.market.inject(list(quotes), now=now or ctx.clock.now())
    for _ in range(200):
        if ctx.serial._queue.empty():  # noqa: SLF001
            await asyncio.sleep(0)
            break
        await asyncio.sleep(0.005)
