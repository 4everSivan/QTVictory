"""T02：迁移幂等、WAL、CRUD 与游标分页。"""

import sqlite3

from app.store.db import Database
from app.store.store import Store, page_result


def make_store(tmp_path, migrate=True) -> tuple[Database, Store]:
    db = Database(str(tmp_path / "t.db"))
    db.connect()
    if migrate:
        db.migrate()
    return db, Store(db)


def test_migrate_idempotent(tmp_path):
    db, _ = make_store(tmp_path, migrate=False)
    assert db.migrate() == [1]
    assert db.migrate() == []  # 重复启动不重复执行
    db.close()


def test_wal_mode(tmp_path):
    db, _ = make_store(tmp_path)
    mode = db.conn.execute("PRAGMA journal_mode").fetchone()["journal_mode"]
    assert mode.lower() == "wal"
    db.close()


def test_trader_crud_and_soft_delete(tmp_path):
    db, s = make_store(tmp_path)
    tid = s.insert_trader("测试", "manual", None, None, 100000.0, 100000.0, "2026-09-16T09:00")
    assert s.get_trader(tid)["name"] == "测试"
    assert s.count_active_traders() == 1
    s.trader_soft_delete(tid, "2026-09-16T10:00")
    assert s.get_trader(tid)["status"] == "deleted"
    assert s.count_active_traders() == 0
    assert s.list_traders() == []                 # 默认不含软删
    assert len(s.list_traders(include_deleted=True)) == 1
    s.trader_hard_delete(tid)
    assert s.get_trader(tid) is None
    db.close()


def test_order_lifecycle_updates(tmp_path):
    db, s = make_store(tmp_path)
    oid = s.insert_order({
        "trader_id": 1, "origin": "manual", "side": "buy", "type": "limit",
        "code": "600519", "price": 10.0, "qty": 500, "status": "wait",
        "frozen_amount": 5010.0, "created_at": "2026-09-16T09:31", "trading_date": "2026-09-16",
    })
    s.order_apply_fill(oid, 200, 10.0, 3006.0, "l2", "partial", None)
    o = s.get_order(oid)
    assert o["filled_qty"] == 200 and o["status"] == "partial"
    assert o["frozen_amount"] == 3006.0
    # 到达顺序：active orders 按 created_at, id
    s.insert_order({
        "trader_id": 1, "origin": "manual", "side": "buy", "type": "limit",
        "code": "600519", "price": 10.0, "qty": 100, "status": "wait",
        "frozen_amount": 1002.0, "created_at": "2026-09-16T09:32", "trading_date": "2026-09-16",
    })
    act = s.active_orders_for_code("600519")
    assert [a["id"] for a in act] == [oid, oid + 1]
    # 日终撤单
    cancelled = s.cancel_day_orders("2026-09-16")
    assert len(cancelled) == 2 and s.get_order(oid)["status"] == "cancel"
    db.close()


def test_pagination_helper(tmp_path):
    db, s = make_store(tmp_path)
    for i in range(5):
        s.insert_event(1, f"2026-09-16T09:0{i}", "tick", None)
    rows = s.events_feed(cursor=0, limit=3)
    page = page_result(rows, 3)
    assert len(page["data"]) == 3 and page["nextCursor"] == 3
    rows2 = s.events_feed(cursor=page["nextCursor"], limit=3)
    page2 = page_result(rows2, 3)
    assert len(page2["data"]) == 2 and page2["nextCursor"] is None  # 尾页
    db.close()


def test_json_roundtrip(tmp_path):
    import json

    db, s = make_store(tmp_path)
    params = {"fast": 5, "slow": 20, "note": "中文"}
    tid = s.insert_trader("策略", "strategy", "trend", json.dumps(params), 1.0, 1.0, "ts")
    row = s.get_trader(tid)
    assert json.loads(row["strategy_params"]) == params  # 往返无损
    db.close()
