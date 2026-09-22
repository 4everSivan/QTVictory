# 变更日志 (Changelog)

本项目的所有显著变更均将记录于此文件中。

本变更日志格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，并且本项目遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/) 规范。

---

## [0.1.0] - 2026-09-17

### 概述 (Overview)

**QTVictory 0.1.0** 是首个正式功能基线版本（**Phase 1 · 模拟底座与观察员控制台**）及其维护期演进（该版本尚未打 tag，发版时统一核定版本号）。系统确立纯私人、单机自部署定位的 A 股实时前向仿真模拟交易系统，完整实现规则级撮合引擎、计划引擎、多交易员实例管理体系以及基于 Nothing 设计系统的现代化 Web 监控控制台。

---

### 变更 (Changed)
- **K线分析工具布局归位**（[C021](docs/devel/change/C021-K线工具布局修正.md)）：M18 落地后控件位置修正——MA/EMA/BOLL 叠加开关归位顶栏第二胶丸组（D4 口径）、VOL/MACD/RSI/KDJ 副图胶丸沉底为图表区底部胶丸组与顶栏上下对称（用户拍板，修订 D2 口径）、图例补周期标签；附带修复空数据 + 光标路径越界崩溃。详见变更卡 [C021](docs/devel/change/C021-K线工具布局修正.md)。
- **K线分析工具（多周期K线数据底座 + 前端图表）**（里程碑 [M18](docs/devel/plan/M18-K线分析工具.md)，任务 T25/T26/T27，来源 FT-0009）：后端冷热双态 bar 模型——`kline_view` 冷热合成（klines 完结冷序列 ∪ 当日热 bar，降级缺 OHLC/停牌诚实少一根不造假）、换日捕获自沉淀（源门禁：tencent/sina 必落、eastmoney 视 OHLC、anchor 恒不落，幂等可重入）、校准重拉深度 ≥ 库存深度、日K引导深度 320 → 800 可配（`QTV_KLINE_DEPTH`，单源失败回落 320）；week/month 纯函数聚合（ISO 自然周/自然月，OHLCV 归约，date 取 period 末交易日，不落表不缓存），`GET /market/kline` period 枚举放行 `day|week|month`（limit = 聚合后根数，C013 移除的 minute 假参数保持拒绝）。前端四周期 Tab（分时｜日K｜周K｜月K）、单副图槽位 VOL｜MACD｜RSI｜KDJ、主图叠加 MA｜EMA｜BOLL、图例与指标色阶令牌（ind3/ind4/ind5）、`ema/macd/rsiWilder/boll/kdj` 纯函数 + golden vectors 单测锚定；§5.1 MA 透明度阶梯废止改色相阶梯。详见 02 §3.11（v7.0 转正）、01 §5.5（v6.0 转正）。
- **品种准入白名单（UNSUPPORTED_BOARD）**：撮合/下单/计划仅覆盖沪深主板/创业板/科创板个股；指数/基金/债券/北交所等行情可及品种下单 400、计划创建 422 `UNSUPPORTED_BOARD` 拒单；前端 errors 映射 field 级文案。详见变更卡 [C015](docs/devel/change/C015-品种准入白名单.md)。
- **最近交易日分时引导**：`/api/market/minute` 缺省查询经回退仍无数据时，在线触发腾讯 `app/day/query` 拉取**最近一个交易日**全量分时（242 点，与实时落桶同时段门禁与量纲，失败 10 分钟冷却）幂等落库并返回——周末/非交易时段选中标的即可见最近交易日完整分时；Q8"历史分钟不回补"边界修订为仅放行最近交易日单日引导（2026-09-20 会话拍板）。详见变更卡 [C019](docs/devel/change/C019-最近交易日分时引导.md)。
- **分钟线盘中增量落库**：当日分时由"次日日切一次性落库"升级为 新分钟桶增量 upsert + 停机终态刷盘 + 日切收口 三层保障（幂等写入），当日盘中即可经 `/api/market/minute` 读取，盘中崩溃/重启损失收敛到当前未完成分钟。详见变更卡 [C012](docs/devel/change/C012-分钟线盘中增量落库.md)。
- **行情数据源扩充与降级链增强**：快照降级链由 腾讯→东财→锚点 扩充为 **腾讯（https→http 协议兜底）→ 新浪（https + Referer 头）→ 东财 → 锚点**，`source` 透出枚举新增 `sina`（前端契约同步）；新浪档自带五档与当日累计量，视同主源完整档参与 ΔV 差分与盘口撮合（非降级语义）；日K 启动引导增加东财 push2his 兜底。本机连通性实测与字段口径对齐详见变更卡 [C008](docs/devel/change/C008-行情数据源扩充与降级链增强.md)。
- **浅色主题接入与三态主题切换**：新增浅色明晰风套系（语义色色相不变、按浅色背景调校明度保对比），顶栏主题按钮按 浅色→深色→跟随系统 循环，模式持久化 `localStorage qtv_theme`，跟随系统经 `prefers-color-scheme` 实时解析；终端深蓝套系维持废弃。详见变更卡 [C002](docs/devel/change/C002-浅色主题细节接入.md)。
- **主题收敛为单一 Nothing 深色套系**：移除终端深蓝备选皮肤、顶栏主题切换按钮与主题持久化机制，全站唯一主题。详见变更卡 [C004](docs/devel/change/C004-主题收敛为单一Nothing深色套系.md)。（其移除的切换机制已由 C002 以三态形态重建。）
- **`GET /api/traders/{id}` 详情响应增补 `strategyParams`**：返回当前生效策略参数（manual 为 null），前端交易员编辑弹窗以此回填，消除模板默认值静默覆盖自定义参数的风险。详见变更卡 [C003](docs/devel/change/C003-交易员编辑态strategyParams读取端点.md)。

