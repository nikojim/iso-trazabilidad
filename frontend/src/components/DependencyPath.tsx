import { Box, Chip, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router'
import { links, parseNodeId } from '../routing'

/**
 * Ruta en el sentido de las aristas: cada paso cita al siguiente. Los pasos pueden ser códigos
 * o ids de nodo (`norma/código`, como en los ciclos); con norma, el enlace la lleva explícita.
 */
export function DependencyPath({ path }: { path: string[] }) {
  const steps = path.map(parseNodeId)
  return (
    <Box
      component="span"
      aria-label={steps.map((step) => step.code).join(' cita a ')}
      sx={{ display: 'inline-flex', alignItems: 'center', flexWrap: 'wrap', gap: 0.5 }}
    >
      {steps.map((step, index) => (
        <Box component="span" key={`${path[index]}-${index}`} sx={{ display: 'inline-flex', gap: 0.5 }}>
          {index > 0 ? (
            <Typography component="span" color="text.secondary" aria-hidden>
              →
            </Typography>
          ) : null}
          <Chip
            size="small"
            label={step.code}
            title={step.norma ? `${step.norma} / ${step.code}` : step.code}
            component={RouterLink}
            to={links.document(step.code, step.norma)}
            clickable
          />
        </Box>
      ))}
    </Box>
  )
}
