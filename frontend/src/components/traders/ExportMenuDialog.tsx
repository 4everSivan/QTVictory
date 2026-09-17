import { useState } from 'react'
import { api, ApiError } from '../../api/client'
import { presentError } from '../../api/errors'
import { toast } from '../panes/Toasts'
import type { TraderListItem } from '../../api/types'

const EXPORT_TYPES = [
  ['trades', '成交'],
  ['orders', '委托'],
  ['positions', '持仓'],
  ['equity', '净值'],
  ['plans', '计划'],
] as const
const EXPORT_FORMATS = [
  ['csv', 'CSV'],
  ['json', 'JSON'],
] as const

interface ExportMenuDialogProps {
  trader: TraderListItem
  onClose: () => void
}

/**
 * 导出菜单（01 §4.10〔v2 新增〕）：类型 × 格式（CSV/JSON）× 时间区间，
 * 直接触发浏览器下载。T19 随侧板菜单交付，T21 在 Dock 复用本组件。
 */
export function ExportMenuDialog({ trader, onClose }: ExportMenuDialogProps) {
  const [type, setType] = useState<(typeof EXPORT_TYPES)[number][0]>('trades')
  const [format, setFormat] = useState<(typeof EXPORT_FORMATS)[number][0]>('csv')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')

  const doExport = async () => {
    const params = new URLSearchParams({ type, format })
    if (from) params.set('from', from)
    if (to) params.set('to', to)
    try {
      await api.download(`/traders/${trader.id}/export?${params.toString()}`, `qtv-${trader.name}-${type}.${format}`)
      toast('success', '导出已触发下载')
      onClose()
    } catch (e) {
      toast('error', presentError(e as ApiError).text)
    }
  }

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()} data-testid="export-menu">
        <div className="dialog-title">导出 · {trader.name}</div>
        <div className="field">
          <span className="micro-label">类型</span>
          <div className="seg">
            {EXPORT_TYPES.map(([key, label]) => (
              <button key={key} type="button" className={type === key ? 'active' : ''} onClick={() => setType(key)}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="field">
          <span className="micro-label">格式</span>
          <div className="seg">
            {EXPORT_FORMATS.map(([key, label]) => (
              <button key={key} type="button" className={format === key ? 'active' : ''} onClick={() => setFormat(key)}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="field-row">
          <label className="field">
            <span className="micro-label">开始日期（可选）</span>
            <input className="num" value={from} placeholder="2026-01-01" onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label className="field">
            <span className="micro-label">结束日期（可选）</span>
            <input className="num" value={to} placeholder="2026-12-31" onChange={(e) => setTo(e.target.value)} />
          </label>
        </div>
        <div className="dialog-actions">
          <button type="button" onClick={onClose}>取消</button>
          <button type="button" className="btn-primary" onClick={() => void doExport()}>
            导出并下载
          </button>
        </div>
      </div>
    </div>
  )
}
