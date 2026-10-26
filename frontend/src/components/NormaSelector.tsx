import { MenuItem, TextField } from '@mui/material'
import { useNormas } from '../api/hooks'

interface Props {
  value: string | null
  onChange: (norma: string | null) => void
  allowAll?: boolean
  label?: string
}

const ALL = '__all__'

/** Norma (carpeta raíz) para filtrar; el grafo es uno solo. */
export function NormaSelector({ value, onChange, allowAll = true, label = 'Norma' }: Props) {
  const { data: normas = [], isLoading } = useNormas()
  const current = value ?? (allowAll ? ALL : '')
  return (
    <TextField
      select
      size="small"
      label={label}
      value={normas.some((n) => n.name === current) || current === ALL ? current : ''}
      onChange={(event) => onChange(event.target.value === ALL ? null : event.target.value)}
      disabled={isLoading}
      sx={{ minWidth: 220 }}
    >
      {allowAll ? <MenuItem value={ALL}>Todas las normas</MenuItem> : null}
      {normas.map((norma) => (
        <MenuItem key={norma.name} value={norma.name}>
          {norma.name} ({norma.documents})
        </MenuItem>
      ))}
    </TextField>
  )
}
