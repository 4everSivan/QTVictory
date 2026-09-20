"""行情服务（T06，02 §3.4 / §6.5）。

- 轮询：连续竞价 QTV_POLL_SEC / 休市 60s；超时 5s；连续 3 败熔断 60s 切换；
- 降级链（C008）：腾讯（https→http 协议兜底）→ 新浪 → 东财 → 内置锚点，
  透出 source/live；新浪档含五档与累计量，视同主源完整档；
- 内存最新档（MarketBus）+ ΔV 差分 + 停牌标志 + 新鲜度时钟（>30s）；
- 日K 全量启动拉取（腾讯 ifzq → 东财 push2his 兜底）
  + 日切步骤 5 关注集重拉（C014，修复长运行末根冻结）；
  分钟线当日累积、新分钟桶触发增量落库（C012）、日切收口、停机兜底；
  新增自选码异步单码引导（T23，串行排队）；
- 交易日历由快照时间戳推定；关注代码集 = 自选 ∪ 持仓 ∪ 计划池 ∪ 指数。

测试经 inject / sync_klines 离线注入（不触网）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date as date_cls, datetime, timedelta
from typing import Any

from app.adapters.fallback import EastmoneyAdapter, FallbackProvider
from app.adapters.sina import SinaAdapter
from app.adapters.tencent import NormalizedQuote, TencentAdapter
from app.domain.engine import BookLevel, Tick, board_code
from app.services.watchlist import normalize_codes

log = logging.getLogger("qtv.market")

INDEX_CODES = ["sh000300"]

_SUGGEST_TTL_SEC = 30.0  # 联想结果服务端短缓存（§3.10）

_KLINE_DEPTH_FALLBACK = 320  # 单源拉取失败的深度回落（ifzq qfq 实测封顶约束，Q11）


def _to_lots(code: str, shares: int) -> int:
    """快照累计量（股）→ 日K volume（手）：688 原值为股直通，其余 ÷100。
    与 tencent._to_shares 互为逆运算——量纲锚定（T25-6/护栏③）。"""
    return int(shares) if board_code(code).startswith("688") else int(shares) // 100


def kline_view(cold: list[dict[str, Any]], hot: NormalizedQuote | None,
               hot_date: str) -> list[dict[str, Any]]:
    """冷热合成视图（02 §3.11 Q12）：klines 完结冷序列 ∪ 当日热 bar（交易日未完结时）。
    降级档缺当日 OHLC、停牌、或当日完结 bar 已入库时热 bar 缺席——
    诚实少最后一根，不造假 bar。展示/API 读本视图；触发域读纯冷序列。"""
    bars = [dict(r) for r in cold]
    if hot is None or hot.last <= 0 or not hot_date:
        return bars
    if bars and bars[-1]["date"] >= hot_date:
        return bars
    if hot.open <= 0 or hot.high <= 0 or hot.low <= 0:
        return bars
    bars.append({
        "code": hot.code,
        "date": hot_date,
        "open": hot.open,
        "close": hot.last,
        "high": max(hot.high, hot.last),
        "low": min(hot.low, hot.last),
        "volume": _to_lots(hot.code, hot.cum_volume),
    })
    return bars


def aggregate_bars(bars: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    """week/month 纯函数聚合（02 §3.11 T26）：week 按 ISO 自然周（周一界）、
    month 按自然月切分；period 内首日 open、末日 close、max high、min low、
    sum volume；`date` 取该 period 内最后交易日（主流行情软件口径）。
    不落表不缓存（单码 ≤800 行 O(n)）。day 原样透传。"""
    if period == "day":
        return [dict(b) for b in bars]
    buckets: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for b in bars:
        d = date_cls.fromisoformat(b["date"])
        key = ((d - timedelta(days=d.weekday())).isoformat() if period == "week"
               else d.replace(day=1).isoformat())
        agg = buckets.get(key)
        if agg is None:
            buckets[key] = dict(b)
            order.append(key)
            continue
        agg["close"] = b["close"]
        agg["date"] = b["date"]
        agg["high"] = max(agg["high"], b["high"])
        agg["low"] = min(agg["low"], b["low"])
        agg["volume"] += b["volume"]
    return [buckets[k] for k in order]


class MarketService:
    def __init__(self, ctx):
        self.ctx = ctx
        self.snapshots: dict[str, NormalizedQuote] = {}
        self._last_cum: dict[str, int] = {}
        self._last_cum_date: dict[str, str] = {}
        self.source: str = "tencent"      # tencent | sina | eastmoney | anchor
        self.live: bool = False           # anchor 模式为 False
        self.last_update: datetime | None = None
        self._fail_streak = 0
        self._circuit_until: datetime | None = None
        self._task: asyncio.Task | None = None
        self._minute_bars: dict[tuple[str, str], tuple[float, int]] = {}
        self._minute_date: str = ""
        self._minute_dirty: bool = False                       # 新分钟桶待刷盘（C012）
        self._minute_flush_tasks: set[asyncio.Task] = set()
        self._watch_override: set[str] | None = None
        self._kline_boot_lock = asyncio.Lock()      # 自选码日K 引导串行排队（T23-3）
        self._kline_boot_tasks: set[asyncio.Task] = set()
        self._suggest_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
        self._minute_boot_fail: dict[str, float] = {}   # 分时引导失败冷却（C019）
        self._client: Any = None
        self._tencent: TencentAdapter | None = None
        self._sina: SinaAdapter | None = None
        self._eastmoney: EastmoneyAdapter | None = None
        self.fallback = FallbackProvider()

    # -- 生命周期 ----------------------------------------------------------

    async def start(self) -> None:
        import httpx

        self._client = httpx.AsyncClient(timeout=5.0)
        self._tencent = TencentAdapter(self._client)
        self._sina = SinaAdapter(self._client)
        self._eastmoney = EastmoneyAdapter(self._client)
        self.live = True
        asyncio.create_task(self._bootstrap_klines())
        self._task = asyncio.create_task(self._poll_loop(), name="quote-poller")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for task in self._kline_boot_tasks:
            task.cancel()
        if self._kline_boot_tasks:
            await asyncio.gather(*self._kline_boot_tasks, return_exceptions=True)
        for task in self._minute_flush_tasks:
            task.cancel()
        if self._minute_flush_tasks:
            await asyncio.gather(*self._minute_flush_tasks, return_exceptions=True)
        if self._client is not None:
            await self._client.aclose()

    def set_watch_override(self, codes: list[str] | None) -> None:
        """测试注入关注集；None = 恢复动态计算。"""
        self._watch_override = set(codes) if codes is not None else None

    def watchlist(self) -> list[str]:
        """关注代码集：自选 ∪ 持仓 ∪ 计划池 ∪ 指数（02 §3.4，v6 并入自选集）。"""
        if self._watch_override is not None:
            return sorted(self._watch_override | set(INDEX_CODES))
        store = self.ctx.store
        codes: set[str] = set(INDEX_CODES)
        codes.update(store.watchlist_codes())
        for pos in store.positions_all():
            codes.add(pos["code"])
        for trader in store.list_traders():
            for plan in store.plans_for_trader(trader["id"], active_only=True):
                try:
                    scope = json.loads(plan["scope"] or "{}")
                except ValueError:
                    scope = {}
                # C011：计划标的池归一（存量裸码行惰性愈合后并入轮询集）
                codes.update(normalize_codes(scope.get("codes", []))[0])
        return sorted(codes)

    # -- 轮询与降级链（T06-1/T06-3，C008 扩充） ---------------------------

    async def _poll_loop(self) -> None:
        while True:
            interval = 10
            try:
                interval = (
                    self.ctx.settings.qtv_poll_sec
                    if self.ctx.session.trading_phase()
                    else 60
                )
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("poll error")
            await asyncio.sleep(interval)

    async def poll_once(self) -> None:
        now = self.ctx.clock.now()
        if self._circuit_until is not None and now < self._circuit_until:
            self._emit_anchor(now)
            return
        codes = self.watchlist()
        try:
            quotes = await self._tencent.fetch_quotes(codes)
            if not quotes:
                raise RuntimeError("empty payload")
        except Exception:
            self._fail_streak += 1
            if self._fail_streak >= 3:  # 熔断：走备源链（新浪→东财），再灭进锚点闭锁 60s
                for source, adapter in (("sina", self._sina), ("eastmoney", self._eastmoney)):
                    try:
                        quotes = await adapter.fetch_quotes(codes)
                    except Exception:
                        continue
                    if quotes:
                        self.source, self.live = source, True
                        self._ingest(quotes, now)
                        return
                self.source, self.live = "anchor", False
                self._circuit_until = now + timedelta(seconds=60)
                self._fail_streak = 0
                self._emit_anchor(now)
            return
        self._fail_streak = 0
        self.source, self.live = "tencent", True
        self._ingest(quotes, now)

    def _emit_anchor(self, now: datetime) -> None:
        self.source, self.live = "anchor", False
        quotes = [
            snap for snap in (
                self.fallback.snapshot(code, now.strftime("%H:%M:%S"))
                for code in self.watchlist()
            ) if snap is not None
        ]
        if quotes:
            self._ingest(quotes, now)

    # -- 快照进入系统（测试注入同一入口） ---------------------------------

    def inject(self, quotes: list[NormalizedQuote], now: datetime | None = None) -> None:
        """离线注入快照（与 poll 同路径）：差分 ΔV、推进交易日历、驱动撮合/计划。"""
        self._ingest(quotes, now or self.ctx.clock.now())

    def _ingest(self, quotes: list[NormalizedQuote], now: datetime) -> None:
        self.last_update = now
        today = now.strftime("%Y-%m-%d")
        # C008：新浪档含五档与累计量，视同主源完整档；仅东财/锚点为降级档
        degraded = self.source not in ("tencent", "sina")
        ticks: list[Tick] = []
        for q in quotes:
            prev_date = self._last_cum_date.get(q.code, "")
            prev_snap = self.snapshots.get(q.code)
            if prev_date and prev_date != today and prev_snap is not None:
                # T25-3：换日捕获自沉淀——新日数据覆盖之前，完结热 bar 落库
                self._capture_hot_bar(prev_snap, prev_date)
            prev_cum = self._last_cum.get(q.code, 0)
            if self._last_cum_date.get(q.code, "") != today:
                prev_cum = 0  # 新交易日：累计量重置
            delta = max(0, q.cum_volume - prev_cum) if q.cum_volume else 0
            self._last_cum[q.code] = q.cum_volume
            self._last_cum_date[q.code] = today
            self.snapshots[q.code] = q
            self.fallback.seed(q.code, q.name, q.last or q.prev_close)
            self._accumulate_minute(q, today)
            ticks.append(Tick(
                code=q.code, last=q.last, prev_close=q.prev_close,
                bids=[BookLevel(p, v) for p, v in q.bids],
                asks=[BookLevel(p, v) for p, v in q.asks],
                delta_volume=0 if degraded else delta,
                suspended=q.last <= 0, degraded=degraded,
                ts=now.isoformat(timespec="seconds"),
            ))
        self._rollover_trading_date(now)
        if self._minute_dirty:
            self._minute_dirty = False
            self._schedule_minute_flush()
        self.ctx.bus.publish("quotes", self.quotes_payload())
        if ticks:
            # §4.4：同一串行基座，PlanEngine.tick 先于 MatchingEngine.tick
            self.ctx.serial.submit(lambda: self.ctx.plans.on_ticks(ticks))
            self.ctx.serial.submit(lambda: self.ctx.trading.on_ticks(ticks))

    def _accumulate_minute(self, q: NormalizedQuote, today: str) -> None:
        if self._minute_date != today:
            self._minute_bars.clear()
            self._minute_date = today
        if q.last <= 0:
            return
        # C010：时间戳不可解析（如降级源空 ts）不落桶——原 09:31 兜底把
        # 无冒号时间戳全部挤进单桶，当日分钟线失真
        minute = q.ts[:5] if ":" in q.ts else ""
        if not minute:
            return
        # C018：时段门禁——仅前端 242 槽窗口（09:30–11:30 / 13:00–15:00）
        # 落桶；盘后/周末快照 ts（15:0x 之后等）落的是槽外垃圾桶，不可见且污表
        if not ("09:30" <= minute <= "11:30" or "13:00" <= minute <= "15:00"):
            return
        key = (q.code, minute)
        if key not in self._minute_bars:
            self._minute_dirty = True   # 进入新分钟桶：触发增量刷盘（C012）
        price, _ = self._minute_bars.get(key, (q.last, 0))
        self._minute_bars[key] = (price, q.cum_volume)

    def _capture_hot_bar(self, q: NormalizedQuote, date: str) -> None:
        """换日捕获自沉淀（T25-3，02 §3.11 冷热双态）：日切前完结热 bar 落库，
        与 C012 分钟自沉淀同构对称。源门禁：tencent/sina（live 完整档）必落；
        eastmoney（真实价但字段可能不全）视 OHLC 有效性；anchor 恒不落
        （人造价格禁止入冷序列）。幂等 upsert；该日完结 bar 已在库
        （上游权威）时不覆盖；崩溃于捕获与 checkpoint 之间可重跑。"""
        if self.source == "anchor":
            return
        if self.source not in ("tencent", "sina") and not (
                q.open > 0 and q.high > 0 and q.low > 0):
            return
        if q.last <= 0 or q.cum_volume <= 0:
            return
        cold = self.ctx.store.klines_for(q.code, limit=1)
        if cold and cold[-1]["date"] >= date:
            return
        row = (q.code, date, q.open, q.last, max(q.high, q.last),
               min(q.low, q.last), _to_lots(q.code, q.cum_volume))
        self.ctx.store.upsert_klines([row])

    def _schedule_minute_flush(self) -> None:
        task = asyncio.create_task(self._flush_minutes_task(), name="minute-flush")
        self._minute_flush_tasks.add(task)
        task.add_done_callback(self._minute_flush_tasks.discard)

    async def _flush_minutes_task(self) -> None:
        try:
            await self.flush_minutes()
        except Exception:
            log.warning("minute incremental flush failed", exc_info=True)

    async def flush_minutes(self) -> int:
        """当日分钟线增量落库（C012）：幂等 upsert 全量当前桶，崩溃/
        重启损失收敛到当前未完成分钟；日切 persist_minutes 仍为最终收口。"""
        date = self._minute_date
        rows = [
            (code, date, minute, price, vol)
            for (code, minute), (price, vol) in self._minute_bars.items()
        ]
        if rows:
            await asyncio.to_thread(self.ctx.store.upsert_minutes, rows)
        return len(rows)

    def _rollover_trading_date(self, now: datetime) -> None:
        today = now.strftime("%Y-%m-%d")
        current = self.ctx.store.get_state("trading_date")
        if current == today:
            return
        if current is not None and current > today:
            # C017：未来日期守卫——绝不因未来日期触发日切（原只判 !=，
            # 周末 advance 到次交易日（周一 > 当日）会每轮 poll 再切一天，
            # 滚雪球式伪日切把 trading_date 推进到远未来）。
            # 小步超前（≤7 天）= 日切推进到的次交易日（跨周末/法定连休），保持；
            # 大幅超前/不可解析 = 时钟回拨或状态污染，告警重同步回真实当日。
            try:
                gap = (
                    date_cls.fromisoformat(current) - date_cls.fromisoformat(today)
                ).days
            except ValueError:
                gap = 999
            if gap <= 7:
                return
            log.warning(
                "trading_date %s ahead of clock %s by %dd; resync",
                current, today, gap,
            )
            self.ctx.store.set_state("trading_date", today)
            return
        if current is not None:
            # 观测到新交易日：对前一交易日执行日切（幂等可重入）。
            # 直接调同步内核——当前已可能处于串行基座回调内，嵌套提交会死锁
            self.ctx.serial.submit(
                lambda: self.ctx.session._day_cut_sync(current or today)
            )
        self.ctx.store.set_state("trading_date", today)

    # -- 视图 --------------------------------------------------------------

    def quote(self, code: str) -> NormalizedQuote | None:
        return self.snapshots.get(code)

    def price(self, code: str) -> float:
        q = self.snapshots.get(code)
        if q and q.last > 0:
            return q.last
        close = self.ctx.store.klines_for(code, limit=1)
        return close[-1]["close"] if close else 0.0

    def kline_view_for(self, code: str, limit: int = 250) -> list[dict[str, Any]]:
        """展示/API 读路径（02 §3.11 双读者）：klines 完结冷序列 ∪ 当日热 bar。
        触发域（price()/PlanEngine 收盘口径）仍读纯冷序列，语义零变化。"""
        cold = self.ctx.store.klines_for(code, limit=limit)
        return kline_view(cold, self.snapshots.get(code),
                          self._last_cum_date.get(code, ""))

    def kline_series(self, code: str, period: str = "day",
                     limit: int = 250) -> list[dict[str, Any]]:
        """多周期 API 读路径（T26）：day = 冷热合成原样；week/month = 聚合后
        截尾 limit 根（limit 语义 = 聚合后根数；取数按周期换算 + 缓冲——
        week 5N+10、month 22N+22，封顶 5000 防失控）。"""
        if period == "day":
            return self.kline_view_for(code, limit=limit)
        per = 5 if period == "week" else 22
        fetch = min(limit * per + 10, 5000)
        bars = aggregate_bars(self.kline_view_for(code, limit=fetch), period)
        return bars[-limit:]

    def quotes_payload(self) -> dict[str, Any]:
        return {
            "source": self.source, "live": self.live,
            "ts": self.ctx.clock.now().isoformat(timespec="seconds"),
            "quotes": [
                {
                    "code": q.code, "name": q.name, "last": q.last,
                    "prevClose": q.prev_close, "open": q.open, "high": q.high,
                    "low": q.low, "volume": q.cum_volume,
                    "bids": q.bids, "asks": q.asks,
                }
                for q in self.snapshots.values()
            ],
        }

    def status(self) -> dict[str, Any]:
        age = None
        if self.last_update is not None:
            age = (self.ctx.clock.now() - self.last_update).total_seconds()
        return {"source": self.source, "live": self.live, "ageSec": age}

    def stale(self) -> bool:
        """新鲜度 >30s：拒市价单（02 §6.5）。"""
        return self.last_update is None or (
            (self.ctx.clock.now() - self.last_update).total_seconds() > 30
        )

    # -- K 线 / 分钟线 / 公司行动 ------------------------------------------

    def _kline_depth_for(self, code: str) -> int:
        """校准重拉深度（T25-4）：max(配置深度, 库存深度)——重拉深度 ≥ 库存深度，
        防旧自沉淀 bar 与重锚后序列错位（02 §3.11 复权口径）。"""
        return max(self.ctx.settings.qtv_kline_depth,
                   self.ctx.store.klines_depth(code))

    async def _fetch_daily_chain(self, code: str, depth: int | None = None) -> list[tuple]:
        """日K 链路：腾讯 ifzq → 东财 push2his 兜底（C008 同款，量纲一致）。
        T25-5：深度经 `QTV_KLINE_DEPTH`（默认 800、上限 800——ifzq qfq 实测
        封顶约 640~800，Q11）；单源失败回落 320 不阻断引导链。"""
        if depth is None:
            depth = self._kline_depth_for(code)
        try:
            return await self._tencent.fetch_daily_klines(code, depth)
        except Exception:
            if self._eastmoney is None:
                raise
            return await self._eastmoney.fetch_daily_klines(code, _KLINE_DEPTH_FALLBACK)

    async def _bootstrap_klines(self) -> None:
        try:
            for code in self.watchlist():
                rows = await self._fetch_daily_chain(code)
                if rows:
                    await asyncio.to_thread(self.ctx.store.upsert_klines, rows)
            log.info("kline bootstrap done")
        except Exception:
            log.exception("kline bootstrap failed")

    def trigger_kline_bootstrap(self, code: str) -> asyncio.Task | None:
        """新增自选成功后异步引导该码日K（T23-3：单码粒度、串行排队、
        失败不阻塞添加回执）；offline 无网络不引导。返回任务便于测试等待。"""
        if self._tencent is None:
            return None
        task = asyncio.create_task(self._bootstrap_kline_one(code),
                                   name=f"kline-boot-{code}")
        self._kline_boot_tasks.add(task)
        task.add_done_callback(self._kline_boot_tasks.discard)
        return task

    async def _bootstrap_kline_one(self, code: str) -> None:
        async with self._kline_boot_lock:  # 批量添加时引导串行排队
            try:
                rows = await self._fetch_daily_chain(code)
                if rows:
                    await asyncio.to_thread(self.ctx.store.upsert_klines, rows)
            except Exception:
                log.warning("kline bootstrap for %s failed", code, exc_info=True)

    def schedule_daily_kline_refresh(self) -> str:
        """日切步骤 5（C014/BG-0008）：关注集日K重拉。修复长运行实例
        klines 末根冻结于上次启动时刻的缺陷（文档宣称的"每日增量"原为
        noop）；幂等 upsert，单码失败仅告警不阻断日切；离线无适配器为空操作。"""
        if self._tencent is None:
            return "noop"
        task = asyncio.create_task(self._refresh_daily_klines(),
                                   name="kline-daily-refresh")
        self._kline_boot_tasks.add(task)
        task.add_done_callback(self._kline_boot_tasks.discard)
        return "scheduled"

    async def _refresh_daily_klines(self) -> None:
        async with self._kline_boot_lock:  # 与单码引导共用串行排队
            for code in self.watchlist():
                try:
                    rows = await self._fetch_daily_chain(code)
                    if rows:
                        await asyncio.to_thread(self.ctx.store.upsert_klines, rows)
                except Exception:
                    log.warning("daily kline refresh for %s failed", code,
                                exc_info=True)
            log.info("daily kline refresh done")

    # -- 自选股支撑（T23）：快照探测与名称联想 ---------------------------------

    async def probe_code(self, code: str) -> NormalizedQuote | None:
        """单码快照可达性探测（WatchlistService 校验用）；offline 恒 None。"""
        if self._tencent is None:
            return None
        quotes = await self._tencent.fetch_quotes([code])
        return quotes[0] if quotes else None

    async def suggest(self, q: str) -> list[dict[str, str]]:
        """名称联想（T23-4）：腾讯 smartbox 代理 + 服务端短缓存；
        上游故障返回空列表（联想场景不阻断前端）。"""
        key = q.strip()
        if not key or self._tencent is None:
            return []
        now = time.monotonic()
        hit = self._suggest_cache.get(key)
        if hit is not None and now - hit[0] < _SUGGEST_TTL_SEC:
            return hit[1]
        try:
            rows = await self._tencent.fetch_suggest(key)
        except Exception:
            log.warning("suggest upstream failed for %r", q, exc_info=True)
            return []
        if len(self._suggest_cache) > 512:
            self._suggest_cache.clear()
        self._suggest_cache[key] = (now, rows)
        return rows

    def sync_klines(self, rows: list[tuple]) -> None:
        """增量/测试注入：[(code, date, open, close, high, low, volume)]。"""
        self.ctx.store.upsert_klines(rows)

    async def bootstrap_latest_minutes(self, code: str) -> str | None:
        """最近交易日分时引导（C019/EN-0009）：/market/minute 缺省查询经
        回退仍空时触发；仅补最近一个交易日（Q8 边界修订，更深历史不回补），
        幂等 upsert；失败/空结果 10 分钟冷却防无效码反复打上游。"""
        if self._tencent is None:
            return None
        now = time.monotonic()
        if now - self._minute_boot_fail.get(code, -1e9) < 600:
            return None
        try:
            result = await self._tencent.fetch_latest_minutes(code)
        except Exception:
            log.warning("latest minutes bootstrap for %s failed", code,
                        exc_info=True)
            self._minute_boot_fail[code] = now
            return None
        if not result:
            self._minute_boot_fail[code] = now
            return None
        day, rows = result
        # 与实时落桶同一时段门禁（C018）：上游可能带 15:00 后参考点，槽外丢弃
        rows = [r for r in rows
                if "09:30" <= r[2] <= "11:30" or "13:00" <= r[2] <= "15:00"]
        if not rows:
            self._minute_boot_fail[code] = now
            return None
        await asyncio.to_thread(self.ctx.store.upsert_minutes, rows)
        log.info("latest minutes bootstrapped for %s @%s (%d rows)",
                 code, day, len(rows))
        return day

    def persist_minutes(self, date: str) -> int:
        """当日分钟线落库（Q8：自部署日起逐日累积）。"""
        rows = [
            (code, date, minute, price, vol)
            for (code, minute), (price, vol) in self._minute_bars.items()
        ]
        if rows:
            self.ctx.store.upsert_minutes(rows)
        self._minute_bars.clear()
        return len(rows)

    async def fetch_corporate_actions(self, next_date: str) -> int:
        """公司行动采集（02 §3.4）：源端无稳定免费接口，钩子默认空；
        数据可直写 corporate_actions 表（处理逻辑在 SessionService，已全测）。"""
        if self._tencent is None:
            return 0
        rows = await self._tencent.fetch_corporate_actions(self.watchlist(), next_date)
        if rows:
            self.ctx.store.upsert_actions(rows)
        return len(rows)
