import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderApp } from '../test/render'

describe('QualityPage', () => {
  it('lista incidencias de la ingesta y calculadas', async () => {
    renderApp('/quality')

    const table = await screen.findByRole('table', { name: 'Incidencias' })
    expect(await within(table).findByText('ambiguous_editions')).toBeInTheDocument()
    expect(within(table).getByText('ingesta')).toBeInTheDocument()
    expect(within(table).getByText('calculada')).toBeInTheDocument()
    expect(within(table).getByText(/¿quiso decir LC-SGSA-928\?/)).toBeInTheDocument()
  })

  it('muestra totales de la norma elegida', async () => {
    renderApp('/quality?norma=B')

    expect(await screen.findByText('Citados sin documento')).toBeInTheDocument()
    const stat = screen.getByText('Documentos').parentElement!
    expect(await within(stat).findByText('2')).toBeInTheDocument()
    expect(screen.getByText('Citan a otra norma')).toBeInTheDocument()
  })

  it('lista los códigos citados sin documento y los ambiguos', async () => {
    const user = userEvent.setup()
    renderApp('/quality')

    await user.click(screen.getByRole('tab', { name: 'Referencias pendientes' }))

    const table = await screen.findByRole('table', { name: 'Referencias pendientes' })
    expect(within(table).getByRole('link', { name: 'RG-SGSA-928' })).toBeInTheDocument()
    expect(within(table).getAllByRole('link', { name: 'MC-SGG-435' })[0]).toHaveAttribute(
      'href',
      '/documents/MC-SGG-435?norma=A',
    )
    expect(within(table).getByText('Ambiguo: existe en A, B')).toBeInTheDocument()
  })

  it('muestra los ciclos, filtrados por norma', async () => {
    renderApp('/quality?norma=A&tab=cycles')

    expect(await screen.findByLabelText('MC-SGG-435 cita a PC-SGSA-914 cita a MC-SGG-435')).toBeInTheDocument()
    expect(screen.queryByLabelText('MC-SGG-435 cita a PO-SGS-400 cita a MC-SGG-435')).not.toBeInTheDocument()
  })

  it('muestra las referencias de cada ingesta y su log', async () => {
    renderApp('/quality?tab=runs')

    const table = await screen.findByRole('table', { name: 'Corridas de ingesta' })
    expect(within(table).getByText('ingest-00001-20261026-120000.log')).toBeInTheDocument()
  })
})
