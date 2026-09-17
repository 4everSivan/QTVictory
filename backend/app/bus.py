"""进程内事件总线（T06/T10 基建）。

topic 集合对齐 02 §5.3：quotes / traders / trader:{id} / plans / events。
WS 网关订阅总线；服务层发布。回调在发布方协程内同步执行（轻量），
重活（DB 写）不放在回调里。
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

Handler = Callable[[str, Any], None]


class Bus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = {}

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs.setdefault(topic, []).append(handler)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        subs = self._subs.get(topic, [])
        if handler in subs:
            subs.remove(handler)

    def publish(self, topic: str, data: Any) -> None:
        for handler in list(self._subs.get(topic, [])):
            try:
                handler(topic, data)
            except Exception:  # 回调异常不阻断发布方
                pass


def fire_and_forget(coro: Awaitable[Any]) -> None:
    """安全调度后台协程（无引用保活需求时使用）。"""
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        pass
