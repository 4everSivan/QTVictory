"""时钟抽象（T01 基建）。

生产用真实时钟；测试用 FakeClock 推进时间（会话状态机/日切测试的关键注入点）。
"""

from __future__ import annotations

from datetime import datetime, timedelta


class Clock:
    def now(self) -> datetime:
        return datetime.now()


class FakeClock(Clock):
    def __init__(self, start: datetime):
        self._now = start

    def now(self) -> datetime:
        return self._now

    def set(self, value: datetime) -> None:
        self._now = value

    def advance(self, **kwargs: float) -> None:
        self._now = self._now + timedelta(**kwargs)
