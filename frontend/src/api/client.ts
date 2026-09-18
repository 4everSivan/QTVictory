import { API_BASE, API_KEY } from './config'
import type { ApiErrorBody } from './types'

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly details: unknown

  constructor(status: number, body: ApiErrorBody) {
    super(body.message)
    this.name = 'ApiError'
    this.code = body.code
    this.status = status
    this.details = body.details
  }
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as ApiErrorBody).code === 'string' &&
    typeof (value as ApiErrorBody).message === 'string'
  )
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH'
  body?: unknown
  headers?: Record<string, string>
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, headers = {} } = options
  const init: RequestInit = {
    method,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(API_KEY ? { 'X-API-Key': API_KEY } : {}),
      ...headers,
    },
  }
  if (body !== undefined) init.body = JSON.stringify(body)

  const res = await fetch(`${API_BASE}${path}`, init)
  if (res.status === 204) return undefined as T

  const text = await res.text()
  const parsed: unknown = text ? JSON.parse(text) : null
  if (!res.ok) {
    if (isApiErrorBody(parsed)) throw new ApiError(res.status, parsed)
    throw new ApiError(res.status, {
      code: `HTTP_${res.status}`,
      message: res.statusText || '请求失败',
      details: parsed,
    })
  }
  return parsed as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  /** 触发浏览器下载（导出菜单，01 §4.10） */
  async download(path: string, filename?: string): Promise<void> {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: API_KEY ? { 'X-API-Key': API_KEY } : {},
    })
    if (!res.ok) {
      const parsed: unknown = await res.json().catch(() => null)
      if (isApiErrorBody(parsed)) throw new ApiError(res.status, parsed)
      throw new ApiError(res.status, { code: `HTTP_${res.status}`, message: '下载失败', details: null })
    }
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename ?? 'export'
    a.click()
    URL.revokeObjectURL(url)
  },
}
