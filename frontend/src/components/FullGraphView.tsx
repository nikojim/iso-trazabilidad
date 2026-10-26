import { useEffect, useLayoutEffect, useRef } from 'react'
import { Box, Button, Stack } from '@mui/material'
import cytoscape, { type Core, type LayoutOptions } from 'cytoscape'
import type { FullGraph } from '../api/types'
import { graphStylesheet } from '../graph/styles'
import {
  highlightClassFor,
  isHighlightedEdge,
  toFullElements,
  type Highlight,
} from '../graph/toElements'

interface Props {
  data: FullGraph
  highlight: Highlight | null
  onSelect: (id: string | null) => void
  height?: number
}

const LAYOUT: LayoutOptions = {
  name: 'cose',
  animate: false,
  padding: 30,
  nodeDimensionsIncludeLabels: true,
  randomize: false,
}
const HIGHLIGHT_CLASSES = 'hl-root hl-direct hl-indirect hl-edge faded'
const LIT = '.hl-root, .hl-direct, .hl-indirect'

/** Aplica el resaltado sin recalcular el layout: el grafo no se mueve al cambiar de documento. */
function applyHighlight(cy: Core, highlight: Highlight | null) {
  cy.batch(() => {
    cy.nodes()
      .not('.norma')
      .forEach((node) => {
        node.removeClass(HIGHLIGHT_CLASSES)
        if (highlight) node.addClass(highlightClassFor(node.id(), highlight))
      })
    cy.edges().forEach((edge) => {
      edge.removeClass(HIGHLIGHT_CLASSES)
      if (highlight) {
        const lit = isHighlightedEdge(edge.source().id(), edge.target().id(), highlight)
        edge.addClass(lit ? 'hl-edge' : 'faded')
      }
    })
  })
}

function focusHighlighted(cy: Core) {
  const lit = cy.nodes(LIT)
  cy.fit(lit.length > 0 ? lit : undefined, 40)
}

/**
 * Grafo completo (todas las normas, cada una como recuadro) con el documento a modificar y lo
 * que cita resaltados; el resto queda atenuado. Clic selecciona un documento.
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
      layout: LAYOUT,
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

  const litCount = highlight ? 1 + highlight.direct.length + highlight.indirect.length : 0
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
        <Button size="small" variant="outlined" onClick={() => cy.current?.layout(LAYOUT).run()}>
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
