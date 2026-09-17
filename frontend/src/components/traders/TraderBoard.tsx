import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../../api/client'
import { presentError } from '../../api/errors'
import { useTraders, traderOps } from '../../state/traders'
import { toast } from '../panes/Toasts'
import { ExportMenuDialog } from './ExportMenuDialog'
import { fmtPct } from '../../lib/format'
import type { TraderListItem } from '../../api/types'

/**
 * 交易员侧板（01 §4.3）：表头 (n) + 「＋ 新建」；行 16px 1fr 56px 52px；
 * 行尾悬停管理菜单（编辑/暂停·恢复/注资/导出/删除二次确认）；
 * 底部动态流（events）；空世界引导"从模板创建"。
 */
export function TraderBoard() {
  const { list, currentId, setCurrent, openCreate, openEdit, openDetail, events, refresh } = useTraders()
  const [menuFor, setMenuFor] = useState<number | null>(null)
  const [capitalFor, setCapitalFor] = useState<TraderListItem | null>(null)
  const [capitalAmount, setCapitalAmount] = useState('100000')
  const [deleteFor, setDeleteFor] = useState<TraderListItem | null>(null)
  const [exportFor, setExportFor] = useState<TraderListItem | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (menuFor === null) return
    const onDoc = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuFor(null)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [menuFor])

  const run = async (fn: () => Promise<unknown>, okText: string) => {
    try {
      await fn()
      toast('success', okText)
      refresh()
    } catch (e) {
      toast('error', presentError(e as ApiError).text)
    }
  }

  const togglePause = (t: TraderListItem) =>
    run(
      () => traderOps.patch(t.id, { status: t.status === 'paused' ? 'running' : 'paused' }),
      t.status === 'paused' ? '已恢复' : '已暂停',
    )

  return (
    <div className="tboard" data-testid="trader-board">
      <div className="tb-head">
        <span className="micro-label">交易员 · TRADERS</span>
        <span className="num tb-count">({list.length})</span>
        <button type="button" className="tb-add num" onClick={openCreate}>
          ＋ 新建
        </button>
      </div>

      <div className="tb-body">
        {list.length === 0 && (
          <div className="tb-empty">
            <p className="flat">空世界 · 从模板创建第一个交易员</p>
            <button type="button" className="tb-add num" onClick={openCreate}>
              从模板创建
            </button>
          </div>
        )}
        {list.map((t, rank) => (
          <div
            key={t.id}
            className={`tb-row num ${t.id === currentId ? 'selected' : ''} ${t.status !== 'running' ? 'tb-stopped' : ''}`}
            onClick={() => setCurrent(t.id)}
            onDoubleClick={() => {
              setCurrent(t.id)
              openDetail()
            }}
          >
            <span className="tb-rank flat">{rank + 1}</span>
            <span className="tb-name">
              {t.name}
              <span className={`mode-badge mode-${t.mode}`}>{t.mode === 'strategy' ? 'STRAT' : 'MANUAL'}</span>
              {t.status === 'paused' && <span className="tb-status">已暂停</span>}
              {t.status === 'closed' && <span className="tb-status">已关闭</span>}
            </span>
            <span className="tb-strategy flat">{t.strategyType ?? '--'}</span>
            <span className={t.totalReturn > 0 ? 'up' : t.totalReturn < 0 ? 'down' : 'flat'}>
              {fmtPct(t.totalReturn)}
            </span>
            <span className="tb-menu-wrap">
              <button
                type="button"
                className="tb-menu-btn"
                aria-label={`管理 ${t.name}`}
                onClick={(e) => {
                  e.stopPropagation()
                  setMenuFor(menuFor === t.id ? null : t.id)
                }}
              >
                ⋯
              </button>
              {menuFor === t.id && (
                <div className="tb-menu" ref={menuRef} role="menu">
                  <button type="button" role="menuitem" onClick={() => { setMenuFor(null); openEdit(t) }}>编辑</button>
                  <button type="button" role="menuitem" onClick={() => { setMenuFor(null); void togglePause(t) }}>
                    {t.status === 'paused' ? '恢复' : '暂停'}
                  </button>
                  <button type="button" role="menuitem" onClick={() => { setMenuFor(null); setCapitalFor(t) }}>注资</button>
                  <button type="button" role="menuitem" onClick={() => { setMenuFor(null); setExportFor(t) }}>导出</button>
                  <button
                    type="button"
                    role="menuitem"
                    className="tb-menu-danger"
                    onClick={() => { setMenuFor(null); setDeleteFor(t) }}
                  >
                    删除
                  </button>
                </div>
              )}
            </span>
          </div>
        ))}
      </div>

      <div className="tb-stream num">
        {events.slice(0, 3).map((e) => (
          <div key={e.id} className="tb-stream-row">
            <span className="flat">{e.ts.slice(11, 19)}</span>
            <span>{e.text}</span>
          </div>
        ))}
      </div>

      {capitalFor && (
        <div className="dialog-overlay" onClick={() => setCapitalFor(null)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <div className="dialog-title">注资 · {capitalFor.name}</div>
            <label className="field">
              <span className="micro-label">金额（正数）</span>
              <input
                className="num"
                value={capitalAmount}
                onChange={(e) => setCapitalAmount(e.target.value)}
              />
            </label>
            <div className="dialog-actions">
              <button type="button" onClick={() => setCapitalFor(null)}>取消</button>
              <button
                type="button"
                className="btn-primary"
                onClick={() => {
                  const amount = Number(capitalAmount)
                  const t = capitalFor
                  setCapitalFor(null)
                  if (!Number.isFinite(amount) || amount <= 0) {
                    toast('error', '金额必须为正数')
                    return
                  }
                  void run(() => traderOps.inject(t.id, amount), '注资成功')
                }}
              >
                确认注资
              </button>
            </div>
          </div>
        </div>
      )}

      {deleteFor && (
        <div className="dialog-overlay" onClick={() => setDeleteFor(null)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <div className="dialog-title">删除交易员 · {deleteFor.name}</div>
            <p className="dialog-note">软删除：数据保留可审计，确认删除？</p>
            <div className="dialog-actions">
              <button type="button" onClick={() => setDeleteFor(null)}>取消</button>
              <button
                type="button"
                className="btn-danger"
                onClick={() => {
                  const t = deleteFor
                  setDeleteFor(null)
                  void run(() => traderOps.remove(t.id), '已删除')
                }}
              >
                确认删除
              </button>
            </div>
          </div>
        </div>
      )}

      {exportFor && <ExportMenuDialog trader={exportFor} onClose={() => setExportFor(null)} />}
    </div>
  )
}
