import { useEffect, useState } from 'react'
import { Autocomplete, Box, TextField, Typography } from '@mui/material'
import { useDocuments } from '../api/hooks'
import type { DocumentSummary } from '../api/types'

interface Props {
  norma: string | null
  onSelect: (document: DocumentSummary) => void
  label?: string
}

function useDebounced(value: string, delay = 250): string {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

/** Búsqueda de documentos por código o título, con sugerencias de la API. */
export function DocumentPicker({ norma, onSelect, label = 'Buscar documento por código o título' }: Props) {
  const [input, setInput] = useState('')
  const query = useDebounced(input)
  const { data, isFetching } = useDocuments(
    { query, norma, page: 1, pageSize: 20 },
    query.trim().length >= 2,
  )
  const options = query.trim().length >= 2 ? (data?.items ?? []) : []

  return (
    <Autocomplete<DocumentSummary>
      options={options}
      loading={isFetching}
      filterOptions={(items) => items}
      getOptionLabel={(option) => `${option.code} ${option.title ?? ''}`.trim()}
      getOptionKey={(option) => `${option.norma}/${option.code}`}
      isOptionEqualToValue={(a, b) => a.code === b.code && a.norma === b.norma}
      inputValue={input}
      onInputChange={(_, value) => setInput(value)}
      onChange={(_, value) => {
        if (value) onSelect(value)
      }}
      noOptionsText={query.trim().length >= 2 ? 'Sin resultados' : 'Escriba al menos 2 caracteres'}
      renderOption={({ key, ...props }, option) => (
        <Box component="li" key={key} {...props}>
          <Box>
            <Typography sx={{ fontFamily: 'monospace', fontWeight: 600 }}>{option.code}</Typography>
            <Typography variant="caption" color="text.secondary">
              {option.title ?? 'Sin título'} · {option.norma}
            </Typography>
          </Box>
        </Box>
      )}
      renderInput={(params) => <TextField {...params} size="small" label={label} />}
      sx={{ minWidth: 320, flex: 1 }}
    />
  )
}
