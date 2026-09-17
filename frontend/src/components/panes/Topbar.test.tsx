import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { state } from '../../test/mockTraders'

vi.mock('../../state/traders', () => import('../../test/mockTraders'))

import type { Quote, QuotesEnvelope, SessionState } from '../../api/types'
import { sessionCapsuleClass, Topbar } from './Topbar'

function envelope(q: Quote): QuotesEnvelope {
  return { source: 'tencent', live: true, ts: '2026-09-17T10:00:00', quotes: [q] }
}

const indexQuote: Quote = {
  code: 'sh000300',
  name: '沪深300',
  last: 4479.85,
  prevClose: 4400,
  open: 4400,
  high: 4480,
  low: 4390,
  volume: 0,
  bids: [],
  asks: [],
}

describe('顶栏状态区（01 §4.1 左段）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    state.list = [
      { id: 1, name: 'Alpha', mode: 'strategy', strategyType: 'trend', status: 'running', initCash: 1e6, equity: 1.05e6, totalReturn: 0.05 },
    ]
    state.currentId = 1
    state.current = state.list[0]
    state.account = null
    state.dayPnl = null
  })

  it('品牌区 + 会话胶囊 + 指数单元 + 切换器', () => {
    const session: SessionState = { state: 'trading', phase: 'continuous', tradingDate: '2026-09-17' }
    render(<Topbar session={session} envelope={envelope(indexQuote)} />)
    expect(screen.getByText('模拟盘')).toBeInTheDocument()
    expect(screen.getByText('PAPER')).toBeInTheDocument()
    expect(screen.getByTestId('session-capsule').textContent).toBe('交易中')
    expect(screen.getByText('4479.85')).toBeInTheDocument()
    expect(screen.getByTestId('trader-switcher')).toBeInTheDocument()
    expect(screen.getByTestId('metric-band')).toBeInTheDocument()
  })

  it('会话状态胶囊映射与配色', () => {
    expect(sessionCapsuleClass('trading')).toBe('up')
    expect(sessionCapsuleClass('auction')).toBe('warn')
    expect(sessionCapsuleClass('degraded')).toBe('warn')
    expect(sessionCapsuleClass('closed')).toBe('flat')
    expect(sessionCapsuleClass(null)).toBe('flat')
  })

  it('degraded 会话显示已降级', () => {
    const session: SessionState = { state: 'degraded', phase: 'continuous', tradingDate: '2026-09-17' }
    render(<Topbar session={session} envelope={null} />)
    expect(screen.getByTestId('session-capsule').textContent).toBe('已降级')
  })

  it('时钟取包络时间戳 HH:MM:SS', () => {
    const session: SessionState = { state: 'closed', phase: 'closed', tradingDate: '2026-09-17' }
    render(<Topbar session={session} envelope={envelope(indexQuote)} />)
    expect(screen.getByText('10:00:00')).toBeInTheDocument()
  })
})
