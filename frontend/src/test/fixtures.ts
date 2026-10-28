// Datos sintéticos (sin documentos reales). Un solo grafo con dos normas:
// - A: PR-SGG-101 → MC-SGG-435 → ES-SGC-001; MC-SGG-435 cita RG-SGSA-928, que no tiene documento.
// - B: otro MC-SGG-435 (documento distinto) y la planilla LC-SGC-500, que A/MC-SGG-435 cita.
import type {
  DocumentDetail,
  DocumentSummary,
  FullGraph,
  FullGraphNode,
  Health,
  Issue,
  Neighborhood,
  NormaSummary,
  References,
  Stats,
  Traversal,
  TraversalItem,
} from '../api/types'

export const normas: NormaSummary[] = [
  { name: 'A', documents: 3, references: 4, unresolved: 1, cross_norma: 1 },
  { name: 'B', documents: 2, references: 1, unresolved: 0, cross_norma: 1 },
]

export const health: Health = {
  status: 'ok',
  database: 'ok',
  schema_revision: '0004',
  graph_version: 7,
  limits: { default_depth: 2, max_depth: 5, graph_max_nodes: 300, graph_full_max_nodes: 3000 },
}

function summary(code: string, title: string, norma = 'A', counts = [1, 1], fileFormat = 'pdf'): DocumentSummary {
  return {
    norma,
    code,
    title,
    document_type: code.split('-')[0],
    system_code: code.split('-')[1],
    version: '01',
    file_format: fileFormat,
    extraction_status: fileFormat === 'xlsx' ? 'not_applicable' : 'ok',
    is_active: true,
    outgoing_count: counts[0],
    incoming_count: counts[1],
  }
}

export const documents: DocumentSummary[] = [
  summary('ES-SGC-001', 'Estándar de calidad', 'A', [0, 2]),
  summary('MC-SGG-435', 'Manual de los Sistemas de Gestión', 'A', [3, 1]),
  summary('PR-SGG-101', 'Gestión del personal', 'A', [1, 0]),
  summary('LC-SGC-500', 'Listado de registros', 'B', [0, 1], 'xlsx'),
  summary('MC-SGG-435', 'Manual de los Sistemas de Gestión', 'B', [1, 0]),
]

export const manualDetail: DocumentDetail = {
  ...summary('MC-SGG-435', 'Manual de los Sistemas de Gestión', 'A', [3, 1]),
  file_path: 'A/MC-SGG-435-23 Manual.pdf',
  folder: 'A',
  code_source: 'filename+content',
  references_stale: false,
  unresolved_count: 1,
  metadata: {},
  last_run_id: 1,
  last_processed_at: '2026-10-23T12:00:00Z',
  updated_at: '2026-10-23T12:00:00Z',
  open_issues: [],
}

const occurrence = (text: string, page = 4) => ({
  group: 'general',
  page_number: page,
  paragraph_index: null,
  table_index: null,
  row_index: null,
  cell_index: null,
  raw_text: text,
  evidence_excerpt: text,
})

export const manualReferences: References = {
  norma: 'A',
  code: 'MC-SGG-435',
  resolved: true,
  outgoing: [
    {
      code: 'ES-SGC-001',
      norma: 'A',
      title: 'Estándar de calidad',
      title_hint: 'Estándar de calidad',
      document_type: 'ES',
      resolved: true,
      cross_norma: false,
      candidate_normas: [],
      group: 'general',
      has_mixed_groups: false,
      occurrence_count: 1,
      occurrences: [occurrence('[ES-SGC-001] Estándar de calidad')],
    },
    {
      code: 'LC-SGC-500',
      norma: 'B',
      title: 'Listado de registros',
      title_hint: 'Listado de registros',
      document_type: 'LC',
      resolved: true,
      cross_norma: true,
      candidate_normas: [],
      group: 'general',
      has_mixed_groups: false,
      occurrence_count: 1,
      occurrences: [occurrence('[LC-SGC-500] Listado de registros')],
    },
  ],
  unresolved: [
    {
      code: 'RG-SGSA-928',
      norma: null,
      title: 'Informes de Servicio',
      title_hint: 'Informes de Servicio',
      document_type: 'RG',
      resolved: false,
      cross_norma: false,
      candidate_normas: [],
      group: 'general',
      has_mixed_groups: false,
      occurrence_count: 1,
      occurrences: [occurrence('[RG-SGSA-928] Informes de Servicio', 5)],
    },
  ],
  incoming: [
    {
      code: 'PR-SGG-101',
      norma: 'A',
      title: 'Gestión del personal',
      title_hint: 'Manual SG',
      document_type: 'PR',
      resolved: true,
      cross_norma: false,
      candidate_normas: [],
      group: 'procedimientos',
      has_mixed_groups: false,
      occurrence_count: 2,
      occurrences: [occurrence('[MC-SGG-435] Manual SG', 3), occurrence('[MC-SGG-435] Manual SG', 4)],
    },
  ],
}

