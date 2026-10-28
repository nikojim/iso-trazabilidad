import {
  Box,
  Link,
  MenuItem,
  Paper,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import { Link as RouterLink } from 'react-router'
import { useCycles, useIssues, useRuns, useStats, useUnresolved } from '../api/hooks'
import { DependencyPath } from '../components/DependencyPath'
import { NormaSelector } from '../components/NormaSelector'
import { IssueTable } from '../components/IssueTable'
import { QueryError } from '../components/QueryError'
import { links, parseNodeId, useUrlParams } from '../routing'

const ISSUE_TYPES: { value: string; label: string }[] = [
  { value: 'cycle', label: 'Referencias circulares' },
  { value: 'ambiguous_reference', label: 'Cita ambigua entre normas' },
  { value: 'duplicate_across_normas', label: 'Mismo archivo en varias normas' },
  { value: 'cited_title_mismatch', label: 'Título citado distinto del real' },
  { value: 'inconsistent_cited_titles', label: 'Mismo código citado con títulos distintos' },
  { value: 'reference_to_inactive', label: 'Cita a documento inactivo' },
  { value: 'unresolved_similar_code', label: 'Código no resuelto parecido a otro' },
  { value: 'isolated_document', label: 'Documento aislado' },
  { value: 'ambiguous_editions', label: 'Ediciones ambiguas' },
  { value: 'duplicate_copy', label: 'Copia duplicada' },
  { value: 'source_code_conflict', label: 'Código del documento en conflicto' },
  { value: 'source_code_missing', label: 'Sin código de documento' },
  { value: 'section_lost', label: 'Sección REFERENCIAS perdida' },
  { value: 'section_ambiguous', label: 'Sección ambigua' },
  { value: 'section_end_uncertain', label: 'Fin de sección incierto' },
  { value: 'invalid_reference_candidate', label: 'Código inválido' },
  { value: 'self_reference', label: 'Autorreferencia' },
  { value: 'duplicate_in_section', label: 'Referencia duplicada' },
  { value: 'requires_ocr', label: 'Requiere OCR' },
  { value: 'read_error', label: 'Error de lectura' },
  { value: 'file_missing', label: 'Archivo faltante' },
]
const TABS = ['issues', 'unresolved', 'cycles', 'runs'] as const
type TabName = (typeof TABS)[number]

function Stat({ label, value }: { label: string; value: number | string | undefined }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, minWidth: 150 }}>
      <Typography variant="h5" component="p">
        {value ?? '—'}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
    </Paper>
  )
}

function Pagination(props: {
  total: number
  page: number
  pageSize: number
  onPage: (page: number) => void
}) {
  return (
    <TablePagination
      component="div"
      count={props.total}
      page={Math.max(0, props.page - 1)}
      rowsPerPage={props.pageSize}
      rowsPerPageOptions={[props.pageSize]}
      onPageChange={(_, next) => props.onPage(next + 1)}
      labelDisplayedRows={({ from, to, count }) => `${from}–${to} de ${count}`}
    />
  )
}

