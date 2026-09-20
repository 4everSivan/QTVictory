# C016 - 修复下单 marketType 空值 422

> **卡片ID**: C016 ｜ **类型**: BugFix ｜ **状态**: 核验通过
> **创建日期**: 2026-09-18 ｜ **关联设计**: [02-后端设计方案.md](../design/02-后端设计方案.md) §5.2

---

## 1. 变更背景与动因

用户实测 UI 买入报错"请求参数校验失败"（422）。根因：**前后端契约空值不对齐**——

- 前端下单面板对限价单固定发送 `marketType: null`（`OrderPanel.tsx`，市价类型 seg 仅市价态出现，限价态无值）；
- 后端 `OrderIn.marketType` 声明为 `Literal["best5_cancel", "opponent_best"] = "best5_cancel"`，**不接受显式 null** → pydantic 校验 422。

存量缺陷：API 直测与既有集成测试均携带枚举值或不带该键，UI 限价单路径从未被真实请求覆盖，缺陷潜伏至用户实测暴露。与同日 C015 无关（未触碰 schemas/OrderPanel）。

## 2. 规则与设计变更对照（人工核验重点）

| 维度 | 变更前（旧逻辑） | 变更后（新逻辑） | 取舍理由与影响边界 |
|---|---|---|---|
| **接口契约** | `marketType` 仅接受两枚举值或缺省；显式 `null` 被 pydantic 422 拒绝 | `marketType: Literal[...] \| None = None`——缺省/null 均可，服务端归一为 `best5_cancel`（限价单不落市价类型） | API-first 机器友好：容忍调用方显式传 null 的常见习惯；业务语义零变化 |
| **前端行为** | 限价单发送 `marketType: null` | 限价单不发送该键（`undefined` 被 JSON 序列化丢弃） | 收敛请求面，契约有氧 |
| **错误处理** | UI 限价买单 100% 报 422"请求参数校验失败" | 正常进入校验链 | — |

## 3. 代码变更与受影响文件

- 核心实现：`backend/app/models/schemas.py`（`OrderIn.marketType` 可空）、`backend/app/services/trading.py`（`payload.get("marketType") or "best5_cancel"` 归一）、`frontend/src/components/panes/OrderPanel.tsx`（限价态停发 null）
- 测试覆盖：`backend/tests/integration/test_api.py::test_order_market_type_nullable_contract`（限价单 null → 201 且不落类型；市价单缺省 → 201 且归一 best5_cancel）

## 4. 人工核验清单（Checklist）

> 核验人照表逐项执行，全勾确认后方可合入主干。

- [x] **自动化测试**（2026-09-20 复跑）：`cd backend && pytest` **204 项全绿**（含 `test_order_market_type_nullable_contract` 契约用例：限价单 null → 201 且不落类型、市价单缺省 → 201 且归一 best5_cancel）；`cd frontend && npm test` **155 项全绿** + `npm run build`（tsc + Vite 零报错）。
- [x] **行为/接口实测**（2026-09-20，8788 实例，API 层——UI 与外部程序同用代下单端点，等价覆盖）：
  - 步骤 1 ✓：限价买单显式 `marketType: null` → 201 委托成功（`market_type` 落库 NULL），不再 422；
  - 步骤 2 ✓：市价买单缺省 `marketType` → 201 委托成功，服务端归一落库 `market_type=best5_cancel`；
  - 实测现场已清理（委托撤单、实测交易员软删）。
- [x] **反向影响排查**：市价单类型选择与撮合回归全绿（随 204 项全量通过）；`market_type` 落库口径实测确认不变（限价单 NULL、市价单实际类型）。
- [ ] **设计方案与双向回链**：
  - [x] 02 §5.2 代下单契约注已更新自洽；
  - [x] §5.2 原位已增补反向引用标签（`> 📌 **关联变更**: [C016]...`）；
  - [x] 02 头部"关联变更"追加 C016，文末变更记录追加回链条目（v6.5）；
  - [x] [CHANGELOG.md](../../../CHANGELOG.md) 条目已登记并双向回链本卡（Fixed 区；2026-09-20 收口时补勾）。

## 5. 核验结论与收尾

- **核验方式**：AI 对话核验代签（由 AI 汇报测试事实与实测结果，人工在会话确认后代签收口）
- **确认人**：sivan（AI 代签）
- **核验日期**：2026-09-20
- **结论**：核验通过
- **会话确认记录**：2026-09-20 收口会话中人工确认（用户实测 UI 买入限价/市价均成功），同意合入。AI 汇报核验事实——后端 pytest 204 项全绿（含 test_order_market_type_nullable_contract）、前端 Vitest 155 项全绿 + tsc/Vite 构建零报错；8788 实例 API 实测（2026-09-20）：限价单显式 `marketType: null` → 201 且不落类型，市价单缺省 → 201 且归一落库 `best5_cancel`，实测现场已清理。
- **版本归档**：
  - 关联提交：（合入后回填）
  - 纳入版本：`[v0.1.0](../../../CHANGELOG.md)`（待发布行）
