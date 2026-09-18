#!/usr/bin/env node
/**
 * T22 浏览器实测 + 几何校验（01 §11 v1 验证方法）：
 * 对 preview 构建 + 真实后端执行——加载零报错、一屏五区几何、主题三态切换（C002：浅色/深色/跟随系统）、降级断点。
 * 运行：node scripts/e2e.mjs（需后端 8787 已启动且 dist 已构建；preview 端口 4312）
 */
import { chromium } from 'playwright'
import { createServer } from 'vite'

let passed = 0
let failed = 0
const problems = []

function check(name, cond, extra = '') {
  if (cond) {
    passed += 1
    console.log(`  ✓ ${name}`)
  } else {
    failed += 1
    problems.push(`${name} ${extra}`)
    console.error(`  ✗ ${name} ${extra}`)
  }
}

const server = await createServer({ root: process.cwd(), server: { port: 4312 } })
await server.listen()

const backendPort = process.env.QTV_PORT || 8787

// 造一个验收用交易员（结束后软删还原空世界）
const created = await fetch(`http://127.0.0.1:${backendPort}/api/traders`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: 'e2e验收', mode: 'manual', initCash: 1_000_000 }),
}).then((r) => r.json())
const probeTraderId = created.id

const browser = await chromium.launch()
const results = {}

async function auditViewport(width, height) {
  const page = await browser.newPage({ viewport: { width, height } })
  const consoleErrors = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  })
  page.on('pageerror', (err) => consoleErrors.push(String(err)))

  await page.goto('http://localhost:4312/', { waitUntil: 'networkidle' })
  await page.waitForSelector('[data-testid="watchlist"]', { timeout: 10000 })
  await page.waitForTimeout(1200)

  const geo = await page.evaluate(() => {
    const r = (sel) => {
      const el = document.querySelector(sel)
      if (!el) return null
      const rect = el.getBoundingClientRect()
      return { width: rect.width, height: rect.height }
    }
    const watch = document.querySelector('.pane-watchlist')
    const board = document.querySelector('.pane-traders')
    const left = r('.leftcol')
    const wr = watch ? watch.getBoundingClientRect() : null
    const br = board ? board.getBoundingClientRect() : null
    return {
      topbar: r('.topbar'),
      dock: r('.dock'),
      leftcol: left,
      rightcol: r('.rightcol'),
      watchPct: wr && left ? (wr.height / left.height) * 100 : null,
      boardPct: br && left ? (br.height / left.height) * 100 : null,
    }
  })

  const regions = await page.evaluate(() => ({
    watchlist: Boolean(document.querySelector('[data-testid="watchlist"]')),
    orderbook: Boolean(document.querySelector('[data-testid="orderbook"]')),
    orderPanel: Boolean(document.querySelector('[data-testid="order-panel"]')),
    dock: Boolean(document.querySelector('[data-testid="dock"]')),
    traderBoard: Boolean(document.querySelector('[data-testid="trader-board"]')),
    chartArea: Boolean(document.querySelector('[data-testid="chart-area"]')),
    metricBand: Boolean(document.querySelector('[data-testid="metric-band"]')),
    switcher: Boolean(document.querySelector('[data-testid="trader-switcher"]')),
  }))

  return { page, consoleErrors, geo, regions }
}

// ---- 1560×940 主视口 ----
const main = await auditViewport(1560, 940)
results.main = main

console.log('--- 区域渲染（一屏五区 + 顶栏组件） ---')
for (const [k, v] of Object.entries(main.regions)) {
  check(`区域 ${k}`, v)
}
check('顶栏高度 48px（±1）', Math.abs(main.geo.topbar.height - 48) <= 1, `got ${main.geo.topbar.height}`)
check('Dock 高度 236px（±1）', Math.abs(main.geo.dock.height - 236) <= 1, `got ${main.geo.dock.height}`)
check('左栏宽 262px（±1）', Math.abs(main.geo.leftcol.width - 262) <= 1, `got ${main.geo.leftcol.width}`)
check('右栏宽 324px（±1）', Math.abs(main.geo.rightcol.width - 324) <= 1, `got ${main.geo.rightcol.width}`)
check(
  '左栏 55/44 分割（watch 55±3）',
  main.geo.watchPct !== null && Math.abs(main.geo.watchPct - 55) <= 3,
  `got ${main.geo.watchPct?.toFixed(1)}%`,
)

