import type { ReactElement } from 'react'
import { render } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from '@mui/material'
import { MemoryRouter, useLocation } from 'react-router'
import App from '../App'
import { createQueryClient } from '../queryClient'
import { theme } from '../theme'

/** Muestra la URL actual para que los tests verifiquen la navegación. */
function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>
}

export function renderApp(route = '/', ui: ReactElement = <App />) {
  const client = createQueryClient()
  client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, retry: false } })
  return render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[route]}>
          {ui}
          <LocationProbe />
        </MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
  )
}
