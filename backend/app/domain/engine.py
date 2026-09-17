"""撮合引擎内核（T03，02 §6.1）——纯函数，零 I/O、零框架依赖。

数据基础（每 tick）：五档买卖盘口、周期增量成交量 ΔV（累计量差分）、
最新价 / 昨收。移植事实来源：前端原型 app.jsx 的 TRADE.*（v1 实测基线）。

规则要点（02 §6.1）：
- 市价单 best5_cancel：按快照五档逐档吃单（档位挂量 ∩ 限额双重约束），
  加权均价，剩余即时撤销；opponent_best：对手一档成交剩余撤销；
- 限价单排队语义：穿越触发（买 last≤price / 卖 last≥price）、
  量约束分批部分成交、成交价 = 委托价；
- 量约束：单交易员单标的每 tick ≤ ΔV × participation，多交易员共享
  限额池按到达顺序分配；
- 冻结：买入 price×qty×1.002，部分成交按比例扣减，撤单/日终解冻；
- 集合竞价：9:20–9:25 不接受撤单，集合竞价价产生后限价按穿越、
  市价直接成交，成交价 = 集合竞价价；
- 降级档：无盘口/ΔV 时固定滑点全量成交，fill_model=fallback。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Side = Literal["buy", "sell"]

FALLBACK_SLIPPAGE = 0.0005  # 降级档固定滑点 ±0.05%
BUY_FREEZE_MARGIN = 1.002   # 买入冻结含费用余量


@dataclass
class BookLevel:
    price: float
    volume: int  # 股


@dataclass
class Tick:
    code: str
    last: float
    prev_close: float
    bids: list[BookLevel] = field(default_factory=list)  # price 降序（买一在前）
    asks: list[BookLevel] = field(default_factory=list)  # price 升序（卖一在前）
    delta_volume: int = 0
    suspended: bool = False
    degraded: bool = False
    ts: str = ""


@dataclass
class Fee:
    commission: float
    stamp_tax: float
    transfer_fee: float

    @property
    def total(self) -> float:
        return self.commission + self.stamp_tax + self.transfer_fee


@dataclass
class Fill:
    price: float
    qty: int
    fill_model: str = "l2"


@dataclass
class MatchOutcome:
    """单订单单 tick 撮合结果（纯数据）。"""

    fills: list[Fill] = field(default_factory=list)
    filled_qty: int = 0
    remaining_qty: int = 0
    avg_price: float | None = None
    status: str = "wait"          # wait | partial | filled | cancel
    fill_model: str = "l2"


def calc_fee(amount: float, is_buy: bool) -> Fee:
    """费用公式（v1 §6 表）：佣金 max(amt×0.00025, 5)；印花税卖出 0.0005；过户费 0.0001。"""
    commission = round(max(amount * 0.00025, 5.0), 2)
    stamp = 0.0 if is_buy else round(amount * 0.0005, 2)
    transfer = round(amount * 0.0001, 2)
    return Fee(commission=commission, stamp_tax=stamp, transfer_fee=transfer)


def board_code(code: str) -> str:
    """剥离市场前缀（sh/sz/bj），返回 6 位证券代码（板块判定基）。"""
    return code[2:] if code[:2] in ("sh", "sz", "bj") and len(code) > 6 else code


def limit_pct(code: str) -> float:
    """涨跌停幅度：主板 ±10%，创业板(30)/科创板(688) ±20%。"""
    pure = board_code(code)
    return 20.0 if pure.startswith(("30", "68")) else 10.0


def price_limits(prev_close: float, code: str) -> tuple[float, float]:
    k = limit_pct(code) / 100.0
    return round(prev_close * (1 - k), 2), round(prev_close * (1 + k), 2)


def valid_band(tick: Tick, side: str, code: str) -> tuple[float, float]:
    """有效申报价格范围（02 §6.1）：涨跌停带 ∩ 连续竞价 ±2%（无档位时取最新价）。"""
    lo, hi = price_limits(tick.prev_close, code)
    if side == "buy":
        ref = tick.asks[0].price if tick.asks else tick.last
        return lo, min(hi, round(ref * 1.02, 2))
    ref = tick.bids[0].price if tick.bids else tick.last
    return max(lo, round(ref * 0.98, 2)), hi


def lot_ok(code: str, qty: int, pos_qty: int = 0, is_sell: bool = False) -> bool:
    """申报单位：主板/创业板 100 整数倍；科创板 ≥200 后 1 股递增，零股须一次卖出。"""
    if qty <= 0:
        return False
    if board_code(code).startswith("68"):
        if is_sell:
            # 余额 <200 的零股须一次性卖出；否则任意 ≥200
            return qty == pos_qty if pos_qty < 200 else qty >= 200
        return qty >= 200
    return qty % 100 == 0


def buy_freeze(price: float, qty: int) -> float:
    """买入冻结资金（含费用余量 0.2%）。"""
    return round(price * qty * BUY_FREEZE_MARGIN, 2)


def tick_volume_cap(tick: Tick, participation: float) -> int:
    """单交易员单标的每 tick 成交量上限 = ΔV × 参与比例。
    ΔV=0（本周期无成交量）→ 限额 0（无量不成交）；降级档无 ΔV → 不限。"""
    if tick.degraded:
        return 10**9
    return max(0, int(tick.delta_volume * participation))


def _best5(side: str, tick: Tick, want_qty: int, cap: int) -> tuple[list[Fill], int]:
    """五档逐档吃单：返回 (fills, 已成交量)。买吃 asks（低→高），卖吃 bids（高→低）。"""
    fills: list[Fill] = []
    done = 0
    levels = tick.asks if side == "buy" else tick.bids
    for level in levels:
        room = min(want_qty - done, level.volume, cap - done)
        if room <= 0:
            break
        fills.append(Fill(price=level.price, qty=room))
        done += room
        if done >= want_qty or done >= cap:
            break
    return fills, done


def market_match(
    side: str, qty: int, tick: Tick, cap: int, market_type: str = "best5_cancel"
) -> MatchOutcome:
    """市价单（02 §6.1 表）：最优五档剩余撤销（默认）/ 对手方最优。"""
    model = "fallback" if tick.degraded else "l2"
    if tick.degraded:
        price = round(tick.last * (1 + FALLBACK_SLIPPAGE), 2) if side == "buy" \
            else round(tick.last * (1 - FALLBACK_SLIPPAGE), 2)
        return MatchOutcome(
            fills=[Fill(price=price, qty=qty, fill_model=model)],
            filled_qty=qty, remaining_qty=0, avg_price=price, status="filled",
            fill_model=model,
        )
    if market_type == "opponent_best":
        levels = tick.asks if side == "buy" else tick.bids
        if not levels:
            return MatchOutcome(status="cancel", fill_model=model, remaining_qty=qty)
        take = min(qty, levels[0].volume, cap)
        if take <= 0:
            return MatchOutcome(status="cancel", fill_model=model, remaining_qty=qty)
        return MatchOutcome(
            fills=[Fill(price=levels[0].price, qty=take, fill_model=model)],
            filled_qty=take, remaining_qty=qty - take, avg_price=levels[0].price,
            status="filled" if take == qty else "cancel",  # 剩余撤销
            fill_model=model,
        )
    fills, done = _best5(side, tick, qty, cap)
    if done == 0:
        return MatchOutcome(status="cancel", fill_model=model, remaining_qty=qty)
    amount = sum(f.price * f.qty for f in fills)
    return MatchOutcome(
        fills=fills, filled_qty=done, remaining_qty=qty - done,
        avg_price=amount / done,  # 加权均价（展示层再取 2 位）
        status="filled" if done == qty else "cancel",  # 剩余未成交部分即时撤销
        fill_model=model,
    )


def limit_match(side: str, price: float, waiting_qty: int, tick: Tick, cap: int) -> MatchOutcome:
    """限价单排队：穿越触发（买 last≤price / 卖 last≥price），成交价 = 委托价。
    降级档：无有效行情，直接全量成交（固定滑点）。"""
    model = "fallback" if tick.degraded else "l2"
    crossed = (tick.last <= price) if side == "buy" else (tick.last >= price)
    if not tick.degraded and not crossed:
        return MatchOutcome(status="wait", fill_model=model, remaining_qty=waiting_qty)
    if tick.degraded:
        take = waiting_qty  # 降级档：全量成交
    else:
        take = min(waiting_qty, cap)
    if take <= 0:
        return MatchOutcome(status="wait", fill_model=model, remaining_qty=waiting_qty)
    fill_price = price if not tick.degraded else round(
        tick.last * (1 + (FALLBACK_SLIPPAGE if side == "buy" else -FALLBACK_SLIPPAGE)), 2
    )
    return MatchOutcome(
        fills=[Fill(price=fill_price, qty=take, fill_model=model)],
        filled_qty=take, remaining_qty=waiting_qty - take, avg_price=fill_price,
        status="filled" if take == waiting_qty else "partial",
        fill_model=model,
    )


def auction_match(
    side: str, otype: str, price: float | None, qty: int,
    auction_price: float, auction_volume: int, participation: float,
) -> MatchOutcome:
    """集合竞价（9:25/15:00）：限价按穿越检查（买单价 ≥ 集合竞价价即成交）、
    市价直接成交；成交价 = 集合竞价价；量约束按集合竞价成交量比例简化。"""
    cap = max(1, int(auction_volume * participation))
    if otype == "market" or (side == "buy" and price is not None and price >= auction_price) \
            or (side == "sell" and price is not None and price <= auction_price):
        take = min(qty, cap)
        return MatchOutcome(
            fills=[Fill(price=auction_price, qty=take)], filled_qty=take,
            remaining_qty=qty - take, avg_price=auction_price,
            status="filled" if take == qty else "cancel", fill_model="l2",
        )
    return MatchOutcome(status="wait", remaining_qty=qty, fill_model="l2")


def release_freeze(side: str, frozen: float, total_qty: int, filled_qty: int) -> float:
    """部分成交后按比例解冻：剩余冻结 = 冻结额 × 剩余量/总量（撤单/日终归零）。"""
    if total_qty <= 0:
        return 0.0
    return round(frozen * (total_qty - filled_qty) / total_qty, 2)
