import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { state, traderOps } from '../../test/mockTraders'

vi.mock('../../state/traders', () => import('../../test/mockTraders'))

import { TraderFormDialog } from './TraderFormDialog'

const templates = {
  data: [
    {
      template: 'trend',
      name: '趋势跟踪',
      params: { fast: { default: 5 }, slow: { default: 20 }, pctOfCash: { default: 0.2 } },
    },
    {
      template: 'grid',
      name: '网格',
      params: { window: { default: 20 }, gridPct: { default: 0.02 } },
    },
  ],
}

const detail = {
  traderId: 1,
  name: 'Alpha',
  mode: 'strategy',
  status: 'running',
  strategyParams: null as Record<string, number> | null,
}

function stubFetch() {
  return vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const body = url.includes('/templates') ? templates : detail
      return Promise.resolve({ ok: true, status: 200, text: async () => JSON.stringify(body) } as Response)
    }),
  )
}

describe('创建/编辑对话框（01 §4.10〔v2 新增〕）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.unstubAllGlobals()
    state.editTarget = null
    state.refresh = vi.fn()
  })

  it('名称必填：空名称阻止提交', () => {
    stubFetch()
    render(<TraderFormDialog mode="create" onClose={() => {}} />)
    expect(screen.getByText('创建')).toBeDisabled()
    fireEvent.change(screen.getByDisplayValue(''), { target: { value: 'Gamma' } })
    expect(screen.getByText('创建')).toBeEnabled()
  })

  it('策略模式：模板选择驱动参数表单（换模板即换字段）', async () => {
    stubFetch()
    render(<TraderFormDialog mode="create" onClose={() => {}} />)
    fireEvent.change(screen.getByDisplayValue(''), { target: { value: 'Gamma' } })
    fireEvent.click(screen.getByRole('button', { name: '策略' }))
    await screen.findByText('趋势跟踪')
    fireEvent.click(screen.getByText('趋势跟踪'))
    expect(screen.getByText('fast')).toBeInTheDocument()
    expect(screen.getByText('slow')).toBeInTheDocument()
    fireEvent.click(screen.getByText('网格'))
    expect(screen.getByText('gridPct')).toBeInTheDocument()
    expect(screen.queryByText('fast')).toBeNull()
  })

  it('创建提交：strategy 载荷含 template/params，可选计划速设入 plan', async () => {
    stubFetch()
    render(<TraderFormDialog mode="create" onClose={() => {}} />)
    fireEvent.change(screen.getByDisplayValue(''), { target: { value: 'Gamma' } })
    fireEvent.click(screen.getByRole('button', { name: '策略' }))
    await screen.findByText('趋势跟踪')
    fireEvent.click(screen.getByText('趋势跟踪'))
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.change(screen.getByPlaceholderText('600519, 000001'), { target: { value: '600519,000001' } })
    fireEvent.change(screen.getByText('止损 %（stopLossPct）').parentElement!.querySelector('input')!, {
      target: { value: '5' },
    })
    fireEvent.click(screen.getByText('创建'))
    await waitFor(() => expect(traderOps.create).toHaveBeenCalled())
    const payload = traderOps.create.mock.calls[0][0] as Record<string, unknown>
    expect(payload.template).toBe('trend')
    expect(payload.params).toMatchObject({ fast: 5, slow: 20 })
    expect(payload.plan).toMatchObject({
      scope: { codes: ['600519', '000001'] },
      risk: { stopLossPct: 5 },
    })
  })

  it('编辑态回显名称与策略参数（strategyParams 为 null 时回落模板默认值）', async () => {
    stubFetch()
    detail.strategyParams = null
    state.editTarget = {
      id: 1,
      name: 'Alpha',
      mode: 'strategy',
      strategyType: 'trend',
      status: 'running',
      initCash: 1e6,
      equity: 1.05e6,
      totalReturn: 0.05,
    }
    render(<TraderFormDialog mode="edit" onClose={() => {}} />)
    expect(screen.getByDisplayValue('Alpha')).toBeInTheDocument()
    await screen.findByText('fast')
    expect(screen.getByDisplayValue('5')).toBeInTheDocument()
  })

  it('编辑态回填当前生效 strategyParams（C003，非模板默认值）', async () => {
    stubFetch()
    detail.strategyParams = { fast: 9, slow: 99, pctOfCash: 0.2 }
    state.editTarget = {
      id: 1,
      name: 'Alpha',
      mode: 'strategy',
      strategyType: 'trend',
      status: 'running',
      initCash: 1e6,
      equity: 1.05e6,
      totalReturn: 0.05,
    }
    render(<TraderFormDialog mode="edit" onClose={() => {}} />)
    await screen.findByText('fast')
    expect(screen.getByDisplayValue('9')).toBeInTheDocument()
    expect(screen.getByDisplayValue('99')).toBeInTheDocument()
  })
})