console.log('--- 交互：Dock Tab / 主题三态切换（C002：浅色→深色→跟随系统） ---')
await main.page.click('[data-testid="dock"] >> role=tab[name="当日委托"]')
await main.page.waitForTimeout(400)
const ordersTab = await main.page.$('[data-testid="dock-orders"]')
check('Dock 委托 Tab 可切换', Boolean(ordersTab))

const themeBtn = await main.page.$('.theme-toggle')
check('顶栏主题切换按钮存在（默认深色）', Boolean(themeBtn) && (await main.page.$eval('.theme-toggle', (el) => el.textContent)) === '深色')
const switcherNameColor = await main.page.$eval('.switcher-name', (el) => getComputedStyle(el).color)
check('交易员切换器名称为主文本色（C006：非 UA 默认黑）', switcherNameColor === 'rgb(232, 232, 232)', `got ${switcherNameColor}`)
const switcherNameFont = await main.page.$eval('.switcher-name', (el) => getComputedStyle(el).fontFamily)
check('按钮字体栈继承 body 三族纪律（C007：含 Space Grotesk）', switcherNameFont.includes('Space Grotesk'), `got ${switcherNameFont}`)
await main.page.click('.theme-toggle')
await main.page.waitForTimeout(200)
const mode1 = await main.page.$eval('.theme-toggle', (el) => el.textContent)
const dt1 = await main.page.$eval('html', (el) => el.dataset.theme)
check('切换 1 次 → 跟随系统（已解析为 light/dark）', mode1 === '跟随系统' && (dt1 === 'light' || dt1 === 'dark'), `got ${mode1}/${dt1}`)
await main.page.click('.theme-toggle')
await main.page.waitForTimeout(200)
const mode2 = await main.page.$eval('.theme-toggle', (el) => el.textContent)
const dt2 = await main.page.$eval('html', (el) => el.dataset.theme)
check('切换 2 次 → 浅色（data-theme=light）', mode2 === '浅色' && dt2 === 'light', `got ${mode2}/${dt2}`)
await main.page.click('.theme-toggle')
await main.page.waitForTimeout(200)
const mode3 = await main.page.$eval('.theme-toggle', (el) => el.textContent)
const dt3 = await main.page.$eval('html', (el) => el.dataset.theme)
check('切换 3 次 → 深色（data-theme=dark）', mode3 === '深色' && dt3 === 'dark', `got ${mode3}/${dt3}`)

const errText = main.consoleErrors.filter((e) => !e.includes('fonts.g') && !e.includes('WebSocket connection'))
check('主视口 console 零报错', errText.length === 0, JSON.stringify(errText.slice(0, 4)))

// ---- ≤1180px 降级断点 ----
const small = await auditViewport(1100, 800)
results.small = small
check('降级断点左栏 220px（±1）', Math.abs(small.geo.leftcol.width - 220) <= 1, `got ${small.geo.leftcol.width}`)
check('降级断点右栏 300px（±1）', Math.abs(small.geo.rightcol.width - 300) <= 1, `got ${small.geo.rightcol.width}`)
const smallErr = small.consoleErrors.filter((e) => !e.includes('fonts.g'))
check('降级断口 console 零报错', smallErr.length === 0, JSON.stringify(smallErr.slice(0, 4)))

await browser.close()
await server.close()
await fetch(`http://127.0.0.1:${backendPort}/api/traders/${probeTraderId}`, { method: 'DELETE' })

console.log('\ngeometry@1560x940:', JSON.stringify(results.main.geo))
console.log(`e2e: ${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
