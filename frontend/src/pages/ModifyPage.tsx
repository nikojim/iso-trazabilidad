import { useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  FormControlLabel,
  Grid,
  LinearProgress,
  Paper,
  Slider,
  Stack,
  Switch,
  Tab,
  Tabs,
  Typography,
} from '@mui/material'
import { Link as RouterLink } from 'react-router'
import { useDependencies, useFullGraph, useHealth, useImpact } from '../api/hooks'
import type { FullGraph, Traversal } from '../api/types'
import { DocumentPicker } from '../components/DocumentPicker'
import { FullGraphView } from '../components/FullGraphView'
import { GraphLegend } from '../components/GraphLegend'
import { ImpactTable } from '../components/ImpactTable'
import { QueryError } from '../components/QueryError'
import { StatusChip } from '../components/StatusChip'
import type { Highlight } from '../graph/toElements'
import { links, useUrlParams } from '../routing'

type View = 'list' | 'graph'

function highlightOf(data: Traversal, citing: Traversal | undefined): Highlight {
  return {
    root: data.root.node_id,
    direct: data.direct.map((item) => item.node_id),
    indirect: data.indirect.map((item) => item.node_id),
    citers: citing ? [...citing.direct, ...citing.indirect].map((item) => item.node_id) : undefined,
  }
}

function SelectedNode({ graph, id, onPick }: { graph: FullGraph; id: string | null; onPick: (id: string) => void }) {
  const node = graph.nodes.find((n) => n.id === id)
  if (!node) {
    return (
      <Typography variant="body2" color="text.secondary">
        Seleccione un nodo para ver sus datos.
      </Typography>
    )
  }
  return (
    <Stack spacing={1}>
      <Typography sx={{ fontFamily: 'monospace', fontWeight: 700 }}>{node.code}</Typography>
      <Typography variant="body2">{node.title ?? (node.resolved ? '' : 'Citado sin documento')}</Typography>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
        {node.norma ? <Chip size="small" variant="outlined" label={`Norma: ${node.norma}`} /> : null}
        {node.resolved ? <StatusChip status={node.status} /> : null}
      </Stack>
      {node.resolved ? (
        <Stack direction="row" spacing={1}>
          <Button size="small" component={RouterLink} to={links.document(node.code, node.norma)}>
            Abrir detalle
          </Button>
          <Button size="small" onClick={() => onPick(node.id)}>
            Modificar este
          </Button>
        </Stack>
      ) : null}
    </Stack>
  )
}

/** Quienes citan al documento, directa o indirectamente: posibles documentos a revisar. */
function CitersList({ impact, depth }: { impact: ReturnType<typeof useImpact>; depth: number }) {
  if (impact.error) return <QueryError error={impact.error} />
  if (!impact.data) return <LinearProgress aria-label="Cargando quién lo cita" />
  const { data } = impact
  return (
    <>
      <Typography variant="subtitle1" component="h4">
        Documentos que lo citan ({data.direct.length + data.indirect.length})
      </Typography>
      <Alert severity="info">{data.disclaimer}</Alert>
      <ImpactTable
        items={data.direct}
        rootNorma={data.root.norma}
        label="Lo citan directamente"
        emptyText="Ningún documento lo cita."
      />
      {depth > 1 ? (
        <ImpactTable
          items={data.indirect}
          rootNorma={data.root.norma}
          label="Lo citan indirectamente"
          emptyText="Nadie lo cita indirectamente hasta esta profundidad."
        />
      ) : null}
    </>
  )
}

/**
 * Documento a modificar: la lista de los documentos que cita (directos y, con más profundidad,
 * indirectos) y los mismos resaltados sobre el grafo completo de todas las normas. Con
 * `citers=1` agrega quienes lo citan (posibles documentos a revisar), en lista y en otro color.
 */