function IssuesTab({ norma }: { norma: string | null }) {
  const params = useUrlParams()
  const type = params.get('type') ?? ''
  const severity = params.get('severity') ?? ''
  const page = params.getInt('page', 1)
  const { data, error } = useIssues({ norma, type, severity, page, pageSize: 50 })
  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2}>
        <TextField
          select
          size="small"
          label="Tipo"
          value={type}
          onChange={(event) => params.update({ type: event.target.value, page: null })}
          sx={{ minWidth: 300 }}
        >
          <MenuItem value="">Todos</MenuItem>
          {ISSUE_TYPES.map((t) => (
            <MenuItem key={t.value} value={t.value}>
              {t.label}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          size="small"
          label="Severidad"
          value={severity}
          onChange={(event) => params.update({ severity: event.target.value, page: null })}
          sx={{ minWidth: 160 }}
        >
          <MenuItem value="">Todas</MenuItem>
          <MenuItem value="error">Error</MenuItem>
          <MenuItem value="warning">Advertencia</MenuItem>
          <MenuItem value="info">Info</MenuItem>
        </TextField>
      </Stack>
      {error ? <QueryError error={error} /> : null}
      {data ? (
        <Box>
          <IssueTable issues={data.items} showNorma={!norma} />
          <Pagination total={data.total} page={page} pageSize={50} onPage={(p) => params.update({ page: p })} />
        </Box>
      ) : null}
    </Stack>
  )
}

function UnresolvedTab({ norma }: { norma: string | null }) {
  const params = useUrlParams()
  const page = params.getInt('page', 1)
  const { data, error } = useUnresolved(norma, page, 50)
  if (error) return <QueryError error={error} />
  if (!data) return null
  return (
    <TableContainer component={Paper} variant="outlined">
      <Table size="small" aria-label="Referencias pendientes">
        <TableHead>
          <TableRow>
            <TableCell>Código citado</TableCell>
            <TableCell>Motivo</TableCell>
            <TableCell>Título con que se cita</TableCell>
            <TableCell>Citado por</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {data.items.map((item) => (
            <TableRow key={item.target_code} hover>
              <TableCell sx={{ fontFamily: 'monospace' }}>
                <Link component={RouterLink} to={links.impact(item.target_code)}>
                  {item.target_code}
                </Link>
              </TableCell>
              <TableCell>
                {item.candidate_normas.length > 1
                  ? `Ambiguo: existe en ${item.candidate_normas.join(', ')}`
                  : 'Sin documento'}
              </TableCell>
              <TableCell>{item.title_hint ?? '—'}</TableCell>
              <TableCell>
                <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
                  {item.cited_by.map((source) => {
                    const { norma, code } = parseNodeId(source)
                    return (
                      <Link key={source} component={RouterLink} to={links.document(code, norma)} title={source} sx={{ fontFamily: 'monospace' }}>
                        {code}
                      </Link>
                    )
                  })}
                </Stack>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Pagination total={data.total} page={page} pageSize={50} onPage={(p) => params.update({ page: p })} />
    </TableContainer>
  )
}

function CyclesTab({ norma }: { norma: string | null }) {
  const { data, error } = useCycles()
  if (error) return <QueryError error={error} />
  if (!data) return null
  // Un ciclo pertenece a la norma elegida si alguno de sus documentos está en ella.
  const cycles = norma
    ? data.cycles.filter((cycle) => cycle.some((id) => parseNodeId(id).norma === norma))
    : data.cycles
  if (cycles.length === 0) return <Typography>No hay referencias circulares.</Typography>
  return (
    <Stack spacing={1} aria-label="Ciclos">
      {cycles.map((cycle) => (
        <Paper key={cycle.join('>')} variant="outlined" sx={{ p: 1 }}>
          <DependencyPath path={[...cycle, cycle[0]]} />
        </Paper>
      ))}
    </Stack>
  )
}

/** Nombre del archivo de log (la ruta completa queda en el tooltip). */
function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path
}

function RunsTab() {
  const params = useUrlParams()
  const page = params.getInt('page', 1)
  const { data, error } = useRuns(page, 20)
  if (error) return <QueryError error={error} />
  if (!data) return null
  return (
    <TableContainer component={Paper} variant="outlined">
      <Table size="small" aria-label="Corridas de ingesta">
        <TableHead>
          <TableRow>
            <TableCell>#</TableCell>
            <TableCell>Inicio</TableCell>
            <TableCell>Modo</TableCell>
            <TableCell>Estado</TableCell>
            <TableCell align="right">Procesados</TableCell>
            <TableCell align="right">Sin cambios</TableCell>
            <TableCell align="right">Nuevos</TableCell>
            <TableCell align="right">Errores</TableCell>
            <TableCell align="right">Faltantes</TableCell>
            <TableCell align="right">Referencias</TableCell>
            <TableCell align="right">Duplicadas</TableCell>
            <TableCell align="right">Pendientes</TableCell>
            <TableCell>Log</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {data.items.map((run) => (
            <TableRow key={run.id}>
              <TableCell>{run.id}</TableCell>
              <TableCell>{new Date(run.started_at).toLocaleString('es')}</TableCell>
              <TableCell>{run.mode}</TableCell>
              <TableCell>{run.status}</TableCell>
              <TableCell align="right">{run.processed_count}</TableCell>
              <TableCell align="right">{run.skipped_count}</TableCell>
              <TableCell align="right">{run.new_count}</TableCell>
              <TableCell align="right">{run.error_count}</TableCell>
              <TableCell align="right">{run.missing_count}</TableCell>
              <TableCell align="right">{run.references_count}</TableCell>
              <TableCell align="right">{run.duplicate_references_count}</TableCell>
              <TableCell align="right">{run.unresolved_count}</TableCell>
              <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }} title={run.log_path ?? ''}>
                {run.log_path ? fileName(run.log_path) : '—'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Pagination total={data.total} page={page} pageSize={20} onPage={(p) => params.update({ page: p })} />
    </TableContainer>
  )
}

export function QualityPage() {
  const params = useUrlParams()
  const norma = params.get('norma')
  const tab: TabName = (TABS as readonly string[]).includes(params.get('tab') ?? '')
    ? (params.get('tab') as TabName)
    : 'issues'
  const stats = useStats().data
  const normaStats = norma ? stats?.normas.find((n) => n.name === norma) : undefined

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
        <Typography variant="h5" component="h2" sx={{ flex: 1 }}>
          Calidad
        </Typography>
        <NormaSelector value={norma} onChange={(value) => params.update({ norma: value, page: null })} />
      </Stack>
      <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap', rowGap: 2 }}>
        <Stat label="Documentos" value={normaStats ? String(normaStats.documents) : stats?.documents} />
        <Stat label="Referencias" value={normaStats ? String(normaStats.references) : stats?.references} />
        <Stat
          label="Citados sin documento"
          value={normaStats ? String(normaStats.unresolved) : stats?.unresolved_references}
        />
        {normaStats ? <Stat label="Citan a otra norma" value={String(normaStats.cross_norma)} /> : null}
        <Stat label="Incidencias abiertas (ingesta)" value={stats?.open_issues} />
        <Stat label="Sin sección REFERENCIAS" value={stats?.by_status.no_section ?? 0} />
      </Stack>
      <Tabs
        value={tab}
        onChange={(_, value: TabName) => params.update({ tab: value === 'issues' ? null : value, page: null, type: null, severity: null })}
      >
        <Tab value="issues" label="Incidencias" />
        <Tab value="unresolved" label="Referencias pendientes" />
        <Tab value="cycles" label="Ciclos" />
        <Tab value="runs" label="Ingestas" />
      </Tabs>
      {tab === 'issues' ? <IssuesTab norma={norma} /> : null}
      {tab === 'unresolved' ? <UnresolvedTab norma={norma} /> : null}
      {tab === 'cycles' ? <CyclesTab norma={norma} /> : null}
      {tab === 'runs' ? <RunsTab /> : null}
    </Stack>
  )
}
