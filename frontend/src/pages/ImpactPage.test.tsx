import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DISCLAIMER } from '../test/fixtures'
import { renderApp } from '../test/render'
import { requests } from '../test/server'

describe('ImpactPage', () => {
  it('muestra el aviso, directos e indirectos con su ruta', async () => {
    renderApp('/impact?code=ES-SGC-001&norma=A&depth=2')

    expect(await screen.findByRole('note')).toHaveTextContent(DISCLAIMER)
    const direct = screen.getByRole('table', { name: 'Directos' })
    const indirect = screen.getByRole('table', { name: 'Indirectos' })
    // El código enlaza al detalle desde su celda y desde la ruta.
    expect(within(direct).getAllByRole('link', { name: 'MC-SGG-435' })).toHaveLength(2)
    expect(within(indirect).getByLabelText('PR-SGG-101 cita a MC-SGG-435 cita a ES-SGC-001')).toBeInTheDocument()
    expect(screen.getByText('Nivel 1: 1')).toBeInTheDocument()
    expect(screen.getByText('Nivel 2: 1')).toBeInTheDocument()
  })

  it('exporta el mismo impacto en CSV', async () => {
    renderApp('/impact?code=ES-SGC-001&norma=A&depth=3&groups=general')

    const button = await screen.findByRole('link', { name: 'Exportar CSV' })
    expect(button).toHaveAttribute(
      'href',
      '/api/documents/ES-SGC-001/impact.csv?norma=A&depth=3&groups=general',
    )
  })

  it('envía profundidad y grupos a la API', async () => {
    renderApp('/impact?code=ES-SGC-001&norma=A&depth=3&groups=general')

    await screen.findByRole('note')
    const call = requests.find((url) => url.pathname.endsWith('/impact'))!
    expect(call.searchParams.get('depth')).toBe('3')
    expect(call.searchParams.getAll('groups')).toEqual(['general'])
  })

  it('cambia a dependencias sin el aviso de impacto', async () => {
    const user = userEvent.setup()
    renderApp('/impact?code=ES-SGC-001&norma=A')
    await screen.findByRole('note')

    await user.click(screen.getByRole('button', { name: 'Qué cita (dependencias)' }))

    expect(await screen.findByText('No cita otros documentos.')).toBeInTheDocument()
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
    expect(requests.some((url) => url.pathname.endsWith('/dependencies'))).toBe(true)
  })

  it('informa si el código no existe', async () => {
    renderApp('/impact?code=XX-ABC-999')

    expect(await screen.findByText('XX-ABC-999 no es un documento ni un código citado')).toBeInTheDocument()
  })
})
