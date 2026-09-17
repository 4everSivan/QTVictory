"""会话服务与日切（T08，02 §3.9 / §6.4 / §6.6）。

- 交易时段状态机：集合竞价（9:15–9:25，其中 9:20–9:25 禁撤）→
  连续竞价（9:25–11:30 / 13:00–14:57）→ 收盘集合竞价（14:57–15:00）→ 已收盘；
- 日切序列（幂等可重入，每步检查点）：日终撤单 → 收盘快照 → 公司行动 →
  T+1 重置 → 日K增量 → 分钟线落库 → 计划到期 → 日期推进；
- 公司行动处理（§6.6）：现金分红（统一税率）+ 送转股（成本摊薄、到账可卖）。
"""

from __future__ import annotations

import json
import logging
from datetime import date as date_cls, datetime, timedelta
from typing import Any

from app.errors import BizError

log = logging.getLogger("qtv.session")

DAY_CUT_STEPS = (
    "eol_cancel", "snapshot", "corporate_actions", "t1_reset",
    "kline_increment", "minute_persist", "plan_expiry", "advance_date",
)


def phase_name(hhmm: str) -> str:
    if "09:15" <= hhmm < "09:25":
        return "call_auction"
    if "09:25" <= hhmm < "11:30" or "13:00" <= hhmm < "14:57":
        return "continuous"
    if "14:57" <= hhmm < "15:00":
        return "closing_auction"
    return "closed"


