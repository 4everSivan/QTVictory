"""T01-5：串行基座——到达顺序保证与异常透传（02 §2.3 一致性）。"""

import asyncio

import pytest

from app.serial import SerialExecutor


async def test_fifo_ordering():
    ex = SerialExecutor()
    await ex.start()
    seen: list[int] = []

    async def work(i: int, delay: float) -> int:
        await asyncio.sleep(delay)
        seen.append(i)
        return i

    # 后提交的先 sleep 完成也不能先执行（串行）
    f1 = ex.submit(lambda: work(1, 0.02))
    f2 = ex.submit(lambda: work(2, 0.0))
    f3 = ex.submit(lambda: work(3, 0.0))
    assert await f1 == 1
    assert await f2 == 2
    assert await f3 == 3
    assert seen == [1, 2, 3]
    await ex.stop()


async def test_exception_passthrough_and_queue_continues():
    ex = SerialExecutor()
    await ex.start()

    async def boom() -> int:
        raise RuntimeError("boom")

    async def ok() -> int:
        return 42

    fut_bad = ex.submit(boom)
    fut_ok = ex.submit(ok)
    with pytest.raises(RuntimeError):
        await fut_bad
    assert await fut_ok == 42  # 工作协程未因前序异常中断
    await ex.stop()
