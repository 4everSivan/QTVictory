"""API 请求模型（T09-1，pydantic 契约 → OpenAPI 全覆盖）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TraderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    mode: Literal["manual", "strategy"] = "manual"
    template: str | None = None
    params: dict[str, Any] | None = None
    strategy: dict[str, Any] | None = None
    initCash: float = Field(default=1_000_000, gt=0)
    plan: dict[str, Any] | None = None


class TraderPatch(BaseModel):
    name: str | None = None
    status: Literal["running", "paused", "closed"] | None = None
    strategy_params: dict[str, Any] | None = None


class CapitalIn(BaseModel):
    amount: float = Field(gt=0)


class OrderIn(BaseModel):
    side: Literal["buy", "sell"]
    type: Literal["limit", "market"] = "limit"
    code: str = Field(min_length=3, max_length=12)
    price: float | None = Field(default=None, gt=0)
    qty: int = Field(gt=0)
    marketType: Literal["best5_cancel", "opponent_best"] | None = None
    clientOrderId: str | None = Field(default=None, max_length=64)


class PlanCreate(BaseModel):
    name: str = "计划"
    scope: dict[str, Any]
    budget: dict[str, Any] | None = None
    positionRule: dict[str, Any] | None = None
    risk: dict[str, Any] | None = None
    schedule: dict[str, Any] | None = None


class PlanPatch(BaseModel):
    name: str | None = None
    status: Literal["active", "paused", "done"] | None = None
    risk: dict[str, Any] | None = None


class EntryCreate(BaseModel):
    triggerType: Literal["price_cross", "pct_change", "time", "ma_cross"]
    triggerParams: dict[str, Any] = Field(default_factory=dict)
    action: dict[str, Any]
    tif: Literal["day", "gtc"] = "day"


class WatchlistBatchIn(BaseModel):
    add: list[str] = Field(default_factory=list, max_length=200)
    remove: list[str] = Field(default_factory=list, max_length=200)
