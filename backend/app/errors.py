"""统一业务错误（02 §5.1 / §5.4）。

服务层抛出 BizError(code, message, details)；API 层统一转为
`{"code", "message", "details"}` 响应。码表见 02 §5.4。
"""

from __future__ import annotations

from typing import Any


class BizError(Exception):
    def __init__(self, code: str, message: str, details: Any = None, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.status = status
