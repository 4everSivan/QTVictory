import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../../api/client'
import { presentError } from '../../api/errors'
import type { SuggestItem } from '../../api/types'
import { rememberName, watchlistOps } from '../../state/watchlist'
import { toast } from './Toasts'

interface WatchAddPopProps {
  onClose: () => void
  /** 添加成功（含幂等命中）后回调：父级重拉自选集并关闭弹层 */
  onAdded: () => void
}

const DEBOUNCE_MS = 250

/**
 * 自选股添加弹层（T24-2，01 §4.2 v5）：输入代码或名称触发模糊联想
 * （GET /market/suggest，输入防抖），↑↓ 选择 + 回车确认、Esc 关闭；
 * 无选中联想项时回车直接按输入码提交（后端校验归一）。确认后
 * PUT /watchlist/{code}，成功即入列置顶，失败转 Toast。
 */
export function WatchAddPop({ onClose, onAdded }: WatchAddPopProps) {
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<SuggestItem[]>([])
  const [active, setActive] = useState(-1)
  const [busy, setBusy] = useState(false)
  const seq = useRef(0)
  const wrapRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [onClose])

  useEffect(() => {
    const q = query.trim()
    if (!q) {
      setItems([])
      setActive(-1)
      return
    }
    const mySeq = ++seq.current
    const timer = setTimeout(() => {
      watchlistOps
        .suggest(q)
        .then((r) => {
          if (seq.current !== mySeq) return
          setItems(r.data)
          setActive(-1)
        })
        .catch(() => {
          if (seq.current === mySeq) setItems([])
        })
    }, DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [query])

  const confirm = async (code: string) => {
    if (busy || !code) return
    setBusy(true)
    try {
      const r = await watchlistOps.add(code)
      rememberName(r.code, r.name)
      onAdded()
    } catch (e) {
      toast('error', presentError(e as ApiError).text)
      setBusy(false)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => (items.length === 0 ? -1 : Math.min(a + 1, items.length - 1)))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => (a <= 0 ? -1 : a - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const code = active >= 0 ? items[active]?.code : query.trim()
      if (code) void confirm(code)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    }
  }

  return (
    <div className="wl-add-pop" ref={wrapRef} data-testid="watch-add">
      <input
        className="wl-add-input"
        autoFocus
        placeholder="代码 / 名称"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={onKeyDown}
      />
      {items.length > 0 && (
        <div className="wl-suggest" role="listbox">
          {items.map((it, i) => (
            <button
              type="button"
              key={it.code}
              role="option"
              aria-selected={i === active}
              className={`wl-suggest-item ${i === active ? 'active' : ''}`}
              onMouseEnter={() => setActive(i)}
              onClick={() => void confirm(it.code)}
            >
              <span className="wl-suggest-name">{it.name}</span>
              <span className="wl-suggest-code num">{it.code}</span>
              <span className="micro-label">{it.kind.toUpperCase()}</span>
            </button>
          ))}
        </div>
      )}
      {query.trim() !== '' && items.length === 0 && (
        <div className="wl-suggest-empty">无联想结果 · 回车按代码直接添加</div>
      )}
    </div>
  )
}
