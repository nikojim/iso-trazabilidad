import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router'
import { buildQuery, type QueryParams } from './api/client'

/** Lee y actualiza parámetros de la URL, para que cada vista se pueda compartir con un enlace. */
export function useUrlParams() {
  const [searchParams, setSearchParams] = useSearchParams()

  const get = useCallback((key: string) => searchParams.get(key), [searchParams])
  const getAll = useCallback((key: string) => searchParams.getAll(key), [searchParams])
  const getInt = useCallback(
    (key: string, fallback: number) => {
      const value = Number.parseInt(searchParams.get(key) ?? '', 10)
      return Number.isFinite(value) ? value : fallback
    },
    [searchParams],
  )

  const update = useCallback(
    (changes: QueryParams) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current)
          for (const [key, value] of Object.entries(changes)) {
            next.delete(key)
            if (value === null || value === undefined || value === '') continue
            if (Array.isArray(value)) value.forEach((item) => next.append(key, item))
            else next.set(key, String(value))
          }
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  return useMemo(() => ({ get, getAll, getInt, update }), [get, getAll, getInt, update])
}

/**
 * Enlaces internos. La norma va explícita cuando se conoce (evita el 409 si el código es
 * documento en varias normas); un código citado sin documento no lleva norma.
 */
export const links = {
  search: (norma?: string | null) => `/${buildQuery({ norma })}`,
  document: (code: string, norma?: string | null) =>
    `/documents/${encodeURIComponent(code)}${buildQuery({ norma })}`,
  impact: (code: string, norma?: string | null, depth?: number) =>
    `/impact${buildQuery({ code, norma, depth })}`,
  graph: (code: string, norma?: string | null, direction?: string) =>
    `/graph${buildQuery({ code, norma, direction })}`,
  modify: (code: string, norma?: string | null, tab?: 'graph') =>
    `/modify${buildQuery({ code, norma, tab })}`,
  quality: (norma?: string | null) => `/quality${buildQuery({ norma })}`,
}

/** `"norma/código"` (documento) o `"código"` (citado sin documento): id de un nodo del grafo. */
export function parseNodeId(id: string): { norma: string | null; code: string } {
  const slash = id.lastIndexOf('/')
  return slash < 0 ? { norma: null, code: id } : { norma: id.slice(0, slash), code: id.slice(slash + 1) }
}
