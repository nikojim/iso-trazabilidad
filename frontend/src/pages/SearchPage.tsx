import { Fragment, useEffect, useState } from 'react'
import {
  Link,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { Link as RouterLink } from 'react-router'
import { useDocuments } from '../api/hooks'
import { NormaSelector } from '../components/NormaSelector'
import { QueryError } from '../components/QueryError'
import { StatusChip } from '../components/StatusChip'
import { KNOWN_TYPES } from '../graph/toElements'
import { links, useUrlParams } from '../routing'

const STATUSES = ['ok', 'no_references', 'no_section', 'not_applicable', 'needs_review', 'requires_ocr', 'error']
const PAGE_SIZES = [25, 50, 100]

export function SearchPage() {
  const params = useUrlParams()
  const norma = params.get('norma')
  const query = params.get('query') ?? ''
  const type = params.get('type') ?? ''
  const status = params.get('status') ?? ''
  const page = params.getInt('page', 1)
  const pageSize = params.getInt('page_size', 50)

  // El texto se escribe en local y se pasa a la URL con un pequeño retardo.
  const [text, setText] = useState(query)
  const [syncedQuery, setSyncedQuery] = useState(query)
  if (query !== syncedQuery) {
    // La URL cambió desde afuera (atrás/adelante, enlace): se refleja en el campo.
    setSyncedQuery(query)
    setText(query)
  }
  useEffect(() => {
    if (text === query) return
    const timer = setTimeout(() => params.update({ query: text, page: null }), 300)
    return () => clearTimeout(timer)
  }, [text, query, params])

  const { data, error, isLoading, isFetching } = useDocuments({
    query,
    norma,
    type,
    status,
    page,
    pageSize,
  })

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h2">
        Documentos por norma
      </Typography>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
        <TextField
          size="small"
          label="Código o título"
          value={text}
          onChange={(event) => setText(event.target.value)}
          sx={{ flex: 1 }}
          slotProps={{ htmlInput: { 'aria-label': 'Buscar por código o título' } }}
        />
        <NormaSelector value={norma} onChange={(value) => params.update({ norma: value, page: null })} />
        <TextField
          select
          size="small"
          label="Tipo"
          value={type}
          onChange={(event) => params.update({ type: event.target.value, page: null })}
          sx={{ minWidth: 120 }}
        >
          <MenuItem value="">Todos</MenuItem>
          {KNOWN_TYPES.map((t) => (
            <MenuItem key={t} value={t}>
              {t}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          size="small"
          label="Estado"
          value={status}
          onChange={(event) => params.update({ status: event.target.value, page: null })}
          sx={{ minWidth: 160 }}
        >
          <MenuItem value="">Todos</MenuItem>
          {STATUSES.map((s) => (
            <MenuItem key={s} value={s}>
              <StatusChip status={s} />
            </MenuItem>
          ))}
        </TextField>
      </Stack>

      {error ? <QueryError error={error} /> : null}

      <TableContainer component={Paper} variant="outlined" sx={{ opacity: isFetching ? 0.7 : 1 }}>
        <Table size="small" aria-label="Documentos">
          <TableHead>
            <TableRow>
              <TableCell>Código</TableCell>
              <TableCell>Título</TableCell>
              <TableCell>Tipo</TableCell>
              <TableCell>Formato</TableCell>
              <TableCell>Versión</TableCell>
              <TableCell>Estado</TableCell>
              <TableCell align="right" title="Documentos que cita">
                Cita
              </TableCell>
              <TableCell align="right" title="Documentos que lo citan">
                Citado por
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={8}>Cargando…</TableCell>
              </TableRow>
            ) : null}
            {data?.items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8}>No hay documentos que coincidan.</TableCell>
              </TableRow>
            ) : null}
            {data?.items.map((doc, index) => (
              <Fragment key={`${doc.norma}/${doc.code}`}>
                {/* La API ordena por norma y nombre: un subtítulo al empezar cada norma. */}
                {index === 0 || data.items[index - 1].norma !== doc.norma ? (
                  <TableRow>
                    <TableCell colSpan={8} component="th" scope="rowgroup" sx={{ bgcolor: 'grey.100', fontWeight: 700 }}>
                      {doc.norma}
                    </TableCell>
                  </TableRow>
                ) : null}
              <TableRow hover>
                <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                  <Link component={RouterLink} to={links.document(doc.code, doc.norma)}>
                    {doc.code}
                  </Link>
                </TableCell>
                <TableCell>{doc.title ?? '—'}</TableCell>
                <TableCell>{doc.document_type}</TableCell>
                <TableCell>{doc.file_format.toUpperCase()}</TableCell>
                <TableCell>{doc.version ?? '—'}</TableCell>
                <TableCell>
                  <StatusChip status={doc.extraction_status} />
                </TableCell>
                <TableCell align="right">{doc.outgoing_count}</TableCell>
                <TableCell align="right">{doc.incoming_count}</TableCell>
              </TableRow>
              </Fragment>
            ))}
          </TableBody>
        </Table>
        <TablePagination
          component="div"
          count={data?.total ?? 0}
          page={Math.max(0, page - 1)}
          rowsPerPage={pageSize}
          rowsPerPageOptions={PAGE_SIZES}
          onPageChange={(_, next) => params.update({ page: next + 1 })}
          onRowsPerPageChange={(event) =>
            params.update({ page_size: Number(event.target.value), page: null })
          }
          labelRowsPerPage="Por página"
          labelDisplayedRows={({ from, to, count }) => `${from}–${to} de ${count}`}
        />
      </TableContainer>
    </Stack>
  )
}
