"""新浪行情适配器（C008，02 §3.4）。

- 快照：hq.sinajs.cn 批量接口（https 强制 Referer 校验，缺失即 403），GBK 编码；
- 字段位（0 起）：0 名称 1 今开 2 昨收 3 现价 4 最高 5 最低 8 成交量(股)
  9 成交额(元)；10–19 买一~买五（量/价交替），20–29 卖一~卖五（量/价交替）；
- 量纲：成交量与五档量均为股（与腾讯归一后口径一致，无需手换算）；
  成交额 ÷10000 归一为万；指数无盘口（字段为 0）按价量非正自然跳过；
- 解析为纯函数（fixtures 可测），网络请求独立封装。
"""

from __future__ import annotations

from typing import Any

from app.adapters.tencent import NormalizedQuote

QUOTE_URL = "https://hq.sinajs.cn/list="
REFERER = "https://finance.sina.com.cn"

_F_NAME, _F_OPEN, _F_PREV, _F_LAST = 0, 1, 2, 3
_F_HIGH, _F_LOW, _F_VOL, _F_AMOUNT = 4, 5, 8, 9
_F_BID1, _F_ASK1 = 10, 20
_F_TIME = 31


def _num(s: str) -> float:
    s = s.strip()
    return float(s) if s else 0.0


def _levels(fields: list[str], start: int) -> list[tuple[float, int]]:
    """五档（量/价交替，量纲：股）。"""
    out: list[tuple[float, int]] = []
    for i in range(start, start + 10, 2):
        if i + 1 >= len(fields):
            break
        vol, price = _num(fields[i]), _num(fields[i + 1])
        if price <= 0 or vol <= 0:
            continue
        out.append((round(price, 2), int(vol)))
    return out


def parse_sina_payload(text: str) -> list[NormalizedQuote]:
    """解析 `var hq_str_sh600519="名称,今开,...";` 批量响应。"""
    quotes: list[NormalizedQuote] = []
    for line in text.splitlines():
        line = line.strip().rstrip(";")
        if "=" not in line or "," not in line:
            continue
        head, body = line.split("=", 1)
        code = head.strip().removeprefix("var hq_str_").strip()
        fields = body.strip().strip('"').split(",")
        if len(fields) <= _F_TIME or not code:
            continue
        last = _num(fields[_F_LAST])
        suspended = last <= 0 and _num(fields[_F_OPEN]) <= 0
        if suspended:
            quotes.append(NormalizedQuote(
                code=code, name=fields[_F_NAME], last=0.0,
                prev_close=_num(fields[_F_PREV]), open=_num(fields[_F_OPEN]),
                high=0.0, low=0.0, cum_volume=0, ts=fields[_F_TIME],
            ))
            continue
        quotes.append(NormalizedQuote(
            code=code, name=fields[_F_NAME], last=round(last, 2),
            prev_close=round(_num(fields[_F_PREV]), 2),
            open=round(_num(fields[_F_OPEN]), 2),
            high=round(_num(fields[_F_HIGH]), 2), low=round(_num(fields[_F_LOW]), 2),
            cum_volume=int(_num(fields[_F_VOL])),
            bids=_levels(fields, _F_BID1), asks=_levels(fields, _F_ASK1),
            ts=fields[_F_TIME],
            amount_wan=round(_num(fields[_F_AMOUNT]) / 10000.0, 2),
        ))
    return quotes


class SinaAdapter:
    """网络请求封装（解析逻辑在纯函数中，可离线测试）。"""

    def __init__(self, client: Any):
        self.client = client  # httpx.AsyncClient

    async def fetch_quotes(self, codes: list[str]) -> list[NormalizedQuote]:
        if not codes:
            return []
        resp = await self.client.get(
            QUOTE_URL + ",".join(codes),
            headers={"Referer": REFERER},
        )
        resp.raise_for_status()
        return parse_sina_payload(resp.content.decode("gbk", errors="replace"))
