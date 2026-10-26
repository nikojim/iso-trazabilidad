import type { ErrorBody } from './types'

export const API_BASE = '/api'

export type QueryValue = string | number | boolean | null | undefined | readonly string[]
export type QueryParams = Record<string, QueryValue>

/** Error de la API con el formato uniforme `{"error": {code, message, details}}`. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(status: number, body: ErrorBody) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.details = body.details ?? {}
  }

  /** Normas entre las que hay que elegir cuando el código es documento en varias (409). */
  get normas(): string[] {
    const normas = this.details.normas
    return Array.isArray(normas) ? normas.map(String) : []
  }
}

/** Arma la query string; omite vacíos y repite las listas (`?types=PR&types=PO`). */
export function buildQuery(params: QueryParams = {}): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, item)
    } else {
      search.append(key, String(value))
    }
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export function apiUrl(path: string, params?: QueryParams): string {
  return `${API_BASE}${path}${buildQuery(params)}`
}

async function errorFrom(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as { error?: ErrorBody }
    if (body.error) return new ApiError(response.status, body.error)
  } catch {
    // respuesta sin JSON: se usa el mensaje genérico
  }
  return new ApiError(response.status, {
    code: 'http_error',
    message: `Error ${response.status} al consultar la API`,
    details: {},
  })
}

export async function apiGet<T>(
  path: string,
  params?: QueryParams,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response
  try {
    response = await fetch(new URL(apiUrl(path, params), window.location.href), {
      headers: { Accept: 'application/json' },
      signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(0, {
      code: 'network_error',
      message: 'No se pudo conectar con la API. ¿Está corriendo `iso-trace api serve`?',
      details: {},
    })
  }
  if (!response.ok) throw await errorFrom(response)
  return (await response.json()) as T
}

/** Ruta de un documento en la API (el código se codifica por si trae caracteres raros). */
export function documentPath(code: string, suffix = ''): string {
  return `/documents/${encodeURIComponent(code)}${suffix}`
}
