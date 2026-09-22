# C026 - 修复 CI E2E 端口环境变量注入

> **卡片ID**: C026 ｜ **类型**: BugFix ｜ **状态**: 核验通过
> **创建日期**: 2026-09-22 ｜ **关联设计**: 无（本卡为 CI 工作流缺陷修复，不改动业务设计规则）

---

## 1. 变更背景与动因

C025 接入 GitHub Actions 自动化流水线后，首次推送触发 CI 运行，E2E 任务（`e2e` job）失败。

**根因**：`e2e.mjs` 通过 Vite `createServer()` 启动开发服务器时，虽然 `frontend/.env` 文件包含 `VITE_API_BASE=http://127.0.0.1:8788/api`，但在 GitHub Actions 环境中 Vite 的 `createServer()` 未正确加载 `.env` 文件中的环境变量。前端运行时回退到 `frontend/src/api/config.ts` 中的硬编码默认值 `http://127.0.0.1:8787/api`（端口 8787），而 CI 后端实际运行在 8788 端口，导致所有 API 请求失败。

**故障表现**：前端无法获取交易员列表 → `TraderSwitcher` 组件渲染空态按钮（`<button className="switcher-empty">`）→ `page.$eval('.switcher-name', ...)` 找不到目标元素 → 未捕获异常导致 E2E 脚本崩溃退出。

---

## 2. 规则与设计变更对照（人工核验重点）

| 维度 | 变更前（旧逻辑） | 变更后（新逻辑） | 取舍理由与影响边界 |
|---|---|---|---|
| **VITE_API_BASE 注入** | `e2e.mjs` 依赖 Vite 自动加载 `.env` 文件获取 `VITE_API_BASE` | 显式从 `QTV_PORT` 环境变量推导 `apiBase`，通过 Vite `define` 选项在编译时注入 `import.meta.env.VITE_API_BASE` | 消除对 `.env` 文件加载行为的隐式依赖，确保 CI 环境与本地行为一致 |
| **CI 工作流 env 声明** | E2E 步骤仅在行内 `QTV_PORT=8788 node ...` 传递环境变量 | E2E 步骤通过 `env:` 块显式声明 `QTV_PORT` 和 `VITE_API_BASE` | GitHub Actions 最佳实践，提升可读性与可维护性 |
| **CI 失败诊断** | 无后端日志转储 | 新增 `if: failure()` 步骤转储后端日志 `/tmp/backend-test.log` | 降低 CI 失败时的排查成本 |

---

## 3. 代码变更与受影响文件

- **核心实现**：
  - `frontend/scripts/e2e.mjs`：将 `backendPort` 提前到 `createServer()` 之前，新增 `apiBase` 推导逻辑，通过 `define: { 'import.meta.env.VITE_API_BASE': JSON.stringify(apiBase) }` 注入
  - `.github/workflows/ci.yml`：E2E 步骤添加 `env` 块（`QTV_PORT`/`VITE_API_BASE`），新增失败日志转储步骤

---

## 4. 人工核验清单（Checklist）

> 核验人照表逐项执行，全勾确认后方可合入主干。

- [x] **自动化测试**：
  - [x] 后端：226 passed ✅
  - [x] 前端 Vitest：180 passed (27 files) ✅
  - [x] 前端构建：TypeScript + Vite clean ✅
  - [x] Jev 治理脚本：157 passed ✅
  - [x] E2E Playwright：37 passed, 0 failed ✅
- [x] **行为/接口实测**：
  - [x] 本地 `QTV_PORT=8788 node frontend/scripts/e2e.mjs` 运行 37 项 E2E 全部通过
  - [x] 确认 `apiBase` 从 `QTV_PORT` 正确推导：默认 8787，`QTV_PORT=8788` 时为 `http://127.0.0.1:8788/api`
  - [x] `VITE_API_BASE` 环境变量优先级高于 `QTV_PORT` 推导值
- [x] **反向影响排查**：
  - [x] `e2e.mjs` 本地开发模式不受影响（默认 `QTV_PORT` 读 `.env` 或回退 8787）
  - [x] `define` 选项仅影响 E2E 开发服务器，不影响生产构建
- [x] **设计方案与双向回链**：
  - [x] 无需更新设计方案（本卡不涉及业务设计规则变更）
  - [x] [CHANGELOG.md](../../../CHANGELOG.md) 条目已登记并双向回链本卡

---

## 5. 核验结论与收尾

- **核验方式**：AI 对话核验代签（由 AI 汇报测试事实与实测结果，人工在会话确认后代签收口）
- **确认人**：sivan（AI 代签）
- **核验日期**：2026-09-22
- **结论**：核验通过
- **会话确认记录**：AI 汇报全量测试结果（后端 226 passed、前端 180 passed、构建 clean、jev 157 passed、E2E 37 passed）及根因分析与修复方案，人工确认通过
- **版本归档**：
  - 关联提交：`2de347c`
  - 纳入版本：`[v0.1.0](../../../CHANGELOG.md)`
