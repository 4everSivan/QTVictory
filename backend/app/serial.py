"""单一事件循环串行化基座（T01-5）。

02 §2.3 一致性：订单/计划触发/观察员操作在同一事件循环串行化。
全部状态变更经 `submit()` 进入单一工作协程按到达顺序执行；
工厂可为同步或异步（返回 awaitable 则等待）；
返回值/异常透传给提交方。
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")

_SENTINEL = object()


class SerialExecutor:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[Callable[[], Any], asyncio.Future]] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._closed = False

    async def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run(), name="serial-executor")

    async def stop(self) -> None:
        self._closed = True
        await self._queue.join()
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    def submit(self, fn: Callable[[], Any]) -> asyncio.Future:
        """提交一个工厂（同步或异步）；执行严格按提交顺序（FIFO）。"""
        if self._closed:
            raise RuntimeError("serial executor is stopped")
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._queue.put_nowait((fn, fut))
        return fut

    async def run(self, fn: Callable[[], Any]) -> Any:
        return await self.submit(fn)

    async def _run(self) -> None:
        while True:
            fn, fut = await self._queue.get()
            try:
                if fut.cancelled():
                    fn()  # 丢弃结果
                else:
                    result = fn()
                    if inspect.isawaitable(result):
                        result = await result
                    fut.set_result(_SENTINEL if result is None else result)
            except asyncio.CancelledError:
                if not fut.done():
                    fut.cancel()
                raise
            except BaseException as exc:  # 透传给提交方，不中断工作协程
                if not fut.done():
                    fut.set_exception(exc)
            finally:
                self._queue.task_done()
