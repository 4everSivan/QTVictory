"""SQLite 访问核心（T02-1/T02-2/T02-3）。

- WAL + 单写者纪律：写操作全部经 SerialExecutor 串行后调用本层；
- 全量 Schema（02 §6.2）：migrate() 内逐条字面量 DDL 执行（显式事务包裹，
  DDL 无动态值，统一以空参数元组走参数化调用形态）；
- 业务 SQL 一律在 store.py 以**字面量语句 + ? 占位符**内联执行，
  动态值绝不拼接进语句；
- 方法为同步函数（sqlite3），服务层经 asyncio.to_thread 调用，
  连接级 threading.RLock 保证跨线程安全。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

_NO_PARAMS: tuple = ()


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: sqlite3.Connection | None = None
        self.lock = threading.RLock()

    # -- lifecycle ---------------------------------------------------------

    def connect(self) -> None:
        if self.path != ":memory:":
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL", _NO_PARAMS)
        self.conn.execute("PRAGMA synchronous=NORMAL", _NO_PARAMS)
        self.conn.isolation_level = None  # 手动事务

    def close(self) -> None:
        with self.lock:
            if self.conn is not None:
                self.conn.close()
                self.conn = None

    # -- migrations (T02-1) ------------------------------------------------

    def migrate(self) -> list[int]:
        """应用未执行的迁移；返回本次应用的版本号列表。幂等可重跑。"""
        assert self.conn is not None
        applied: list[int] = []
        with self.lock, self.transaction():
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                _NO_PARAMS,
            )
            current = 0
            row = self.conn.execute(
                "SELECT value FROM _meta WHERE key = ?", ("schema_version",)
            ).fetchone()
            if row is not None:
                current = int(row["value"])
            if current < 1:
                self._migrate_v1()
                self.conn.execute(
                    "INSERT INTO _meta(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    ("schema_version", "1"),
                )
                applied.append(1)
        return applied

    def _migrate_v1(self) -> None:
        """v1：02 §6.2 全量 Schema（+ 实现支撑表 idempotency_keys/_meta）。"""
        assert self.conn is not None
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS sync_state (key TEXT PRIMARY KEY, value TEXT)", _NO_PARAMS
        )
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts TEXT NOT NULL,
              actor TEXT NOT NULL DEFAULT 'observer',
              method TEXT NOT NULL,
              path TEXT NOT NULL,
              target TEXT,
              payload_digest TEXT,
              status_code INTEGER NOT NULL
            )""", _NO_PARAMS)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS traders (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              mode TEXT NOT NULL,
              strategy_type TEXT,
              strategy_params TEXT,
              status TEXT NOT NULL DEFAULT 'running',
              init_cash REAL NOT NULL,
              cash REAL NOT NULL,
              created_at TEXT NOT NULL,
              deleted_at TEXT
            )""", _NO_PARAMS)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              trader_id INTEGER NOT NULL,
              origin TEXT NOT NULL,
              plan_entry_id INTEGER,
              client_order_id TEXT,
              side TEXT NOT NULL,
              type TEXT NOT NULL,
              market_type TEXT,
              code TEXT NOT NULL,
              price REAL,
              qty INTEGER NOT NULL,
              filled_qty INTEGER NOT NULL DEFAULT 0,
              avg_filled_price REAL,
              frozen_amount REAL,
              fill_model TEXT,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              trading_date TEXT NOT NULL,
              filled_at TEXT
            )""", _NO_PARAMS)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_trader_date "
            "ON orders(trader_id, trading_date, status)",
            _NO_PARAMS,
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_code_active ON orders(code, status)", _NO_PARAMS
        )
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              order_id INTEGER NOT NULL,
              trader_id INTEGER NOT NULL,
              code TEXT NOT NULL,
              side TEXT NOT NULL,
              price REAL NOT NULL,
              qty INTEGER NOT NULL,
              amount REAL NOT NULL,
              commission REAL NOT NULL,
              stamp_tax REAL NOT NULL,
              transfer_fee REAL NOT NULL,
              realized_pnl REAL,
              origin TEXT NOT NULL,
              ts TEXT NOT NULL,
              trading_date TEXT NOT NULL
            )""", _NO_PARAMS)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trades_trader ON trades(trader_id, ts)", _NO_PARAMS
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trades_order ON trades(order_id)", _NO_PARAMS
        )
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
              trader_id INTEGER NOT NULL,
              code TEXT NOT NULL,
              qty INTEGER NOT NULL DEFAULT 0,
              avg_cost REAL NOT NULL DEFAULT 0,
              today_bought INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (trader_id, code)
            )""", _NO_PARAMS)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS plans (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              trader_id INTEGER NOT NULL,
              name TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active',
              scope TEXT NOT NULL,
              budget TEXT,
              position_rule TEXT,
              risk TEXT,
              schedule TEXT,
              created_at TEXT NOT NULL
            )""", _NO_PARAMS)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_plans_trader ON plans(trader_id, status)", _NO_PARAMS
        )
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS plan_entries (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              plan_id INTEGER NOT NULL,
              trigger_type TEXT NOT NULL,
              trigger_params TEXT NOT NULL,
              action TEXT NOT NULL,
              tif TEXT NOT NULL DEFAULT 'day',
              status TEXT NOT NULL DEFAULT 'waiting',
              last_triggered_on TEXT,
              created_at TEXT NOT NULL
            )""", _NO_PARAMS)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entries_plan ON plan_entries(plan_id, status)",
            _NO_PARAMS,
        )
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS equity_snapshots (
              trader_id INTEGER NOT NULL,
              date TEXT NOT NULL,
              total_equity REAL NOT NULL,
              cash REAL NOT NULL,
              PRIMARY KEY (trader_id, date)
            )""", _NO_PARAMS)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS trader_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              trader_id INTEGER,
              ts TEXT NOT NULL,
              action TEXT NOT NULL,
              detail TEXT
            )""", _NO_PARAMS)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_id ON trader_events(id)", _NO_PARAMS
        )
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS klines (
              code TEXT NOT NULL,
              date TEXT NOT NULL,
              open REAL, close REAL, high REAL, low REAL, volume INTEGER,
              PRIMARY KEY (code, date)
            )""", _NO_PARAMS)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS corporate_actions (
              code TEXT NOT NULL,
              ex_date TEXT NOT NULL,
              dividend_per_share REAL,
              bonus_ratio REAL,
              transfer_ratio REAL,
              record_date TEXT,
              source TEXT,
              PRIMARY KEY (code, ex_date)
            )""", _NO_PARAMS)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS minute_klines (
              code TEXT NOT NULL,
              date TEXT NOT NULL,
              minute TEXT NOT NULL,
              price REAL,
              volume INTEGER,
              PRIMARY KEY (code, date, minute)
            )""", _NO_PARAMS)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS idempotency_keys (
              key TEXT PRIMARY KEY,
              path TEXT NOT NULL,
              request_digest TEXT NOT NULL,
              status_code INTEGER,
              response_body TEXT,
              created_at TEXT NOT NULL
            )""", _NO_PARAMS)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            _NO_PARAMS,
        )

    # -- transactions ------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """显式事务：多语句写操作的原子性（仅在串行基座内使用）。"""
        assert self.conn is not None
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE", _NO_PARAMS)
            try:
                yield
            except BaseException:
                self.conn.execute("ROLLBACK", _NO_PARAMS)
                raise
            else:
                self.conn.execute("COMMIT", _NO_PARAMS)
