# QTVictory 文档归档库 (Archive)

> **文档ID**: ARCHIVE-INDEX ｜ **定位**: 历史版本文档封存区（只读） ｜ **最后更新**: 2026-09-17

---

## 1. 定位与归档纪律

`docs/archive/` 存放**已随版本打 tag 封存的历史文档快照**。每当仓库打出一个版本 tag（如 `v0.1.0`），该版本对应的阶段性文档（里程碑计划、任务卡、验收报告、研发评估）即从 `docs/devel/` 物理迁移至 `docs/archive/<版本号>/` 对应目录下。

**归档红线**：

1. **只读封存**：`docs/archive/` 下所有文档一律不允许再修改。历史即证据，发现错误也不得回改——对现行系统的修正走 `docs/devel/change/` 变更卡，对认知的修正写在现行文档中；
2. **整体迁移**：归档以版本为单位整体迁移（`plan/`、`task/`、`report/`、`assessment/` 同进同出），保持归档内部交叉引用相对链接完好；
3. **活文档不归档**：`design/`（活基线）、`change/`（变更台账）、`todo/`（缓冲池）、`env/`（环境治理）始终留在 `docs/devel/` 持续演进；
4. **归档即更新索引**：每次归档必须同步更新本索引、`docs/README.md`、`docs/devel/README.md` 及全库指向旧路径的引用。

---

## 2. 归档索引

| 版本 | 目录 | 封存内容 | 对应 tag | 归档日期 |
|---|---|---|---|---|
| *（暂无归档——首个版本 tag 打出后按 §3 SOP 执行并在此登记）* | - | - | - | - |

---

## 3. 归档操作 SOP（打版本 tag 后执行）

1. 确认 CHANGELOG 该版本条目已合入、`git tag` 已打；
2. `mkdir -p docs/archive/<版本号>`，将 `docs/devel/` 下的 `plan`、`task`、`report`、`assessment` 四个目录 `git mv` 至 `docs/archive/<版本号>/`；
3. 修正归档文档内部指向 devel 活文档的相对链接（层级 +1：`](../design/` → `](../../design/`、`](../change/` → `](../../change/`）；归档四目录之间的相互链接无需改动；
4. 全库检索旧路径（`devel/plan`、`devel/task`、`devel/report`、`devel/assessment`），更新所有外部引用（导航、README、CHANGELOG、todo）；
5. 在本文件 §2 索引表登记新版本行，更新 `最后更新` 日期；
6. 新 Phase 立项时在 `docs/devel/` 下重建 `plan/` 与 `task/`；编号沿用只增序列（M、T 编号不复用已归档编号）。
