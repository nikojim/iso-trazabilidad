import { Alert, AlertTitle, Button, Stack } from '@mui/material'
import { ApiError } from '../api/client'

interface Props {
  error: unknown
  /** Si el código es documento en varias normas (409), ofrecer elegir una. */
  onChooseNorma?: (norma: string) => void
}

export function QueryError({ error, onChooseNorma }: Props) {
  if (error instanceof ApiError && error.code === 'norma_required') {
    return (
      <Alert severity="info">
        <AlertTitle>El código es un documento en varias normas</AlertTitle>
        Elija de qué norma consultarlo:
        <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: 'wrap' }}>
          {error.normas.map((norma) => (
            <Button key={norma} size="small" variant="outlined" onClick={() => onChooseNorma?.(norma)}>
              {norma}
            </Button>
          ))}
        </Stack>
      </Alert>
    )
  }
  const message = error instanceof Error ? error.message : 'Error inesperado'
  const notFound = error instanceof ApiError && error.status === 404
  return (
    <Alert severity={notFound ? 'warning' : 'error'}>
      {notFound ? <AlertTitle>No encontrado</AlertTitle> : null}
      {message}
    </Alert>
  )
}
