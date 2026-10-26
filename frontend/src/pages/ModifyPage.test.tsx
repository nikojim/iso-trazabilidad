import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ElementDefinition } from 'cytoscape'
import { renderApp } from '../test/render'
import { requests } from '../test/server'

type Handler = (event: { target: unknown }) => void

// Cytoscape necesita canvas: un doble mínimo que guarda elementos, clases y eventos.
const fake = vi.hoisted(() => {
  class FakeElement {
    readonly def: ElementDefinition
    readonly classes: Set<string>
    constructor(def: ElementDefinition) {
      this.def = def
      this.classes = new Set(String(def.classes ?? '').split(' ').filter(Boolean))
    }
    id = () => String(this.def.data.id)
    hasClass = (name: string) => this.classes.has(name)
    addClass = (names: string) => names.split(' ').forEach((n) => this.classes.add(n))
    removeClass = (names: string) => names.split(' ').forEach((n) => this.classes.delete(n))
    source = () => ({ id: () => String(this.def.data.source) })
    target = () => ({ id: () => String(this.def.data.target) })
  }
  const collection = (items: FakeElement[]) => ({
    length: items.length,
    forEach: (fn: (item: FakeElement) => void) => items.forEach(fn),
    not: (selector: string) => collection(items.filter((i) => !i.hasClass(selector.replace('.', '')))),
  })
  const state = {
    elements: [] as FakeElement[],
    handlers: new Map<string, Handler>(),
    fits: [] as unknown[],
    create: vi.fn((options: { elements: ElementDefinition[] }) => {
      state.elements = options.elements.map((def) => new FakeElement(def))
      const nodes = () => state.elements.filter((e) => e.def.group === 'nodes')
      return {
        on: (event: string, selectorOrHandler: string | Handler, handler?: Handler) => {
          const key = typeof selectorOrHandler === 'string' ? `${event} ${selectorOrHandler}` : event
          state.handlers.set(key, handler ?? (selectorOrHandler as Handler))
        },
        batch: (fn: () => void) => fn(),
        nodes: (selector?: string) =>
          collection(
            selector
              ? nodes().filter((n) => selector.split(', ').some((s) => n.hasClass(s.replace('.', ''))))
              : nodes(),
          ),
        edges: () => collection(state.elements.filter((e) => e.def.group === 'edges')),
        fit: (target: unknown) => state.fits.push(target),
        layout: () => ({ run: vi.fn() }),
        destroy: vi.fn(),
      }
    }),
  }
  return state
})

vi.mock('cytoscape', () => ({ default: fake.create }))

const classesOf = (id: string) => fake.elements.find((e) => e.id() === id)!.classes

beforeAll(async () => {
  await import('./ModifyPage')
})

beforeEach(() => {
  fake.create.mockClear()
  fake.handlers.clear()
  fake.fits.length = 0
})

describe('ModifyPage', () => {
  it('lista los documentos que cita, con su norma', async () => {
    renderApp('/modify?code=MC-SGG-435&norma=A')

    const table = await screen.findByRole('table', { name: 'Citados directamente' })
    // Cada código enlaza desde su celda (y desde la ruta, como chip).
    expect(within(table).getAllByRole('link', { name: 'ES-SGC-001' })[0]).toHaveAttribute(
      'href',
      '/documents/ES-SGC-001?norma=A',
    )
    expect(within(table).getAllByRole('link', { name: 'LC-SGC-500' })[0]).toHaveAttribute(
      'href',
      '/documents/LC-SGC-500?norma=B',
    )
    expect(within(table).getByText('otra norma')).toBeInTheDocument()
    expect(within(table).getByText('sin documento')).toBeInTheDocument()
    expect(screen.getByText(/Cita 3 documentos directamente/)).toBeInTheDocument()
    // Solo los directos por defecto: no se muestran indirectos ni se pide el grafo completo.
    expect(screen.queryByRole('table', { name: 'Citados indirectamente' })).not.toBeInTheDocument()
    const call = requests.find((url) => url.pathname.endsWith('/dependencies'))!
    expect(call.searchParams.get('depth')).toBe('1')
    expect(call.searchParams.get('norma')).toBe('A')
    expect(requests.some((url) => url.pathname === '/api/graph/full')).toBe(false)
  })

  it('con más profundidad agrega los citados indirectamente', async () => {
    renderApp('/modify?code=MC-SGG-435&norma=A&depth=2')

    const table = await screen.findByRole('table', { name: 'Citados indirectamente' })
    expect(within(table).getAllByRole('link', { name: 'PO-SGS-400' })[0]).toHaveAttribute(
      'href',
      '/documents/PO-SGS-400?norma=B',
    )
    expect(within(table).getByLabelText('MC-SGG-435 cita a LC-SGC-500 cita a PO-SGS-400')).toBeInTheDocument()
  })

  it('resalta lo que cita sobre el grafo completo', async () => {
    const user = userEvent.setup()
    renderApp('/modify?code=MC-SGG-435&norma=A')

    await user.click(await screen.findByRole('tab', { name: 'Ver en el grafo' }))

    await screen.findByTestId('full-graph-canvas')
    expect(screen.getByTestId('location')).toHaveTextContent('tab=graph')
    expect(requests.some((url) => url.pathname === '/api/graph/full')).toBe(true)
    // Todas las normas se dibujan como recuadros, con el resto del grafo atenuado.
    expect(classesOf('norma::A')).toContain('norma')
    expect(classesOf('A/MC-SGG-435')).toContain('hl-root')
    expect(classesOf('A/ES-SGC-001')).toContain('hl-direct')
    expect(classesOf('B/LC-SGC-500')).toContain('hl-direct')
    expect(classesOf('RG-SGSA-928')).toContain('hl-direct')
    expect(classesOf('B/MC-SGG-435')).toContain('faded')
    expect(classesOf('A/MC-SGG-435->B/LC-SGC-500')).toContain('hl-edge')
    expect(classesOf('B/MC-SGG-435->A/ES-SGC-001')).toContain('faded')
    expect(classesOf('norma::B')).not.toContain('faded')
    expect(screen.getByLabelText('Leyenda del grafo')).toHaveTextContent('Documento a modificar')
  })

  it('permite seleccionar otro documento del grafo para modificar', async () => {
    renderApp('/modify?code=MC-SGG-435&norma=A&tab=graph')
    await screen.findByTestId('full-graph-canvas')

    act(() =>
      fake.handlers.get('tap node')!({ target: { id: () => 'B/MC-SGG-435', hasClass: () => false } }),
    )
    const panel = screen.getByLabelText('Documento seleccionado')
    expect(within(panel).getByText('Norma: B')).toBeInTheDocument()
    await userEvent.setup().click(within(panel).getByRole('button', { name: 'Modificar este' }))

    expect(screen.getByTestId('location')).toHaveTextContent('code=MC-SGG-435&norma=B')
  })

  it('pide la norma si el código es documento en varias', async () => {
    renderApp('/modify?code=MC-SGG-435')

    expect(await screen.findByText('El código es un documento en varias normas')).toBeInTheDocument()
  })

  it('sin documento elegido no consulta nada', async () => {
    renderApp('/modify')

    expect(await screen.findByText(/Elija el documento que va a modificar/)).toBeInTheDocument()
    expect(requests.some((url) => url.pathname.endsWith('/dependencies'))).toBe(false)
  })
})
