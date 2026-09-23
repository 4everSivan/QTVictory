# T26 多周期聚合与K线API

> **任务ID**: T26 ｜ **所属里程碑**: [M18-K线分析工具](../plan/M18-K线分析工具.md) ｜ **状态**: 已完成
> **前置依赖**: [T25-冷热双态bar模型](T25-冷热双态bar模型.md)（`kline_view` 冷热合成序列为聚合基座） ｜ **后置下游**: [T27-K线图与指标副图](T27-K线图与指标副图.md)（消费 `period` 契约）
> **设计依据**: [02-后端设计方案](../../../devel/design/02-后端设计方案.md) §3.11（多周期聚合 / API 修正，v6 · 讨论稿）、§5.2（kline 行 `period` 枚举） ｜ **最后更新**: 2026-09-20

---

## 1. 目标与范围

在 `kline_view`（T25）之上落地**纯函数聚合内核**并放行 `period` 枚举：week 按 ISO 自然周（周一界）、month 按自然月切分；period 内首日 open、末日 close、max high、min low、sum volume；周/月 K 的 `date` 取该 period 内最后交易日（主流行情软件口径）；**不落表、不缓存**（单码 ≤800 行 O(n) 聚合，本机单用户量级无缓存意义）。`GET /market/kline` 的 `period` 放行 `day | week | month`，其余值 400 `BAD_REQUEST`（minute 假参数已随 C013 移除，保持拒绝）。

明确不做：源端原生周/月 K（已否决：klines 单一事实源、聚合与库内精确一致，Q10）；前端图表（归 T27）；冷热双态模型本体（T25 已交付）。

## 2. 任务明细

### T26-1 week/month 纯函数聚合内核
- **内容**：聚合纯函数（period 内 OHLCV 归约 + `date` 取末日交易日）；week ISO 自然周（周一界）/ month 自然月切分；对 `kline_view` 输出聚合（冷热合成之上）。
- **交付物**：聚合纯函数 + 单测。
- **验收标准**：跨年周界、节假日短周、单交易日周、月末切分、`limit` 作用于**聚合后**根数（week 按约 5N+缓冲换算取日K再截尾）全场景单测；800 根日K → 约 165 周K / 38 月K 量级核对。

### T26-2 API 契约放行
- **内容**：`market_kline` 路由 `period` 校验收紧为 `day | week | month`（非 day 值走聚合分支）；错误模型保持 C013 落地的 `BizError` 400。
- **交付物**：路由层接线 + 契约测试。
- **验收标准**：`period=week|month` 实测返回聚合序列；`period=minute` 及其他非法值 400 `BAD_REQUEST`（含 C013 回归断言）。

### T26-3 端到端正确性断言
- **内容**：离线注入（`sync_klines`）→ `/market/kline?period=week|month` 聚合正确性断言（同数据手工归约对照）。
- **交付物**：集成测试。
- **验收标准**：聚合结果与手工归约逐字段一致；显式 `date`/`limit` 组合查询语义符合 §3.11。

## 3. 验收命令

- `cd backend && pytest`（含聚合单测、period 契约、离线注入集成断言）。
