import { useState, type ReactNode } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  Grid,
  Paper,
  Stack,
  Tab,
  Tabs,
  Typography,
} from '@mui/material'
import { Link as RouterLink, useParams } from 'react-router'
import { ApiError } from '../api/client'
import { useDocument, useReferences } from '../api/hooks'
import type { DocumentDetail } from '../api/types'
import { IssueTable } from '../components/IssueTable'
import { QueryError } from '../components/QueryError'
import { ReferenceList } from '../components/ReferenceList'
import { StatusChip } from '../components/StatusChip'
import { links, useUrlParams } from '../routing'

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2">{value ?? '—'}</Typography>
    </Box>
  )
}

function DocumentHeader({ document }: { document: DocumentDetail }) {
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={2}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
          <StatusChip status={document.extraction_status} />
          {!document.is_active ? <Chip size="small" color="default" label="Inactivo" /> : null}
          <Chip size="small" variant="outlined" label={`Norma: ${document.norma}`} />
        </Stack>
        {document.references_stale ? (
          <Alert severity="warning">
            Las referencias pueden estar desactualizadas: la última versión del archivo no se pudo
            procesar y se conservan las referencias anteriores.
          </Alert>
        ) : null}
        <Grid container spacing={2}>
          <Grid size={{ xs: 6, md: 2 }}>
            <Field label="Tipo" value={document.document_type} />
          </Grid>
          <Grid size={{ xs: 6, md: 2 }}>
            <Field label="Sistema" value={document.system_code} />
          </Grid>
          <Grid size={{ xs: 6, md: 2 }}>
            <Field label="Versión" value={document.version} />
          </Grid>
          <Grid size={{ xs: 6, md: 2 }}>
            <Field label="Formato" value={document.file_format.toUpperCase()} />
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <Field
              label="Última ingesta"
              value={
                document.last_processed_at
                  ? new Date(document.last_processed_at).toLocaleString('es')
                  : null
              }
            />
          </Grid>
          <Grid size={12}>
            <Field label="Archivo" value={document.file_path} />
          </Grid>
        </Grid>
      </Stack>
    </Paper>
  )
}

export function DocumentPage() {
  const { code: rawCode = '' } = useParams()
  const code = rawCode.toUpperCase()
  const params = useUrlParams()
  const norma = params.get('norma')
  const [tab, setTab] = useState(0)

  const detail = useDocument(code, norma)
  const references = useReferences(code, norma)
  const chooseNorma = (value: string) => params.update({ norma: value })

  const onlyCited =
    detail.error instanceof ApiError && detail.error.status === 404 && references.data?.resolved === false
  // Un código citado sin documento no tiene norma: sus enlaces van sin ella.
  const resolvedNorma = references.data ? references.data.norma : (detail.data?.norma ?? norma)

  if (references.error) return <QueryError error={references.error} onChooseNorma={chooseNorma} />

  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ alignItems: { md: 'center' } }}>
        <Box sx={{ flex: 1 }}>
          <Typography variant="h5" component="h2" sx={{ fontFamily: 'monospace' }}>
            {code}
          </Typography>
          <Typography color="text.secondary">
            {detail.data?.title ?? (onlyCited ? 'Código citado sin documento' : '')}
          </Typography>
        </Box>
        {references.data ? (
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
            {references.data.resolved ? (
              <Button variant="contained" component={RouterLink} to={links.modify(code, resolvedNorma)}>
                Ver documentos que cita
              </Button>
            ) : null}
            <Button variant="outlined" component={RouterLink} to={links.impact(code, resolvedNorma)}>
              Análisis de impacto
            </Button>
            <Button variant="outlined" component={RouterLink} to={links.graph(code, resolvedNorma)}>
              Ver grafo
            </Button>
          </Stack>
        ) : null}
      </Stack>

      {detail.data ? <DocumentHeader document={detail.data} /> : null}
      {onlyCited ? (
        <Alert severity="info">
          Ningún archivo tiene este código (o existe en varias normas y la cita es ambigua): se
          muestran solo los documentos que lo citan.
        </Alert>
      ) : null}
      {detail.error && !onlyCited && !references.isLoading ? <QueryError error={detail.error} /> : null}

      <Tabs value={tab} onChange={(_, value: number) => setTab(value)}>
        <Tab label="Referencias" />
        <Tab label={`Incidencias (${detail.data?.open_issues.length ?? 0})`} disabled={!detail.data} />
      </Tabs>

      {tab === 0 && references.data ? (
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, lg: 6 }}>
            <Stack spacing={2}>
              <ReferenceList
                title="Documentos que cita"
                subtitle="Referencias salientes: este documento los menciona en su sección REFERENCIAS"
                items={references.data.outgoing}
                emptyText={
                  detail.data?.extraction_status === 'no_section'
                    ? 'El documento no tiene sección REFERENCIAS.'
                    : detail.data?.extraction_status === 'not_applicable'
                      ? 'Las planillas no se analizan: solo pueden ser citadas.'
                      : 'No cita otros documentos.'
                }
              />
              {references.data.unresolved.length > 0 ? (
                <ReferenceList
                  title="Citados sin documento"
                  subtitle="Códigos que cita sin archivo, o presentes en varias normas (no resueltos)"
                  items={references.data.unresolved}
                  emptyText=""
                />
              ) : null}
            </Stack>
          </Grid>
          <Grid size={{ xs: 12, lg: 6 }}>
            <ReferenceList
              title="Documentos que lo citan"
              subtitle="Referencias entrantes: podrían requerir revisión si este documento cambia"
              items={references.data.incoming}
              emptyText="Ningún documento lo cita."
            />
          </Grid>
        </Grid>
      ) : null}
      {tab === 0 && references.isLoading ? <Typography>Cargando referencias…</Typography> : null}
      {tab === 1 && detail.data ? (
        <IssueTable issues={detail.data.open_issues} showNorma={false} />
      ) : null}
    </Stack>
  )
}
