import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderApp } from './test/render'

// Cytoscape necesita canvas, que jsdom no tiene.
vi.mock('cytoscape', () => ({
  default: () => ({ on: vi.fn(), destroy: vi.fn(), fit: vi.fn(), layout: () => ({ run: vi.fn() }) }),
}))

describe('App', () => {
  it('muestra el nombre y las secciones', () => {
    renderApp('/')

    expect(screen.getByRole('heading', { name: 'ISO Trace' })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Secciones' })
    expect(nav).toHaveTextContent('BuscarDocumento a modificarImpactoGrafoCalidad')
  })

  it('conserva norma y documento al cambiar de sección', async () => {
    const user = userEvent.setup()
    renderApp('/impact?code=ES-SGC-001&norma=A')

    await user.click(screen.getByRole('link', { name: 'Grafo' }))

    expect(screen.getByTestId('location')).toHaveTextContent('/graph?norma=A&code=ES-SGC-001')
  })

  it('muestra una página para rutas inexistentes', () => {
    renderApp('/nada')

    expect(screen.getByRole('heading', { name: 'Página no encontrada' })).toBeInTheDocument()
  })
})
