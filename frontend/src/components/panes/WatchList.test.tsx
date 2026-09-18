import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Quote } from '../../api/types'
import { watchlistOps, type WatchRow } from '../../state/watchlist'
import { WatchList } from './WatchList'

vi.mock('../../state/watchlist', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../../state/watchlist')>()
  return {
    ...mod,
    watchlistOps: {
      ...mod.watchlistOps,
      add: vi.fn(),
      remove: vi.fn(() => Promise.resolve({ code: 'x', removed: true })),
      suggest: vi.fn(),
    },
  }
})

function q(code: string, last: number, prevClose: number, name = code): Quote {
  return { code, name, last, prevClose, open: prevClose, high: last, low: prevClose, volume: 0, bids: [], asks: [] }
}

function row(code: string, last: number, prevClose: number, opts: { name?: string; pinned?: boolean } = {}): WatchRow {
  return { code, name: opts.name ?? code, quote: q(code, last, prevClose, opts.name ?? code), pinned: opts.pinned ?? false }
}

/** 自选项行情快照未达时的占位行 */
function pendingRow(code: string, name: string): WatchRow {
  return { code, name, quote: null, pinned: true }
}

describe('自选股列表（01 §4.2）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('渲染行情行与涨跌统计，指数不入列表', () => {
    render(
      <WatchList
        rows={[row('sh000300', 4479, 4400, { name: '沪深300' }), row('600519', 1700, 1680), row('000001', 9.9, 10)]}
        selected={null}
        onSelect={() => {}}
        onChanged={() => {}}
      />,
    )
    expect(screen.queryByText('沪深300')).toBeNull()
    expect(screen.getAllByText('600519').length).toBeGreaterThan(0)
    expect(screen.getAllByText('000001').length).toBeGreaterThan(0)
    expect(screen.getByText('涨 1')).toBeInTheDocument()
    expect(screen.getByText('跌 1')).toBeInTheDocument()
    expect(screen.getByText('平 0')).toBeInTheDocument()
  })

  it('选中行挂 selected 类并回调 code', () => {
    const onSelect = vi.fn()
    render(<WatchList rows={[row('600519', 1700, 1680)]} selected="600519" onSelect={onSelect} onChanged={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /600519/ }))
    expect(onSelect).toHaveBeenCalledWith('600519')
  })

  it('价格变化挂闪动类（flash-up）', () => {
    const { rerender } = render(
      <WatchList rows={[row('600519', 1700, 1680)]} selected={null} onSelect={() => {}} onChanged={() => {}} />,
    )
    rerender(<WatchList rows={[row('600519', 1710, 1680)]} selected={null} onSelect={() => {}} onChanged={() => {}} />)
    expect(document.querySelector('.flash-up')).toBeTruthy()
  })

  it('空列表显示空态', () => {
    render(<WatchList rows={[]} selected={null} onSelect={() => {}} onChanged={() => {}} />)
    expect(screen.getByText(/暂无关注标的/)).toBeInTheDocument()
  })
})

describe('自选股编辑（01 §4.2 v5 / T24）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('自选项行尾有删除钮（pinned），动态项无此入口', () => {
    render(
      <WatchList
        rows={[row('sh600519', 1700, 1680, { pinned: true }), row('sz000001', 9.9, 10)]}
        selected={null}
        onSelect={() => {}}
        onChanged={() => {}}
      />,
    )
    expect(screen.getByLabelText('删除 sh600519')).toBeInTheDocument()
    expect(screen.queryByLabelText('删除 sz000001')).toBeNull()
    expect(document.querySelector('.wl-row[data-code="sh600519"]')?.getAttribute('data-pinned')).toBe('true')
    expect(document.querySelector('.wl-row[data-code="sz000001"]')?.getAttribute('data-pinned')).toBeNull()
  })

  it('点击删除钮调 DELETE 幂等端点并触发重排回调，不冒泡选中', async () => {
    const onSelect = vi.fn()
    const onChanged = vi.fn()
    render(
      <WatchList
        rows={[row('sh600519', 1700, 1680, { pinned: true })]}
        selected={null}
        onSelect={onSelect}
        onChanged={onChanged}
      />,
    )
    fireEvent.click(screen.getByLabelText('删除 sh600519'))
    expect(watchlistOps.remove).toHaveBeenCalledWith('sh600519')
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('占位行（行情未达）以名称缓存展示且价格 --，计入平盘统计', () => {
    render(
      <WatchList rows={[pendingRow('sh601318', '中国平安')]} selected={null} onSelect={() => {}} onChanged={() => {}} />,
    )
    expect(screen.getByText('中国平安')).toBeInTheDocument()
    expect(screen.getByText('sh601318')).toBeInTheDocument()
    expect(screen.getAllByText('--').length).toBeGreaterThan(0)
    expect(screen.getByText('平 1')).toBeInTheDocument()
  })

  it('头部 + 按钮打开添加弹层', () => {
    render(<WatchList rows={[]} selected={null} onSelect={() => {}} onChanged={() => {}} />)
    fireEvent.click(screen.getByLabelText('添加自选'))
    expect(screen.getByTestId('watch-add')).toBeInTheDocument()
  })
})
