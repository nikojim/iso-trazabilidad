import {
  Chip,
  Link,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  type ChipProps,
} from '@mui/material'
import { Link as RouterLink } from 'react-router'
import type { Issue } from '../api/types'
import { links } from '../routing'

const SEVERITY: Record<string, { label: string; color: ChipProps['color'] }> = {
  error: { label: 'Error', color: 'error' },
  warning: { label: 'Advertencia', color: 'warning' },
  info: { label: 'Info', color: 'info' },
}

export function SeverityChip({ severity }: { severity: string }) {
  const info = SEVERITY[severity] ?? { label: severity, color: 'default' }
  return <Chip size="small" label={info.label} color={info.color} variant="outlined" />
}

interface Props {
  issues: Issue[]
  emptyText?: string
  showNorma?: boolean
}

export function IssueTable({ issues, emptyText = 'Sin incidencias abiertas.', showNorma = true }: Props) {
  if (issues.length === 0) {
    return (
      <Typography color="text.secondary" sx={{ py: 2 }}>
        {emptyText}
      </Typography>
    )
  }
  return (
    <TableContainer component={Paper} variant="outlined">
      <Table size="small" aria-label="Incidencias">
        <TableHead>
          <TableRow>
            <TableCell>Severidad</TableCell>
            <TableCell>Tipo</TableCell>
            {showNorma ? <TableCell>Norma</TableCell> : null}
            <TableCell>Código</TableCell>
            <TableCell>Detalle</TableCell>
            <TableCell>Origen</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {issues.map((issue, index) => (
            <TableRow key={issue.id ?? `derived-${index}`} hover>
              <TableCell>
                <SeverityChip severity={issue.severity} />
              </TableCell>
              <TableCell sx={{ fontFamily: 'monospace' }}>{issue.type}</TableCell>
              {showNorma ? <TableCell>{issue.norma ?? '—'}</TableCell> : null}
              <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                {issue.code ? (
                  <Link component={RouterLink} to={links.document(issue.code, issue.norma)}>
                    {issue.code}
                  </Link>
                ) : (
                  '—'
                )}
              </TableCell>
              <TableCell>
                {issue.message}
                {issue.file_path ? (
                  <Typography variant="caption" color="text.secondary" component="div">
                    {issue.file_path}
                  </Typography>
                ) : null}
              </TableCell>
              <TableCell>{issue.source === 'derived' ? 'calculada' : 'ingesta'}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}
