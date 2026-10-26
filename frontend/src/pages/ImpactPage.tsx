import { useState } from 'react'
import {
  Box,
  Button,
  Chip,
  FormControlLabel,
  Paper,
  Slider,
  Stack,
  Switch,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import DownloadIcon from '@mui/icons-material/Download'
import { Link as RouterLink, useNavigate } from 'react-router'
import { apiUrl, documentPath } from '../api/client'
import { useDependencies, useHealth, useImpact } from '../api/hooks'
import { DocumentPicker } from '../components/DocumentPicker'
import { ImpactTable } from '../components/ImpactTable'
import { PotentialImpactNotice } from '../components/PotentialImpactNotice'
import { QueryError } from '../components/QueryError'
import { links, useUrlParams } from '../routing'

type Mode = 'impact' | 'dependencies'

export function ImpactPage() {
  const params = useUrlParams()
  const navigate = useNavigate()
  const code = (params.get('code') ?? '').toUpperCase()
  const norma = params.get('norma')
  const limits = useHealth().data?.limits
  const maxDepth = limits?.max_depth ?? 10
  const depth = Math.min(params.getInt('depth', limits?.default_depth ?? 2), maxDepth)
  const mode: Mode = params.get('mode') === 'dependencies' ? 'dependencies' : 'impact'
  const onlyGeneral = params.get('groups') === 'general'
  const groups = onlyGeneral ? ['general'] : undefined

  const [draftDepth, setDraftDepth] = useState<number | null>(null)

  const query = { code, norma, depth, groups }
  const impact = useImpact({ ...query, code: mode === 'impact' ? code : '' })
  const dependencies = useDependencies({ ...query, code: mode === 'dependencies' ? code : '' })
  const result = mode === 'impact' ? impact : dependencies
  const data = result.data

  const csvHref = apiUrl(documentPath(code, '/impact.csv'), {
    norma: data ? data.root.norma : norma,
    depth,
    groups,
  })

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h2">
        Análisis de impacto
      </Typography>
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack spacing={2}>
          <DocumentPicker
            norma={null}
            label={code ? `Documento: ${code} (buscar otro)` : 'Documento a analizar'}
            onSelect={(doc) => params.update({ code: doc.code, norma: doc.norma })}
          />
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={3} sx={{ alignItems: { md: 'center' } }}>
            <ToggleButtonGroup
              size="small"
              exclusive
              value={mode}
              onChange={(_, value: Mode | null) => value && params.update({ mode: value === 'impact' ? null : value })}
            >
              <ToggleButton value="impact">Quién lo cita (impacto)</ToggleButton>
              <ToggleButton value="dependencies">Qué cita (dependencias)</ToggleButton>
            </ToggleButtonGroup>
            <Box sx={{ width: 240 }}>
              <Typography variant="caption" id="depth-label">
                Profundidad: {draftDepth ?? depth}
              </Typography>
              <Slider
                size="small"
                min={1}
                max={maxDepth}
                step={1}
                marks
                value={draftDepth ?? depth}
                onChange={(_, value) => setDraftDepth(value as number)}
                onChangeCommitted={(_, value) => {
                  setDraftDepth(null)
                  params.update({ depth: value as number })
                }}
                aria-labelledby="depth-label"
              />
            </Box>
            <FormControlLabel
              control={
                <Switch
                  checked={onlyGeneral}
                  onChange={(event) => params.update({ groups: event.target.checked ? 'general' : null })}
                />
              }
              label="Solo referencias generales"
            />
          </Stack>
        </Stack>
      </Paper>

      {!code ? (
        <Typography color="text.secondary">Elija un documento para ver su impacto.</Typography>
      ) : null}
      {result.error ? (
        <QueryError error={result.error} onChooseNorma={(value) => params.update({ norma: value })} />
      ) : null}

      {data ? (
        <Stack spacing={2}>
          {mode === 'impact' ? <PotentialImpactNotice text={data.disclaimer} /> : null}
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ alignItems: { md: 'center' } }}>
            <Box sx={{ flex: 1 }}>
              <Typography variant="h6" component="h3" sx={{ fontFamily: 'monospace' }}>
                {data.root.code}
              </Typography>
              <Typography color="text.secondary">
                {data.root.title ?? (data.root.resolved ? '' : 'Código citado sin documento')}
                {data.root.norma ? ` · Norma ${data.root.norma}` : ''}
              </Typography>
            </Box>
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
              {Object.entries(data.summary.by_depth).map(([level, count]) => (
                <Chip key={level} label={`Nivel ${level}: ${count}`} size="small" />
              ))}
            </Stack>
            <Stack direction="row" spacing={1}>
              {data.root.resolved ? (
                <Button component={RouterLink} to={links.document(data.root.code, data.root.norma)}>
                  Detalle
                </Button>
              ) : null}
              <Button onClick={() => navigate(links.graph(data.root.code, data.root.norma, mode === 'impact' ? 'in' : 'out'))}>
                Ver grafo
              </Button>
              {mode === 'impact' ? (
                <Button variant="contained" startIcon={<DownloadIcon />} href={csvHref} download>
                  Exportar CSV
                </Button>
              ) : null}
            </Stack>
          </Stack>

          <Typography variant="subtitle1" component="h4">
            Directos ({data.direct.length})
          </Typography>
          <ImpactTable
            items={data.direct}
            rootNorma={data.root.norma}
            label="Directos"
            emptyText={mode === 'impact' ? 'Ningún documento lo cita.' : 'No cita otros documentos.'}
          />
          <Typography variant="subtitle1" component="h4">
            Indirectos ({data.indirect.length})
          </Typography>
          <ImpactTable
            items={data.indirect}
            rootNorma={data.root.norma}
            label="Indirectos"
            emptyText="Sin resultados indirectos hasta esta profundidad."
          />
        </Stack>
      ) : null}
    </Stack>
  )
}
