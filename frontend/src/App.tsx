import { lazy, Suspense } from 'react'
import { LinearProgress, Link, Stack, Typography } from '@mui/material'
import { Link as RouterLink, Route, Routes } from 'react-router'
import { AppLayout } from './components/AppLayout'
import { DocumentPage } from './pages/DocumentPage'
import { ImpactPage } from './pages/ImpactPage'
import { QualityPage } from './pages/QualityPage'
import { SearchPage } from './pages/SearchPage'

// Cytoscape es la dependencia más pesada: se descarga solo al abrir una vista con grafo.
const GraphPage = lazy(() => import('./pages/GraphPage').then((m) => ({ default: m.GraphPage })))
const ModifyPage = lazy(() => import('./pages/ModifyPage').then((m) => ({ default: m.ModifyPage })))

function NotFoundPage() {
  return (
    <Stack spacing={1}>
      <Typography variant="h5" component="h2">
        Página no encontrada
      </Typography>
      <Link component={RouterLink} to="/">
        Volver a la búsqueda
      </Link>
    </Stack>
  )
}

/** Rutas de la aplicación (el router y el cliente de consultas los provee `main.tsx`). */
export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<SearchPage />} />
        <Route path="documents/:code" element={<DocumentPage />} />
        <Route path="impact" element={<ImpactPage />} />
        <Route
          path="modify"
          element={
            <Suspense fallback={<LinearProgress aria-label="Cargando" />}>
              <ModifyPage />
            </Suspense>
          }
        />
        <Route
          path="graph"
          element={
            <Suspense fallback={<LinearProgress aria-label="Cargando grafo" />}>
              <GraphPage />
            </Suspense>
          }
        />
        <Route path="quality" element={<QualityPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
