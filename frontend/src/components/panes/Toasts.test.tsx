import { act, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Toasts, toast, useToasts } from './Toasts'

describe('Toast（01 §4.10）', () => {
  it('toast() 推入并渲染，自动消退', () => {
    function Probe() {
      const items = useToasts(100)
      return <Toasts items={items} />
    }
    render(<Probe />)
    act(() => toast('success', '成交回报'))
    act(() => toast('error', '撤单失败'))
    expect(screen.getByText('成交回报')).toBeInTheDocument()
    expect(screen.getByText('撤单失败')).toBeInTheDocument()
    expect(document.querySelector('.toast-success')).toBeTruthy()
    expect(document.querySelector('.toast-error')).toBeTruthy()
  })

  it('并发展示上限 5 条', () => {
    function Probe() {
      const items = useToasts(60000)
      return <Toasts items={items} />
    }
    render(<Probe />)
    act(() => {
      for (let i = 0; i < 8; i += 1) toast('info', `t${i}`)
    })
    expect(screen.getByTestId('toasts').children).toHaveLength(5)
  })
})
