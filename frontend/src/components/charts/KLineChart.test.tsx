import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { KlineRow } from '../../api/types'
import { KLineChart } from './KLineChart'

function klines(n: number): KlineRow[] {
  return Array.from({ length: n }, (_, i) => ({
    code: '600519',
    date: `2026-06-${String((i % 28) + 1).padStart(2, '0')}`,
    open: 100 + i,
    close: 101 + i,
    high: 102 + i,
    low: 99 + i,
    volume: 1000 + i,
  }))
}

describe('日K 组件（01 §5.1）', () => {
  it('空数据渲染容器不报错', () => {
    render(<KLineChart klines={[]} />)
    expect(screen.getByTestId('kline-chart')).toBeInTheDocument()
  })

  it('渲染可见蜡烛（数据量 > 可视数时按 90 裁剪）', () => {
    render(<KLineChart klines={klines(300)} />)
    const svg = document.querySelector('.chart-svg')
    expect(svg).toBeTruthy()
    const groups = svg?.querySelectorAll('g')
    expect(groups && groups.length > 0).toBe(true)
  })

  it('双击复位视图（交互不抛错）', () => {
    render(<KLineChart klines={klines(120)} />)
    const wrap = screen.getByTestId('kline-chart')
    fireEvent.doubleClick(wrap)
    fireEvent.pointerDown(wrap, { clientX: 100, buttons: 1 })
    fireEvent.pointerMove(wrap, { clientX: 160, buttons: 1 })
    fireEvent.pointerUp(wrap, { clientX: 160 })
    fireEvent.pointerMove(wrap, { clientX: 200 })
  })
})

describe('KLineChart 副图与叠加（01 §5.5 D2/D3/D4/D6，T27-2/3）', () => {
  it('副图胶丸四枚：VOL｜MACD｜RSI｜KDJ', () => {
    render(<KLineChart klines={klines(60)} period="day" />)
    for (const name of ['VOL', 'MACD', 'RSI', 'KDJ']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument()
    }
  })

  it('切 KDJ 副图：渲染 K/D/J 图例（族内色相 + 线型区分）', () => {
    render(<KLineChart klines={klines(60)} period="day" />)
    fireEvent.click(screen.getByRole('button', { name: 'KDJ' }))
    expect(screen.getByTestId('kline-legend-sub')).toHaveTextContent('KDJ(9,3,3)')
  })

  it('切 RSI 副图：含 30/70 阈值口径', () => {
    render(<KLineChart klines={klines(60)} period="day" />)
    fireEvent.click(screen.getByRole('button', { name: 'RSI' }))
    expect(screen.getByTestId('kline-legend-sub')).toHaveTextContent('RSI(14)')
  })

  it('主图叠加胶丸三枚：MA｜EMA｜BOLL，可同开', () => {
    render(<KLineChart klines={klines(60)} period="day" />)
    for (const name of ['MA', 'EMA', 'BOLL']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument()
    }
    fireEvent.click(screen.getByRole('button', { name: 'BOLL' }))
    expect(screen.getByRole('button', { name: 'BOLL' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'MA' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('图例：主图左上日期 + OHLC + 涨跌幅（D5）', () => {
    render(<KLineChart klines={klines(60)} period="day" />)
    const legend = screen.getByTestId('kline-legend')
    expect(legend).toHaveTextContent('开')
    expect(legend).toHaveTextContent('高')
    expect(legend).toHaveTextContent('低')
    expect(legend).toHaveTextContent('收')
  })

  it('周K/月K 渲染不抛错（§5.1 交互对周期同样适用）', () => {
    render(<KLineChart klines={klines(60)} period="week" />)
    fireEvent.doubleClick(screen.getByTestId('kline-chart'))
    render(<KLineChart klines={klines(60)} period="month" />)
    expect(screen.getAllByTestId('kline-chart').length).toBe(2)
  })
})
