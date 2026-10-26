import { Alert } from '@mui/material'

const DEFAULT_TEXT =
  'Posibles documentos a revisar: citan al documento, directa o indirectamente. ' +
  'No implica que deban modificarse.'

export function PotentialImpactNotice({ text }: { text?: string }) {
  return (
    <Alert severity="info" role="note">
      {text ?? DEFAULT_TEXT}
    </Alert>
  )
}
