import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const plansFeed = {
  data: [
    {
      id: 11,
      traderId: 1,
      name: '池计划',
      status: 'active',
      scope: { codes: ['600519'] },
      budget: { total: 500000, used: 120000 },
      positionRule: { targetPct: 0.3 },
      risk: { stopLossPct: 5, takeProfitPct: 10, dailyMaxLoss: 20000 },
      schedule: { frequency: 'daily' },
      createdAt: '2026-09-17T09:00:00',
    },
  ],
}

const entriesFeed = {
  data: [
    {
      id: 101,
      plan_id: 11,
      trigger_type: 'price_cross',
      trigger_params: '{"side":"buy","price":1250,"code":"600519"}',
      action: '{"side":"buy","qty":100,"type":"limit","price":1250}',
      tif: 'day',
      status: 'waiting',
      last_triggered_on: null,
      created_at: '2026-09-17T09:01:00',
    },
    {
      id: 102,
      plan_id: 11,
      trigger_type: 'time',
      trigger_params: '{"at":"14:50"}',
      action: '{"side":"sell","pctOfPosition":0.5,"type":"market"}',
      tif: 'gtc',
      status: 'triggered',
      last_triggered_on: '2026-09-17',
      created_at: '2026-09-17T09:02:00',
    },
  ],
}

function stub(posts: Array<[string, unknown]>) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        return Promise.resolve({ ok: true, status: 201, text: async () => '{"id":103}' } as Response)
      }
      const hit = posts.find(([k]) => url.includes(k))
      return Promise.resolve({
        ok: true,
        status: 200,
        text: async () => JSON.stringify(hit?.[1] ?? { data: [] }),
      } as Response)
    }),
  )
}

vi.mock('../../state/traders', () => import('../../test/mockTraders'))

import { PlanPanel } from './PlanPanel'

describe('交易计划面板（01 §4.10〔v2 新增〕）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.unstubAllGlobals()
    stub([['/traders/1/plans', plansFeed], ['/plans/11/entries', entriesFeed]])
  })

  it('计划卡五要素：状态/预算水位条/风控参数/执行进度/目标仓位规则', async () => {
    render(<PlanPanel traderId={1} />)
    const card = await screen.findByTestId('plan-card')
    await screen.findByText(/条件单 2 · 触发 1 · 成交 0/)
    expect(card).toHaveTextContent('池计划')
    expect(card).toHaveTextContent('ACTIVE')
    expect(card.querySelector('.water-fill')).toBeTruthy() // 预算水位条
    expect(card).toHaveTextContent('stopLossPct: 5')
    expect(card).toHaveTextContent('条件单 2 · 触发 1 · 成交 0')
    expect(card).toHaveTextContent('targetPct: 0.3')
  })

  it('条件单列表：触发器 → 动作 → 状态', async () => {
    render(<PlanPanel traderId={1} />)
    const list = await screen.findByTestId('entry-list')
    await waitFor(() => expect(list).toHaveTextContent('价格穿越'))
    expect(list).toHaveTextContent('价格穿越 ≤ 1250')
    expect(list).toHaveTextContent('买入 ×100 限价@1250')
    expect(list).toHaveTextContent('WAITING')
    expect(list).toHaveTextContent('定时 14:50')
    expect(list).toHaveTextContent('卖出 仓位 50% 市价')
    expect(list).toHaveTextContent('TRIGGERED')
    expect(list).toHaveTextContent('GTC')
  })

  it('新建条件单表单：四类触发器字段切换 + 提交载荷', async () => {
    render(<PlanPanel traderId={1} />)
    await screen.findByTestId('plan-card')
    fireEvent.click(screen.getByText('＋ 条件单'))
    const form = await screen.findByTestId('entry-form')

    // price_cross 默认：填触发价与数量即可提交
    fireEvent.change(form.querySelectorAll('input')[1], { target: { value: '1240' } }) // 触发价
    fireEvent.change(form.querySelectorAll('input')[2], { target: { value: '100' } }) // 数量
    fireEvent.click(screen.getByText('创建条件单'))
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([, i]) => i?.method === 'POST')).toBe(true))
    const post = vi.mocked(fetch).mock.calls.find(([, i]) => i?.method === 'POST')!
    const body = JSON.parse((post[1] as RequestInit).body as string)
    expect(String(post[0])).toContain('/api/plans/11/entries')
    expect(body).toMatchObject({
      triggerType: 'price_cross',
      triggerParams: { side: 'buy', price: 1240 },
      action: { side: 'buy', qty: 100, type: 'market' },
      tif: 'day',
    })
  })

  it('切换触发器类型切换字段（定时无方向）', async () => {
    render(<PlanPanel traderId={1} />)
    await screen.findByTestId('plan-card')
    fireEvent.click(screen.getByText('＋ 条件单'))
    const form = await screen.findByTestId('entry-form')
    expect(form).toHaveTextContent('方向（触发侧）')
    fireEvent.click(screen.getByRole('button', { name: '定时' }))
    expect(form).not.toHaveTextContent('方向（触发侧）')
    expect(form).toHaveTextContent('触发时间 HH:MM')
    fireEvent.click(screen.getByRole('button', { name: '均线交叉' }))
    expect(form).toHaveTextContent('快线')
    expect(form).toHaveTextContent('慢线')
  })
})
