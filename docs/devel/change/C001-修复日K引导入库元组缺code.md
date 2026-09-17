# C001 - 修复日K引导入库元组缺 code 导致 klines 表永空

> **卡片ID**: C001 ｜ **类型**: BugFix ｜ **状态**: 核验通过
> **创建日期**: 2026-09-17 ｜ **关联设计**: [02-后端设计方案.md §3.4](../design/02-后端设计方案.md#34-行情服务marketservice)

---

## 1. 变更背景与动因

- **Bug 表现**：前端图表区"日K"页签永远空白（数据为空数组），任意标的均无 K 线渲染。
- **根因定位**：`TencentAdapter.fetch_daily_klines` 返回 6 元组 `(date, open, close, high, low, volume)`（不含 code），而 `DataStore.upsert_klines` 的 INSERT 语句要求 7 元组 `(code, date, open, close, high, low, volume)`。`MarketService._bootstrap_klines` 将适配器输出直接塞入 `upsert_klines`，sqlite 绑定数量不匹配抛 `ProgrammingError`，被 `except Exception` 捕获后仅记录日志 "kline bootstrap failed"，`klines` 表因此永远为空。
- **实测证据**：本机 8788 测试实例 `GET /api/market/kline?code=sh000300&period=day` 返回 `data: []`；同机直连腾讯 K 线接口同一代码可返回 5 根日K，网络与源端均正常。
- **测试盲区说明**：后端测试均经 `sync_klines` 离线注入 7 元组（store 契约正确），"适配器 → store" 真触网链路无端到端覆盖，故缺陷漏网。属"非改不可"：设计 02 §3.4 明确"日K 启动拉取全量历史入库"，当前实现与设计决议不符。

---

## 2. 规则与设计变更对照（人工核验重点）

| 维度 | 变更前（旧逻辑） | 变更后（新逻辑） | 取舍理由与影响边界 |
|---|---|---|---|
| **代码/接口契约** | `fetch_daily_klines` 返回 `(date, open, close, high, low, volume)` 6 元组 | 返回 `(code, date, open, close, high, low, volume)` 7 元组，code 取请求入参 | 与 `upsert_klines` / `sync_klines` 的 7 元组契约对齐；适配器返回自带 code 也消除调用方歧义 |
| **错误处理/异常流** | 绑定数量错误被泛化 `except` 吞掉，仅日志 | 不变（本卡最小修复，不扩大范围） | 启动引导失败的可见性改进另立事项，不混入本卡 |
| **业务规则** | 无变化 | 无变化 | 修复后行为即设计 02 §3.4 既定行为：启动拉取全量历史日K入库 |

---

## 3. 代码变更与受影响文件

- 核心实现：`backend/app/adapters/tencent.py`（`fetch_daily_klines` 返回 7 元组）
- 测试覆盖：`backend/tests/` 新增适配器→store 契约回归测试（断言经 `upsert_klines` 落库后可 `klines_for` 读回，防元组维度漂移再发）

---

## 4. 人工核验清单（Checklist）

> 核验人照表逐项执行，全勾确认后方可合入主干。

- [x] **自动化测试**：`cd backend && pytest` 全量通过（133 passed，含新增 `TestKlineBootstrapContract` 两例）。
- [x] **行为/接口实测**：
  - 步骤 1：按 `local/deployment-report.md` 维护命令重启 8788 测试实例（旧 PID 34696 → 新 PID 69087）；
  - 步骤 2：`GET /api/market/kline?code=sh000300&period=day` 返回非空日K（2026-09-11 起多根，腾讯源）；
  - 步骤 3：前端浏览器刷新后"日K"页签正常渲染，人工确认。
- [x] **反向影响排查**：`sync_klines` 离线注入路径（计划引擎/测试依赖）未受影响（全量测试绿）；分钟线、行情降级链、撮合均无波及。
- [x] **设计方案与双向回链**：
  - [x] 02-后端设计方案.md §3.4 原位已增补反向引用标签（`> 📌 **关联变更**: [C001]...`）；
  - [x] 02 头部“关联变更”追加 C001，文末变更记录追加回链条目；
  - [x] [CHANGELOG.md](../../../CHANGELOG.md) 条目已登记并双向回链本卡。

---

## 5. 核验结论与收尾

- **核验方式**：AI 对话核验代签（由 AI 汇报测试事实与实测结果，人工在会话确认后代签收口）
- **确认人**：sivan（AI 代签）
- **核验日期**：2026-09-17
- **结论**：通过
- **会话确认记录**：2026-09-17 会话中人工确认原话"日k显示正常了"；此前 AI 已汇报核验事实——pytest 133 项全绿、8788 实例重启后 `/api/market/kline` 返回真实日K、design 02 双向回链齐备。
- **版本归档**：
  - 关联提交：`[14d108e](https://github.com/4everSivan/QTVictory/commit/14d108e)`
  - 纳入版本：`[v0.1.0](../../../CHANGELOG.md)`
