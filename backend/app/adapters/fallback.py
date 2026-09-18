"""内置锚点降级源（T06-3，FallbackProvider，02 §3.4）。"""

from __future__ import annotations

from typing import Any

from app.adapters.tencent import NormalizedQuote


class FallbackProvider:
    """三级降级链末端：以最后已知价/日K收盘为锚点输出静态快照。

    无五档、无增量量（degraded 语义）；live=False。
    """

    def __init__(self):
        self.anchors: dict[str, tuple[str, float]] = {}  # code -> (name, price)

    def seed(self, code: str, name: str, price: float) -> None:
        if price > 0:
            self.anchors[code] = (name, price)

    def snapshot(self, code: str, ts: str) -> NormalizedQuote | None:
        anchor = self.anchors.get(code)
        if anchor is None:
            return None
        name, price = anchor
        return NormalizedQuote(
            code=code, name=name, last=price, prev_close=price, open=price,
            high=price, low=price, cum_volume=0, ts=ts,
        )


class EastmoneyAdapter:
    """东财备用源（T06-1 备源）：快照价格级（无五档字段位 → 无盘口，
    撮合按降级档处理，fill_model=fallback）。"""

    KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    def __init__(self, client: Any):
        self.client = client

    def _secid(self, code: str) -> str:
        market = "1" if code.startswith(("sh", "6")) else "0"
        pure = code[2:] if code[:2] in ("sh", "sz") else code
        return f"{market}.{pure}"

    async def fetch_quotes(self, codes: list[str]) -> list[NormalizedQuote]:
        out: list[NormalizedQuote] = []
        fields = "f43,f60,f46,f44,f45,f47,f57,f58"
        for code in codes:
            try:
                resp = await self.client.get(
                    "https://push2.eastmoney.com/api/qt/stock/get",
                    params={"secid": self._secid(code), "fields": fields},
                )
                resp.raise_for_status()
                d = resp.json().get("data") or {}
                if not d or not d.get("f43"):
                    continue
                out.append(NormalizedQuote(
                    code=code, name=d.get("f58", code),
                    last=round(float(d["f43"]) / 100.0, 2),
                    prev_close=round(float(d.get("f60", 0)) / 100.0, 2),
                    open=round(float(d.get("f46", 0)) / 100.0, 2),
                    high=round(float(d.get("f44", 0)) / 100.0, 2),
                    low=round(float(d.get("f45", 0)) / 100.0, 2),
                    cum_volume=int(float(d.get("f47", 0))),
                    ts="",
                ))
            except Exception:
                continue
        return out

    async def fetch_daily_klines(self, code: str, limit: int = 320) -> list[tuple]:
        """日K兜底（C008）：push2his 前复权，量纲手（与腾讯 ifzq 一致），
        7 元组契约 [(code, date, open, close, high, low, volume)]。"""
        resp = await self.client.get(
            self.KLINE_URL,
            params={
                "secid": self._secid(code),
                "klt": "101", "fqt": "1", "lmt": limit,
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            },
        )
        resp.raise_for_status()
        rows = (resp.json().get("data") or {}).get("klines") or []
        out: list[tuple] = []
        for row in rows:
            # "date,open,close,high,low,volume,..."（fields2 顺序）
            p = row.split(",")
            out.append((code, p[0], float(p[1]), float(p[2]), float(p[3]),
                        float(p[4]), int(float(p[5]))))
        return out
