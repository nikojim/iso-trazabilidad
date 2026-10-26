import { QueryClient } from '@tanstack/react-query'
import { ApiError } from './api/client'

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        // Los errores 4xx (no encontrado, grafo requerido…) no se reintentan.
        retry: (failureCount, error) =>
          !(error instanceof ApiError && error.status >= 400 && error.status < 500) &&
          failureCount < 2,
      },
    },
  })
}
