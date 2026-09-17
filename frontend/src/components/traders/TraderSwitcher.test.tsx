import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { state } from '../../test/mockTraders'

vi.mock('../../state/traders', () => import('../../test/mockTraders'))

import { FiveMetricBand, TraderSwitcher } from './TraderSwitcher'

const account = {
  traderId: 1,
  name: 'Alpha',
  mode: 'strategy' as const,
  status: 'running' as const,
  initCash: 1_000_000,
  cash: 600_000,
  frozenCash: 50_000,
  availableCash: 550_000,
  marketValue: 500_000,
  equity: 1_050_000,
  totalReturn: 0.05,
  positions: [],
}

describe('当前交易员切换器（01 §4.1〔v2 新增〕）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    state.list = [
      { id: 1, name: 'Alpha', mode: 'strategy', strategyType: 'trend', status: 'running', initCash: 1e6, equity: 1.05e6, totalReturn: 0.05 },
      { id: 2, name: 'Beta', mode: 'manual', strategyType: null, status: 'running', initCash: 5e5, equity: 4.8e5, totalReturn: -0.04 },
    ]
    state.currentId = 1
    state.current = state.list[0]
    state.account = null
    state.dayPnl = null
  })

  it('胶囊显示名称 + 模式徽标 + 总资产速览', () => {
    state.account = account
    render(<TraderSwitcher />)
    expect(screen.getByText('Alpha')).toBeInTheDocument()
    expect(screen.getByText('STRAT')).toBeInTheDocument()
    expect(screen.getByText('1050000.00')).toBeInTheDocument()
  })

  it('下拉选择切换当前交易员', () => {
    render(<TraderSwitcher />)
    fireEvent.click(screen.getByRole('button', { name: /Alpha/ }))
    fireEvent.click(screen.getByRole('menuitem', { name: /Beta/ }))
    expect(state.setCurrent).toHaveBeenCalledWith(2)
  })

  it('空世界显示"创建交易员"空态按钮', () => {
    state.list = []
    render(<TraderSwitcher />)
    fireEvent.click(screen.getByText('＋ 创建交易员'))
    expect(state.openCreate).toHaveBeenCalled()
  })
})

describe('五指标均分数据带（01 §4.1 v2.1）', () => {
  it('五项等分布局，值缺失显示 --', () => {
    state.account = null
    state.dayPnl = null
    const { container } = render(<FiveMetricBand />)
    const band = screen.getByTestId('metric-band')
    expect(band.children).toHaveLength(5)
    expect(band.querySelectorAll('.metric-divided')).toHaveLength(4) // 项间 1px 细线
    const values = [...container.querySelectorAll('.metric-value')].map((el) => el.textContent)
    expect(values).toEqual(['--', '--', '--', '--', '--'])
  })

  it('有账户数据时渲染数值与当日盈亏语义色', () => {
    state.account = account
    state.dayPnl = 12000
    const { container } = render(<FiveMetricBand />)
    const values = [...container.querySelectorAll('.metric-value')].map((el) => el.textContent)
    expect(values[0]).toBe('1050000.00')
    expect(values[1]).toBe('500000.00')
    expect(values[2]).toBe('550000.00')
    expect(values[3]).toBe('+12000.00')
    expect(values[4]).toBe('+5.00%')
    const dayPnl = container.querySelectorAll('.metric-value')[3]
    expect(dayPnl.classList.contains('up')).toBe(true)
  })
})
