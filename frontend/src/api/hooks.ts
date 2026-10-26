import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { apiGet, documentPath, type QueryParams } from './client'
import type {
  Cycles,
  DocumentDetail,
  DocumentPage,
  Direction,
  FullGraph,
  Health,
  IssuePage,
  Neighborhood,
  NormaSummary,
  References,
  RunPage,
  Stats,
  Traversal,
  UnresolvedPage,
} from './types'

/** Consulta GET con la clave derivada de la ruta y los parámetros. */
function useApi<T>(path: string, params: QueryParams = {}, enabled = true) {
  return useQuery({
    queryKey: [path, params],
    queryFn: ({ signal }) => apiGet<T>(path, params, signal),
    enabled,
  })
}

export const useHealth = () => useApi<Health>('/health')
export const useNormas = () => useApi<NormaSummary[]>('/normas')
export const useStats = () => useApi<Stats>('/stats')

export interface DocumentSearch {
  query?: string
  norma?: string | null
  type?: string
  status?: string
  page: number
  pageSize: number
}

export function useDocuments(search: DocumentSearch, enabled = true) {
  const params = {
    query: search.query?.trim(),
    norma: search.norma,
    type: search.type,
    status: search.status,
    page: search.page,
    page_size: search.pageSize,
  }
  return useQuery({
    queryKey: ['/documents', params],
    queryFn: ({ signal }) => apiGet<DocumentPage>('/documents', params, signal),
    placeholderData: keepPreviousData, // la tabla no parpadea al paginar
    enabled,
  })
}

export const useDocument = (code: string, norma: string | null) =>
  useApi<DocumentDetail>(documentPath(code), { norma }, Boolean(code))

export const useReferences = (code: string, norma: string | null) =>
  useApi<References>(documentPath(code, '/references'), { norma }, Boolean(code))

export interface TraversalQuery {
  code: string
  norma: string | null
  depth: number
  types?: string[]
  groups?: string[]
}

function traversalParams(query: TraversalQuery): QueryParams {
  return { norma: query.norma, depth: query.depth, types: query.types, groups: query.groups }
}

export const useImpact = (query: TraversalQuery) =>
  useApi<Traversal>(documentPath(query.code, '/impact'), traversalParams(query), Boolean(query.code))

export const useDependencies = (query: TraversalQuery) =>
  useApi<Traversal>(
    documentPath(query.code, '/dependencies'),
    traversalParams(query),
    Boolean(query.code),
  )

export interface NeighborhoodQuery extends TraversalQuery {
  direction: Direction
  includeUnresolved: boolean
}

export const useNeighborhood = (query: NeighborhoodQuery) =>
  useApi<Neighborhood>(
    '/graph',
    {
      code: query.code,
      ...traversalParams(query),
      direction: query.direction,
      include_unresolved: query.includeUnresolved,
    },
    Boolean(query.code),
  )

/**
 * Grafo completo (todas las normas). Se pide una sola vez por versión del grafo: la clave
 * incluye `graph_version`, así una reingesta invalida la copia en memoria.
 */
export function useFullGraph(enabled: boolean) {
  const version = useHealth().data?.graph_version
  return useQuery({
    queryKey: ['/graph/full', version],
    queryFn: ({ signal }) => apiGet<FullGraph>('/graph/full', {}, signal),
    enabled: enabled && version !== undefined,
    staleTime: Infinity,
  })
}

export const useCycles = () => useApi<Cycles>('/graph/cycles')

export interface IssueQuery {
  norma: string | null
  type?: string
  severity?: string
  page: number
  pageSize: number
}

export const useIssues = (query: IssueQuery) =>
  useApi<IssuePage>('/quality/issues', {
    norma: query.norma,
    type: query.type,
    severity: query.severity,
    page: query.page,
    page_size: query.pageSize,
  })

export const useUnresolved = (norma: string | null, page: number, pageSize: number) =>
  useApi<UnresolvedPage>('/references/unresolved', { norma, page, page_size: pageSize })

export const useRuns = (page: number, pageSize: number) =>
  useApi<RunPage>('/ingestion/runs', { page, page_size: pageSize })