class SessionService:
    def __init__(self, ctx):
        self.ctx = ctx

    # -- 状态机（T08-1） ----------------------------------------------------

    def phase_at(self, when: datetime) -> str:
        return phase_name(when.strftime("%H:%M"))

    def trading_phase(self) -> bool:
        return self.phase_at(self.ctx.clock.now()) != "closed"

    def state_view(self) -> dict[str, Any]:
        phase = self.phase_at(self.ctx.clock.now())
        state = {
            "call_auction": "call_auction",
            "continuous": "trading",
            "closing_auction": "call_auction",
            "closed": "closed",
        }[phase]
        if state != "closed" and self.ctx.market.source == "anchor":
            state = "degraded"  # 已降级（01 §4.1 状态胶囊口径）
        return {
            "state": state,
            "phase": phase,
            "tradingDate": self.ctx.store.get_state("trading_date")
            or self.ctx.clock.now().strftime("%Y-%m-%d"),
        }

    # -- 日切（T08-2，幂等可重入） -----------------------------------------

    async def day_cut(self, trading_date: str | None = None) -> dict[str, Any]:
        """对给定交易日执行日切序列；重复调用按检查点跳过已完成步骤。"""
        d = trading_date or (
            self.ctx.store.get_state("trading_date")
            or self.ctx.clock.now().strftime("%Y-%m-%d")
        )
        return await self.ctx.serial.run(lambda: self._day_cut_sync(d))

    def _day_cut_sync(self, d: str) -> dict[str, Any]:
        """同步内核（供串行基座内调用方直接使用，避免嵌套提交死锁）。"""
        report: dict[str, Any] = {"date": d, "steps": {}}
        for step in DAY_CUT_STEPS:
            if self._done(d, step):
                report["steps"][step] = "skipped"
                continue
            result = getattr(self, f"_step_{step}")(d)
            self._mark_done(d, step)
            report["steps"][step] = result
        return report

    def _checkpoint(self, d: str, step: str) -> str:
        return f"daycut:{d}:{step}"

    def _done(self, d: str, step: str) -> bool:
        return self.ctx.store.get_state(self._checkpoint(d, step)) == "done"

    def _mark_done(self, d: str, step: str) -> None:
        self.ctx.store.set_state(self._checkpoint(d, step), "done")

    # 步骤 1：日终撤单（全体交易员日内订单 + day 条件单）
    def _step_eol_cancel(self, d: str) -> int:
        n_orders = len(self.ctx.store.cancel_day_orders(d))
        n_entries = self.ctx.store.expire_day_entries(d)
        return {"orders": n_orders, "dayEntries": n_entries}

    # 步骤 2：收盘快照（全体未关闭）
    def _step_snapshot(self, d: str) -> int:
        return self.ctx.metrics.close_snapshots(d)

    # 步骤 3：公司行动处理（次日除权标的）
    def _step_corporate_actions(self, d: str) -> int:
        return self._apply_corporate_actions(d)

    # 步骤 4：T+1 重置
    def _step_t1_reset(self, d: str) -> str:
        self.ctx.store.t1_reset_all()
        return "ok"

    # 步骤 5：日K增量（离线/测试为空操作，实盘由行情适配器拉取）
    def _step_kline_increment(self, d: str) -> str:
        return "noop"

    # 步骤 6：当日分钟线落库
    def _step_minute_persist(self, d: str) -> int:
        return self.ctx.market.persist_minutes(d)

    # 步骤 7：计划到期检查
    def _step_plan_expiry(self, d: str) -> int:
        return self.ctx.plans.day_rollover(d)

    # 步骤 8：交易日期推进
    def _step_advance_date(self, d: str) -> str:
        try:
            base = datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            return d
        nxt = base + timedelta(days=1)
        while nxt.weekday() >= 5:  # 跳过周末（节假日以快照缺失推定）
            nxt += timedelta(days=1)
        self.ctx.store.set_state("trading_date", nxt.strftime("%Y-%m-%d"))
        return nxt.strftime("%Y-%m-%d")

    # -- 公司行动（T08-3/T08-4，§6.6） ------------------------------------

    def _apply_corporate_actions(self, date_str: str) -> int:
        """处理次日除权标的：登记日收盘持仓口径（处理时点即日切边界）。

        - 现金分红：现金 += 持仓 × 每股派息 × (1 − QTV_DIVIDEND_TAX)；
        - 送转股：股数 = 原股数 × (1+送+转)（零股并入），avg_cost 摊薄；
          到账股份不占 today_bought（除权日即可卖）；
        - 除权参考价：数据源快照已处理，无需自行计算；
        - 事件留痕：dividend / transfer。
        """
        try:
            base = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return 0
        next_day = base + timedelta(days=1)
        ex_date = next_day.strftime("%Y-%m-%d")
        tax = self.ctx.settings.qtv_dividend_tax
        store = self.ctx.store
        now_s = self.ctx.clock.now().isoformat(timespec="seconds")
        touched = 0
        for action in store.actions_for_ex_date(ex_date):
            dividend = action["dividend_per_share"] or 0.0
            bonus = action["bonus_ratio"] or 0.0
            transfer = action["transfer_ratio"] or 0.0
            for pos in store.positions_all():
                if pos["code"] != action["code"]:
                    continue
                trader = store.get_trader(pos["trader_id"])
                if trader is None or trader["status"] == "deleted":
                    continue
                touched += 1
                if dividend > 0:
                    cash_in = pos["qty"] * dividend * (1 - tax)
                    store.trader_set_cash(pos["trader_id"], trader["cash"] + cash_in)
                    store.insert_event(pos["trader_id"], now_s, "dividend", json.dumps({
                        "code": pos["code"], "perShare": dividend,
                        "qty": pos["qty"], "tax": tax, "cashIn": round(cash_in, 2),
                    }))
                if bonus > 0 or transfer > 0:
                    new_qty = int(pos["qty"] * (1 + bonus + transfer))
                    total_cost = pos["qty"] * pos["avg_cost"]
                    new_avg = total_cost / new_qty if new_qty else 0.0
                    # today_bought 保持原值：到账股份当日可卖
                    store.upsert_position(pos["trader_id"], pos["code"], new_qty,
                                          new_avg, pos["today_bought"])
                    store.insert_event(pos["trader_id"], now_s, "transfer", json.dumps({
                        "code": pos["code"], "oldQty": pos["qty"], "newQty": new_qty,
                        "bonus": bonus, "transfer": transfer,
                        "avgCost": round(new_avg, 4),
                    }))
        return touched
