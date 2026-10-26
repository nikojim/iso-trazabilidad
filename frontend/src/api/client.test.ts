import { http, HttpResponse } from 'msw'
import { server } from '../test/server'
import { ApiError, apiGet, apiUrl, buildQuery, documentPath } from './client'

describe('buildQuery', () => {
  it('omite vacíos y repite las listas', () => {
    expect(buildQuery({ norma: 'SGSA ISO 20000', depth: 2, query: '', type: null, types: ['PR', 'PO'] })).toBe(
      '?norma=SGSA+ISO+20000&depth=2&types=PR&types=PO',
    )
  })

  it('devuelve cadena vacía sin parámetros', () => {
    expect(buildQuery({ norma: undefined })).toBe('')
  })

  it('codifica el código del documento en la ruta', () => {
    expect(apiUrl(documentPath('MC-SGG-435', '/impact.csv'), { depth: 3 })).toBe(
      '/api/documents/MC-SGG-435/impact.csv?depth=3',
    )
  })
})

describe('apiGet', () => {
  it('convierte el error uniforme de la API en ApiError', async () => {
    const error = await apiGet('/documents/MC-SGG-435').catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(409)
    expect((error as ApiError).code).toBe('norma_required')
    expect((error as ApiError).normas).toEqual(['A', 'B'])
  })

  it('tolera respuestas de error sin JSON', async () => {
    server.use(http.get('*/api/health', () => new HttpResponse('boom', { status: 502 })))

    await expect(apiGet('/health')).rejects.toMatchObject({ status: 502, code: 'http_error' })
  })

  it('informa cuando la API no responde', async () => {
    server.use(http.get('*/api/health', () => HttpResponse.error()))

    await expect(apiGet('/health')).rejects.toMatchObject({ code: 'network_error' })
  })
})
