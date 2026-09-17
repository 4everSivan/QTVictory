export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://127.0.0.1:8787/api'

export const API_KEY: string = (import.meta.env.VITE_API_KEY as string | undefined) ?? ''

export const WS_URL: string = API_BASE.replace(/^http/, 'ws').replace(/\/api\/?$/, '/ws')
