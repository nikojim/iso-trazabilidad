import { fullGraph, manualNeighborhood } from '../test/fixtures'
import { graphStylesheet } from './styles'
import {
  colorForType,
  highlightClassFor,
  isHighlightedEdge,
  normaNodeId,
  toElements,
  toFullElements,
  type Highlight,
} from './toElements'

describe('toElements', () => {
  const elements = toElements(manualNeighborhood)
  const node = (id: string) => elements.find((e) => e.group === 'nodes' && e.data.id === id)!
  const edge = (id: string) => elements.find((e) => e.group === 'edges' && e.data.id === id)!

  it('conserva la dirección origen → citado', () => {
    expect(edge('A/PR-SGG-101->A/MC-SGG-435').data).toMatchObject({
      source: 'A/PR-SGG-101',
      target: 'A/MC-SGG-435',
    })
    expect(edge('A/MC-SGG-435->A/ES-SGC-001').data).toMatchObject({
      source: 'A/MC-SGG-435',
      target: 'A/ES-SGC-001',
    })
  })

  it('rotula con el código y conserva la norma', () => {
    expect(node('A/MC-SGG-435').data).toMatchObject({ label: 'MC-SGG-435', norma: 'A' })
    expect(node('RG-SGSA-928').data.norma).toBe('')
  })

  it('marca la raíz, los no resueltos, los inactivos y las planillas', () => {
    expect(node('A/MC-SGG-435').classes).toContain('root')
    expect(node('RG-SGSA-928').classes).toContain('unresolved')
    expect(node('A/ES-SGC-001').classes).not.toContain('unresolved')
    expect(node('A/PR-SGG-101').classes).toContain('inactive')
    expect(node('B/LC-SGC-500').classes).toContain('sheet')
  })

  it('clasifica aristas por grupo, grupos mixtos y normas cruzadas', () => {
    expect(edge('A/PR-SGG-101->A/MC-SGG-435').classes).toBe('group-procedimientos mixed')
    expect(edge('A/MC-SGG-435->A/ES-SGC-001').classes).toBe('group-general')
    expect(edge('A/MC-SGG-435->B/LC-SGC-500').classes).toBe('group-general cross')
  })

  it('genera un nodo por documento y una arista por relación', () => {
    expect(elements.filter((e) => e.group === 'nodes')).toHaveLength(5)
    expect(elements.filter((e) => e.group === 'edges')).toHaveLength(4)
  })
})

describe('toFullElements', () => {
  const elements = toFullElements(fullGraph)
  const node = (id: string) => elements.find((e) => e.group === 'nodes' && e.data.id === id)!

  it('agrupa los documentos de cada norma en un nodo compuesto', () => {
    expect(node(normaNodeId('A'))).toMatchObject({ classes: 'norma', data: { label: 'A' } })
    expect(node('A/MC-SGG-435').data.parent).toBe(normaNodeId('A'))
    expect(node('B/MC-SGG-435').data.parent).toBe(normaNodeId('B'))
  })

  it('deja fuera de toda norma a los citados sin documento', () => {
    expect(node('RG-SGSA-928').data.parent).toBeUndefined()
  })

  it('incluye todas las normas, documentos y referencias', () => {
    expect(elements.filter((e) => e.classes === 'norma')).toHaveLength(2)
    expect(elements.filter((e) => e.group === 'nodes')).toHaveLength(2 + fullGraph.nodes.length)
    expect(elements.filter((e) => e.group === 'edges')).toHaveLength(fullGraph.edges.length)
  })
})

describe('resaltado del documento a modificar', () => {
  const highlight: Highlight = {
    root: 'A/MC-SGG-435',
    direct: ['A/ES-SGC-001', 'B/LC-SGC-500'],
    indirect: ['B/PO-SGS-400'],
  }

  it('distingue raíz, directos, indirectos y el resto', () => {
    expect(highlightClassFor('A/MC-SGG-435', highlight)).toBe('hl-root')
    expect(highlightClassFor('B/LC-SGC-500', highlight)).toBe('hl-direct')
    expect(highlightClassFor('B/PO-SGS-400', highlight)).toBe('hl-indirect')
    expect(highlightClassFor('B/MC-SGG-435', highlight)).toBe('faded')
  })

  it('resalta solo las aristas entre documentos resaltados', () => {
    expect(isHighlightedEdge('A/MC-SGG-435', 'B/LC-SGC-500', highlight)).toBe(true)
    expect(isHighlightedEdge('B/MC-SGG-435', 'A/ES-SGC-001', highlight)).toBe(false)
  })
})

describe('estilos del grafo', () => {
  const sheet = graphStylesheet()
  const style = (selector: string) =>
    sheet.find((block) => 'selector' in block && block.selector === selector) as
      | { style: Record<string, unknown> }
      | undefined

  it('dibuja la flecha en el extremo del citado y punteado para no resueltos', () => {
    expect(style('edge')?.style['target-arrow-shape']).toBe('triangle')
    expect(style('edge')?.style['source-arrow-shape']).toBeUndefined()
    expect(style('node.unresolved')?.style['border-style']).toBe('dashed')
  })

  it('atenúa lo no resaltado y diferencia las planillas', () => {
    expect(style('.faded')?.style.opacity).toBeLessThan(0.5)
    expect(style('node.sheet')?.style.shape).toBe('round-rectangle')
    expect(style('node.hl-root')).toBeDefined()
  })

  it('usa un color de respaldo para tipos desconocidos', () => {
    expect(colorForType('ZZ')).toBe(colorForType(''))
    expect(colorForType('PR')).not.toBe(colorForType('ZZ'))
  })
})
