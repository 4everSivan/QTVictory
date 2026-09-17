# 开发环境与治理指南 (env/)

> **定位**: 开发环境配置、依赖管理、磁盘缓存盘点与环境安全清理规范
> **适用平台**: macOS (Darwin) / Linux

---

## 1. 文档清单

| 文档 | 核心内容 | 状态 |
|---|---|---|
| [01-环境缓存与依赖清理指南.md](01-环境缓存与依赖清理指南.md) | 盘点开发过程中产生的本地与全局缓存（含 Playwright Chromium ~563MB、node_modules ~126MB、venv ~35MB、全局 npm/uv 缓存 ~1.3GB），提供分级清理命令与一键重置指引 | 现行有效 |

---

## 2. 常用分级清理命令速查

- **日常轻量瘦身（不破坏依赖，耗时 1 秒）**：
  ```bash
  rm -rf backend/.pytest_cache frontend/dist frontend/*.tsbuildinfo frontend/coverage
  find backend -type d -name "__pycache__" -exec rm -rf {} +
  ```

- **重置为空世界首启态（清除运行时数据库）**：
  ```bash
  rm -f backend/data/qtvictory.db*
  ```

- **工作区纯净还原（释放 ~160 MB）**：
  ```bash
  rm -rf backend/.venv backend/data/qtvictory.db* backend/.pytest_cache
  rm -rf frontend/node_modules frontend/dist frontend/*.tsbuildinfo
  ```

- **全局深度释放（清理 Chromium 与全局缓存，释放 ~2 GB+）**：
  ```bash
  rm -rf ~/Library/Caches/ms-playwright
  uv cache clean && npm cache clean --force
  ```
