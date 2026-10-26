import { AppBar, Box, Button, Container, Stack, Toolbar, Typography } from '@mui/material'
import { NavLink, Outlet, useLocation, useSearchParams } from 'react-router'
import { buildQuery } from '../api/client'

const SECTIONS = [
  { to: '/', label: 'Buscar', match: (path: string) => path === '/' || path.startsWith('/documents') },
  { to: '/modify', label: 'Documento a modificar', match: (path: string) => path.startsWith('/modify') },
  { to: '/impact', label: 'Impacto', match: (path: string) => path.startsWith('/impact') },
  { to: '/graph', label: 'Grafo', match: (path: string) => path.startsWith('/graph') },
  { to: '/quality', label: 'Calidad', match: (path: string) => path.startsWith('/quality') },
]

export function AppLayout() {
  const { pathname } = useLocation()
  const [searchParams] = useSearchParams()
  // Al cambiar de sección se conservan la norma y el documento en consulta.
  const carry = buildQuery({ norma: searchParams.get('norma'), code: searchParams.get('code') })

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'grey.50' }}>
      <AppBar position="static" elevation={0}>
        <Toolbar sx={{ gap: 3 }}>
          <Typography variant="h6" component="h1" sx={{ fontWeight: 700 }}>
            ISO Trace
          </Typography>
          <Stack direction="row" spacing={1} component="nav" aria-label="Secciones">
            {SECTIONS.map((section) => {
              const active = section.match(pathname)
              return (
                <Button
                  key={section.to}
                  component={NavLink}
                  to={`${section.to}${section.to === '/' ? buildQuery({ norma: searchParams.get('norma') }) : carry}`}
                  color="inherit"
                  aria-current={active ? 'page' : undefined}
                  sx={{ borderBottom: 2, borderColor: active ? 'common.white' : 'transparent', borderRadius: 0 }}
                >
                  {section.label}
                </Button>
              )
            })}
          </Stack>
        </Toolbar>
      </AppBar>
      <Container maxWidth="xl" sx={{ py: 3 }}>
        <Outlet />
      </Container>
    </Box>
  )
}
