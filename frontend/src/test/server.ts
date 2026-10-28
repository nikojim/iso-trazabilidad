import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import * as data from './fixtures'

/** Solicitudes recibidas, para verificar los parámetros enviados a la API. */
export const requests: URL[] = []

const error = (status: number, code: string, message: string, details = {}) =>
  HttpResponse.json({ error: { code, message, details } }, { status })

/** MC-SGG-435 es documento en A y en B: sin `norma` la API responde 409 como la real. */
function normaFor(code: string, url: URL) {
  const norma = url.searchParams.get('norma')
  if (norma) return norma
  if (code === 'MC-SGG-435') {
    return error(409, 'norma_required', `${code} es un documento en varias normas; indicar ?norma=`, {
      code,
      normas: ['A', 'B'],
    })
  }
  return 'A'
}

function page<T>(items: T[], url: URL) {
  const current = Number(url.searchParams.get('page') ?? 1)
  const size = Number(url.searchParams.get('page_size') ?? 50)
  return {
    items: items.slice((current - 1) * size, current * size),
    total: items.length,
    page: current,
    page_size: size,
  }
}

const track = (request: Request) => {
  const url = new URL(request.url)
  requests.push(url)
  return url
}

export const handlers = [
  http.get('*/api/health', ({ request }) => (track(request), HttpResponse.json(data.health))),
  http.get('*/api/normas', ({ request }) => (track(request), HttpResponse.json(data.normas))),
  http.get('*/api/stats', ({ request }) => (track(request), HttpResponse.json(data.stats))),
  http.get('*/api/documents', ({ request }) => {
    const url = track(request)
    const query = (url.searchParams.get('query') ?? '').toUpperCase()
    const norma = url.searchParams.get('norma')
    const found = data.documents.filter(
      (doc) =>
        (!norma || doc.norma === norma) &&
        (!query || doc.code.includes(query) || (doc.title ?? '').toUpperCase().includes(query)),
    )
    return HttpResponse.json(page(found, url))
  }),
  http.get('*/api/documents/:code/references', ({ request, params }) => {
    const url = track(request)
    const norma = normaFor(String(params.code), url)
    if (norma instanceof Response) return norma
    if (params.code !== 'MC-SGG-435') {
      return HttpResponse.json({ norma: null, code: params.code, resolved: false, outgoing: [], unresolved: [], incoming: [] })
    }
    return HttpResponse.json({ ...data.manualReferences, norma })
  }),
  http.get('*/api/documents/:code/impact', ({ request, params }) => {
    track(request)
    if (params.code === 'XX-ABC-999') {
      return error(404, 'document_not_found', 'XX-ABC-999 no es un documento ni un código citado')
    }
    if (params.code === 'MC-SGG-435') return HttpResponse.json(data.impactOfManual)
    return HttpResponse.json(data.impactOfStandard)
  }),
  http.get('*/api/documents/:code/dependencies', ({ request, params }) => {
    const url = track(request)
    const norma = normaFor(String(params.code), url)
    if (norma instanceof Response) return norma
    if (params.code === 'MC-SGG-435') {
      return HttpResponse.json(data.dependenciesOfManual(Number(url.searchParams.get('depth') ?? 2)))
    }
    return HttpResponse.json({ ...data.impactOfStandard, kind: 'dependencies', direct: [], indirect: [] })
  }),
  http.get('*/api/documents/:code', ({ request, params }) => {
    const url = track(request)
    const norma = normaFor(String(params.code), url)
    if (norma instanceof Response) return norma
    if (params.code !== 'MC-SGG-435') {
      return error(404, 'document_not_found', `${params.code} no es un documento (solo está citado)`)
    }
    return HttpResponse.json({ ...data.manualDetail, norma })
  }),
  http.get('*/api/graph/cycles', ({ request }) => {
    track(request)
    return HttpResponse.json({ cycles: [['A/MC-SGG-435', 'A/PC-SGSA-914'], ['B/MC-SGG-435', 'B/PO-SGS-400']] })
  }),
  http.get('*/api/graph/full', ({ request }) => {
    track(request)
    return HttpResponse.json(data.fullGraph)
  }),
  http.get('*/api/graph', ({ request }) => {
    const url = track(request)
    const code = url.searchParams.get('code') ?? ''
    const norma = url.searchParams.get('norma')
    return HttpResponse.json({
      ...data.manualNeighborhood,
      root: norma ? `${norma}/${code}` : code,
      direction: url.searchParams.get('direction') ?? 'both',
      truncated: url.searchParams.get('depth') === '5',
    })
  }),
  http.get('*/api/quality/issues', ({ request }) => {
    const url = track(request)
    const type = url.searchParams.get('type')
    return HttpResponse.json(page(data.issues.filter((i) => !type || i.type === type), url))
  }),
  http.get('*/api/references/unresolved', ({ request }) => {
    const url = track(request)
    return HttpResponse.json(
      page(
        [
          {
            target_code: 'RG-SGSA-928',
            title_hint: 'Informes de Servicio',
            cited_by_count: 1,
            cited_by: ['A/MC-SGG-435'],
            candidate_normas: [],
          },
          {
            target_code: 'PR-SGI-001',
            title_hint: 'Gestión integrada',
            cited_by_count: 1,
            cited_by: ['C/MC-SGG-435'],
            candidate_normas: ['A', 'B'],
          },
        ],
        url,
      ),
    )
  }),
  http.get('*/api/ingestion/runs', ({ request }) => {
    const url = track(request)
    return HttpResponse.json(
      page(
        [
          {
            id: 1,
            mode: 'full',
            status: 'completed',
            root_path: 'data/documents',
            started_at: '2026-10-26T12:00:00Z',
            ended_at: '2026-10-26T12:01:00Z',
            processed_count: 5,
            skipped_count: 0,
            error_count: 0,
            warning_count: 1,
            new_count: 5,
            updated_count: 0,
            missing_count: 0,
            no_section_count: 0,
            unsupported_skipped_count: 0,
            root_files_count: 0,
            references_count: 5,
            occurrences_count: 7,
            duplicate_references_count: 1,
            unresolved_count: 1,
            log_path: 'data/logs/ingest-00001-20261026-120000.log',
          },
        ],
        url,
      ),
    )
  }),
]

export const server = setupServer(...handlers)
