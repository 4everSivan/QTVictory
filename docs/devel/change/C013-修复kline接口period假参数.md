# C013 - 修复market/kline period=minute假参数

> **卡片ID**: C013 ｜ **类型**: BugFix ｜ **状态**: 核验通过
> **创建日期**: 2026-09-18 ｜ **关联设计**: [02-后端设计方案.md](../design/02-后端设计方案.md) §5.2（REST 表 kline 行）、§3.11（API 修正）

---

## 1. 变更背景与动因

BG-0007（FT-0009 后端设计起草时发现，Phase 1 遗留）：`GET /market/kline` 的 `period` 校验放行 `day | minute`，但路由恒调用 `store.klines_for` 返回日K行——`period=minute` 名存实亡，调用方拿到的是日K数据却以为拿到了分钟线，属误导性假参数（分时实际须走 `/market/minute`）。

02 §3.11（K线分析数据底座〔讨论中〕）已就 API 修正定调：period 枚举最终定为 `day | week | month`，minute 假参数移除并返回 `BAD_REQUEST`。本卡先落地其中**缺陷修复部分**（移除 minute 假参数）；week/month 聚合属 §3.11 功能范畴，待其立项后另行放行。前端现仅用 `period=day` + `/market/minute`（`frontend/src/state/marketData.ts:53`），不受影响。

另顺手修复同点位的错误模型漂移：原校验失败回执为 **200 + 错误 dict**（绕过统一错误模型），改为抛 `BizError`（400，`{code, message, details}`），与 §5.1/§5.4 契约一致。

## 2. 规则与设计变更对照（人工核验重点）

| 维度 | 变更前（旧逻辑） | 变更后（新逻辑） | 取舍理由与影响边界 |
|---|---|---|---|
| **接口契约** | `period=minute` 校验放行，但静默返回日K行（假参数） | `period` 仅放行 `day`；`minute` 及其他值（含未落地的 `week`/`month`）一律 `BAD_REQUEST`，message 指引分时走 `/market/minute` | 杜绝调用方误拿日K冒充分钟线；week/month 待 §3.11 落地后放行，届时仅扩枚举不改路由结构 |
| **错误处理** | 校验失败返回 200 + `{"code":"BAD_REQUEST",...}` dict | 抛 `BizError("BAD_REQUEST", …, 400)`，经统一异常处理器出 400 | 对齐统一错误模型；前端未消费该错误分支（只用 period=day），无破坏面 |

## 3. 代码变更与受影响文件

- 核心实现：`backend/app/api/routes_market.py`（`market_kline` period 校验收紧 + BizError 化）
- 测试覆盖：`backend/tests/integration/test_api.py`（`test_market_endpoints` 增补 minute/week 拒放断言）

## 4. 人工核验清单（Checklist）

> 核验人照表逐项执行，全勾确认后方可合入主干。

- [x] **自动化测试**：`cd backend && pytest` 全绿（`test_market_endpoints` 新增断言：`period=minute`/`period=week` → 400 `BAD_REQUEST`；`period=day` 行为不变）。
- [x] **行为/接口实测**（2026-09-20，8788 实例）：
  - 步骤 1 ✓：`GET /api/market/kline?code=sh600519&period=minute` 返回 400 `{"code":"BAD_REQUEST","message":"period 当前仅支持 day；分时数据请用 /market/minute","details":null}`；
  - 步骤 2 ✓：`GET /api/market/kline?code=sh600519&limit=1` 正常返回日K行（2026-09-18 完结 bar，close 1257.12）。
- [x] **反向影响排查**：前端唯一调用点为 `period=day`（marketData.ts:53），不受影响；`/market/minute` 路由未触碰；前端 Vitest/tsc 无后端契约依赖变化（schema.d.ts 中 period 本为 `string` 自由枚举）。
- [ ] **设计方案与双向回链**：
  - [x] 02 §5.2 kline 行与 §3.11 API 修正条目已更新自洽（minute 移除已落地，week/month 标注待 §3.11 立项放行）；
  - [x] §5.2 与 §3.11 原位已增补反向引用标签（`> 📌 **关联变更**: [C013]...`）；
  - [x] 02 头部"关联变更"追加 C013，文末变更记录追加回链条目；
  - [x] [CHANGELOG.md](../../../CHANGELOG.md) 条目已登记并双向回链本卡。

## 5. 核验结论与收尾

- **核验方式**：AI 对话核验代签（由 AI 汇报测试事实与实测结果，人工在会话确认后代签收口）
- **确认人**：sivan（AI 代签）
- **核验日期**：2026-09-20
- **结论**：核验通过
- **会话确认记录**：2026-09-20 收口会话中人工确认，同意合入。AI 汇报核验事实——后端 pytest 204 项全绿、前端 Vitest 155 项全绿；8788 实例实测复验（2026-09-20）：`period=minute` → 400 `BAD_REQUEST`（message 指引分时走 `/market/minute`），`period=day` 行为不变（末根 2026-09-18 完结 bar，close 1257.12）。
- **版本归档**：
  - 关联提交：`[4bcd769](https://github.com/4everSivan/QTVictory/commit/4bcd769)`
  - 纳入版本：`[v0.1.0](../../../CHANGELOG.md)`（待发布行）
