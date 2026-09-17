# T09 REST 与鉴权幂等

> **任务ID**：T09 ｜ **所属里程碑**：[M5-API全能力层](../plan/M5-API全能力层.md)
> **设计依据**：[02-后端设计方案](../design/02-后端设计方案.md) §2.2 F2/F8、§3.3、§4.1（API-first）、§4.6、§5.1、§5.2、§5.4、§6.3、§6.12
> **依赖**：[T05](T05-交易员服务.md)–[T08](T08-会话服务与日切.md) ｜ **下游**：[T10](T10-WebSocket与实时推送.md)（握手鉴权复用）、[T14](T14-验收与性能基准.md)（UI↔API 对照）
> **状态**：已完成（2026-09-17） ｜ **最后更新**：2026-09-17

---

## 1. 目标与范围

REST 全端点与四横切中间件（鉴权/幂等/限速/审计）、观察员初始化（02 §5 / §6.3）。API-first 纪律：**UI 能做的 API 都能做**（§4.1），端点覆盖以 §5.2 表为唯一清单。

## 2. 任务明细

### T09-1 API 通用约定
- **内容**：统一错误模型 `{"code", "message", "details"}`（§5.1）；游标分页参数与 `nextCursor` 响应（复用 [T02-4](T02-持久层与Schema.md) helper）；pydantic 请求/响应模型全端点覆盖（OpenAPI 完整，F8）。
- **交付物**：通用层 + 模型集。
- **验收标准**：OpenAPI 导出含全部端点与模型；分页参数边界用例。

### T09-2 全端点实现（§5.2 表）
- **内容**：逐项实现：`GET /session`；`GET /market/quotes|kline|minute`；`GET /templates`；`GET|POST /traders`；`GET|PATCH|DELETE /traders/{id}`；`POST /traders/{id}/reset|capital`；`POST|DELETE /traders/{id}/orders(/{orderId})`；`GET /traders/{id}/orders|trades|positions|equity|metrics`；`GET|POST /traders/{id}/plans` 与 `GET|PATCH|DELETE /plans/{id}`；`GET|POST /plans/{id}/entries` 与 `DELETE /plans/entries/{id}`；`GET /traders/{id}/export`；`GET /traders/events`；`GET /audit`。请求/响应与 §5.2 示例一致（含下单的 `clientOrderId`、创建交易员的 `template`/`initCash`/`plan`）。
- **交付物**：`api/` 路由层。
- **验收标准**：端点 ↔ §5.2 表逐项勾稽清单（文档化）；每端点至少一条正例 + 一条错误例。

### T09-3 观察员初始化
- **内容**：首次启动创建唯一观察员（`sync_state.observer_initialized`，§3.3）；观察员无账户、不交易、不入排行榜（Q1 决议边界在此固化）。
- **交付物**：初始化逻辑（挂 [T01-6](T01-工程骨架与配置.md) lifespan）。
- **验收标准**：首启创建；重启不重复；观察员不可被创建为交易员等边界约束。

### T09-4 鉴权（默认免鉴权，Q4 决议）
- **内容**：默认免鉴权：仅监听 127.0.0.1 + 启动日志告警；配置 `QTV_API_KEY` 后：REST 全端点校验 `X-API-Key`（**常量时间比较**）、WS 握手经 `?key=` 或 `Sec-WebSocket-Protocol`（供 T10 复用）；`QTV_PUBLIC_READ=true` 放行只读端点；未授权 `UNAUTHORIZED`。
- **交付物**：鉴权中间件。
- **验收标准**：§6.12 鉴权矩阵（有/无 Key × PUBLIC_READ × 读/写）全组合用例。

### T09-5 幂等（Idempotency-Key）
- **内容**：全部写操作接受 `Idempotency-Key` 头（订单亦可 `clientOrderId`，§5.1）；重复提交返回**首次结果**；键冲突且请求体不一致 → `DUPLICATE_REQUEST`；与 [T07-4](T07-交易服务.md) 服务层兜底双层配合。
- **交付物**：幂等中间件 + 键存储（SQLite）。
- **验收标准**：§6.12 幂等重放断言；同键不同体的冲突用例；过期策略（实施时定）登记变更记录。

### T09-6 限速（令牌桶）
- **内容**：令牌桶 `QTV_RATE_LIMIT`（默认 20 req/s）；超限 `429` + `Retry-After`。
- **交付物**：限速中间件。
- **验收标准**：突发与持续速率双用例；`Retry-After` 值合理。

### T09-7 审计中间件
- **内容**：全部非 GET 请求落 `audit_log`（who=observer / method / path / target / payload 摘要**不含密钥** / status_code，§6.2）；**失败请求同样记录、鉴权关闭时同样生效**（§6.3）；`GET /api/audit` 游标查询。
- **交付物**：审计中间件 + 查询端点。
- **验收标准**：§6.12 审计断言（含失败请求与免鉴权模式）；payload 无密钥泄漏检查。

### T09-8 UI↔API 对照准备
- **内容**：按 [01 §7.2 映射表](../design/01-前端设计方案.md)输出"UI 能力 → 端点"清单草案，交 [T14-3](T14-验收与性能基准.md) 终审（防能力漂移，§6.12）。
- **交付物**：对照清单草案。
- **验收标准**：01 §7.2 每行均有对应端点或显式标注缺口。

## 3. 完成定义（DoD）

- [ ] 八个条目验收全过；
- [ ] §5.2 端点勾稽清单全勾；
- [ ] 四横切中间件（鉴权/幂等/限速/审计）独立可测、组合无相互干扰；
- [ ] [M5 退出条件](../plan/M5-API全能力层.md)中 REST 侧项达成。

## 4. 设计 ↔ 任务条目映射

| 设计章节（02） | 条目 |
|---|---|
| §5.1 通用约定（错误模型/分页/幂等/限速） | T09-1、T09-5、T09-6 |
| §5.2 REST 全表 | T09-2 |
| §3.3 / §6.3 观察员与鉴权 | T09-3、T09-4 |
| §3.3 审计 / §6.2 audit_log | T09-7 |
| §6.11 前端影响清单（对接侧） | T09-8 |

## 5. 变更记录

- v1（2026-09-16）：随 [00-总体开发计划](../plan/00-总体开发计划.md) v1 制定。待登记：幂等键过期策略（T09-5 实施时）。
- 实施记录（2026-09-17）：幂等键暂无过期策略（存续于 idempotency_keys 表，量级极小，需要时再引入 TTL）；交易员行响应统一驼峰契约（trader_public）；pydantic 校验失败统一映射 BAD_REQUEST 错误模型。
