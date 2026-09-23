# QTVictory 前端（观察员控制台）

技术栈：TypeScript（strict）+ React 18 + Vite · 纯 SVG 图表 · Nothing 设计系统双主题。
设计事实源：`../docs/devel/design/01-前端设计方案.md`（v2.1）；开发计划：`../docs/archive/v0.1.0/plan/00-前端开发计划.md`。

## 快速开始

```bash
npm install
npm run dev        # http://localhost:4312（后端 QTV_CORS 默认放行该端口）
npm run test       # vitest 单测/组件测试（133 用例）
npm run build      # tsc -b && vite build → dist/
node scripts/smoke.mjs  # 数据层对真实后端冒烟（11 项，需后端 8787）
node scripts/e2e.mjs    # 无头浏览器实测 + 几何校验（19 项，需 chromium 与后端）
```

## 环境变量

复制 `.env.example` 为 `.env`（不入库）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `VITE_API_BASE` | `http://127.0.0.1:8787/api` | 后端 REST 基址（01 §7.1） |
| `VITE_API_KEY` | 空 | 观察员 Key，透传 `X-API-Key`（私人部署默认免鉴权） |

## 目录（01 §10.1 映射）

```
src/
├── api/            # client.ts / ws.ts / errors.ts（数据层）
├── components/
│   ├── charts/     # 图表组件（ChartArea 及 §5 图表）
│   ├── panes/      # 顶栏/自选/个股头部/盘口/下单/Dock
│   └── traders/    # 交易员侧板与弹窗
├── styles/         # tokens.css（双主题令牌）/ base.css（栅格与基线）
└── theme.ts        # 主题切换 + window.__THEME 图表钩子
```
