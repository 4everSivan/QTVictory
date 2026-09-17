# T16 数据层与 API 客户端

> **任务ID**：T16 ｜ **所属里程碑**：[M10-数据层与API客户端](../plan/M10-数据层与API客户端.md)
> **设计依据**：[01-前端设计方案](../design/01-前端设计方案.md) §6（错误码呈现）、§7（数据层全章）、§9（服务端状态缓存）
> **依赖**：[T15-工程骨架与样式基线](T15-工程骨架与样式基线.md)；后端接口事实源 [T09-REST与鉴权幂等](T09-REST与鉴权幂等.md)、[T10-WebSocket与实时推送](T10-WebSocket与实时推送.md)（均已完成） ｜ **下游**：[T17](T17-行情面板.md)、[T18](T18-图表组件.md)、[T19](T19-交易员模块.md)（全部展示层）
> **状态**：已完成（2026-09-17） ｜ **最后更新**：2026-09-17

---

## 1. 目标与范围

落地 01 §7 数据层与 §9 服务端状态缓存：`api/client.ts`（REST）、`api/ws.ts`（订阅管理）、`api/errors.ts`（错误码→文案映射）三件套 + 类型生成 + 连接策略（REST 全量初始化 → WS 增量；断线 REST 拉回再续订；WS 不可用自动轮询降级）。对接对象为已验收的后端真实 API（02 §5），**无 Mock 阶段**。

明确不做：任何 UI 组件（展示层归 T17–T21）；业务数据写 localStorage（§9 废止项）。

## 2. 任务明细

### T16-1 API 类型与契约
- **内容**：`openapi-typescript` 从后端 `/openapi.json` 生成 REST 类型；WS 消息类型按 02 §5.3 手写（五类 topic 的 `{"topic","data"}` 帧 + 订阅协议 `{op,topics}`）；`api/types.ts` 统一出口；WS 帧边界做轻量运行时校验（类型守卫，防后端字段漂移时静默错渲）。
- **交付物**：生成脚本 + 类型模块 + 守卫函数。
- **验收标准**：类型覆盖 01 §7.2 映射表全部端点与五类 topic；守卫对缺字段帧给出明确 console 错误而非渲染异常。

### T16-2 REST 客户端（api/client.ts）
- **内容**：base/key 经 `VITE_API_BASE` / `VITE_API_KEY` 注入（§7.1，`X-API-Key` 头透传，私人部署默认免鉴权）；统一错误模型解析（02 §5.1：code/message/details 结构，含 `PRICE_BAND` 的 details 区间透传）；游标分页 helper；导出下载（blob）helper——供 [T21](T21-计划收益与导出.md) 复用。
- **交付物**：REST 客户端模块。
- **验收标准**：对真实后端冒烟：`/api/session`、`/api/market/quotes`、`/api/traders` 全过；401/错误码路径有断言测试。

### T16-3 WS 订阅管理（api/ws.ts）
- **内容**：订阅协议 `{op:"sub",topics:[...]}`；五类 topic：`quotes` / `traders` / `trader:{id}` / `plans` / `events`（01 §7.2、后端 T10-2）；订阅注册/退订、按 id 动态订退 `trader:{id}`；断线指数退避重连；重连后触发「REST 全量刷新 → 续订」序（§7.3）；心跳保活。
- **交付物**：WS 管理模块 + 重连序状态机。
- **验收标准**：对真实后端冒烟：五类 topic 订阅均收到推送；`trader:{id}` 按 id 生效；手动断网恢复后自动重连并触发全量刷新（集成测试可注入断连）。

### T16-4 轮询降级与行情状态
- **内容**：WS 不可用时自动降级 REST 轮询（§7.3：quotes 3s / traders 5s），恢复后自动切回 WS；行情降级状态（`source/live/fallback`）解析并作为状态输出（T17 顶栏徽标、盘口 DEGRADED 条的输入）；降级切换对外暴露稳定接口（展示层无感）。
- **交付物**：降级策略模块。
- **验收标准**：WS 断开期间轮询持续供数且间隔符合 §7.3；恢复后无重复订阅/泄漏；`live/fallback` 状态断言正确。

### T16-5 错误码→文案映射（api/errors.ts）
- **内容**：01 §6 错误码表映射：`LOT_SIZE / PRICE_BAND（details 含区间，文案须给出两区间）/ INSUFFICIENT_FUNDS / T1_LOCKED / SESSION_CLOSED / STALE_QUOTE / PLAN_CONSTRAINT / RATE_LIMITED`；输出分级：下单面板校验文案（就地）vs Toast（全局）；文案表结构对齐 OpenAPI 后落 constants（§6 "文案表在实现阶段随 OpenAPI 对齐"）。
- **交付物**：错误映射模块 + 文案表。
- **验收标准**：每码有映射用例；`PRICE_BAND` 用真实 details 渲染含区间的文案；未识别码回落通用文案并 console 告警（不白屏）。

### T16-6 服务端状态缓存 hooks
- **内容**：轻量 `useQuery`/`useSubscription` 封装（§9：服务端状态由 WS 增量维护、REST 初始化与兜底；**不引重型状态库**）；缓存以 topic+参数为键；组件卸载退订；UI 态读写白名单 helper（localStorage 仅主题/上次选中交易员，§9）。
- **交付物**：hooks 模块 + 使用文档（docstring 示例）。
- **交付标准**：两个展示层消费方（如 T17 quotes、T19 traders）接入方式可各自 ≤10 行代码完成；同一 topic 多组件订阅不重复开 WS 连接/订阅帧。

## 3. 完成定义（DoD）

- [x] 六个条目验收全过；
- [x] 对真实后端（本地 uvicorn）数据层冒烟脚本全绿：`scripts/smoke.mjs` 11 项（REST 全量 + 五类 topic 协议 + 包络字段契约）；
- [x] 01 §7.2 端点映射表在类型层全覆盖（`src/api/types.ts` 手工契约，线上载荷逐字段核对）；
- [x] 单测覆盖：错误映射全码表、重连状态机（退避封顶）、降级切换、运行时守卫（vitest 51 用例全绿）。

## 4. 设计 ↔ 任务条目映射

| 设计章节（01） | 条目 |
|---|---|
| §7.1 架构（唯一数据源/鉴权透传） | T16-2 |
| §7.2 端点映射 | T16-1、T16-2 |
| §7.3 连接策略（重连/轮询降级/行情状态） | T16-3、T16-4 |
| §6 错误码 UI 呈现 | T16-5 |
| §9 服务端状态缓存 / UI 态白名单 | T16-6、T16-4 |

## 5. 变更记录

- v1（2026-09-17）：随 [00-前端开发计划](../plan/00-前端开发计划.md) v1 制定。
- 实施记录（2026-09-17）：完成——51 vitest 用例全绿 + `smoke.mjs` 对真实后端 11 项全绿。实现决策：① 后端 REST 200 多为 `unknown`（视图手工组包），`types.ts` 以线上实测载荷 + store schema 手工建契；列表端点（orders/trades/positions/plans/entries/events/equity）为 snake_case 原始行、详情/账户为驼峰视图，类型按实拆分；② `openapi-typescript` 生成 `schema.d.ts` 保留用于请求体校验模型，WS 五类 topic 类型 + 运行时守卫手写（`isServerFrame`）；③ WS 控制帧（ack/error）走 `onControl` 通道，不按主题分发；④ 降级轮询无宽限立即启动（§7.3 语义最直接，恢复即停）；⑤ 逐笔成交数据后端未单设端点，T17 以 quotes 推送 Δ 派生（T17 变更记录登记）。
