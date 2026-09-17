const memory = new Map<string, string>()

export function lsGet(key: string): string | null {
  try {
    if (typeof globalThis.localStorage?.getItem === 'function') {
      return globalThis.localStorage.getItem(key)
    }
  } catch {
    // 落入内存兜底
  }
  return memory.has(key) ? (memory.get(key) as string) : null
}

export function lsSet(key: string, value: string): void {
  try {
    if (typeof globalThis.localStorage?.setItem === 'function') {
      globalThis.localStorage.setItem(key, value)
      return
    }
  } catch {
    // 落入内存兜底
  }
  memory.set(key, value)
}

export function lsClear(): void {
  try {
    if (typeof globalThis.localStorage?.clear === 'function') {
      globalThis.localStorage.clear()
    }
  } catch {
    // 忽略，仍清空内存兜底
  }
  memory.clear()
}
