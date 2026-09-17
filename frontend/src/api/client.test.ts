import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, request } from './client'

const fetchMock = vi.fn()

vi.stubGlobal('fetch', fetchMock)

afterEach(() => {
  fetchMock.mockReset()
})

describe('REST client（02 §5.1 统一错误模型）', () => {
  it('成功响应解析 JSON', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ state: 'trading', phase: 'continuous', tradingDate: '2026-09-17' }),
    })
    const data = await api.get('/session')
    expect(data).toEqual({ state: 'trading', phase: 'continuous', tradingDate: '2026-09-17' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/session')
    expect((init as RequestInit).method).toBe('GET')
  })

  it('错误包络转 ApiError（code/message/details/status）', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 400,
      statusText: 'Bad Request',
      text: async () =>
        JSON.stringify({
          code: 'PRICE_BAND',
          message: '申报价格超出有效申报范围',
          details: { limitBand: [9.8, 11.2], effectiveBand: [10.5, 11.2] },
        }),
    })
    const e = await api.post('/traders/1/orders', { code: '600519' }).then(
      () => null,
      (x) => x,
    )
    expect(e).toBeInstanceOf(ApiError)
    expect((e as ApiError).code).toBe('PRICE_BAND')
    expect((e as ApiError).status).toBe(400)
    expect((e as unknown as { details: { limitBand: number[] } }).details.limitBand).toEqual([9.8, 11.2])
  })

  it('非包络错误回落 HTTP_<status>', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      text: async () => '"boom"',
    })
    const e = await request('/x').then(
      () => null,
      (x) => x,
    )
    expect((e as ApiError).code).toBe('HTTP_500')
  })

  it('POST 携带 JSON 头与序列化 body', async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, status: 201, text: async () => '{"id":1}' })
    await api.post('/traders', { name: 'T', mode: 'manual', initialCash: 100 })
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
    expect(JSON.parse(init.body as string).name).toBe('T')
  })

  it('download：成功取 blob 并触发下载', async () => {
    const click = vi.fn()
    vi.spyOn(document, 'createElement').mockReturnValue({ click, href: '', download: '' } as unknown as HTMLAnchorElement)
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:fake')
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      blob: async () => new Blob(['a,b'], { type: 'text/csv' }),
    })
    await api.download('/traders/1/export?type=trades&format=csv')
    expect(click).toHaveBeenCalledOnce()
    expect(revoke).toHaveBeenCalledOnce()
  })
})