---

### 维护与修复 (Fixed)
- **治理自检脚本取证失效与门禁逃逸缺陷修复（19 项）**（[C023](docs/devel/change/C023-修复治理自检脚本取证失效与门禁逃逸缺陷.md)）：`scripts/jev_workflow_check.py` 首次作为红线 7 门禁投入实战后，经对抗性复查 + 本地实证发现 19 项缺陷并一次修完。无声失效类：零沉淀账本正则漏配复合流转 `EN-0002/EN-0003 已流转至 [C002]/[C003]`，EN-0002 整个从账本消失、EN-0003 被错配，`sediment_violations` 静默放行；`--offline` 跳过代码侧硬判，非法状态只打印不门禁、退出码仍为 0；`sync_complete` 取证指令引用不存在的 `latest_change_card`；`call_jev` 读体/解码/解析异常逃逸成契约外 exit 1；`validate_response` 不校验置信与概率类型，畸形响应留到打印阶段崩溃。误拦类：`cross_check` 逐事实独立设约束，把本仓库常态（新卡待核验 + 上一卡已核验未合入）判成矛盾，3 次实跑全部误拦 exit 4；低置信语义判定被当作硬判据（实跑置信 0.30~0.52 照样拦）；noul 型答案无 `confidence` 字段却永久打「⚠ 低置信」噪音。修复：流转账本改 ID 组/链接组按位置配对（不漏记）；offline 同权执行代码硬判；新增 `expected_stage()` 按最早未完成步骤推唯一期望阶段；`semantic_review_items()` 把未过 0.60 置信门禁的判定降级为人工复核（退出码 6），`detect_violation()` 只把过门禁的判定当硬判据；新增 `frozen_dir_dirty` 断言让红线 2 可确定性判定；`unmerged_cards` 判别从字面「待提交」改为非 commit hash 即未合入；凭据解析兼容 `export` 前缀；git 输出显式 utf-8。回归保护：`scripts/tests/` 新增 123 项单测。详见变更卡 [C023](docs/devel/change/C023-修复治理自检脚本取证失效与门禁逃逸缺陷.md)。
- **calc_fee 过户费率高估 10 倍**：`calc_fee` 原按 `amount × 0.0001`（万分之一）计收过户费，与中证登 2022-04-29 起现行口径（成交金额十万分之一、双向收取）差 10 倍，系统性高估费用、低估净值与超额基准。已对齐为 `0.00001`；前后端费率镜像（`validate/order.ts` 费用预估）与存量断言同步修订。详见变更卡 [C020](docs/devel/change/C020-修复calc_fee过户费率高估10倍.md)。
- **下单 `marketType` 显式 null/缺省被 422 拒绝**：契约容忍并归一 `best5_cancel`（限价单不落类型），市价单缺省/显式 null 均 201 正常落单。详见变更卡 [C016](docs/devel/change/C016-下单marketType空值容忍.md)。
- **分时数据链路三缺陷（分时无数据/不出数）**：① 分钟桶无时段门禁，盘后/周末快照 ts（15:33–18:15 等）落成前端不可见的槽外垃圾桶污表——已对齐 242 槽窗口（09:30–11:30 / 13:00–15:00）落桶；② `/api/market/minute` 缺省 date 恒取 trading_date，非交易时段恒空——已改为该日无行时回退该码最近有分时数据的交易日（响应 `date` 如实标识，显式 date 精确查询不变）；③ 前端 minute 缓存选中即永久、盘中须手动 reload——已改为随 quotes 包络分钟戳滚动刷新（每分钟至多一次），盘中免 reload 逐分钟出数。详见变更卡 [C018](docs/devel/change/C018-分时数据链路修复.md)。
- **trading_date 未来日期无守卫致日切滚雪球（分时无数据根因）**：周末日切把交易日期推进到次交易日（周一 > 真实当日）后，原 `!=` 触发条件每轮 poll 再伪日切一天，约每 8s 一天无限前滚（实测滚至 2028），每次伪日切附带日K重拉打满上游，且 `trading_date` 停在未来日期致 `/api/market/minute` 默认日期查询恒空、前端分时恒"积累中"。已加未来日期守卫：仅在库存日期 < 真实当日时触发日切，未来日期 ≤7 天（跨周末/法定连休的次交易日）保持、大幅超前告警重同步为真实当日。详见变更卡 [C017](docs/devel/change/C017-修复tradingdate未来日期无守卫致日切滚雪球.md)。
- **`/api/market/kline` period=minute 假参数**：`period` 校验原放行 `day | minute` 但路由恒返回日K行，误导调用方拿日K冒充分钟线。已收紧为仅放行 `day`（其余值 400 `BAD_REQUEST`，message 指引分时走 `/api/market/minute`），错误回执顺手对齐统一错误模型（原 200 + 错误 dict）；`week|month` 待 02 §3.11 立项后放行。详见变更卡 [C013](docs/devel/change/C013-修复kline接口period假参数.md)。
- **日K"每日增量"noop 致长运行 klines 末根冻结**：日切步骤 5 原为空操作，运行时无任何日K重拉路径，`ma_cross` 收盘口径与超额基准实际在用陈旧收盘价。已落实为日切触发关注集日K重拉（腾讯 ifzq → 东财兜底链，幂等 upsert，单码失败不阻断日切，离线为空操作）。详见变更卡 [C014](docs/devel/change/C014-修复日K每日增量noop改日切关注集重拉.md)。
- **腾讯源时间戳致分钟线单桶失真**：快照字段 30 实为 `YYYYMMDDHHMMSS`（无冒号），分钟累积的无冒号兜底把当日全部 tick 挤进 "09:31" 单桶，收盘落库后当日分时仅一根。已在适配器层统一归一为 `HH:MM:SS`，不可解析时间戳（如降级源空 ts）不再落桶。详见变更卡 [C010](docs/devel/change/C010-修复腾讯源时间戳致分钟线单桶失真.md)。
- **计划标的池裸码静默落空**：plan `scope.codes` 原样落库，裸 6 位码（如 `601318`）与行情前缀码口径不一致，计划条件单静默不触发。已建立与自选同源的代码归一（创建校验 + 读取边界存量愈合，非法码 422 拒绝）。详见变更卡 [C011](docs/devel/change/C011-修复计划标的池裸码不归一静默落空.md)。
- **suggest 联想名称 unicode 转义未解码**：腾讯 smartbox hint 串名称字段为字面 `\uXXXX` 转义文本，`parse_suggest_payload` 原文透传导致联想下拉名称不可读。已补正则反转义还原（直编码中文路径不受影响），E2E 中文名称断言恢复。详见变更卡 [C009](docs/devel/change/C009-修复suggest联想名称unicode转义未解码.md)。
- **按钮样式未对齐原型重置**：生产仅移植了按钮颜色重置（C006），字体/背景/边框/指针仍走 UA 默认，按钮渲染系统字体而非 Space Grotesk 三族。已补全为 v1 原型完整口径 `font: inherit; color: inherit; background: none; border: none; cursor: pointer`。详见变更卡 [C007](docs/devel/change/C007-按钮重置全量对齐原型口径.md)。
- **交易员切换器名称黑字不可辨**：生产移植丢失 v1 原型的全局按钮重置，`button` UA 默认 `color: ButtonText`（黑）不继承正文文本色。已补回全局 `button { color: inherit }` 并重归一。详见变更卡 [C006](docs/devel/change/C006-按钮颜色继承重置缺失修复.md)。
- **滚动条样式缺失**：生产移植丢失 v1 原型的全局细滚动条样式，逐笔成交/下单面板等溢出区域露出浏览器原生粗亮滚动条。已补回全局 8px 细条（`--line2` thumb / 透明 track / Firefox `scrollbar-width: thin`），深浅套系令牌驱动自适应。详见变更卡 [C005](docs/devel/change/C005-滚动条样式缺失修复.md)。
- **日K 引导入库元组缺 code 导致 klines 表永空**：`TencentAdapter.fetch_daily_klines` 返回 6 元组与 `DataStore.upsert_klines` 的 7 元组契约不匹配，启动引导静默失败，前端"日K"页签永远空白。已对齐为 7 元组契约并补适配器→store 契约回归测试。详见变更卡 [C001](docs/devel/change/C001-修复日K引导入库元组缺code.md)。

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
  - 三态主题规范（浅色/深色/跟随系统，C002；深色为 Nothing 纯黑默认基线，终端深蓝套系 C004 起废弃）。
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
  - 监听真实浏览器运行时，断言主题三态切换与全链路控制台 Console 零报错（22 项几何与交互验收全过）。

