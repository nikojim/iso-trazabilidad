import { useEffect, useLayoutEffect, useRef } from 'react'
import { Box, Button, Stack } from '@mui/material'
import cytoscape, { type Core, type LayoutOptions, type Position } from 'cytoscape'
import fcose from 'cytoscape-fcose'
import type { FullGraph } from '../api/types'
import { graphStylesheet } from '../graph/styles'
import { highlighter, toFullElements, type Highlight } from '../graph/toElements'

cytoscape.use(fcose)

interface Props {
  data: FullGraph
  highlight: Highlight | null
  onSelect: (id: string | null) => void
  height?: number
}

/**
 * Hasta este tamaño, fcose con calidad completa (alrededor de 1 s). Por encima, solo su fase
 * espectral ("draft"): 3000 nodos se ordenan en segundos en vez de minutos.
 */
export const FULL_QUALITY_MAX_NODES = 400

function layoutFor(nodeCount: number): LayoutOptions {
  return {
    name: 'fcose',
    quality: nodeCount > FULL_QUALITY_MAX_NODES ? 'draft' : 'default',
    randomize: true,
    animate: false,
    padding: 30,
    nodeDimensionsIncludeLabels: true,
  } as LayoutOptions
}

/** Posiciones de la última versión del grafo: volver a la pestaña no recalcula el layout. */
const positionCache = new Map<string, Record<string, Position>>()
const cacheKey = (data: FullGraph) =>
  `${data.graph_version}:${data.nodes.length}:${data.edges.length}`

function arrange(cy: Core, data: FullGraph) {
  const layout = cy.layout(layoutFor(data.nodes.length))
  layout.one('layoutstop', () => {
    const positions: Record<string, Position> = {}
    cy.nodes()
      .not('.norma')
      .forEach((node) => {
        positions[node.id()] = { ...node.position() }
      })
    positionCache.clear()
    positionCache.set(cacheKey(data), positions)
  })
  layout.run()
}

const HIGHLIGHT_CLASSES = 'hl-root hl-direct hl-indirect hl-citer hl-edge hl-citer-edge faded'
const LIT = '.hl-root, .hl-direct, .hl-indirect, .hl-citer'

/** Aplica el resaltado sin recalcular el layout: el grafo no se mueve al cambiar de documento. */
function applyHighlight(cy: Core, highlight: Highlight | null) {
  const hl = highlight ? highlighter(highlight) : null
  cy.batch(() => {
    cy.nodes()
      .not('.norma')
      .forEach((node) => {
        node.removeClass(HIGHLIGHT_CLASSES)
        if (hl) node.addClass(hl.node(node.id()))
      })
    cy.edges().forEach((edge) => {
      edge.removeClass(HIGHLIGHT_CLASSES)
      if (hl) edge.addClass(hl.edge(edge.source().id(), edge.target().id()))
    })
  })
}

function focusHighlighted(cy: Core) {
  const lit = cy.nodes(LIT)
  cy.fit(lit.length > 0 ? lit : undefined, 40)
}

/**
 * Grafo completo (todas las normas, cada una como recuadro) con el documento a modificar, lo
 * que cita y, si se pide, quienes lo citan resaltados; el resto queda atenuado. Clic selecciona
 * un documento.
 */
export function FullGraphView({ data, highlight, onSelect, height = 640 }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const cy = useRef<Core | null>(null)
  const handlers = useRef({ onSelect })
  const current = useRef(highlight)
  useLayoutEffect(() => {
    handlers.current = { onSelect }
    current.current = highlight
  })

  useEffect(() => {
    if (!container.current) return
    const instance = cytoscape({
      container: container.current,
      elements: toFullElements(data),
      style: graphStylesheet(),
      wheelSensitivity: 0.3,
      minZoom: 0.05,
      maxZoom: 3,
    })
    instance.on('tap', 'node', (event) => {
      if (!event.target.hasClass('norma')) handlers.current.onSelect(event.target.id())
    })
    instance.on('tap', (event) => {
      if (event.target === instance) handlers.current.onSelect(null)
    })
    const cached = positionCache.get(cacheKey(data))
    if (cached) instance.layout({ name: 'preset', positions: cached, fit: false }).run()
    else arrange(instance, data)
    cy.current = instance
    applyHighlight(instance, current.current)
    focusHighlighted(instance)
    return () => {
      instance.destroy()
      cy.current = null
    }
  }, [data])

  useEffect(() => {
    if (!cy.current) return
    applyHighlight(cy.current, highlight)
    focusHighlighted(cy.current)
  }, [highlight])

  const litCount = highlight
    ? 1 + highlight.direct.length + highlight.indirect.length + (highlight.citers?.length ?? 0)
    : 0
  return (
    <Box>
      <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
        <Button
          size="small"
          variant="outlined"
          onClick={() => cy.current && focusHighlighted(cy.current)}
          disabled={!highlight}
        >
          Enfocar resaltados
        </Button>
        <Button size="small" variant="outlined" onClick={() => cy.current?.fit(undefined, 30)}>
          Ver todo
        </Button>
        <Button size="small" variant="outlined" onClick={() => cy.current && arrange(cy.current, data)}>
          Reordenar
        </Button>
      </Stack>
      <Box
        ref={container}
        data-testid="full-graph-canvas"
        role="img"
        aria-label={`Grafo completo: ${data.nodes.length} documentos y ${data.edges.length} referencias en ${data.normas.length} normas; ${litCount} resaltados`}
        sx={{ height, border: 1, borderColor: 'divider', borderRadius: 1, bgcolor: '#fafbfc' }}
      />
    </Box>
  )
}
