# QTVictory 文档归档库 (Archive)

> **文档ID**: ARCHIVE-INDEX ｜ **定位**: 历史版本文档封存区（只读） ｜ **最后更新**: 2026-09-23

---

## 1. 定位与归档纪律

`docs/archive/` 存放**已随版本打 tag 封存的历史文档快照**。每当仓库打出一个版本 tag（如 `v0.1.0`），该版本对应的阶段性文档（里程碑计划、任务卡、验收报告以及研发评分报告）即从 `docs/devel/` 物理迁移至 `docs/archive/<版本号>/` 对应目录下。

**归档红线**：

1. **只读封存**：`docs/archive/` 下所有文档一律不允许再修改。历史即证据，发现错误也不得回改——对现行系统的修正走 `docs/devel/change/` 变更卡，对认知的修正写在现行文档中；
2. **迁移范围与同进同出**：
   - 阶段性全量归档：`plan/`（里程碑计划）、`task/`（任务卡）、`report/`（验收报告）以版本为单位整体迁移；
   - **评分文档只归档报告、不归档规则**：`assessment/` 目录下**仅归档该版本的具体评分报告**（如 `03-评分报告.md`，迁移至 `docs/archive/<版本号>/assessment/` 封存），**评分规则（`01-评分标准.md`、`02-评分流程与证据清单.md` 及索引 `README.md`）作为跨版本长期复用的通用基线，常驻 `docs/devel/assessment/` 不归档**；
3. **活文档与通用规则不归档**：`design/`（活基线）、`change/`（变更台账）、`todo/`（缓冲池）、`env/`（环境治理）以及 `assessment/` 中的评分规则文档始终留在 `docs/devel/` 持续演进；
4. **归档即更新索引**：每次归档必须同步更新本索引、`docs/README.md`、`docs/devel/README.md` 及全库指向旧路径的引用。

---

## 2. 归档索引

| 版本 | 目录 | 封存内容 | 对应 tag | 归档日期 |
|---|---|---|---|---|
| v0.1.0 | [v0.1.0/](v0.1.0/) | Phase 1 里程碑计划（M1–M18）、任务卡（T01–T27）、阶段终验报告（01–04）与研发评分报告（03） | `v0.1.0` | 2026-09-23 |

---

## 3. 归档操作 SOP（打版本 tag 后执行）

1. 确认 CHANGELOG 该版本条目已合入、`git tag` 已打；
2. 执行物理迁移：
   - `mkdir -p docs/archive/<版本号>/assessment`；
   - 将 `docs/devel/` 下的 `plan`、`task`、`report` 三个目录整体 `git mv` 至 `docs/archive/<版本号>/`；
   - 将 `docs/devel/assessment/` 下该版本对应的评分报告（如 `03-评分报告.md`）`git mv` 至 `docs/archive/<版本号>/assessment/`；
   - **注意**：`docs/devel/assessment/` 下的 `01-评分标准.md`、`02-评分流程与证据清单.md` 与 `README.md` 必须原地保留，继续作为后续版本的评分规则事实源；
3. 修正归档文档内部指向 devel 活文档的相对链接（层级 +1：`](../design/` → `](../../../devel/design/`、`](../change/` → `](../../../devel/change/`、`](../assessment/01-` → `](../../../devel/assessment/01-`）；归档各目录之间的相互链接按实际相对层级校对；
4. 全库检索旧路径（`devel/plan`、`devel/task`、`devel/report` 及已迁移的评分报告路径），更新所有外部引用（导航、README、CHANGELOG、todo）；
5. 在本文件 §2 索引表登记新版本行，更新 `最后更新` 日期；
6. 新 Phase 立项时在 `docs/devel/` 下重建 `plan/` 与 `task/`；编号沿用只增序列（M、T 编号不复用已归档编号）。
