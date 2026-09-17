import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { state, traderOps } from '../../test/mockTraders'

vi.mock('../../state/traders', () => import('../../test/mockTraders'))

import { TraderBoard } from './TraderBoard'

describe('交易员侧板（01 §4.3）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    state.list = [
      { id: 1, name: 'Alpha', mode: 'strategy', strategyType: 'trend', status: 'running', initCash: 1e6, equity: 1.05e6, totalReturn: 0.05 },
      { id: 2, name: 'Beta', mode: 'manual', strategyType: null, status: 'paused', initCash: 5e5, equity: 4.8e5, totalReturn: -0.04 },
    ]
    state.currentId = 1
    state.events = [{ id: 1, ts: '2026-09-17T09:31:00', text: '创建 · Alpha' }]
  })

  it('表头计数 + 排行行（模式徽标/收益率语义色）', () => {
    render(<TraderBoard />)
    expect(screen.getByText('(2)')).toBeInTheDocument()
    expect(screen.getByText('Alpha')).toBeInTheDocument()
    expect(screen.getByText('STRAT')).toBeInTheDocument()
    expect(screen.getByText('MANUAL')).toBeInTheDocument()
    expect(screen.getByText('已暂停')).toBeInTheDocument()
    const board = screen.getByTestId('trader-board')
    const up = board.querySelector('.up')
    const down = board.querySelector('.down')
    expect(up?.textContent).toContain('+5.00%')
    expect(down?.textContent).toContain('-4.00%')
  })

  it('行点击切换当前交易员（跟随语义入口）', () => {
    render(<TraderBoard />)
    fireEvent.click(screen.getByText('Beta'))
    expect(state.setCurrent).toHaveBeenCalledWith(2)
  })

  it('管理菜单：暂停/恢复接 patch，删除需二次确认', () => {
    render(<TraderBoard />)
    fireEvent.click(screen.getByLabelText('管理 Alpha'))
    expect(screen.getByRole('menuitem', { name: '暂停' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('menuitem', { name: '暂停' }))
    expect(traderOps.patch).toHaveBeenCalledWith(1, { status: 'paused' })

    fireEvent.click(screen.getByLabelText('管理 Beta'))
    fireEvent.click(screen.getByRole('menuitem', { name: '恢复' }))
    expect(traderOps.patch).toHaveBeenCalledWith(2, { status: 'running' })

    fireEvent.click(screen.getByLabelText('管理 Alpha'))
    fireEvent.click(screen.getByRole('menuitem', { name: '删除' }))
    expect(screen.getByText(/软删除/)).toBeInTheDocument()
    fireEvent.click(screen.getByText('确认删除'))
    expect(traderOps.remove).toHaveBeenCalledWith(1)
  })

  it('注资与导出入口', () => {
    render(<TraderBoard />)
    fireEvent.click(screen.getByLabelText('管理 Alpha'))
    fireEvent.click(screen.getByRole('menuitem', { name: '注资' }))
    expect(screen.getByText(/注资 · Alpha/)).toBeInTheDocument()
    fireEvent.click(screen.getByText('确认注资'))
    expect(traderOps.inject).toHaveBeenCalledWith(1, 100000)

    fireEvent.click(screen.getByLabelText('管理 Beta'))
    fireEvent.click(screen.getByRole('menuitem', { name: '导出' }))
    expect(screen.getByTestId('export-menu')).toBeInTheDocument()
  })

  it('空世界引导"从模板创建"', () => {
    state.list = []
    render(<TraderBoard />)
    expect(screen.getByText(/空世界/)).toBeInTheDocument()
    fireEvent.click(screen.getByText('从模板创建'))
    expect(state.openCreate).toHaveBeenCalled()
  })

  it('底部动态流渲染事件文本', () => {
    render(<TraderBoard />)
    expect(screen.getByText(/创建 · Alpha/)).toBeInTheDocument()
  })
})
