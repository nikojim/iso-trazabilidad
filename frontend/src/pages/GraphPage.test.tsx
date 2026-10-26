import { act, screen } from '@testing-library/react'
import type { ElementDefinition } from 'cytoscape'
import { renderApp } from '../test/render'
import { requests } from '../test/server'

type Handler = (event: { target: unknown }) => void

// Cytoscape necesita canvas: se reemplaza por un doble que registra elementos y eventos.
const fake = vi.hoisted(() => ({
  options: [] as { elements: ElementDefinition[] }[],
  handlers: new Map<string, Handler>(),
}))

vi.mock('cytoscape', () => ({
  default: vi.fn((options: { elements: ElementDefinition[] }) => {
    fake.options.push(options)
    const instance = {
      on: (event: string, selectorOrHandler: string | Handler, handler?: Handler) => {
        const key = typeof selectorOrHandler === 'string' ? `${event} ${selectorOrHandler}` : event
        fake.handlers.set(key, handler ?? (selectorOrHandler as Handler))
      },
      destroy: vi.fn(),
      fit: vi.fn(),
      layout: vi.fn(() => ({ run: vi.fn() })),
    }
    return instance
  }),
}))

const nodeEvent = (id: string) => ({ target: { id: () => id } })

// La página se carga con lazy(): se importa antes para no medir esa demora en el primer test.
beforeAll(async () => {
  await import('./GraphPage')
})

beforeEach(() => {
  fake.options.length = 0
  fake.handlers.clear()
})

describe('GraphPage', () => {
  it('pide solo la vecindad del documento', async () => {
    renderApp('/graph?code=MC-SGG-435&norma=A&direction=in')

    await screen.findByTestId('graph-canvas')
    const call = requests.find((url) => url.pathname === '/api/graph')!
    expect(call.searchParams.get('code')).toBe('MC-SGG-435')
    expect(call.searchParams.get('direction')).toBe('in')
    expect(call.searchParams.get('norma')).toBe('A')
  })

  it('no consulta el grafo sin documento central', async () => {
    renderApp('/graph')

    expect(await screen.findByText(/nunca el grafo completo/)).toBeInTheDocument()
    expect(requests.some((url) => url.pathname === '/api/graph')).toBe(false)
  })

  it('entrega a Cytoscape aristas origen → citado', async () => {
    renderApp('/graph?code=MC-SGG-435&norma=A')

    await screen.findByTestId('graph-canvas')
    const edges = fake.options.at(-1)!.elements.filter((e) => e.group === 'edges')
    expect(edges.map((e) => `${e.data.source}>${e.data.target}`)).toContain('A/PR-SGG-101>A/MC-SGG-435')
    expect(edges.find((e) => e.data.target === 'B/LC-SGC-500')!.classes).toContain('cross')
    expect(screen.getByLabelText('Leyenda del grafo')).toHaveTextContent('Citado sin documento')
  })

  it('muestra el nodo seleccionado y recentra con doble clic', async () => {
    renderApp('/graph?code=MC-SGG-435&norma=A')
    await screen.findByTestId('graph-canvas')

    act(() => fake.handlers.get('tap node')!(nodeEvent('B/LC-SGC-500')))
    expect(screen.getByRole('link', { name: 'Abrir detalle' })).toHaveAttribute(
      'href',
      '/documents/LC-SGC-500?norma=B',
    )
    expect(screen.getByText('Norma: B')).toBeInTheDocument()

    act(() => fake.handlers.get('dbltap node')!(nodeEvent('B/LC-SGC-500')))
    expect(screen.getByTestId('location')).toHaveTextContent('code=LC-SGC-500&norma=B')
  })

  it('avisa cuando el subgrafo se recortó', async () => {
    renderApp('/graph?code=MC-SGG-435&norma=A&depth=5')

    expect(await screen.findByText(/se muestran los más cercanos/)).toBeInTheDocument()
  })
})