export const DISCLAIMER =
  'Posibles documentos a revisar: citan al documento analizado. No implica necesidad de modificación.'

function traversalItem(
  code: string,
  norma: string | null,
  title: string | null,
  depth: number,
  path: string[],
): TraversalItem {
  return {
    code,
    norma,
    node_id: norma ? `${norma}/${code}` : code,
    title,
    document_type: code.split('-')[0],
    depth,
    relation: depth === 1 ? 'directo' : 'indirecto',
    path,
    resolved: norma !== null,
  }
}

export const impactOfStandard: Traversal = {
  kind: 'impact',
  root: { code: 'ES-SGC-001', norma: 'A', node_id: 'A/ES-SGC-001', title: 'Estándar de calidad', resolved: true },
  depth: 2,
  disclaimer: DISCLAIMER,
  direct: [
    traversalItem('MC-SGG-435', 'A', 'Manual de los Sistemas de Gestión', 1, ['MC-SGG-435', 'ES-SGC-001']),
  ],
  indirect: [
    traversalItem('PR-SGG-101', 'A', 'Gestión del personal', 2, ['PR-SGG-101', 'MC-SGG-435', 'ES-SGC-001']),
  ],
  summary: { by_depth: { '1': 1, '2': 1 }, by_type: { MC: 1, PR: 1 } },
}

/** Quienes citan a A/MC-SGG-435: el procedimiento de la misma norma. */
export const impactOfManual: Traversal = {
  ...impactOfStandard,
  root: {
    code: 'MC-SGG-435',
    norma: 'A',
    node_id: 'A/MC-SGG-435',
    title: 'Manual de los Sistemas de Gestión',
    resolved: true,
  },
  direct: [traversalItem('PR-SGG-101', 'A', 'Gestión del personal', 1, ['PR-SGG-101', 'MC-SGG-435'])],
  indirect: [],
  summary: { by_depth: { '1': 1 }, by_type: { PR: 1 } },
}

/** Lo que cita A/MC-SGG-435: ES (misma norma), la planilla de B y un código sin documento. */
export const dependenciesOfManual = (depth: number): Traversal => ({
  kind: 'dependencies',
  root: {
    code: 'MC-SGG-435',
    norma: 'A',
    node_id: 'A/MC-SGG-435',
    title: 'Manual de los Sistemas de Gestión',
    resolved: true,
  },
  depth,
  disclaimer: DISCLAIMER,
  direct: [
    traversalItem('ES-SGC-001', 'A', 'Estándar de calidad', 1, ['MC-SGG-435', 'ES-SGC-001']),
    traversalItem('LC-SGC-500', 'B', 'Listado de registros', 1, ['MC-SGG-435', 'LC-SGC-500']),
    traversalItem('RG-SGSA-928', null, 'Informes de Servicio', 1, ['MC-SGG-435', 'RG-SGSA-928']),
  ],
  indirect:
    depth > 1
      ? [traversalItem('PO-SGS-400', 'B', 'Política', 2, ['MC-SGG-435', 'LC-SGC-500', 'PO-SGS-400'])]
      : [],
  summary: { by_depth: { '1': 3 }, by_type: { ES: 1, LC: 1, RG: 1 } },
})

function graphNode(
  code: string,
  norma: string | null,
  title: string | null,
  extra: Partial<FullGraphNode> = {},
): FullGraphNode {
  return {
    id: norma ? `${norma}/${code}` : code,
    code,
    norma,
    title,
    document_type: code.split('-')[0],
    system_code: code.split('-')[1],
    file_format: norma ? 'pdf' : null,
    status: norma ? 'ok' : null,
    resolved: norma !== null,
    active: norma !== null,
    ...extra,
  }
}

