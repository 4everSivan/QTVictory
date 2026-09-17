# 变更日志 (Changelog)

本项目的所有显著变更均将记录于此文件中。

本变更日志格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，并且本项目遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/) 规范。

---

## [0.1.1] - 2026-09-17

### 修复 (Fixed)
- **日K 引导入库元组缺 code 导致 klines 表永空**：`TencentAdapter.fetch_daily_klines` 返回 6 元组与 `DataStore.upsert_klines` 的 7 元组契约不匹配，启动引导静默失败，前端"日K"页签永远空白。已对齐为 7 元组契约并补适配器→store 契约回归测试。详见变更卡 [C001](docs/devel/change/C001-修复日K引导入库元组缺code.md)。

---

## [0.1.0] - 2026-09-17

### 概述 (Overview)

**QTVictory 0.1.0** 是首个正式功能基线版本（**Phase 1 · 模拟底座与观察员控制台**）。该版本确立了纯私人、单机自部署定位的 A 股实时前向仿真模拟交易系统，完整实现了规则级撮合引擎、计划引擎、多交易员实例管理体系以及基于 Nothing 设计系统的现代化 Web 监控控制台。

---

### 新增 (Added)

#### 1. 核心领域与撮合引擎 (Domain & Matching Engine)
- **纯函数规则级撮合内核** (`backend/app/domain/engine.py`)：
  - **A 股制度仿真**：实现严格 T+1 交易规则、涨跌停硬限制、连续竞价有效申报范围（价格笼子 ±2%）。
  - **流动性与滑点模型**：支持买卖五档盘口撮合，单 tick 引入真实成交量 25% 上限约束（多实例共享池），形成真实流动性滑点与部分成交（Partial Fill）。
  - **交易时段状态机**：完整覆盖集合竞价（9:15–9:25）、开盘准备、连续竞价（9:30–11:30, 13:00–15:00）及收盘阶段限制。
  - **精准费用与冻结**：支持买入资金冻结、卖出股份锁定、印花税（千分之 0.5 单向）、过户费、经手费及佣金（最低 5 元保底口径）。
- **交易计划引擎** (`backend/app/domain/plan_engine.py`)：
  - 支持 4 类独立触发器：价格穿越（Price Break）、当日涨跌幅（Daily Change）、定时触发（Scheduled Time）、均线交叉（MA Cross）。
  - 实行四道围栏过滤：订单执行前强制经“标的池 → 资金预算 → 仓位目标 → 单笔限额”规则校验。
- **8 种内置量化策略模板** (`backend/app/domain/strategies.py`)：
  - 提供网格交易 (Grid)、双均线交叉 (Dual MA)、MACD 趋势、RSI 振荡器、布林带突破 (Bollinger Bands)、海龟通道 (Turtle)、动量跟随 (Momentum) 与超买超卖反转 (Reversal)。

#### 2. 后端服务与基础设施 (Backend Services & Infra)
- **持久层与存储服务** (`backend/app/store/`)：
  - SQLite 单文件数据库，开启 WAL (Write-Ahead Logging) 模式，零外部服务依赖。
  - 线程安全 DataStore，提供完整的 Schema 自动迁移、日切结算及全量观察员审计日志落库。
- **行情采集与三级降级链** (`backend/app/adapters/`)：
  - 腾讯公开行情接口轮询采集器（约 3 秒快照周期），支持东财备选接口与内置基准锚点（Anchor）兜底。
  - 行情异常中断时自动回落固定滑点保底档，并在订单层逐笔标记 `fill_model=fallback`。
- **观察员-交易员体系** (`backend/app/services/`)：
  - 确立“观察员唯一且不交易”原则：观察员为全局审计者，无资金账户、不下单；交易员支持任意数量与资金规模（`manual / strategy / plan / operator` 四种来源区分）。
  - 提供资产净值走势快照、仓位收益分析、分红除权除息处理及 CSV/JSON 双格式交易流水导出。
- **API-First 与网络通道** (`backend/app/api/`)：
  - 基于 FastAPI 构建异步 RESTful 接口与 WebSocket 双向实时数据通道（行情与事件订阅）。
  - 具备令牌桶限流、基于 `Idempotency-Key` 的写操作幂等保证、游标分页与统一错误包络。
  - 默认本机免鉴权（监听 `127.0.0.1:8787`），支持通过 `QTV_API_KEY` 环境变量按需启用观察员鉴权。

#### 3. 前端 Web 控制台 (Frontend Web Console)
- **Nothing 设计系统** (`frontend/src/styles/`):
  - 采用 Nothing 极简工业美学，以单色灰阶构筑信息层级，仅将红色用于数据语义。
  - 支持 Nothing Dark 与 Standard Light 双主题即时无缝切换。
  - 全屏数据数值统一强制 `tabular-nums`，执行 15px（数据）/ 14px（品牌）/ 12px（交互）/ 9px（微标签）四档字号纪律。
- **一屏式高密度监控工作台** (`frontend/src/components/panes/`):
  - **顶栏**：系统状态胶囊、交易员下拉切换器、均分五指标数据带（等分拉宽）、沪深300 指数及系统时钟。
  - **左栏**：自选股实时列表（带涨跌呼吸闪动与微型条形统计）及交易员多维度排行看板。
  - **中央主视区**：自适应金融图表组件（分时图、K 线图及净值走势曲线，基于纯 SVG 矢量渲染）。
  - **右栏**：实时五档买卖盘口、动态逐笔成交流（由买卖量差派生）及交易下单面板（限价/市价、滑点提示与交易员身份显性标注）。
  - **底部 Dock**：持仓一览、当日委托（带 `partial` 部分成交胶囊）、成交记录（按订单分组标示）与收益分析指标卡。
- **容灾与自愈连接机制** (`frontend/src/api/`):
  - 启动序：先经由 REST 获取全量基线数据，再无缝接入 WebSocket 增量推送。
  - 断线重连状态机：支持 1s → 2s → 4s → 15s 指数退避重连与全量自动续订。
  - 降级适配：当 WebSocket 不可用时自动切入 REST 轮询降级，并同步呈现行情降级徽标。

#### 4. 质量保障与自动化测试 (Verification & Tooling)
- **后端测试套件**：涵盖领域内核单测、服务层测试、端到端集成测试与并发基准测试。
- **前端测试套件**：133 个 Vitest / jsdom 单元与组件测试用例全部通过。
- **无头浏览器端到端验收** (`frontend/scripts/e2e.mjs`)：
  - 基于 Playwright + Chromium 自动化验证 1560×940 主视口各区域物理像素尺寸（误差 ≤ 1px）与 ≤1180px 响应式降级断点。
  - 监听真实浏览器运行时，断言双主题切换全链路控制台 Console 零报错。

#### 5. 工程与开发规范文档 (Documentation)
- **架构方案**：前端设计规范 [01-前端设计方案.md (v2.1)](docs/devel/design/01-前端设计方案.md) 与后端设计方案 [02-后端设计方案.md (v3)](docs/devel/design/02-后端设计方案.md)。
- **开发计划与任务卡**：18 篇里程碑计划（`docs/devel/plan/M1–M16`）与 22 篇任务细化卡（`docs/devel/task/T01–T22`）。
- **终验报告**：[01-M8 后端验收报告.md](docs/devel/report/01-M8-验收报告.md) 与 [02-M16 前端验收报告.md](docs/devel/report/02-M16-前端验收报告.md)。
- **环境治理**：[01-环境缓存与依赖清理指南.md](docs/devel/env/01-环境缓存与依赖清理指南.md)，规范磁盘缓存与依赖清理路径。
