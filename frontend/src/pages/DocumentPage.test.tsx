import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderApp } from '../test/render'

describe('DocumentPage', () => {
  it('separa salientes, citados sin documento y entrantes', async () => {
    renderApp('/documents/MC-SGG-435?norma=A')

    expect(await screen.findByText('Manual de los Sistemas de Gestión')).toBeInTheDocument()
    const outgoing = await screen.findByRole('region', { name: 'Documentos que cita' })
    const unresolved = screen.getByRole('region', { name: 'Citados sin documento' })
    const incoming = screen.getByRole('region', { name: 'Documentos que lo citan' })

    expect(within(outgoing).getByRole('link', { name: 'ES-SGC-001' })).toHaveAttribute(
      'href',
      '/documents/ES-SGC-001?norma=A',
    )
    // Un código sin documento no tiene detalle ni norma: enlaza a su impacto.
    expect(within(unresolved).getByRole('link', { name: 'RG-SGSA-928' })).toHaveAttribute(
      'href',
      '/impact?code=RG-SGSA-928',
    )
    expect(within(incoming).getByRole('link', { name: 'PR-SGG-101' })).toBeInTheDocument()
    expect(within(incoming).queryByText('ES-SGC-001')).not.toBeInTheDocument()
  })

  it('marca las referencias a otra norma y enlaza con su norma', async () => {
    renderApp('/documents/MC-SGG-435?norma=A')

    const outgoing = await screen.findByRole('region', { name: 'Documentos que cita' })
    expect(within(outgoing).getByRole('link', { name: 'LC-SGC-500' })).toHaveAttribute(
      'href',
      '/documents/LC-SGC-500?norma=B',
    )
    expect(within(outgoing).getByText('B')).toBeInTheDocument()
    expect(screen.getByText('Norma: A')).toBeInTheDocument()
  })

  it('lleva a la vista de documento a modificar', async () => {
    renderApp('/documents/MC-SGG-435?norma=A')

    expect(await screen.findByRole('link', { name: 'Ver documentos que cita' })).toHaveAttribute(
      'href',
      '/modify?code=MC-SGG-435&norma=A',
    )
  })

  it('muestra la evidencia de cada ocurrencia', async () => {
    const user = userEvent.setup()
    renderApp('/documents/MC-SGG-435?norma=A')

    await user.click(await screen.findByRole('button', { name: 'Evidencia de PR-SGG-101' }))

    expect(screen.getByText('pág. 3')).toBeInTheDocument()
    expect(screen.getByText('pág. 4')).toBeInTheDocument()
    expect(screen.getByText(/Citado como: “Manual SG”/)).toBeInTheDocument()
  })

  it('pide elegir la norma si el código es documento en varias', async () => {
    const user = userEvent.setup()
    renderApp('/documents/MC-SGG-435')

    expect(await screen.findByText('El código es un documento en varias normas')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'B' }))

    expect(screen.getByTestId('location')).toHaveTextContent('/documents/MC-SGG-435?norma=B')
    expect(await screen.findByRole('region', { name: 'Documentos que cita' })).toBeInTheDocument()
  })

  it('distingue un código citado sin documento', async () => {
    renderApp('/documents/ES-SGC-100')

    expect(await screen.findByText(/Ningún archivo tiene este código/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Análisis de impacto' })).toHaveAttribute(
      'href',
      '/impact?code=ES-SGC-100',
    )
    expect(screen.queryByRole('link', { name: 'Ver documentos que cita' })).not.toBeInTheDocument()
  })
})
