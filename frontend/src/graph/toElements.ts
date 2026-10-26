import type { ElementDefinition } from 'cytoscape'
import type { FullGraph, FullGraphNode, GraphEdge, Neighborhood } from '../api/types'

function nodeClasses(node: FullGraphNode, extra: string[] = []): string {
  return [
    `type-${node.document_type}`,
    ...extra,
    node.resolved ? '' : 'unresolved',
    node.active ? '' : 'inactive',
    node.file_format === 'xlsx' ? 'sheet' : '',
  ]
    .filter(Boolean)
    .join(' ')
}

function nodeData(node: FullGraphNode) {
  return {
    id: node.id,
    label: node.code,
    code: node.code,
    norma: node.norma ?? '',
    title: node.title ?? '',
    documentType: node.document_type,
    resolved: node.resolved,
    active: node.active,
  }
}

function edgeElement(edge: GraphEdge): ElementDefinition {
  return {
    group: 'edges',
    data: {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      group: edge.group,
      occurrences: edge.occurrences,
    },
    classes: [`group-${edge.group}`, edge.mixed_groups ? 'mixed' : '', edge.cross_norma ? 'cross' : '']
      .filter(Boolean)
      .join(' '),
  }
}

/**
 * Convierte el subgrafo de la API en elementos de Cytoscape.
 *
 * Las aristas conservan la semántica de la API: `source` cita a `target`, así que la flecha
 * apunta al documento citado. Las clases permiten distinguir la raíz, los códigos citados sin
 * documento (no resueltos), los inactivos, las planillas, el grupo de la relación y las
 * referencias entre normas.
 */
export function toElements(neighborhood: Neighborhood): ElementDefinition[] {
  const nodes: ElementDefinition[] = neighborhood.nodes.map((node) => ({
    group: 'nodes',
    data: { ...nodeData(node), distance: node.distance },
    classes: nodeClasses(node, [node.is_root ? 'root' : '']),
  }))
  return [...nodes, ...neighborhood.edges.map(edgeElement)]
}

/** Id del nodo compuesto que agrupa los documentos de una norma. */
export const normaNodeId = (norma: string) => `norma::${norma}`

/**
 * Grafo completo: cada norma es un nodo compuesto que contiene sus documentos; los citados
 * sin documento quedan fuera de toda norma. Las aristas pueden cruzar de una norma a otra.
 */
export function toFullElements(graph: FullGraph): ElementDefinition[] {
  const normas: ElementDefinition[] = graph.normas.map((norma) => ({
    group: 'nodes',
    data: { id: normaNodeId(norma), label: norma },
    classes: 'norma',
  }))
  const nodes: ElementDefinition[] = graph.nodes.map((node) => ({
    group: 'nodes',
    data: { ...nodeData(node), ...(node.norma ? { parent: normaNodeId(node.norma) } : {}) },
    classes: nodeClasses(node),
  }))
  return [...normas, ...nodes, ...graph.edges.map(edgeElement)]
}

/** Documento a modificar y lo que cita (ids de nodo), para resaltar sobre el grafo completo. */
export interface Highlight {
  root: string
  direct: string[]
  indirect: string[]
}

export type HighlightClass = 'hl-root' | 'hl-direct' | 'hl-indirect' | 'faded'

/** Clase de resaltado de un nodo documento (los nodos de norma no se resaltan ni atenúan). */
export function highlightClassFor(id: string, highlight: Highlight): HighlightClass {
  if (id === highlight.root) return 'hl-root'
  if (highlight.direct.includes(id)) return 'hl-direct'
  if (highlight.indirect.includes(id)) return 'hl-indirect'
  return 'faded'
}

/** Una arista se resalta si une dos documentos resaltados (es parte de lo que se cita). */
export function isHighlightedEdge(source: string, target: string, highlight: Highlight): boolean {
  const lit = (id: string) => highlightClassFor(id, highlight) !== 'faded'
  return lit(source) && lit(target)
}

/** Paleta estable por tipo de documento (prefijo del código). */
const TYPE_COLORS: Record<string, string> = {
  MC: '#0b4d3c',
  PO: '#1565c0',
  PR: '#6a1b9a',
  PC: '#00838f',
  ES: '#ef6c00',
  AL: '#2e7d32',
  LC: '#5d4037',
  FC: '#ad1457',
  RG: '#455a64',
  AC: '#827717',
  IN: '#283593',
}

const FALLBACK_COLOR = '#607d8b'

export function colorForType(documentType: string): string {
  return TYPE_COLORS[documentType] ?? FALLBACK_COLOR
}

export const KNOWN_TYPES = Object.keys(TYPE_COLORS)
