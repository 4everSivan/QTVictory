"""腾讯行情适配器（T06-1，02 §3.4 / §6.5）。

- 快照：qt.gtimg.cn 批量接口，GBK 编码，`~` 分隔字段位映射；
  字段 9–28 为五档买卖盘（价/量交替，量单位为手）；
- 成交量归一为股：非 688 字段为手（×100），科创板字段为股
  （设计口径"688 成交量 ÷100 归一"：先统一 ×100 再 ÷100，即保持原值）；
- 解析为纯函数（fixtures 可测），网络请求独立封装。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

QUOTE_URL = "https://qt.gtimg.cn/q="
QUOTE_URL_HTTP = "http://qt.gtimg.cn/q="
KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
SUGGEST_URL = "https://smartbox.gtimg.cn/s3/"

# smartbox 类别归一（T23-4）：GP-A/GP-B→stock、ZS→index，其余小写透传（ETF/LOF/…）
_SUGGEST_KINDS = {"gp-a": "stock", "gp-b": "stock", "zs": "index"}

# smartbox hint 名称字段以字面 \uXXXX 转义承载中文（C009），还原为 Unicode 字符；
# 无转义的直编码中文原样通过
_UESC = re.compile(r"\\u([0-9a-fA-F]{4})")


def _unescape_name(s: str) -> str:
    return _UESC.sub(lambda m: chr(int(m.group(1), 16)), s)

# 字段位（0 起）：3 现价 4 昨收 5 今开 6 成交量 30 时间 33 最高 34 最低 47 涨停 48 跌停
# 9–18 买一~买五（价/量交替），19–28 卖一~卖五（价/量交替），36 成交量(手) 37 成交额(万)
_F_LAST, _F_PREV, _F_OPEN = 3, 4, 5
_F_VOL, _F_TIME, _F_HIGH, _F_LOW = 6, 30, 33, 34
_F_BID1, _F_ASK1 = 9, 19


@dataclass
class NormalizedQuote:
    code: str
    name: str
    last: float
    prev_close: float
    open: float
    high: float
    low: float
    cum_volume: int          # 股
    bids: list[tuple[float, int]] = field(default_factory=list)   # (价, 股) 买一在前
    asks: list[tuple[float, int]] = field(default_factory=list)   # 卖一在前
    ts: str = ""             # 原始时间戳 HH:MM:SS
    amount_wan: float = 0.0


def _num(s: str) -> float:
    s = s.strip()
    return float(s) if s else 0.0


def _to_shares(code: str, hand: float) -> int:
    """量纲归一为股：手×100；科创板原值为股（÷100 归一后再 ×100 还原为股）。"""
    pure = code[2:] if code[:2] in ("sh", "sz", "bj") and len(code) > 6 else code
    return int(hand) if pure.startswith("688") else int(hand * 100)


def _levels(fields: list[str], start: int, code: str) -> list[tuple[float, int]]:
    out: list[tuple[float, int]] = []
    for i in range(start, start + 10, 2):
        if i + 1 >= len(fields):
            break
        price, vol = _num(fields[i]), _num(fields[i + 1])
        if price <= 0 or vol <= 0:
            continue
        out.append((round(price, 2), _to_shares(code, vol)))
    return out


def parse_quote_payload(text: str) -> list[NormalizedQuote]:
    """解析 `v_sh600519="1~名称~代码~...";` 批量响应。"""
    quotes: list[NormalizedQuote] = []
    for line in text.splitlines():
        line = line.strip().rstrip(";")
        if "=" not in line or "~" not in line:
            continue
        head, body = line.split("=", 1)
        code = head.strip().removeprefix("v_").strip()
        fields = body.strip().strip('"').split("~")
        if len(fields) <= _F_ASK1 or not code:
            continue
        last = _num(fields[_F_LAST])
        suspended = last <= 0 and _num(fields[_F_OPEN]) <= 0
        if suspended:
            quotes.append(NormalizedQuote(
                code=code, name=fields[1], last=0.0, prev_close=_num(fields[_F_PREV]),
                open=_num(fields[_F_OPEN]), high=0.0, low=0.0, cum_volume=0, ts=fields[_F_TIME],
            ))
            continue
        quotes.append(NormalizedQuote(
            code=code, name=fields[1], last=round(last, 2),
            prev_close=round(_num(fields[_F_PREV]), 2), open=round(_num(fields[_F_OPEN]), 2),
            high=round(_num(fields[_F_HIGH]), 2), low=round(_num(fields[_F_LOW]), 2),
            cum_volume=_to_shares(code, _num(fields[_F_VOL])),
            bids=_levels(fields, _F_BID1, code), asks=_levels(fields, _F_ASK1, code),
            ts=fields[_F_TIME], amount_wan=_num(fields[37]) if len(fields) > 37 else 0.0,
        ))
    return quotes


def parse_suggest_payload(text: str) -> list[dict[str, str]]:
    """解析 smartbox v2 联想响应为规范化 [{code, name, kind}]（T23-4）。

    原始格式：`v_hint="sh~600519~贵州茅台~gzmt~GP-A^sz~000001~平安银行~payh~GP-A";`，
    条目间 `^`、字段间 `~`（市场/代码/名称/拼音/类别）；无结果返回 `v_hint="N";`。
    code 输出为带市场前缀的规范码（与 watchlist 落库口径一致）。
    """
    body = text.strip().rstrip(";")
    if "=" not in body:
        return []
    body = body.split("=", 1)[1].strip().strip('"')
    if not body or body == "N":
        return []
    out: list[dict[str, str]] = []
    for item in body.split("^"):
        fields = item.split("~")
        if len(fields) < 3 or not fields[0] or not fields[1]:
            continue
        kind = fields[4].lower() if len(fields) > 4 else ""
        out.append({
            "code": f"{fields[0]}{fields[1]}",
            "name": _unescape_name(fields[2]),
            "kind": _SUGGEST_KINDS.get(kind, kind),
        })
    return out


class TencentAdapter:
    """网络请求封装（解析逻辑在纯函数中，可离线测试）。"""

    def __init__(self, client: Any):
        self.client = client  # httpx.AsyncClient

    async def fetch_quotes(self, codes: list[str]) -> list[NormalizedQuote]:
        if not codes:
            return []
        try:
            resp = await self.client.get(QUOTE_URL + ",".join(codes))
            resp.raise_for_status()
        except Exception:
            # C008：快照域 https 可能被网络环境阻断（http 实测可达），同解析器协议兜底
            resp = await self.client.get(QUOTE_URL_HTTP + ",".join(codes))
            resp.raise_for_status()
        return parse_quote_payload(resp.content.decode("gbk", errors="replace"))

    async def fetch_daily_klines(self, code: str, limit: int = 320) -> list[tuple]:
        """日K（前复权）：[(code, date, open, close, high, low, volume)]。"""
        resp = await self.client.get(
            KLINE_URL, params={"param": f"{code},day,,,{limit},qfq"}
        )
        resp.raise_for_status()
        payload = resp.json().get("data", {}).get(code, {})
        rows = payload.get("qfqday") or payload.get("day") or []
        out: list[tuple] = []
        for row in rows:
            # [date, open, close, high, low, volume, ...]
            out.append((code, row[0], float(row[1]), float(row[2]), float(row[3]),
                        float(row[4]), int(float(row[5]))))
        return out

    async def fetch_corporate_actions(self, codes: list[str], next_date: str) -> list[tuple]:
        """公司行动采集钩子：公开免费源无稳定接口，默认返回空
        （数据可经 corporate_actions 表写入；处理逻辑见 SessionService）。
        03 号详细设计文档若给出接口，在此接入。"""
        return []

    async def fetch_suggest(self, q: str) -> list[dict[str, str]]:
        """名称联想（T23-4）：smartbox v2，GBK 解码，规范化 [{code, name, kind}]。"""
        resp = await self.client.get(SUGGEST_URL, params={"v": "2", "q": q, "t": "gp"})
        resp.raise_for_status()
        return parse_suggest_payload(resp.content.decode("gbk", errors="replace"))
