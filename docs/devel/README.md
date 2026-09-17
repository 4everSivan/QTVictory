# QTVictory 开发文档（devel）

> **用途**: `docs/devel/` 开发者主目录索引 ｜ **最后更新**: 2026-09-17

---

## 1. 简介

`docs/devel/` 是 QTVictory 的开发文档根目录，全面覆盖系统架构设计、阶段计划、任务拆解、终验报告、日常变更核验与环境治理。

为了避免线性瀑布流导致的“Bug 修复/回调破坏文档真实性”并方便人工高效核验，本目录采用**“基线规范 + 变更核验卡 + 阶段历史 + 环境治理”**的分层架构：

- **[design/](design/README.md)** —— 系统现行基准事实源（Living Baseline），保持全文自洽；
- **[change/](change/README.md)** —— 变更与人工核验卡，专为日常 BugFix、功能回调与参数微调提供对比表与 Checklist；
- **[plan/](plan/README.md)** —— 开发计划，承载 Phase 1 阶段流程总述、里程碑（M 编号）与进度矩阵；
- **[task/](task/README.md)** —— 任务细化卡（T 编号），每模块一份，是具体执行单元；
- **[report/](report/README.md)** —— 阶段验收报告与机器证据记录；
- **[env/](env/README.md)** —— 开发环境配置、缓存盘点与安全清理指南；
- **[assessment/](assessment/README.md)** —— AI Agent 研发质量量化评估体系与报告；
- **[todo/](todo/README.md)** —— 待办与需求缓冲池，未入轨缺陷与需求的登记表（落地即移出，零沉淀）。

当前状态：Phase 1 模拟底座与观察员控制台双线（M1–M16 / T01–T22）均已收口并通过终验。项目总览见根 [README.md](../../README.md)。

---

## 2. 目录架构

```
docs/devel/
├── README.md          # 本文档（devel 顶层总览与导航）
├── design/            # 【设计基线】现行完整设计方案（2 份 + 索引）
├── change/            # 【变更核验】Bug 修复、功能回调卡与标准模板
├── plan/              # 【里程碑计划】总体计划 ×2 + 里程碑 M1–M16
├── task/              # 【任务规格】原子任务卡 T01–T22
├── report/            # 【阶段验收】M8 / M16 终验报告
├── env/               # 【环境治理】缓存依赖盘点与清理指南
├── assessment/        # 【研发评估】Agent 评分标准、流程与报告
└── todo/              # 【待办缓冲】未入轨缺陷与需求登记表（落地即移出）
```

---

## 3. 子目录索引

| 目录 | 索引文档 | 核心职责 | 现行状态 |
|---|---|---|---|
| **design/** | [design/README.md](design/README.md) | 包含 [01-前端设计方案](design/01-前端设计方案.md) (v2.1) 与 [02-后端设计方案](design/02-后端设计方案.md) (v3.0)，为系统现行真理 | 现行基线 |
| **change/** | [change/README.md](change/README.md) | 承载 Bug 修复与回调的核验流，提供 [template.md](change/template.md) 变更卡模板与前后对比 Checklist | 持续演进 |
| **plan/** | [plan/README.md](plan/README.md) | 包含 [00-总体开发计划](plan/00-总体开发计划.md)、[00-前端开发计划](plan/00-前端开发计划.md) 与 M1–M16 里程碑 | Phase 1 收口 |
| **task/** | [task/README.md](task/README.md) | 包含 T01–T14（后端）与 T15–T22（前端）共 22 篇任务细化规格卡 | 全量完成 |
| **report/** | [report/README.md](report/README.md) | 包含 [01-M8-验收报告](report/01-M8-验收报告.md) 与 [02-M16-前端验收报告](report/02-M16-前端验收报告.md) | 阶段收口 |
| **env/** | [env/README.md](env/README.md) | 包含 [01-环境缓存与依赖清理指南](env/01-环境缓存与依赖清理指南.md)，指导磁盘与缓存治理 | 现行有效 |
| **assessment/** | [assessment/README.md](assessment/README.md) | 包含评分标准、执行流程与 AI Agent 研发质量评估最终报告 | 已定稿 |
| **todo/** | [todo/README.md](todo/README.md) | 未入轨缺陷与需求的缓冲池（[now.md](todo/now.md)、[future.md](todo/future.md)），落地即移出、零沉淀 | 持续轮转 |

---

## 4. 人工核验与阅读指引

- **想要了解系统当下完整规则**：请直接阅读 [design/](design/README.md) 中的两份设计大稿；
- **想要核验最新代码修复或功能回调**：请查看 [change/](change/README.md) 中的变更卡，直接核对三联前后对比表与人工 Checklist；
- **想要查验历史交付质量与测试证据**：请查阅 [report/](report/README.md) 中的阶段验收报告或 [assessment/](assessment/README.md) 中的评估报告；
- **想要定位特定模块的历史任务定义**：请通过 [plan/](plan/README.md) 的追踪矩阵跳转到对应的 [task/](task/README.md) 任务卡；
- **想要登记或查看未入轨的缺陷与需求**：请查阅 [todo/](todo/README.md) 缓冲池，注意事项一旦建卡或落入设计即被物理移出。
