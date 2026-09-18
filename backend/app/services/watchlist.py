"""自选股服务（T23，02 §3.10 / §5.2 v6）。

- 观察员级全局自选集，落 watchlist 表；仅影响行情关注集（§3.4 并集第四支）；
- 代码规范化：qt.gtimg.cn 仅识别带市场前缀代码，裸 6 位码按板块规则推导
  候选前缀逐个快照探测，以首个命中的规范码落库（输入写法变体幂等归一）；
- 校验 = 格式合法 + 行情源快照可达（停牌码跳过，§6.12）；
- 单码幂等：重复添加返回原态（不重复探测）、删除不存在视为成功；
- 批量：逐码校验、部分应用、逐码回执；
- 新增成功后异步触发该码日K 引导（MarketService，串行排队、失败不阻塞回执）。

探测为网络 I/O，一律在串行基座外执行；库写经 serial.run 入基座。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Awaitable, Callable

from app.adapters.tencent import NormalizedQuote
from app.errors import BizError

_PREFIXED = re.compile(r"(?:sh|sz|bj)\d{6}")
_BARE = re.compile(r"\d{6}")

# 裸码 → 市场前缀推导：沪深主板/科创/创业板/场内基金/北交所
_PREFIX_RULES = (
    ("sh", ("60", "68", "90", "50", "51", "52", "56", "58", "11", "13")),
    ("sz", ("00", "30", "20", "12", "15", "16", "18")),
    ("bj", ("43", "83", "87", "88", "92")),
)

ProbeFn = Callable[[str], Awaitable[NormalizedQuote | None]]


def code_candidates(raw: str) -> list[str]:
    """输入代码的规范码候选（保序去重）：已带前缀直取；
    裸 6 位按板块规则优先、其余市场依次兜底（如 000300 命中 sh 指数）。"""
    code = (raw or "").strip().lower()
    if _PREFIXED.fullmatch(code):
        return [code]
    if _BARE.fullmatch(code):
        primary = [m for m, heads in _PREFIX_RULES if code.startswith(heads)]
        ordered = primary + [m for m in ("sh", "sz", "bj") if m not in primary]
        return [m + code for m in ordered]
    return []


class WatchlistService:
    def __init__(self, ctx):
        self.ctx = ctx
        self._probe: ProbeFn | None = None  # 测试注入；None = 走行情源快照探测

    # -- 查询（added_at 倒序） ------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        return [
            {"code": r["code"], "addedAt": r["added_at"]}
            for r in self.ctx.store.watchlist_all()
        ]

    # -- 单码增删（幂等） ------------------------------------------------------

    async def add(self, code: str) -> dict[str, Any]:
        candidates = code_candidates(code)
        if not candidates:
            raise BizError("BAD_CODE", f"代码格式非法：{code}",
                           {"code": code, "reason": "BAD_FORMAT"}, 400)
        store = self.ctx.store
        existing = await asyncio.to_thread(store.watchlist_get_any, candidates)
        if existing is not None:  # 重复添加返回原态（不再探测）
            return {"code": existing["code"], "addedAt": existing["added_at"],
                    "created": False}
        quote = await self._probe_first(candidates)
        canonical, name = quote.code, quote.name

        def _apply() -> tuple[dict[str, str], bool]:
            current = store.watchlist_get_any(candidates + [canonical])
            if current is not None:
                return current, False
            now = self.ctx.clock.now().isoformat(timespec="seconds")
            store.watchlist_add(canonical, now)
            return {"code": canonical, "added_at": now}, True

        row, created = await self.ctx.serial.run(_apply)
        if created:
            # §3.10：添加即异步引导日K（失败不阻塞回执）
            self.ctx.market.trigger_kline_bootstrap(canonical)
        out: dict[str, Any] = {"code": row["code"], "addedAt": row["added_at"],
                               "created": created}
        if created:
            out["name"] = name
        return out

    async def remove(self, code: str) -> dict[str, Any]:
        candidates = code_candidates(code)
        if not candidates:
            raise BizError("BAD_CODE", f"代码格式非法：{code}",
                           {"code": code, "reason": "BAD_FORMAT"}, 400)

        def _apply() -> dict[str, Any]:
            removed = self.ctx.store.watchlist_remove(candidates)
            return {"code": removed or candidates[0], "removed": removed is not None}

        return await self.ctx.serial.run(_apply)

    # -- 批量（逐码校验、部分应用、逐码回执） -----------------------------------

    async def batch(self, add: list[str], remove: list[str]) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for code in add:
            results.append(await self._receipt("add", code, self.add))
        for code in remove:
            results.append(await self._receipt("remove", code, self.remove))
        return {"results": results}

    async def _receipt(self, op: str, code: str, fn) -> dict[str, Any]:
        try:
            await fn(code)
            return {"code": code, "op": op, "ok": True, "error": None}
        except BizError as exc:
            reason = (exc.details or {}).get("reason", exc.code)
            return {"code": code, "op": op, "ok": False, "error": reason}

    # -- 校验：格式 + 快照可达性 ----------------------------------------------

    async def _probe_first(self, candidates: list[str]) -> NormalizedQuote:
        """逐候选快照探测：首个可达且非停牌者胜出；全灭 → 不可达。"""
        probe = self._probe or self.ctx.market.probe_code
        for cand in candidates:
            try:
                quote = await probe(cand)
            except Exception as exc:
                raise BizError("QUOTE_SOURCE_ERROR", "行情源校验不可用，稍后重试",
                               {"code": cand, "reason": "SOURCE_ERROR"}, 503) from exc
            if quote is None or not quote.name:
                continue
            if quote.last <= 0 and quote.open <= 0:
                raise BizError("BAD_CODE", f"标的停牌，暂不可收录：{cand}",
                               {"code": cand, "reason": "SUSPENDED"}, 400)
            return quote
        raise BizError("BAD_CODE", "行情源无此代码快照",
                       {"code": candidates[0], "reason": "UNREACHABLE"}, 400)
