import type { StylesheetJson } from 'cytoscape'
import { KNOWN_TYPES, colorForType } from './toElements'

/**
 * Estilos de Cytoscape: flecha hacia el citado, no resueltos punteados, raíz destacada,
 * planillas cuadradas, normas como recuadros y resaltado del documento a modificar.
 */
export function graphStylesheet(): StylesheetJson {
  return [
    {
      selector: 'node',
      style: {
        label: 'data(label)',
        'background-color': colorForType(''),
        color: '#1f2933',
        'font-size': 10,
        'text-valign': 'bottom',
        'text-margin-y': 4,
        width: 22,
        height: 22,
        'border-width': 1,
        'border-color': '#ffffff',
      },
    },
    ...KNOWN_TYPES.map((type) => ({
      selector: `node.type-${type}`,
      style: { 'background-color': colorForType(type) },
    })),
    {
      selector: 'node.root',
      style: { width: 34, height: 34, 'border-width': 4, 'border-color': '#ffb300', 'font-weight': 'bold' },
    },
    {
      selector: 'node.unresolved',
      style: {
        'background-color': '#eceff1',
        'border-width': 2,
        'border-style': 'dashed',
        'border-color': '#78909c',
        color: '#607d8b',
      },
    },
    { selector: 'node.inactive', style: { opacity: 0.45 } },
    { selector: 'node.sheet', style: { shape: 'round-rectangle' } },
    {
      selector: 'node.norma',
      style: {
        label: 'data(label)',
        shape: 'round-rectangle',
        'background-color': '#f5f7fa',
        'background-opacity': 0.6,
        'border-width': 1,
        'border-color': '#b0bec5',
        'text-valign': 'top',
        'text-halign': 'center',
        'font-size': 14,
        'font-weight': 'bold',
        color: '#455a64',
        padding: '18px',
      },
    },
    { selector: 'node:selected', style: { 'overlay-opacity': 0.15, 'overlay-color': '#ffb300' } },
    {
      selector: 'edge',
      style: {
        width: 1.5,
        'curve-style': 'bezier',
        'line-color': '#90a4ae',
        'target-arrow-color': '#90a4ae',
        'target-arrow-shape': 'triangle', // la flecha apunta al documento citado
        'arrow-scale': 1,
      },
    },
    { selector: 'edge.group-procedimientos', style: { 'line-style': 'dashed' } },
    { selector: 'edge.mixed', style: { 'line-color': '#8d6e63', 'target-arrow-color': '#8d6e63' } },
    { selector: 'edge.cross', style: { 'line-color': '#7e57c2', 'target-arrow-color': '#7e57c2' } },
    // Resaltado del documento a modificar, de lo que cita y de quienes lo citan (grafo completo).
    { selector: '.faded', style: { opacity: 0.12 } },
    {
      selector: 'node.hl-root',
      style: { width: 38, height: 38, 'border-width': 5, 'border-color': '#ffb300', 'font-weight': 'bold', 'z-index': 10 },
    },
    {
      selector: 'node.hl-direct',
      style: { width: 30, height: 30, 'border-width': 4, 'border-color': '#e53935', 'font-weight': 'bold', 'z-index': 9 },
    },
    {
      selector: 'node.hl-indirect',
      style: { width: 26, height: 26, 'border-width': 3, 'border-color': '#fb8c00', 'z-index': 8 },
    },
    {
      selector: 'node.hl-citer',
      style: { width: 28, height: 28, 'border-width': 4, 'border-color': '#1e88e5', 'z-index': 8 },
    },
    {
      selector: 'edge.hl-edge',
      style: { width: 3, 'line-color': '#e53935', 'target-arrow-color': '#e53935', 'z-index': 9 },
    },
    {
      selector: 'edge.hl-citer-edge',
      style: { width: 3, 'line-color': '#1e88e5', 'target-arrow-color': '#1e88e5', 'z-index': 8 },
    },
  ]
}
