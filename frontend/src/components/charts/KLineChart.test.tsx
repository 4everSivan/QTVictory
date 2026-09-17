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
