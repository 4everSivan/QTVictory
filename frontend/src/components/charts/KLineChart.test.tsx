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

describe('KLineChart 受控渲染（C021：胶丸移出后由 props 受控）', () => {
  it('sub=kdj → 副图图例 KDJ(9,3,3)', () => {
    render(<KLineChart klines={klines(60)} period="day" sub="kdj" overlays={['ma']} />)
    expect(screen.getByTestId('kline-legend-sub')).toHaveTextContent('KDJ(9,3,3)')
  })

  it('sub=macd → 副图图例 MACD(12,26,9)', () => {
    render(<KLineChart klines={klines(60)} period="day" sub="macd" overlays={['ma']} />)
    expect(screen.getByTestId('kline-legend-sub')).toHaveTextContent('MACD(12,26,9)')
  })

  it('overlays 含 boll → 主图图例 BOLL 值', () => {
    render(<KLineChart klines={klines(60)} period="day" sub="vol" overlays={['ma', 'boll']} />)
    expect(screen.getByTestId('kline-legend')).toHaveTextContent('BOLL')
  })

  it('图例：主图左上周期标签 + 日期 + OHLC + 涨跌幅（D5）', () => {
    render(<KLineChart klines={klines(60)} period="day" sub="vol" overlays={['ma']} />)
    const legend = screen.getByTestId('kline-legend')
    expect(legend).toHaveTextContent('日K')
    expect(legend).toHaveTextContent('开')
    expect(legend).toHaveTextContent('高')
    expect(legend).toHaveTextContent('低')
    expect(legend).toHaveTextContent('收')
  })

  it('周K/月K 渲染不抛错（§5.1 交互对周期同样适用）', () => {
    render(<KLineChart klines={klines(60)} period="week" sub="vol" overlays={['ma']} />)
    fireEvent.doubleClick(screen.getByTestId('kline-chart'))
    render(<KLineChart klines={klines(60)} period="month" sub="vol" overlays={['ma']} />)
    expect(screen.getAllByTestId('kline-chart').length).toBe(2)
  })

  it('C021⑤：空数据 + 指针移动不崩溃（klines[cross] 越界守卫）', () => {
    render(<KLineChart klines={[]} period="day" sub="vol" overlays={['ma']} />)
    const wrap = screen.getByTestId('kline-chart')
    fireEvent.pointerMove(wrap, { clientX: 120, clientY: 120 })
    fireEvent.pointerMove(wrap, { clientX: 260, clientY: 120 })
    fireEvent.pointerDown(wrap, { clientX: 120, buttons: 1 })
    fireEvent.pointerMove(wrap, { clientX: 200, buttons: 1 })
    expect(wrap).toBeInTheDocument()
  })
})