export function ModifyPage() {
  const params = useUrlParams()
  const code = (params.get('code') ?? '').toUpperCase()
  const norma = params.get('norma')
  const view: View = params.get('tab') === 'graph' ? 'graph' : 'list'
  const showCiters = params.get('citers') === '1'
  const limits = useHealth().data?.limits
  const maxDepth = limits?.max_depth ?? 10
  const depth = Math.min(params.getInt('depth', 1), maxDepth)
  const [draftDepth, setDraftDepth] = useState<number | null>(null)
  const [selected, setSelected] = useState<string | null>(null)

  const dependencies = useDependencies({ code, norma, depth })
  const data = dependencies.data
  const impact = useImpact({ code, norma, depth }, showCiters)
  const citing = showCiters ? impact.data : undefined
  const full = useFullGraph(view === 'graph' && Boolean(data))
  const highlight = useMemo(() => (data ? highlightOf(data, citing) : null), [data, citing])
  const presentTypes = useMemo(
    () => [...new Set(full.data?.nodes.map((node) => node.document_type) ?? [])].sort(),
    [full.data],
  )
  const total = data ? data.direct.length + data.indirect.length : 0
  const citerTotal = citing ? citing.direct.length + citing.indirect.length : 0

  const pick = (nodeId: string) => {
    const node = full.data?.nodes.find((n) => n.id === nodeId)
    if (!node) return
    setSelected(null)
    params.update({ code: node.code, norma: node.norma })
  }

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h2">
        Documento a modificar
      </Typography>
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={3} sx={{ alignItems: { md: 'center' } }}>
          <DocumentPicker
            norma={null}
            label={code ? `Documento: ${code} (buscar otro)` : 'Documento a modificar'}
            onSelect={(doc) => {
              setSelected(null)
              params.update({ code: doc.code, norma: doc.norma })
            }}
          />
          <Box sx={{ width: 240 }}>
            <Typography variant="caption" id="modify-depth-label">
              Profundidad: {draftDepth ?? depth} {(draftDepth ?? depth) === 1 ? '(solo los que cita directamente)' : ''}
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
                params.update({ depth: value === 1 ? null : (value as number) })
              }}
              aria-labelledby="modify-depth-label"
            />
          </Box>
          <FormControlLabel
            control={
              <Switch
                checked={showCiters}
                onChange={(_, checked) => params.update({ citers: checked ? 1 : null })}
              />
            }
            label="Mostrar también quién lo cita"
          />
        </Stack>
      </Paper>

      {!code ? (
        <Typography color="text.secondary">
          Elija el documento que va a modificar para ver los documentos que referencia.
        </Typography>
      ) : null}
      {dependencies.error ? (
        <QueryError error={dependencies.error} onChooseNorma={(value) => params.update({ norma: value })} />
      ) : null}

      {data ? (
        <Stack spacing={2}>
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
            <Typography aria-live="polite">
              Cita {data.direct.length} documento{data.direct.length === 1 ? '' : 's'} directamente
              {depth > 1 ? ` y ${data.indirect.length} indirectamente` : ''}
              {citing ? ` · lo cita${citerTotal === 1 ? '' : 'n'} ${citerTotal}` : ''}
            </Typography>
            {data.root.resolved ? (
              <Button component={RouterLink} to={links.document(data.root.code, data.root.norma)}>
                Detalle
              </Button>
            ) : null}
          </Stack>

          <Tabs
            value={view}
            onChange={(_, value: View) => params.update({ tab: value === 'list' ? null : value })}
          >
            <Tab value="list" label={`Lista (${total + citerTotal})`} />
            <Tab value="graph" label="Ver en el grafo" />
          </Tabs>

          {view === 'list' ? (
            <Stack spacing={2}>
              <Typography variant="subtitle1" component="h4">
                Documentos que cita directamente ({data.direct.length})
              </Typography>
              <ImpactTable
                items={data.direct}
                rootNorma={data.root.norma}
                label="Citados directamente"
                emptyText="No cita otros documentos."
              />
              {depth > 1 ? (
                <>
                  <Typography variant="subtitle1" component="h4">
                    Documentos que cita indirectamente ({data.indirect.length})
                  </Typography>
                  <ImpactTable
                    items={data.indirect}
                    rootNorma={data.root.norma}
                    label="Citados indirectamente"
                    emptyText="Sin referencias indirectas hasta esta profundidad."
                  />
                </>
              ) : null}
              {showCiters ? <CitersList impact={impact} depth={depth} /> : null}
            </Stack>
          ) : null}

          {view === 'graph' ? (
            <>
              {full.isLoading ? <LinearProgress aria-label="Cargando grafo completo" /> : null}
              {full.error ? (
                <Stack spacing={1}>
                  <QueryError error={full.error} />
                  <Alert severity="info">
                    Puede ver la vecindad del documento en{' '}
                    <RouterLink to={links.graph(data.root.code, data.root.norma, 'out')}>la vista de grafo</RouterLink>.
                  </Alert>
                </Stack>
              ) : null}
              {full.data && highlight ? (
                <Grid container spacing={2}>
                  <Grid size={{ xs: 12, lg: 9 }}>
                    <FullGraphView data={full.data} highlight={highlight} onSelect={setSelected} />
                    <Typography variant="caption" color="text.secondary">
                      Grafo completo: {full.data.nodes.length} documentos en {full.data.normas.length} normas ·
                      resaltados el documento, los {total} que cita
                      {citing ? ` y los ${citerTotal} que lo citan` : ''} · clic para ver un documento.
                    </Typography>
                  </Grid>
                  <Grid size={{ xs: 12, lg: 3 }}>
                    <Stack spacing={2}>
                      <Paper variant="outlined" sx={{ p: 2 }} aria-label="Documento seleccionado">
                        <SelectedNode graph={full.data} id={selected} onPick={pick} />
                      </Paper>
                      <Paper variant="outlined" sx={{ p: 2 }}>
                        <GraphLegend types={presentTypes} highlight citers={Boolean(citing)} />
                      </Paper>
                    </Stack>
                  </Grid>
                </Grid>
              ) : null}
            </>
          ) : null}
        </Stack>
      ) : null}
    </Stack>
  )
}
