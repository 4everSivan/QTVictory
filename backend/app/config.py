"""配置模块（T01-2）。

落实 02 §6.10 配置项全表：全部经 QTV_* 环境变量注入，默认值与设计一致。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """QTV_* 环境变量集合（02 §6.10）。"""

    model_config = SettingsConfigDict(extra="ignore")

    qtv_port: int = Field(default=8787, description="监听端口")
    qtv_db: str = Field(default="data/qtvictory.db", description="SQLite 路径（WAL）")
    qtv_poll_sec: int = Field(default=3, ge=1, description="连续竞价轮询间隔（秒）")
    qtv_api_key: str = Field(default="", description="观察员凭证；空 = 仅本机免鉴权")
    qtv_public_read: bool = Field(default=False, description="鉴权模式下放行只读端点")
    qtv_rate_limit: int = Field(default=20, ge=1, description="每秒请求上限（令牌桶）")
    qtv_volume_participation: float = Field(
        default=0.25, gt=0, le=1, description="单标的每 tick 成交量占真实成交量比例上限"
    )
    qtv_dividend_tax: float = Field(default=0.10, ge=0, le=1, description="现金分红统一税率")
    qtv_max_traders: int = Field(default=64, ge=1, description="交易员数量上限")
    qtv_cors: str = Field(default="http://localhost:4312", description="允许来源")

    @field_validator("qtv_port")
    @classmethod
    def _port_range(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("qtv_port must be in [1, 65535]")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
