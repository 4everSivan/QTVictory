"""应用上下文（T01-6 启动装配序）。

启动顺序（固定，失败即中止）：迁移 → 观察员初始化 → 串行基座 →
行情启动（offline 模式跳过，测试离线注入）。全部服务单例挂载于此。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.bus import Bus
from app.clock import Clock
from app.config import Settings
from app.serial import SerialExecutor
from app.store.db import Database
from app.store.store import Store

log = logging.getLogger("qtv.context")


class AppContext:
    def __init__(self, settings: Settings | None = None, clock: Clock | None = None,
                 offline: bool = False):
        from app.services.export import ExportService
        from app.services.market import MarketService
        from app.services.metrics import MetricsService
        from app.services.plan import PlanService
        from app.services.session import SessionService
        from app.services.trader import TraderService
        from app.services.trading import TradingService
        from app.services.watchlist import WatchlistService

        self.settings = settings or Settings()
        self.clock = clock or Clock()
        self.offline = offline
        self.db = Database(self.settings.qtv_db)
        self.store = Store(self.db)
        self.serial = SerialExecutor()
        self.bus = Bus()
        self.market = MarketService(self)
        self.traders = TraderService(self)
        self.trading = TradingService(self)
        self.session = SessionService(self)
        self.plans = PlanService(self)
        self.metrics = MetricsService(self)
        self.exporter = ExportService(self)
        self.watchlist = WatchlistService(self)

    async def start(self) -> None:
        # 1) 持久层：连接 + 迁移（幂等）
        def _open() -> None:
            self.db.connect()
            applied = self.db.migrate()
            if applied:
                log.info("applied migrations: %s", applied)

        await asyncio.to_thread(_open)
        # 2) 观察员初始化（Q4：系统唯一观察员，首启创建）
        await asyncio.to_thread(self._init_observer)
        # 3) 串行基座
        await self.serial.start()
        # 4) 行情（offline 跳过：测试经 market.inject 注入）
        if not self.offline:
            await self.market.start()
        log.info("context started (offline=%s)", self.offline)

    def _init_observer(self) -> None:
        initialized = self.store.get_state("observer_initialized")
        if initialized != "true":
            self.store.set_state("observer_initialized", "true")
            log.info("observer initialized (system unique)")
        if not self.settings.qtv_api_key:
            log.warning("无鉴权模式：QTV_API_KEY 未配置，仅监听 127.0.0.1（私人使用定位）")

    async def stop(self) -> None:
        # C012：停机终态刷盘当日分钟线（offline 同样生效——market.stop 在
        # offline 下被跳过，兜底必须挂在这里才能覆盖测试与实盘两条路径）
        try:
            await self.market.flush_minutes()
        except Exception:
            log.exception("minute final flush on stop failed")
        if not self.offline:
            await self.market.stop()
        await self.serial.stop()
        await asyncio.to_thread(self.db.close)
