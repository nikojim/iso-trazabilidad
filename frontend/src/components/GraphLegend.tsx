import type { ReactNode } from 'react'
import { Box, Stack, Typography } from '@mui/material'
import { colorForType } from '../graph/toElements'

function Swatch({ sx }: { sx: object }) {
  return <Box component="span" sx={{ width: 14, height: 14, borderRadius: '50%', display: 'inline-block', ...sx }} />
}

function Line({ dashed, color = '#90a4ae' }: { dashed?: boolean; color?: string }) {
  return (
    <Box
      component="span"
      sx={{ width: 28, borderTopWidth: 2, borderTopColor: color, borderTopStyle: dashed ? 'dashed' : 'solid' }}
    />
  )
}

interface Props {
  /** Tipos presentes en el grafo dibujado. */
  types: string[]
  /** Leyenda del resaltado del documento a modificar (grafo completo). */
  highlight?: boolean
  /** El resaltado incluye a quienes citan al documento. */
  citers?: boolean
}

export function GraphLegend({ types, highlight = false, citers = false }: Props) {
  const item = (symbol: ReactNode, text: string) => (
    <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }} key={text}>
      {symbol}
      <Typography variant="caption">{text}</Typography>
    </Stack>
  )
  return (
    <Stack spacing={0.75} aria-label="Leyenda del grafo">
      {item(<Typography variant="caption">A → B</Typography>, 'A cita a B')}
      {highlight ? (
        <>
          {item(<Swatch sx={{ bgcolor: '#607d8b', border: '3px solid #ffb300' }} />, 'Documento a modificar')}
          {item(<Swatch sx={{ bgcolor: '#607d8b', border: '3px solid #e53935' }} />, 'Citado directamente')}
          {item(<Swatch sx={{ bgcolor: '#607d8b', border: '3px solid #fb8c00' }} />, 'Citado indirectamente')}
          {citers
            ? item(<Swatch sx={{ bgcolor: '#607d8b', border: '3px solid #1e88e5' }} />, 'Lo cita (posible a revisar)')
            : null}
          {item(<Swatch sx={{ bgcolor: '#607d8b', opacity: 0.2 }} />, 'Resto del grafo')}
        </>
      ) : (
        item(<Swatch sx={{ bgcolor: '#607d8b', border: '3px solid #ffb300' }} />, 'Documento consultado')
      )}
      {item(<Swatch sx={{ bgcolor: '#eceff1', border: '2px dashed #78909c' }} />, 'Citado sin documento')}
      {item(<Swatch sx={{ bgcolor: '#607d8b', borderRadius: '3px' }} />, 'Planilla (Excel)')}
      {item(<Swatch sx={{ bgcolor: '#607d8b', opacity: 0.45 }} />, 'Inactivo')}
      {item(<Line />, 'Referencia general')}
      {item(<Line dashed />, 'Procedimientos')}
      {item(<Line color="#7e57c2" />, 'Referencia entre normas')}
      {types.map((type) => item(<Swatch sx={{ bgcolor: colorForType(type) }} />, type))}
    </Stack>
  )
}
