"""WebSocket 网关（T10，02 §5.3）。

订阅式 /ws：{"op":"sub","topics":[...]}；topic 集：quotes / traders /
trader:{id} / plans / events。traders 排行节流 2s；心跳 ping/pong；
断线由客户端 REST 全量拉回再续订（服务端无会话状态）。
不做 Webhook（Q6 决议）。
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import time

from starlette.websockets import WebSocket, WebSocketDisconnect

STATIC_TOPICS = ("quotes", "traders", "plans", "events")
TRADER_TOPIC_PREFIX = "trader:"
TRADERS_THROTTLE_SEC = 2.0


class WSConn:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.topics: set[str] = set()
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=512)
        self.alive = True

    def offer(self, topic: str, data) -> None:
        if not self.alive or topic not in self.topics:
            return
        with contextlib.suppress(asyncio.QueueFull):
            self.queue.put_nowait((topic, data))


class WSHub:
    def __init__(self, ctx):
        self.ctx = ctx
        self.conns: set[WSConn] = set()
        self._dynamic_subscribed: set[str] = set()
        self._traders_latest = None
        self._traders_last_sent = 0.0
        for topic in STATIC_TOPICS:
            ctx.bus.subscribe(topic, self._on_bus)

    def _on_bus(self, topic: str, data) -> None:
        if topic == "traders":
            self._traders_latest = data
            now = time.monotonic()
            if now - self._traders_last_sent >= TRADERS_THROTTLE_SEC:
                self._traders_last_sent = now
                for conn in self.conns:
                    conn.offer(topic, data)
            return
        for conn in self.conns:
            conn.offer(topic, data)

    def ensure_dynamic(self, topic: str) -> None:
        """trader:{id} 按需订阅总线（首个订阅者时挂回调）。"""
        if topic in self._dynamic_subscribed:
            return
        self.ctx.bus.subscribe(topic, self._on_bus)
        self._dynamic_subscribed.add(topic)

    async def sender(self, conn: WSConn) -> None:
        while conn.alive:
            topic, data = await conn.queue.get()
            await conn.ws.send_json({"topic": topic, "data": data})


def _authorized(ctx, websocket: WebSocket) -> bool:
    api_key = ctx.settings.qtv_api_key
    if not api_key:
        return True
    provided = websocket.query_params.get("key", "")
    if hmac.compare_digest(provided.encode(), api_key.encode()):
        return True
    protocol = websocket.headers.get("sec-websocket-protocol", "")
    return bool(protocol) and hmac.compare_digest(protocol.encode(), api_key.encode())


async def ws_endpoint(websocket: WebSocket) -> None:
    ctx = websocket.app.state.ctx
    hub: WSHub = websocket.app.state.ws_hub
    if not _authorized(ctx, websocket):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    conn = WSConn(websocket)
    hub.conns.add(conn)
    sender_task = asyncio.create_task(hub.sender(conn))
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                await websocket.send_json({"topic": "error",
                                           "data": {"message": "invalid json"}})
                continue
            op, topics = msg.get("op"), msg.get("topics", [])
            if op not in ("sub", "unsub"):
                await websocket.send_json({"topic": "error",
                                           "data": {"message": f"unknown op {op}"}})
                continue
            valid: list[str] = []
            for t in topics:
                if t in STATIC_TOPICS or (
                    t.startswith(TRADER_TOPIC_PREFIX) and t[len(TRADER_TOPIC_PREFIX):].isdigit()
                ):
                    valid.append(t)
            if op == "sub":
                conn.topics.update(valid)
                for t in valid:
                    if t.startswith(TRADER_TOPIC_PREFIX):
                        hub.ensure_dynamic(t)
            else:
                conn.topics.difference_update(valid)
            await websocket.send_json({"topic": "ack", "data": {"op": op, "topics": sorted(conn.topics)}})
    except WebSocketDisconnect:
        pass
    finally:
        conn.alive = False
        hub.conns.discard(conn)
        sender_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender_task
