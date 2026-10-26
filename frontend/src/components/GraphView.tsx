import { useEffect, useLayoutEffect, useRef } from 'react'
import { Box, Button, Stack } from '@mui/material'
import cytoscape, { type Core, type LayoutOptions } from 'cytoscape'
import type { Direction, Neighborhood } from '../api/types'
import { graphStylesheet } from '../graph/styles'
import { toElements } from '../graph/toElements'

interface Props {
  data: Neighborhood
  onSelect: (code: string | null) => void
  onRecenter: (code: string) => void
  height?: number
}

function layoutFor(direction: Direction, root: string): LayoutOptions {
  if (direction === 'both') return { name: 'cose', animate: false, padding: 30 }
  return { name: 'breadthfirst', directed: true, roots: [root], spacingFactor: 1.2, padding: 30 }
}

/** Subgrafo interactivo: clic selecciona, doble clic recentra en ese documento. */
export function GraphView({ data, onSelect, onRecenter, height = 560 }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const cy = useRef<Core | null>(null)
  const handlers = useRef({ onSelect, onRecenter })
  useLayoutEffect(() => {
    handlers.current = { onSelect, onRecenter }
  })

  useEffect(() => {
    if (!container.current) return
    const instance = cytoscape({
      container: container.current,
      elements: toElements(data),
      style: graphStylesheet(),
      layout: layoutFor(data.direction as Direction, data.root),
      wheelSensitivity: 0.3,
      minZoom: 0.2,
      maxZoom: 3,
    })
    instance.on('tap', 'node', (event) => handlers.current.onSelect(event.target.id()))
    instance.on('tap', (event) => {
      if (event.target === instance) handlers.current.onSelect(null)
    })
    instance.on('dbltap', 'node', (event) => handlers.current.onRecenter(event.target.id()))
    cy.current = instance
    return () => {
      instance.destroy()
      cy.current = null
    }
  }, [data])

  return (
    <Box>
      <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
        <Button size="small" variant="outlined" onClick={() => cy.current?.fit(undefined, 30)}>
          Ajustar
        </Button>
        <Button
          size="small"
          variant="outlined"
          onClick={() => cy.current?.layout(layoutFor(data.direction as Direction, data.root)).run()}
        >
          Reordenar
        </Button>
      </Stack>
      <Box
        ref={container}
        data-testid="graph-canvas"
        role="img"
        aria-label={`Grafo de ${data.root}: ${data.nodes.length} documentos y ${data.edges.length} referencias`}
        sx={{ height, border: 1, borderColor: 'divider', borderRadius: 1, bgcolor: '#fafbfc' }}
      />
    </Box>
  )
}
