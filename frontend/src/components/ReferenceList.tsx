import { useState } from 'react'
import {
  Box,
  Chip,
  Collapse,
  IconButton,
  Link,
  List,
  ListItem,
  Paper,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import { Link as RouterLink } from 'react-router'
import type { Occurrence, ReferenceItem } from '../api/types'
import { links } from '../routing'

interface Props {
  title: string
  subtitle: string
  items: ReferenceItem[]
  emptyText: string
}

function location(occurrence: Occurrence): string {
  const parts: string[] = []
  if (occurrence.page_number != null) parts.push(`pág. ${occurrence.page_number}`)
  if (occurrence.table_index != null) {
    let table = `tabla ${occurrence.table_index + 1}`
    if (occurrence.row_index != null) table += `, fila ${occurrence.row_index + 1}`
    parts.push(table)
  }
  if (occurrence.paragraph_index != null && occurrence.table_index == null) {
    parts.push(`párrafo ${occurrence.paragraph_index + 1}`)
  }
  return parts.join(' · ') || 'sin ubicación'
}

function ReferenceRow({ item }: { item: ReferenceItem }) {
  const [open, setOpen] = useState(false)
  const differentHint =
    item.title_hint && item.title && item.title_hint.trim() !== item.title.trim()
  return (
    <ListItem divider sx={{ display: 'block', py: 1 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <Link
          component={RouterLink}
          to={item.resolved ? links.document(item.code, item.norma) : links.impact(item.code)}
          sx={{ fontFamily: 'monospace', fontWeight: 600, whiteSpace: 'nowrap' }}
        >
          {item.code}
        </Link>
        <Typography variant="body2" sx={{ flex: 1, minWidth: 0 }} noWrap title={item.title ?? ''}>
          {item.title ?? item.title_hint ?? ''}
        </Typography>
        {item.cross_norma && item.norma ? (
          <Tooltip title="Referencia entre normas">
            <Chip size="small" label={item.norma} color="secondary" variant="outlined" />
          </Tooltip>
        ) : null}
        {item.candidate_normas.length > 1 ? (
          <Tooltip title={`El código existe en varias normas (${item.candidate_normas.join(', ')}): no se puede saber a cuál se refiere`}>
            <Chip size="small" label="ambiguo" color="warning" variant="outlined" />
          </Tooltip>
        ) : null}
        {item.group !== 'general' ? <Chip size="small" label={item.group} /> : null}
        {item.has_mixed_groups ? (
          <Tooltip title="Aparece en más de un grupo de la sección">
            <Chip size="small" label="grupos mixtos" color="warning" variant="outlined" />
          </Tooltip>
        ) : null}
        <Tooltip title={open ? 'Ocultar evidencia' : 'Ver evidencia'}>
          <IconButton
            size="small"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-label={`Evidencia de ${item.code}`}
          >
            {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
      </Stack>
      {differentHint ? (
        <Typography variant="caption" color="warning.main">
          Citado como: “{item.title_hint}”
        </Typography>
      ) : null}
      <Collapse in={open} unmountOnExit>
        <Box component="ul" sx={{ m: 0, mt: 1, pl: 3 }}>
          {item.occurrences.map((occurrence, index) => (
            <Typography component="li" variant="caption" key={index} sx={{ display: 'list-item' }}>
              <strong>{location(occurrence)}</strong> ({occurrence.group}):{' '}
              {occurrence.evidence_excerpt ?? occurrence.raw_text}
            </Typography>
          ))}
        </Box>
      </Collapse>
    </ListItem>
  )
}

export function ReferenceList({ title, subtitle, items, emptyText }: Props) {
  return (
    <Paper variant="outlined" component="section" aria-label={title}>
      <Box sx={{ px: 2, pt: 1.5 }}>
        <Typography variant="subtitle1" component="h3">
          {title} ({items.length})
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {subtitle}
        </Typography>
      </Box>
      {items.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ px: 2, py: 2 }}>
          {emptyText}
        </Typography>
      ) : (
        <List dense disablePadding>
          {items.map((item) => (
            <ReferenceRow key={`${item.norma ?? ''}/${item.code}`} item={item} />
          ))}
        </List>
      )}
    </Paper>
  )
}
