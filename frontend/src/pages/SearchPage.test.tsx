import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderApp } from '../test/render'
import { requests } from '../test/server'

describe('SearchPage', () => {
  it('lista los documentos organizados por norma con sus conteos', async () => {
    renderApp('/')

    const table = await screen.findByRole('table', { name: 'Documentos' })
    await within(table).findByText('Estándar de calidad')
    expect(within(table).getAllByRole('link', { name: 'MC-SGG-435' })).toHaveLength(2)
    expect(within(table).getAllByRole('rowheader').map((cell) => cell.textContent)).toEqual(['A', 'B'])
    expect(within(table).getByText('XLSX')).toBeInTheDocument()
    expect(screen.getByText('1–5 de 5')).toBeInTheDocument()
  })

  it('enlaza el detalle con la norma explícita', async () => {
    renderApp('/?norma=B')

    const link = await screen.findByRole('link', { name: 'MC-SGG-435' })
    expect(link).toHaveAttribute('href', '/documents/MC-SGG-435?norma=B')
  })

  it('busca por texto y lo refleja en la URL', async () => {
    const user = userEvent.setup()
    renderApp('/')

    await user.type(screen.getByLabelText('Buscar por código o título'), 'personal')

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('query=personal'))
    const table = screen.getByRole('table', { name: 'Documentos' })
    // Encabezado, subtítulo de la norma A y el único documento encontrado.
    await waitFor(() => expect(within(table).getAllByRole('row')).toHaveLength(3))
    expect(within(table).getByText('PR-SGG-101')).toBeInTheDocument()
    expect(requests.some((url) => url.searchParams.get('query') === 'personal')).toBe(true)
  })
})