export const manualNeighborhood: Neighborhood = {
  root: 'A/MC-SGG-435',
  depth: 2,
  direction: 'both',
  truncated: false,
  nodes: [
    { ...graphNode('MC-SGG-435', 'A', 'Manual de los Sistemas de Gestión'), distance: 0, is_root: true },
    { ...graphNode('ES-SGC-001', 'A', 'Estándar de calidad'), distance: 1, is_root: false },
    {
      ...graphNode('LC-SGC-500', 'B', 'Listado de registros', { file_format: 'xlsx', status: 'not_applicable' }),
      distance: 1,
      is_root: false,
    },
    { ...graphNode('RG-SGSA-928', null, null, { active: true }), distance: 1, is_root: false },
    { ...graphNode('PR-SGG-101', 'A', 'Gestión del personal', { active: false }), distance: 1, is_root: false },
  ],
  edges: [
    {
      id: 'A/MC-SGG-435->A/ES-SGC-001',
      source: 'A/MC-SGG-435',
      target: 'A/ES-SGC-001',
      group: 'general',
      occurrences: 1,
      mixed_groups: false,
      cross_norma: false,
    },
    {
      id: 'A/MC-SGG-435->B/LC-SGC-500',
      source: 'A/MC-SGG-435',
      target: 'B/LC-SGC-500',
      group: 'general',
      occurrences: 1,
      mixed_groups: false,
      cross_norma: true,
    },
    {
      id: 'A/MC-SGG-435->RG-SGSA-928',
      source: 'A/MC-SGG-435',
      target: 'RG-SGSA-928',
      group: 'general',
      occurrences: 1,
      mixed_groups: false,
      cross_norma: false,
    },
    {
      id: 'A/PR-SGG-101->A/MC-SGG-435',
      source: 'A/PR-SGG-101',
      target: 'A/MC-SGG-435',
      group: 'procedimientos',
      occurrences: 2,
      mixed_groups: true,
      cross_norma: false,
    },
  ],
}

export const fullGraph: FullGraph = {
  graph_version: 7,
  normas: ['A', 'B'],
  nodes: [
    graphNode('ES-SGC-001', 'A', 'Estándar de calidad'),
    graphNode('MC-SGG-435', 'A', 'Manual de los Sistemas de Gestión'),
    graphNode('PR-SGG-101', 'A', 'Gestión del personal'),
    graphNode('LC-SGC-500', 'B', 'Listado de registros', { file_format: 'xlsx', status: 'not_applicable' }),
    graphNode('MC-SGG-435', 'B', 'Manual de los Sistemas de Gestión'),
    graphNode('PO-SGS-400', 'B', 'Política'),
    graphNode('RG-SGSA-928', null, 'Informes de Servicio'),
  ],
  edges: [
    ...manualNeighborhood.edges,
    {
      id: 'B/MC-SGG-435->A/ES-SGC-001',
      source: 'B/MC-SGG-435',
      target: 'A/ES-SGC-001',
      group: 'general',
      occurrences: 1,
      mixed_groups: false,
      cross_norma: true,
    },
  ],
}

export const issues: Issue[] = [
  {
    id: 3,
    source: 'stored',
    norma: 'A',
    type: 'ambiguous_editions',
    severity: 'error',
    code: 'ES-SGS-525',
    file_path: 'A/ES-SGS-525-02 Matriz.pdf',
    message: 'Ediciones ambiguas: versión y fecha no coinciden',
    details: {},
    created_at: '2026-10-23T12:00:00Z',
    resolved_at: null,
  },
  {
    id: null,
    source: 'derived',
    norma: null,
    type: 'unresolved_similar_code',
    severity: 'info',
    code: 'RG-SGSA-928',
    file_path: null,
    message: 'RG-SGSA-928 no existe; ¿quiso decir LC-SGSA-928?',
    details: {},
    created_at: null,
    resolved_at: null,
  },
]

export const stats: Stats = {
  normas: normas.map((n) => ({ ...n })),
  documents: 5,
  inactive_documents: 0,
  by_status: { ok: 4, not_applicable: 1 },
  by_type: { MC: 2, ES: 1, PR: 1, LC: 1 },
  references: 5,
  unresolved_references: 1,
  open_issues: 1,
  graph_version: 7,
  last_run: null,
}
