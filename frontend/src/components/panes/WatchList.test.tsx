import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Quote } from '../../api/types'
import { WatchList } from './WatchList'

function q(code: string, last: number, prevClose: number, name = code): Quote {
  return { code, name, last, prevClose, open: prevClose, high: last, low: prevClose, volume: 0, bids: [], asks: [] }
}

describe('自选股列表（01 §4.2）', () => {
  it('渲染行情行与涨跌统计，指数不入列表', () => {
    render(
      <WatchList
        quotes={[q('sh000300', 4479, 4400, '沪深300'), q('600519', 1700, 1680), q('000001', 9.9, 10)]}
        selected={null}
        onSelect={() => {}}
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
    render(<WatchList quotes={[q('600519', 1700, 1680)]} selected="600519" onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: /600519/ }))
    expect(onSelect).toHaveBeenCalledWith('600519')
  })

  it('价格变化挂闪动类（flash-up）', () => {
    const { rerender } = render(
      <WatchList quotes={[q('600519', 1700, 1680)]} selected={null} onSelect={() => {}} />,
    )
    rerender(<WatchList quotes={[q('600519', 1710, 1680)]} selected={null} onSelect={() => {}} />)
    expect(document.querySelector('.flash-up')).toBeTruthy()
  })

  it('空列表显示空态', () => {
    render(<WatchList quotes={[]} selected={null} onSelect={() => {}} />)
    expect(screen.getByText(/暂无关注标的/)).toBeInTheDocument()
  })
})
