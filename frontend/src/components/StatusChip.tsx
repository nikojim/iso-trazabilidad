import { Chip, Tooltip, type ChipProps } from '@mui/material'

const STATUS: Record<string, { label: string; color: ChipProps['color']; help: string }> = {
  ok: { label: 'OK', color: 'success', help: 'Sección REFERENCIAS leída correctamente' },
  no_references: {
    label: 'Sin referencias',
    color: 'default',
    help: 'La sección REFERENCIAS existe y está vacía',
  },
  no_section: {
    label: 'Sin sección',
    color: 'default',
    help: 'El documento no tiene sección REFERENCIAS (listados, formularios…)',
  },
  needs_review: {
    label: 'Revisar',
    color: 'warning',
    help: 'No se pudo delimitar la sección con certeza; se conservan las referencias anteriores',
  },
  requires_ocr: {
    label: 'Requiere OCR',
    color: 'warning',
    help: 'PDF escaneado: no se pudo leer el texto',
  },
  error: { label: 'Error', color: 'error', help: 'No se pudo leer el archivo' },
  not_applicable: {
    label: 'Planilla',
    color: 'info',
    help: 'Planilla XLSX: se puede citar, pero no se analizan sus referencias',
  },
  source_code_unresolved: {
    label: 'Código dudoso',
    color: 'error',
    help: 'No se pudo confirmar el código del documento',
  },
}

export function StatusChip({ status }: { status: string | null | undefined }) {
  const info = (status && STATUS[status]) || { label: status ?? '—', color: 'default', help: '' }
  return (
    <Tooltip title={info.help}>
      <Chip size="small" label={info.label} color={info.color} variant="outlined" />
    </Tooltip>
  )
}
