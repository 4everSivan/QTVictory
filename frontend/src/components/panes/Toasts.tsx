import { useEffect, useState } from 'react'

export interface ToastItem {
  id: number
  kind: 'info' | 'success' | 'error'
  text: string
}

type Listener = (t: ToastItem) => void
const listeners = new Set<Listener>()
let seq = 0

/** 全局 Toast（01 §4.10；T19 随生命周期操作引入，T20 接入成交/撤单事件） */
export function toast(kind: ToastItem['kind'], text: string): void {
  seq += 1
  const item: ToastItem = { id: seq, kind, text }
  for (const l of listeners) l(item)
}

export function Toasts({ items }: { items: ToastItem[] }) {
  return (
    <div className="toasts" data-testid="toasts">
      {items.map((t) => (
        <div key={t.id} className={`toast toast-${t.kind}`}>
          {t.text}
        </div>
      ))}
    </div>
  )
}

export function useToasts(ttlMs = 4000): ToastItem[] {
  const [items, setItems] = useState<ToastItem[]>([])
  useEffect(() => {
    const listener: Listener = (t) => {
      setItems((prev) => [...prev.slice(-4), t])
      setTimeout(() => {
        setItems((prev) => prev.filter((x) => x.id !== t.id))
      }, ttlMs)
    }
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
    }
  }, [ttlMs])
  return items
}
