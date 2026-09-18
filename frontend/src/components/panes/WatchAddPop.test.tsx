import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { rememberName, watchlistOps } from '../../state/watchlist'
import { toast } from './Toasts'
import { WatchAddPop } from './WatchAddPop'

vi.mock('../../state/watchlist', () => ({
  watchlistOps: {
    list: vi.fn(),
    add: vi.fn(),
    remove: vi.fn(),
    batch: vi.fn(),
    suggest: vi.fn(),
  },
  rememberName: vi.fn(),
}))

vi.mock('./Toasts', () => ({ toast: vi.fn() }))

const SUGGESTED = { code: 'sh601318', name: '中国平安', kind: 'stock' }

function typeQuery(value: string) {
  fireEvent.change(screen.getByPlaceholderText('代码 / 名称'), { target: { value } })
}

function keyDown(key: string) {
  fireEvent.keyDown(screen.getByPlaceholderText('代码 / 名称'), { key })
}

describe('自选股添加弹层（T24-2，01 §4.2 v5）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(watchlistOps.suggest).mockResolvedValue({ data: [SUGGESTED] })
    vi.mocked(watchlistOps.add).mockResolvedValue({
      code: 'sh601318',
      addedAt: '2026-09-18T14:00:00',
      created: true,
      name: '中国平安',
    })
  })

  it('输入防抖后触发联想并渲染规范化条目', async () => {
    render(<WatchAddPop onClose={() => {}} onAdded={() => {}} />)
    typeQuery('6')
    typeQuery('601318')
    expect(await screen.findByText('中国平安')).toBeInTheDocument()
    expect(screen.getByText('sh601318')).toBeInTheDocument()
    expect(screen.getByText('STOCK')).toBeInTheDocument()
    await waitFor(() => expect(watchlistOps.suggest).toHaveBeenCalledTimes(1))
    expect(watchlistOps.suggest).toHaveBeenCalledWith('601318')
  })

  it('↓ 选中联想项 + Enter 确认：PUT 规范码成功后回调 onAdded', async () => {
    const onAdded = vi.fn()
    render(<WatchAddPop onClose={() => {}} onAdded={onAdded} />)
    typeQuery('601318')
    await screen.findByText('中国平安')
    keyDown('ArrowDown')
    expect(screen.getByRole('option', { name: /中国平安/ })).toHaveAttribute('aria-selected', 'true')
    keyDown('Enter')
    await waitFor(() => expect(watchlistOps.add).toHaveBeenCalledWith('sh601318'))
    await waitFor(() => expect(onAdded).toHaveBeenCalled())
    expect(rememberName).toHaveBeenCalledWith('sh601318', '中国平安')
    expect(toast).not.toHaveBeenCalled()
  })

  it('无选中联想项时 Enter 按输入码直接提交（后端校验归一）', async () => {
    render(<WatchAddPop onClose={() => {}} onAdded={() => {}} />)
    vi.mocked(watchlistOps.suggest).mockResolvedValue({ data: [] })
    typeQuery('601318')
    expect(await screen.findByText(/无联想结果/)).toBeInTheDocument()
    keyDown('Enter')
    await waitFor(() => expect(watchlistOps.add).toHaveBeenCalledWith('601318'))
  })

  it('↑ 从首项回到未选中态，Enter 回落输入码', async () => {
    render(<WatchAddPop onClose={() => {}} onAdded={() => {}} />)
    typeQuery('601318')
    await screen.findByText('中国平安')
    keyDown('ArrowDown')
    keyDown('ArrowUp')
    expect(screen.getByRole('option', { name: /中国平安/ })).toHaveAttribute('aria-selected', 'false')
    keyDown('Enter')
    await waitFor(() => expect(watchlistOps.add).toHaveBeenCalledWith('601318'))
  })

  it('Esc 关闭弹层', () => {
    const onClose = vi.fn()
    render(<WatchAddPop onClose={onClose} onAdded={() => {}} />)
    keyDown('Escape')
    expect(onClose).toHaveBeenCalled()
  })

  it('添加失败转 Toast 且不关闭（BAD_CODE 文案透传）', async () => {
    vi.mocked(watchlistOps.add).mockRejectedValue(
      new ApiError(400, { code: 'BAD_CODE', message: '行情源无此代码快照', details: { reason: 'UNREACHABLE' } }),
    )
    const onAdded = vi.fn()
    render(<WatchAddPop onClose={() => {}} onAdded={onAdded} />)
    typeQuery('999999')
    await screen.findByText('中国平安') // suggest mock 仍返回一条
    keyDown('ArrowDown')
    keyDown('Enter')
    await waitFor(() => expect(toast).toHaveBeenCalledWith('error', '行情源无此代码快照'))
    expect(onAdded).not.toHaveBeenCalled()
  })
})
