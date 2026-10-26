import {
  Chip,
  Link,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Typography,
} from '@mui/material'
import { Link as RouterLink } from 'react-router'
import type { TraversalItem } from '../api/types'
import { links } from '../routing'
import { DependencyPath } from './DependencyPath'

interface Props {
  items: TraversalItem[]
  emptyText: string
  label: string
  /** Norma del documento analizado: las otras se destacan como referencias entre normas. */
  rootNorma?: string | null
}

export function ImpactTable({ items, emptyText, label, rootNorma }: Props) {
  if (items.length === 0) {
    return (
      <Typography color="text.secondary" sx={{ py: 2 }}>
        {emptyText}
      </Typography>
    )
  }
  return (
    <TableContainer component={Paper} variant="outlined">
      <Table size="small" aria-label={label}>
        <TableHead>
          <TableRow>
            <TableCell>Código</TableCell>
            <TableCell>Título</TableCell>
            <TableCell>Norma</TableCell>
            <TableCell>Tipo</TableCell>
            <TableCell align="right">Profundidad</TableCell>
            <TableCell>Relación</TableCell>
            <TableCell>Ruta (→ = cita a)</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.node_id} hover>
              <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                {item.resolved ? (
                  <Link component={RouterLink} to={links.document(item.code, item.norma)}>
                    {item.code}
                  </Link>
                ) : (
                  <>
                    {item.code}{' '}
                    <Chip size="small" label="sin documento" variant="outlined" />
                  </>
                )}
              </TableCell>
              <TableCell>{item.title ?? '—'}</TableCell>
              <TableCell sx={{ whiteSpace: 'nowrap' }}>
                {item.norma ?? '—'}
                {rootNorma && item.norma && item.norma !== rootNorma ? (
                  <Chip size="small" label="otra norma" color="secondary" variant="outlined" sx={{ ml: 1 }} />
                ) : null}
              </TableCell>
              <TableCell>{item.document_type}</TableCell>
              <TableCell align="right">{item.depth}</TableCell>
              <TableCell>{item.relation}</TableCell>
              <TableCell>
                <DependencyPath path={item.path} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}
