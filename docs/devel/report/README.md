# 阶段验收报告 (report/)

> **定位**: 记录项目关键阶段收口的正式验收报告与可复核机器证据
> **依据**: [01-前端设计方案 §11](../design/01-前端设计方案.md) 与 [02-后端设计方案 §6.12](../design/02-后端设计方案.md)

---

## 1. 验收报告清单

| 报告文档 | 验收对象 | 对应里程碑 | 核心证据与结论 | 状态 |
|---|---|---|---|---|
| [01-M8-验收报告.md](01-M8-验收报告.md) | 后端开发线（T01–T14） | M8 | - §6.12 财务勾稽（资金+持仓守恒，4 组复杂用例全部闭合）<br>- 并发撮合吞吐达 25,000 ops/s（远超 5,000 指标）<br>- REST/WS 接口与 UI 清单 100% 对齐无缺口 | **通过（收口）** |
| [02-M16-前端验收报告.md](02-M16-前端验收报告.md) | 前端开发线（T15–T22） | M16 | - 133 项 Vitest/jsdom 单元与组件测试全绿<br>- `smoke.mjs` 真实后端冒烟 11 项全过<br>- `e2e.mjs` 无头浏览器 19 项通过（1560×940 像素级几何全中、双主题 Console 零报错）<br>- 撮合成交因行情源环境受限真实登记 | **通过（收口）** |

---

## 2. 验收复验命令速查

### 后端基线复验
```bash
cd backend
source .venv/bin/activate
pytest tests/unit tests/service tests/integration -q   # 运行全量测试套件
python -m tests.benchmark.test_bench                 # 运行撮合与存储性能基准
```

### 前端基线复验
```bash
cd frontend
npm run test          # 133 项单元/组件测试
npm run build         # tsc -b && vite build 生产构建
node scripts/smoke.mjs # 真实后端 REST/WS 冒烟（需后端 8787 运行中）
node scripts/e2e.mjs   # 无头 Chromium 几何实测与 Console 零报错（需 Chromium）
```
