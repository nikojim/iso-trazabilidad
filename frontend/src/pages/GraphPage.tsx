import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  FormControlLabel,
  Grid,
  ListItemText,
  MenuItem,
  Paper,
  Slider,
  Stack,
  Switch,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import { Link as RouterLink } from 'react-router'
import { useHealth, useNeighborhood } from '../api/hooks'
import type { Direction } from '../api/types'
import { DocumentPicker } from '../components/DocumentPicker'
import { GraphLegend } from '../components/GraphLegend'
import { GraphView } from '../components/GraphView'
import { QueryError } from '../components/QueryError'
import { StatusChip } from '../components/StatusChip'
import { KNOWN_TYPES } from '../graph/toElements'
import { links, useUrlParams } from '../routing'

const DIRECTIONS: { value: Direction; label: string }[] = [
  { value: 'in', label: 'Quién lo cita' },
  { value: 'out', label: 'Qué cita' },
  { value: 'both', label: 'Ambos' },
]

function parseDirection(value: string | null): Direction {
  return value === 'in' || value === 'out' ? value : 'both'
}

export function GraphPage() {
  const params = useUrlParams()
  const code = (params.get('code') ?? '').toUpperCase()
  const norma = params.get('norma')
  const direction = parseDirection(params.get('direction'))
  const limits = useHealth().data?.limits
  const maxDepth = limits?.max_depth ?? 10
  const depth = Math.min(params.getInt('depth', limits?.default_depth ?? 2), maxDepth)
  const types = params.getAll('types')
  const includeUnresolved = params.get('unresolved') !== 'false'
  const [draftDepth, setDraftDepth] = useState<number | null>(null)
  const [selected, setSelected] = useState<string | null>(null)

  const { data, error, isFetching } = useNeighborhood({
    code,
    norma,
    depth,
    direction,
    types: types.length ? types : undefined,
    includeUnresolved,
  })
  const selectedNode = data?.nodes.find((node) => node.id === selected)
  const presentTypes = [...new Set(data?.nodes.map((node) => node.document_type) ?? [])].sort()

  const recenter = (nodeId: string) => {
    const node = data?.nodes.find((n) => n.id === nodeId)
    if (!node) return
    setSelected(null)
    params.update({ code: node.code, norma: node.norma })
  }

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h2">
        Grafo de referencias
      </Typography>
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack spacing={2}>
          <DocumentPicker
            norma={null}
            label={code ? `Centro: ${code} (buscar otro)` : 'Documento central'}
            onSelect={(doc) => {
              setSelected(null)
              params.update({ code: doc.code, norma: doc.norma })
            }}
          />
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={3} sx={{ alignItems: { md: 'center' } }}>
            <ToggleButtonGroup
              size="small"
              exclusive
              value={direction}
              onChange={(_, value: Direction | null) => value && params.update({ direction: value })}
              aria-label="Dirección"
            >
              {DIRECTIONS.map((d) => (
                <ToggleButton key={d.value} value={d.value}>
                  {d.label}
                </ToggleButton>
              ))}
            </ToggleButtonGroup>
            <Box sx={{ width: 200 }}>
              <Typography variant="caption" id="graph-depth-label">
                Profundidad: {draftDepth ?? depth}
              </Typography>
              <Slider
                size="small"
                min={1}
                max={maxDepth}
                marks
                value={draftDepth ?? depth}
                onChange={(_, value) => setDraftDepth(value as number)}
                onChangeCommitted={(_, value) => {
                  setDraftDepth(null)
                  params.update({ depth: value as number })
                }}
                aria-labelledby="graph-depth-label"
              />
            </Box>
            <TextField
              select
              size="small"
              label="Tipos"
              value={types}
              onChange={(event) => {
                const value = event.target.value as unknown as string[] | string
                params.update({ types: typeof value === 'string' ? value.split(',') : value })
              }}
              slotProps={{ select: { multiple: true, renderValue: (value) => (value as string[]).join(', ') || 'Todos' } }}
              sx={{ minWidth: 160 }}
            >
              {KNOWN_TYPES.map((type) => (
                <MenuItem key={type} value={type}>
                  <Checkbox size="small" checked={types.includes(type)} />
                  <ListItemText primary={type} />
                </MenuItem>
              ))}
            </TextField>
            <FormControlLabel
              control={
                <Switch
                  checked={includeUnresolved}
                  onChange={(event) => params.update({ unresolved: event.target.checked ? null : 'false' })}
                />
              }
              label="Incluir citados sin documento"
            />
          </Stack>
        </Stack>
      </Paper>

      {!code ? (
        <Typography color="text.secondary">
          Elija un documento: se muestra su vecindad (atraviesa normas), nunca el grafo completo.
          Para ver lo que cita un documento sobre el grafo completo, use “Documento a modificar”.
        </Typography>
      ) : null}
      {error ? <QueryError error={error} onChooseNorma={(value) => params.update({ norma: value })} /> : null}
      {data?.truncated ? (
        <Alert severity="warning">
          El subgrafo supera {limits?.graph_max_nodes ?? 'el máximo de'} nodos: se muestran los más
          cercanos. Reduzca la profundidad o filtre por tipo.
        </Alert>
      ) : null}

      {data ? (
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, lg: 9 }} sx={{ opacity: isFetching ? 0.6 : 1 }}>
            <GraphView data={data} onSelect={setSelected} onRecenter={recenter} />
            <Typography variant="caption" color="text.secondary">
              {data.nodes.length} documentos · {data.edges.length} referencias ·
              clic para ver un documento, doble clic para centrarlo.
            </Typography>
          </Grid>
          <Grid size={{ xs: 12, lg: 3 }}>
            <Stack spacing={2}>
              <Paper variant="outlined" sx={{ p: 2 }} aria-label="Documento seleccionado">
                {selectedNode ? (
                  <Stack spacing={1}>
                    <Typography sx={{ fontFamily: 'monospace', fontWeight: 700 }}>
                      {selectedNode.code}
                    </Typography>
                    <Typography variant="body2">
                      {selectedNode.title ?? (selectedNode.resolved ? '' : 'Citado sin documento')}
                    </Typography>
                    <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
                      {selectedNode.norma ? <Chip size="small" variant="outlined" label={`Norma: ${selectedNode.norma}`} /> : null}
                      {selectedNode.resolved ? <StatusChip status={selectedNode.status} /> : null}
                      <Typography variant="caption">Distancia: {selectedNode.distance}</Typography>
                    </Stack>
                    <Stack direction="row" spacing={1}>
                      {selectedNode.resolved ? (
                        <Button size="small" component={RouterLink} to={links.document(selectedNode.code, selectedNode.norma)}>
                          Abrir detalle
                        </Button>
                      ) : null}
                      {!selectedNode.is_root ? (
                        <Button size="small" onClick={() => recenter(selectedNode.id)}>
                          Centrar aquí
                        </Button>
                      ) : null}
                    </Stack>
                  </Stack>
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    Seleccione un nodo para ver sus datos.
                  </Typography>
                )}
              </Paper>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <GraphLegend types={presentTypes} />
              </Paper>
            </Stack>
          </Grid>
        </Grid>
      ) : null}
    </Stack>
  )
}
