// Alias legibles de los tipos generados desde OpenAPI (npm run gen:api).
import type { components } from './schema'

type Schemas = components['schemas']

export type NormaSummary = Schemas['NormaOut']
export type Health = Schemas['HealthResponse']
export type Limits = Schemas['LimitsOut']
export type Stats = Schemas['StatsResponse']
export type DocumentSummary = Schemas['DocumentSummary']
export type DocumentDetail = Schemas['DocumentDetail']
export type DocumentPage = Schemas['Page_DocumentSummary_']
export type Issue = Schemas['IssueOut']
export type IssuePage = Schemas['Page_IssueOut_']
export type Occurrence = Schemas['OccurrenceOut']
export type ReferenceItem = Schemas['ReferenceItem']
export type References = Schemas['ReferencesResponse']
export type Traversal = Schemas['TraversalResponse']
export type TraversalItem = Schemas['TraversalItemOut']
export type Neighborhood = Schemas['GraphResponse']
export type GraphNode = Schemas['NeighborhoodNodeOut']
export type FullGraph = Schemas['FullGraphResponse']
export type FullGraphNode = Schemas['GraphNodeOut']
export type GraphEdge = Schemas['GraphEdgeOut']
export type Cycles = Schemas['CyclesResponse']
export type Unresolved = Schemas['UnresolvedOut']
export type UnresolvedPage = Schemas['Page_UnresolvedOut_']
export type Run = Schemas['RunOut']
export type RunPage = Schemas['Page_RunOut_']
export type ErrorBody = Schemas['ErrorBody']

export type Direction = 'in' | 'out' | 'both'