#### 5. 工程与开发规范文档 (Documentation)
- **架构方案**：前端设计规范 [01-前端设计方案.md (v5.0)](docs/devel/design/01-前端设计方案.md) 与后端设计方案 [02-后端设计方案.md (v6.0)](docs/devel/design/02-后端设计方案.md)。
- **开发计划与任务卡**：19 篇里程碑计划（`docs/devel/plan/M1–M17`）与 24 篇任务细化卡（`docs/devel/task/T01–T24`）。
- **终验报告**：[01-M8 后端验收报告.md](docs/devel/report/01-M8-验收报告.md)、[02-M16 前端验收报告.md](docs/devel/report/02-M16-前端验收报告.md) 与 [03-M17 自选股编辑验收报告.md](docs/devel/report/03-M17-自选股编辑验收报告.md)。
- **环境治理**：[01-环境缓存与依赖清理指南.md](docs/devel/env/01-环境缓存与依赖清理指南.md)，规范磁盘缓存与依赖清理路径。
- **待办缓冲池**：`docs/devel/todo/` 未入轨缺陷与需求登记（按版本分文件、落地即移出零沉淀、BG/EN/FT/TD 编号契约）。
- **治理规则**：变更核收 AI 汇报 + 会话确认代签；design 章节、变更卡与 CHANGELOG 双向互链；测试环境《部署验收单》（`local/deployment-report.md`，现实绑定维护命令与 Cmd+点击前端入口）。

#### 6. 维护期增补 (Post-Phase-1 Enhancements)
- **自选股编辑**（里程碑 [M17](docs/devel/plan/M17-自选股编辑.md)，验收 [R-M17](docs/devel/report/03-M17-自选股编辑验收报告.md)，来源 FT-0001）：观察员级全局自选集增删标的（品种不限），行情关注集扩为 自选 ∪ 持仓 ∪ 计划池 ∪ 指数；新增端点 `GET /api/watchlist`、`PUT/DELETE /api/watchlist/{code}`（单码幂等、裸码按板块规则归一前缀码落库）、`POST /api/watchlist/batch`（逐码校验、部分应用、逐码回执 `{code, op, ok, error}`）、`GET /api/market/suggest`（腾讯 smartbox 联想代理，GBK 解码 + 30s 缓存）；添加即异步引导日K 历史（腾讯 ifzq → 东财 push2his 兜底，批量串行排队）；前端自选股列表 "+" 弹层联想添加、hover 删除（动态项不可删）、自选置顶按添加时间倒序。
