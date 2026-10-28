// cytoscape-fcose no publica tipos: es una extensión de layout que se registra con cytoscape.use().
declare module 'cytoscape-fcose' {
  import type { Ext } from 'cytoscape'

  const fcose: Ext
  export default fcose
}
