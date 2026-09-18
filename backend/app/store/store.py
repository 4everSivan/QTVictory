"""Store 访问层（T02-4/T02-5）。

- 全部语句为**字面量 + ? 占位符**，动态值一律走参数，绝不拼接；
- 方法为同步函数，服务层经 asyncio.to_thread 调用；写操作在
  SerialExecutor 串行基座内执行（单写者纪律）；
- 游标分页：cursor = 上一页最后一条的 id，`WHERE id > ? LIMIT ?`，
  多取一条判断是否有下一页（nextCursor）。
"""

from __future__ import annotations

from typing import Any


class Store:
    def __init__(self, db):
        self.db = db

    # -- sync_state --------------------------------------------------------

    def get_state(self, key: str) -> str | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT value FROM sync_state WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "INSERT INTO sync_state(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self.db.conn.commit()

    # -- traders (T05) -----------------------------------------------------

    def insert_trader(
        self,
        name: str,
        mode: str,
        strategy_type: str | None,
        strategy_params: str | None,
        init_cash: float,
        cash: float,
        created_at: str,
    ) -> int:
        with self.db.lock:
            cur = self.db.conn.execute(
                "INSERT INTO traders(name, mode, strategy_type, strategy_params, "
                "status, init_cash, cash, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (name, mode, strategy_type, strategy_params, "running", init_cash, cash, created_at),
            )
            self.db.conn.commit()
            return cur.lastrowid or 0

    def get_trader(self, trader_id: int) -> dict[str, Any] | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT * FROM traders WHERE id = ?", (trader_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_traders(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        with self.db.lock:
            if include_deleted:
                rows = self.db.conn.execute(
                    "SELECT * FROM traders ORDER BY id"
                ).fetchall()
            else:
                rows = self.db.conn.execute(
                    "SELECT * FROM traders WHERE status != ? ORDER BY id", ("deleted",)
                ).fetchall()
        return [dict(r) for r in rows]

    def count_active_traders(self) -> int:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT COUNT(*) AS n FROM traders WHERE status != ?", ("deleted",)
            ).fetchone()
        return int(row["n"])

    def trader_set_status(self, trader_id: int, status: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE traders SET status = ? WHERE id = ?", (status, trader_id)
            )
            self.db.conn.commit()

    def trader_set_cash(self, trader_id: int, cash: float) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE traders SET cash = ? WHERE id = ?", (cash, trader_id)
            )
            self.db.conn.commit()

    def trader_set_capital(self, trader_id: int, cash: float, init_cash: float) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE traders SET cash = ?, init_cash = ? WHERE id = ?",
                (cash, init_cash, trader_id),
            )
            self.db.conn.commit()

    def trader_set_name(self, trader_id: int, name: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE traders SET name = ? WHERE id = ?", (name, trader_id)
            )
            self.db.conn.commit()

    def trader_set_strategy(self, trader_id: int, stype: str, params: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE traders SET strategy_type = ?, strategy_params = ? WHERE id = ?",
                (stype, params, trader_id),
            )
            self.db.conn.commit()

    def trader_reset(self, trader_id: int, init_cash: float) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE traders SET cash = ?, init_cash = ? WHERE id = ?",
                (init_cash, init_cash, trader_id),
            )
            self.db.conn.execute("DELETE FROM positions WHERE trader_id = ?", (trader_id,))
            self.db.conn.commit()

    def trader_soft_delete(self, trader_id: int, deleted_at: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE traders SET status = ?, deleted_at = ? WHERE id = ?",
                ("deleted", deleted_at, trader_id),
            )
            self.db.conn.commit()

    def trader_hard_delete(self, trader_id: int) -> None:
        with self.db.lock:
            for stmt in (
                "DELETE FROM traders WHERE id = ?",
                "DELETE FROM positions WHERE trader_id = ?",
                "DELETE FROM orders WHERE trader_id = ?",
                "DELETE FROM trades WHERE trader_id = ?",
                "DELETE FROM equity_snapshots WHERE trader_id = ?",
                "DELETE FROM trader_events WHERE trader_id = ?",
            ):
                self.db.conn.execute(stmt, (trader_id,))
            self.db.conn.execute(
                "DELETE FROM plan_entries WHERE plan_id IN (SELECT id FROM plans WHERE trader_id = ?)",
                (trader_id,),
            )
            self.db.conn.execute("DELETE FROM plans WHERE trader_id = ?", (trader_id,))
            self.db.conn.commit()

    # -- trader_events -----------------------------------------------------

    def insert_event(self, trader_id: int | None, ts: str, action: str, detail: str | None) -> int:
        with self.db.lock:
            cur = self.db.conn.execute(
                "INSERT INTO trader_events(trader_id, ts, action, detail) VALUES(?, ?, ?, ?)",
                (trader_id, ts, action, detail),
            )
            self.db.conn.commit()
            return cur.lastrowid or 0

    def events_feed(self, cursor: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT * FROM trader_events WHERE id > ? ORDER BY id LIMIT ?",
                (cursor, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- orders ------------------------------------------------------------

    def insert_order(self, o: dict[str, Any]) -> int:
        with self.db.lock:
            cur = self.db.conn.execute(
                "INSERT INTO orders(trader_id, origin, plan_entry_id, client_order_id, side, "
                "type, market_type, code, price, qty, filled_qty, avg_filled_price, "
                "frozen_amount, fill_model, status, created_at, trading_date) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    o["trader_id"], o["origin"], o.get("plan_entry_id"), o.get("client_order_id"),
                    o["side"], o["type"], o.get("market_type"), o["code"], o.get("price"),
                    o["qty"], 0, None, o.get("frozen_amount"), o.get("fill_model"),
                    o["status"], o["created_at"], o["trading_date"],
                ),
            )
            self.db.conn.commit()
            return cur.lastrowid or 0

    def get_order(self, order_id: int) -> dict[str, Any] | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT * FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_order_by_client_id(self, trader_id: int, client_order_id: str) -> dict[str, Any] | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT * FROM orders WHERE trader_id = ? AND client_order_id = ? ORDER BY id LIMIT 1",
                (trader_id, client_order_id),
            ).fetchone()
        return dict(row) if row else None

    def active_orders_for_code(self, code: str) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT * FROM orders WHERE code = ? AND status IN (?, ?) ORDER BY created_at, id",
                (code, "wait", "partial"),
            ).fetchall()
        return [dict(r) for r in rows]

    def orders_feed(
        self, trader_id: int, cursor: int = 0, limit: int = 50, active_only: bool = False
    ) -> list[dict[str, Any]]:
        with self.db.lock:
            if active_only:
                rows = self.db.conn.execute(
                    "SELECT * FROM orders WHERE trader_id = ? AND id > ? AND status IN (?, ?) "
                    "ORDER BY id LIMIT ?",
                    (trader_id, cursor, "wait", "partial", limit),
                ).fetchall()
            else:
                rows = self.db.conn.execute(
                    "SELECT * FROM orders WHERE trader_id = ? AND id > ? ORDER BY id LIMIT ?",
                    (trader_id, cursor, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    def order_apply_fill(
        self,
        order_id: int,
        filled_qty: int,
        avg_filled_price: float | None,
        frozen_amount: float | None,
        fill_model: str | None,
        status: str,
        filled_at: str | None,
    ) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE orders SET filled_qty = ?, avg_filled_price = ?, frozen_amount = ?, "
                "fill_model = ?, status = ?, filled_at = ? WHERE id = ?",
                (filled_qty, avg_filled_price, frozen_amount, fill_model, status, filled_at, order_id),
            )
            self.db.conn.commit()

    def order_set_status(self, order_id: int, status: str, frozen_amount: float | None = None) -> None:
        with self.db.lock:
            if frozen_amount is None:
                self.db.conn.execute(
                    "UPDATE orders SET status = ? WHERE id = ?", (status, order_id)
                )
            else:
                self.db.conn.execute(
                    "UPDATE orders SET status = ?, frozen_amount = ? WHERE id = ?",
                    (status, frozen_amount, order_id),
                )
            self.db.conn.commit()

    def cancel_day_orders(self, trading_date: str) -> list[dict[str, Any]]:
        """日终撤单：撤当日全部 wait/partial 订单并解冻；返回被撤订单。"""
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT * FROM orders WHERE trading_date = ? AND status IN (?, ?)",
                (trading_date, "wait", "partial"),
            ).fetchall()
            self.db.conn.execute(
                "UPDATE orders SET status = ?, frozen_amount = ? "
                "WHERE trading_date = ? AND status IN (?, ?)",
                ("cancel", None, trading_date, "wait", "partial"),
            )
            self.db.conn.commit()
        return [dict(r) for r in rows]

    # -- trades ------------------------------------------------------------

    def insert_trade(self, t: dict[str, Any]) -> int:
        with self.db.lock:
            cur = self.db.conn.execute(
                "INSERT INTO trades(order_id, trader_id, code, side, price, qty, amount, "
                "commission, stamp_tax, transfer_fee, realized_pnl, origin, ts, trading_date) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    t["order_id"], t["trader_id"], t["code"], t["side"], t["price"], t["qty"],
                    t["amount"], t["commission"], t["stamp_tax"], t["transfer_fee"],
                    t.get("realized_pnl"), t["origin"], t["ts"], t["trading_date"],
                ),
            )
            self.db.conn.commit()
            return cur.lastrowid or 0

    def trades_feed(self, trader_id: int, cursor: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT * FROM trades WHERE trader_id = ? AND id > ? ORDER BY id LIMIT ?",
                (trader_id, cursor, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def trades_for_order(self, order_id: int) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT * FROM trades WHERE order_id = ? ORDER BY id", (order_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def active_orders_by_plan(self, plan_id: int) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT o.* FROM orders o JOIN plan_entries e ON o.plan_entry_id = e.id "
                "WHERE e.plan_id = ? AND o.status IN (?, ?) ORDER BY o.id",
                (plan_id, "wait", "partial"),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- positions ---------------------------------------------------------

    def get_position(self, trader_id: int, code: str) -> dict[str, Any] | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT * FROM positions WHERE trader_id = ? AND code = ?",
                (trader_id, code),
            ).fetchone()
        return dict(row) if row else None

    def positions_for_trader(self, trader_id: int) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT * FROM positions WHERE trader_id = ? ORDER BY code", (trader_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def positions_all(self) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT * FROM positions ORDER BY trader_id, code"
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert_position(
        self, trader_id: int, code: str, qty: int, avg_cost: float, today_bought: int
    ) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "INSERT INTO positions(trader_id, code, qty, avg_cost, today_bought) "
                "VALUES(?, ?, ?, ?, ?) "
                "ON CONFLICT(trader_id, code) DO UPDATE SET qty = excluded.qty, "
                "avg_cost = excluded.avg_cost, today_bought = excluded.today_bought",
                (trader_id, code, qty, avg_cost, today_bought),
            )
            self.db.conn.commit()

    def delete_position(self, trader_id: int, code: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "DELETE FROM positions WHERE trader_id = ? AND code = ?", (trader_id, code)
            )
            self.db.conn.commit()

    def t1_reset_all(self) -> None:
        with self.db.lock:
            self.db.conn.execute("UPDATE positions SET today_bought = 0")
            self.db.conn.commit()

    # -- plans / entries ---------------------------------------------------

    def insert_plan(
        self,
        trader_id: int,
        name: str,
        scope: str,
        budget: str | None,
        position_rule: str | None,
        risk: str | None,
        schedule: str | None,
        created_at: str,
    ) -> int:
        with self.db.lock:
            cur = self.db.conn.execute(
                "INSERT INTO plans(trader_id, name, status, scope, budget, position_rule, "
                "risk, schedule, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (trader_id, name, "active", scope, budget, position_rule, risk, schedule, created_at),
            )
            self.db.conn.commit()
            return cur.lastrowid or 0

    def get_plan(self, plan_id: int) -> dict[str, Any] | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT * FROM plans WHERE id = ?", (plan_id,)
            ).fetchone()
        return dict(row) if row else None

    def plans_for_trader(self, trader_id: int, active_only: bool = False) -> list[dict[str, Any]]:
        with self.db.lock:
            if active_only:
                rows = self.db.conn.execute(
                    "SELECT * FROM plans WHERE trader_id = ? AND status = ? ORDER BY id",
                    (trader_id, "active"),
                ).fetchall()
            else:
                rows = self.db.conn.execute(
                    "SELECT * FROM plans WHERE trader_id = ? ORDER BY id", (trader_id,)
                ).fetchall()
        return [dict(r) for r in rows]

    def plan_set_status(self, plan_id: int, status: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE plans SET status = ? WHERE id = ?", (status, plan_id)
            )
            self.db.conn.commit()

    def update_plan_risk(self, plan_id: int, risk_json: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE plans SET risk = ? WHERE id = ?", (risk_json, plan_id)
            )
            self.db.conn.commit()

    def plan_delete(self, plan_id: int) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "DELETE FROM plan_entries WHERE plan_id = ?", (plan_id,)
            )
            self.db.conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
            self.db.conn.commit()

    def insert_entry(
        self,
        plan_id: int,
        trigger_type: str,
        trigger_params: str,
        action: str,
        tif: str,
        created_at: str,
    ) -> int:
        with self.db.lock:
            cur = self.db.conn.execute(
                "INSERT INTO plan_entries(plan_id, trigger_type, trigger_params, action, tif, "
                "status, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (plan_id, trigger_type, trigger_params, action, tif, "waiting", created_at),
            )
            self.db.conn.commit()
            return cur.lastrowid or 0

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT * FROM plan_entries WHERE id = ?", (entry_id,)
            ).fetchone()
        return dict(row) if row else None

    def entries_for_plan(self, plan_id: int) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT * FROM plan_entries WHERE plan_id = ? ORDER BY id", (plan_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def active_entries(self) -> list[dict[str, Any]]:
        """全部生效条件单（所属计划 active）。"""
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT e.* FROM plan_entries e JOIN plans p ON e.plan_id = p.id "
                "WHERE e.status = ? AND p.status = ? ORDER BY e.id",
                ("waiting", "active"),
            ).fetchall()
        return [dict(r) for r in rows]

    def entry_set_status(self, entry_id: int, status: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE plan_entries SET status = ? WHERE id = ?", (status, entry_id)
            )
            self.db.conn.commit()

    def entry_set_triggered(self, entry_id: int, triggered_on: str, status: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE plan_entries SET last_triggered_on = ?, status = ? WHERE id = ?",
                (triggered_on, status, entry_id),
            )
            self.db.conn.commit()

    def entry_delete(self, entry_id: int) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "DELETE FROM plan_entries WHERE id = ?", (entry_id,)
            )
            self.db.conn.commit()

    def expire_day_entries(self, trading_date: str) -> int:
        """日切：tif=day 且未触发的条件单过期；gtc 保持 waiting（续期）。"""
        with self.db.lock:
            cur = self.db.conn.execute(
                "UPDATE plan_entries SET status = ? WHERE status = ? AND tif = ?",
                ("expired", "waiting", "day"),
            )
            self.db.conn.commit()
            return cur.rowcount or 0

    # -- equity snapshots --------------------------------------------------

    def upsert_snapshot(self, trader_id: int, date: str, total_equity: float, cash: float) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "INSERT INTO equity_snapshots(trader_id, date, total_equity, cash) "
                "VALUES(?, ?, ?, ?) "
                "ON CONFLICT(trader_id, date) DO UPDATE SET total_equity = excluded.total_equity, "
                "cash = excluded.cash",
                (trader_id, date, total_equity, cash),
            )
            self.db.conn.commit()

    def snapshots_for_trader(self, trader_id: int) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT * FROM equity_snapshots WHERE trader_id = ? ORDER BY date",
                (trader_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- klines / minute / corporate --------------------------------------

    def upsert_klines(self, rows: list[tuple]) -> None:
        with self.db.lock:
            self.db.conn.executemany(
                "INSERT INTO klines(code, date, open, close, high, low, volume) "
                "VALUES(?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(code, date) DO UPDATE SET open = excluded.open, "
                "close = excluded.close, high = excluded.high, low = excluded.low, "
                "volume = excluded.volume",
                rows,
            )
            self.db.conn.commit()

    def klines_for(self, code: str, limit: int = 250) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT * FROM klines WHERE code = ? ORDER BY date DESC LIMIT ?",
                (code, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def upsert_minutes(self, rows: list[tuple]) -> None:
        with self.db.lock:
            self.db.conn.executemany(
                "INSERT INTO minute_klines(code, date, minute, price, volume) "
                "VALUES(?, ?, ?, ?, ?) "
                "ON CONFLICT(code, date, minute) DO UPDATE SET price = excluded.price, "
                "volume = excluded.volume",
                rows,
            )
            self.db.conn.commit()

    def minutes_for(self, code: str, date: str) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT * FROM minute_klines WHERE code = ? AND date = ? ORDER BY minute",
                (code, date),
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert_actions(self, rows: list[tuple]) -> None:
        with self.db.lock:
            self.db.conn.executemany(
                "INSERT INTO corporate_actions(code, ex_date, dividend_per_share, bonus_ratio, "
                "transfer_ratio, record_date, source) VALUES(?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(code, ex_date) DO UPDATE SET dividend_per_share = excluded.dividend_per_share, "
                "bonus_ratio = excluded.bonus_ratio, transfer_ratio = excluded.transfer_ratio, "
                "record_date = excluded.record_date, source = excluded.source",
                rows,
            )
            self.db.conn.commit()

    def actions_for_ex_date(self, ex_date: str) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT * FROM corporate_actions WHERE ex_date = ? ORDER BY code", (ex_date,)
            ).fetchall()
        return [dict(r) for r in rows]

    # -- audit / idempotency ----------------------------------------------

    def insert_audit(
        self, ts: str, method: str, path: str, target: str | None,
        payload_digest: str | None, status_code: int,
    ) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "INSERT INTO audit_log(ts, actor, method, path, target, payload_digest, status_code) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (ts, "observer", method, path, target, payload_digest, status_code),
            )
            self.db.conn.commit()

    def audit_feed(self, cursor: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT * FROM audit_log WHERE id > ? ORDER BY id LIMIT ?", (cursor, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def idem_get(self, key: str) -> dict[str, Any] | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT * FROM idempotency_keys WHERE key = ?", (key,)
            ).fetchone()
        return dict(row) if row else None

    def idem_put(
        self, key: str, path: str, digest: str, status_code: int, body: str, ts: str
    ) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "INSERT INTO idempotency_keys(key, path, request_digest, status_code, "
                "response_body, created_at) VALUES(?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(key) DO NOTHING",
                (key, path, digest, status_code, body, ts),
            )
            self.db.conn.commit()


def page_result(rows: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    """游标分页响应组装：页满（== limit）即给出 nextCursor，短页为尾页。"""
    next_cursor = rows[-1]["id"] if len(rows) == limit and limit > 0 else None
    return {"data": rows, "nextCursor": next_cursor}
