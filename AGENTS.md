# AGENTS.md

> QTVictory 协作红线 —— 给 AI Agent 与贡献者的流程底线。完整文档规范见 [docs/README.md](docs/README.md) §3。

## 流程红线（不可绕过）

1. **变更先行卡**：Bug 修复 / 功能回调 / 参数调整 / 接口微调，先在 `docs/devel/change/` 复制 `template.md` 建 `C00x` 变更卡，再动代码；严禁跳过。
2. **任务卡只读**：`docs/devel/task/` 与 `docs/devel/plan/` 已随 Phase 1 封存归档，一律不修改；Phase 2 立项才可在 plan/task 新建卡片。
3. **design 活基线与双向回链**：变更涉及设计规则时，同步修订 `docs/devel/design/` 对应章节（保持全文自洽），对应章节原位增补回链（`> 📌 **关联变更**: [C00x]...`），文末变更记录增补条目并回链 C 编号，头部"关联变更"追加 C 编号，杜绝单向孤岛。
4. **CHANGELOG 同步**：核验通过的 C 卡按 semver 记账（规则见 [docs/README.md](docs/README.md) §3.3），CHANGELOG 条目与 C 卡双向互链。
5. **元数据契约**：文档头部引用块 `**键名**: 值 ｜ 键值`——半角冒号加单空格、全角竖线分隔、状态枚举纯净（禁括号小尾巴）、日期 ISO `YYYY-MM-DD`。
6. **锚点纪律**：章节号只增不插中间；废弃章节原位保留并标注 `[已废弃]`，编号不复用。

## 入口流程

两类工作各走一条链路，共同遵守：文档先行 → 开发 → 测试 → 验收，每步产出落在对应目录，不跨步、不省略。

### 功能设计入口（新功能 / 新 Phase 立项）

1. **方向登记**：在 `docs/devel/TODO.md` 登记方向级事项（仅方向，不写实现细节）。
2. **设计稿先行**：在 `docs/devel/design/` 新增或修订对应章节，头部状态从 `讨论中` 起步，评审通过后改 `现行基线`。
3. **立项拆解**：在 `docs/devel/plan/` 新建 M 卡、`docs/devel/task/` 新建 T 卡（编号只增不插）；Phase 2 起才允许新建，Phase 1 卡片已封存。
4. **开发**：按 T 卡范围与 DoD 执行，不超范围。
5. **测试**：跑下方"测试命令"全部适用项，结果写入验收材料。
6. **验收**：在 `docs/devel/report/` 新建验收报告（结论枚举：通过 / 受限通过 / 未通过）。
7. **收口**：验收通过的 T 卡冻结为只读；按 §3.3 同步 `CHANGELOG` 与版本号，打对应 `git tag`。

### Bug 修复入口（缺陷 / 功能回调 / 参数调整）

1. **登记与建卡**：发现 Bug 先在 `docs/devel/TODO.md` 对应版本章节登记，再在 `docs/devel/change/` 复制 `template.md` 建 `C00x`（编号只增），类型枚举：BugFix / Rollback / Refactor / Param。
2. **对比表与 Checklist**：卡内填前后对比表，列清影响面与回滚方式。
3. **改代码 + 补测试**：实现修复并补回归测试，跑下方"测试命令"。
4. **同步 design**：涉及设计规则时修订 `docs/devel/design/` 对应章节（红线 3）。
5. **对齐核验与收尾**：AI 执行测试与实测后在会话中向人工汇报核验事实；人工确认后，AI 代为在卡内签署收口（记录会话确认依据），卡状态由 `待核验` 转为 `核验通过` / `核验驳回`，无需人工手动改写文档。
6. **合入**：核验通过后才允许合入主干。
7. **双向回写闭环**：design 对应章节原位增补回链提示、文末变更记录增补条目回链 C 编号、头部"关联变更"追加；按 §3.3 记 `CHANGELOG`（双向互链）、需要时打 `git tag`。

细则与状态枚举：变更卡见 [docs/devel/change/README.md](docs/devel/change/README.md)；六类目录契约见 [docs/README.md](docs/README.md) §3。

## 测试命令（核验必跑）

- 后端：`cd backend && pytest`
- 前端：`cd frontend && npm test`（Vitest 单测）+ `npm run build`（tsc + Vite 构建）
- E2E：`node frontend/scripts/e2e.mjs`（Playwright 无头几何验收）

## 测试环境（隔离红线）

测试环境部署与运行细则见 [docs/guide/02-测试环境部署指南.md](docs/guide/02-测试环境部署指南.md)，以下为不可绕过的隔离红线：

1. **产物收拢 `local/`**：测试产生的数据库、日志、框架缓存、截图与临时文件全部写入 `local/`（已 gitignore），严禁向 `backend/`、`frontend/` 源码树扩散脏文件。
2. **资源隔离**：测试实例必须用 `QTV_PORT=8788`、`QTV_DB=local/data/qtvictory_test.db`，不得占用生产默认端口 `8787` 与 `backend/data/qtvictory.db`。
3. **环境复用优先**：优先复用已激活虚拟环境 → `backend/.venv` → `local/.venv`，均无才在 `local/.venv` 新建。
4. **长期保留**：测试环境默认长期保留，不随测试结束销毁；仅在需要时按指南第 8 章分级清理。

## 文档地图

- 设计事实源：`docs/devel/design/`（01 前端 / 02 后端）
- 变更核验：`docs/devel/change/`
- 待办与缺陷清单：`docs/devel/TODO.md`（按当前版本与 future 分类登记缺陷与功能规划）
- 验收证据：`docs/devel/report/`、`docs/devel/assessment/`
- 部署运维：`docs/guide/`（01 单机部署运维 / 02 测试环境部署）
