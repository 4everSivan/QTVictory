# C025 - 接入 GitHub Actions 自动化流水线

> **卡片ID**: C025 ｜ **类型**: Refactor ｜ **状态**: 核验通过
> **创建日期**: 2026-09-22 ｜ **关联设计**: 无（本卡为 CI/CD 自动化流水线与工程效能基础设施接入，不改动业务设计规则，不触发 design 双向回链）

---

## 1. 变更背景与动因

QTVictory 在经过 Phase 1 收口与持续演进后，已具备严格的质量防线（后端 226 项 pytest 单测、脚本 157 项单测、前端 180 项 Vitest 单测、37 项 Playwright E2E 几何校验以及基于 Jev 模型的文档治理自检）。然而，目前所有测试与治理检查均依赖开发者在本地终端手工运行，存在以下工程风险：
1. **本地与远端环境差异**：本地测试依赖本地环境缓存或特定 Python/Node 运行时，缺乏云端纯净无状态环境的自动化验证；
2. **PR / Push 缺乏自动化门禁**：代码提交或发起 Pull Request 时，缺少 GitHub Actions 自动化触发运行回归套件与文档治理硬判门禁；
3. **交付流程效率**：随着后续 Phase 2 演进与外部贡献者介入，亟需引入标准化 CI/CD 流水线，在代码合并前自动拦截违规或缺陷。

因此，本卡在仓库中接入 GitHub Actions 自动化流水线（`.github/workflows/ci.yml`），提供后端单测、脚本测试、前端测试构建以及文档治理自检（离线硬判 / 具备凭证时在线全检）的自动化流水线。

---

## 2. 规则与设计变更对照（人工核验重点）

| 维度 | 变更前（旧逻辑） | 变更后（新逻辑） | 取舍理由与影响边界 |
|---|---|---|---|
| **CI/CD 工作流** | 无 `.github/workflows/`，完全依赖开发者本地手动执行测试 | 接入 `.github/workflows/ci.yml`，在 `push` / `pull_request` 时自动触发 | 实现云端纯净环境自动化持续集成，拦截缺陷入库 |
| **后端检验流水线** | 仅本地环境执行 `pytest` | Actions 矩阵/标准 Python 3.11 环境自动执行后端 226 项测试与 scripts 157 项单测 | 保障后端领域撮合、服务层与工具链在纯净 Linux 环境的一致性 |
| **前端检验流水线** | 仅本地执行 `npm test` 与 `npm run build` | Actions Node.js 环境自动运行 `npm test`（180项）与 `npm run build`（TypeScript + Vite） | 杜绝类型不一致、构建破损或单测失败合入主干 |
| **文档治理门禁** | 本地手工运行 `scripts/jev_workflow_check.py` | 流水线默认集成 `python3 scripts/jev_workflow_check.py --offline`（代码侧硬判门禁全覆盖），并在注入凭据时支持 Jev 模型自检 | 自动化落实 AGENTS.md 协作红线，防止治理违规提交 |

---

## 3. 代码变更与受影响文件

- 核心实现：`.github/workflows/ci.yml`
- 治理登记：`docs/devel/todo/now.md`、`docs/devel/change/README.md`、`CHANGELOG.md`

---

## 4. 人工核验清单（Checklist）

> 核验人照表逐项执行，全勾确认后方可合入主干。

- [x] **自动化测试**：
  - [x] 本地执行后端测试：`backend/.venv/bin/pytest backend/tests`（226 项全绿）
  - [x] 本地执行治理测试：`backend/.venv/bin/pytest scripts/tests -q`（157 项全绿）
  - [x] 本地执行前端测试：`cd frontend && npm test`（180 项全绿）
  - [x] 本地执行前端构建：`cd frontend && npm run build`（编译通过无报错）
  - [x] 本地执行治理自检：`python3 scripts/jev_workflow_check.py --offline`（退出码 0）
- [x] **CI 配置有效性校验**：
  - [x] `.github/workflows/ci.yml` YAML 语法解析正常，无语法错误与缩进缺陷；
  - [x] 覆盖 `push` 与 `pull_request` 事件，工作流划分清晰（backend、frontend、e2e）；
  - [x] 缓存机制配置合理（pip 依赖与 npm 依赖缓存），提升 CI 执行速度。
- [x] **文档与双向互链**：
  - [x] `now.md` 按零沉淀纪律移出并记录流转；
  - [x] `change/README.md` 索引表增补 C025 条目；
  - [x] [CHANGELOG.md](../../../CHANGELOG.md) 条目已登记并双向回链本卡。

---

## 5. 核验结论与收尾

- **核验方式**：AI 对话核验代签（由 AI 汇报测试事实与实测结果，人工在会话确认后代签收口）
- **确认人**：sivan（AI 代签）
- **核验日期**：2026-09-22
- **结论**：核验通过
- **会话确认记录**：用户在会话中明确核验通过（全量测试 226 项后端、157 项脚本、180 项前端、37 项 E2E 与 CI/CD 流水线配置均已验证通过）
- **版本归档**：
  - 关联提交：`待提交`
  - 纳入版本：`[0.1.0](../../../CHANGELOG.md)`
