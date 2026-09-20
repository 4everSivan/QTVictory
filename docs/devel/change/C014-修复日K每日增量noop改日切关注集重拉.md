# C014 - 修复日K每日增量noop改日切关注集重拉

> **卡片ID**: C014 ｜ **类型**: BugFix ｜ **状态**: 核验通过
> **创建日期**: 2026-09-18 ｜ **关联设计**: [02-后端设计方案.md](../design/02-后端设计方案.md) §3.4（行情服务）、§6.4（日切流程）

---

## 1. 变更背景与动因

BG-0008（FT-0009 §3.11 对抗评审 Q12 推演发现，Phase 1 遗留，文档-实现漂移）：日切步骤 5 `_step_kline_increment` 恒返回 `"noop"`，market.py 运行时亦无任何日K重拉路径（仅启动引导 `_bootstrap_klines` 与新增自选单码引导）。长运行实例的 `klines` 末根冻结于上次启动时刻——`ma_cross` 收盘口径与"超额 vs 沪深300"基准实际在拿陈旧收盘价计算；而 02 §3.4 宣称"每日 16:00 增量"、market.py docstring 宣称"每日增量"，名不副实。

按 BG-0008 登记的**最小修复口径**落地：日切步骤 5 落实为关注集日K重拉（复用既有 `_fetch_daily_chain`：腾讯 ifzq → 东财 push2his 兜底），`upsert_klines` 幂等覆盖，上游为最终权威——同时顺带承担 §3.11 所说的除权后前复权重锚自愈（重叠区间幂等覆盖）。§3.11 冷热双态 bar 模型（换日捕获自沉淀 + 校准重拉深度约束）属讨论中功能，不在本卡范围。

## 2. 规则与设计变更对照（人工核验重点）

| 维度 | 变更前（旧逻辑） | 变更后（新逻辑） | 取舍理由与影响边界 |
|---|---|---|---|
| **日切步骤 5** | `_step_kline_increment` 恒返回 `"noop"`，klines 仅启动时刷新 | 调用 `MarketService.schedule_daily_kline_refresh()`：在线调度异步任务逐码重拉关注集日K（返回 `"scheduled"`）；离线/测试无适配器仍为 `"noop"` | 长运行实例每个交易日日切后 klines 末根更新为最近完结 bar；重拉为全量深度（默认 320），幂等 upsert 无破坏 |
| **失败语义** | 无（noop 不会失败） | 单码拉取失败仅 `log.warning` 跳过，不阻断日切后续步骤（checkpoint 照常标记）；与单码引导共用 `_kline_boot_lock` 串行排队，避免并发打满上游 | 行情源故障不应卡住日切序列；任务纳入 `_kline_boot_tasks` 统一生命周期（`stop()` 取消并等待） |
| **文档口径** | §3.4"每日 16:00 增量"、market.py docstring"每日增量"（无对应实现） | §3.4 / §6.4 / docstring 修订为"日切步骤 5 关注集日K重拉（幂等 upsert）"，实现与文档一致 | 消除漂移；16:00 定时器从未存在，改为日切触发（观测到新交易日即执行，等价且更稳） |

## 3. 代码变更与受影响文件

- 核心实现：`backend/app/services/session.py`（`_step_kline_increment` 落实调用）、`backend/app/services/market.py`（新增 `schedule_daily_kline_refresh()` + `_refresh_daily_klines()`，docstring 修订）
- 测试覆盖：`backend/tests/service/test_session.py`（新增 `TestKlineIncrementRefresh` 3 例：离线 noop / 调度重拉落库 + 幂等重入跳过 / 源失败不阻断日切）

## 4. 人工核验清单（Checklist）

> 核验人照表逐项执行，全勾确认后方可合入主干。

- [x] **自动化测试**：`cd backend && pytest` 全绿（新增 3 例：`test_offline_noop` / `test_refresh_scheduled_and_applied`（断言重拉逐码调用、新 bar 落库、幂等重入 skipped）/ `test_refresh_failure_does_not_block_day_cut`）。
- [ ] **行为/接口实测**（须在线实例 + 跨交易日，下一窗口 2026-09-21）：
  - 步骤 1：8788 实例长运行过夜，次日首个快照触发日切后 `GET /api/market/kline?code=sh600519&limit=1`；
  - 步骤 2：日志检索 `daily kline refresh done`；
  - 预期回执/现象：klines 末根 date 推进到前一交易日（不再冻结于启动日）；日志有重拉完成记录。
- [x] **反向影响排查**：日切 checkpoint 机制不变（步骤 5 幂等可重入）；重拉复用 `_fetch_daily_chain` 与 `upsert_klines` 既有契约（C001 7 元组）；与 `_bootstrap_klines`/单码引导共用锁，无并发写冲突；offline 测试装配行为不变（noop）。
- [ ] **设计方案与双向回链**：
  - [x] 02 §3.4 日K口径与 §6.4 日切序列已修订自洽（"每日 16:00 增量"改为"日切步骤 5 关注集重拉"）；
  - [x] §3.4 与 §6.4 原位已增补反向引用标签（`> 📌 **关联变更**: [C014]...`）；
  - [x] 02 头部"关联变更"追加 C014，文末变更记录追加回链条目；
  - [x] [CHANGELOG.md](../../../CHANGELOG.md) 条目已登记并双向回链本卡。

## 5. 核验结论与收尾

- **核验方式**：AI 对话核验代签（由 AI 汇报测试事实与实测结果，人工在会话确认后代签收口）
- **确认人**：sivan（AI 代签）
- **核验日期**：2026-09-20
- **结论**：核验通过
- **会话确认记录**：2026-09-20 收口会话中人工确认，同意合入。AI 汇报核验事实——后端 pytest 204 项全绿（含 TestKlineIncrementRefresh 3 例：离线 noop / 调度重拉落库 + 幂等重入跳过 / 源失败不阻断日切）。在线跨日实测（步骤 1–2：长运行实例过夜日切后 klines 末根推进到前一交易日）留待 2026-09-21 交易时段补记，不阻塞收口。
- **版本归档**：
  - 关联提交：（合入后回填）
  - 纳入版本：`[v0.1.0](../../../CHANGELOG.md)`（待发布行）
