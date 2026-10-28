# ISO Trace — API REST

API de **solo lectura** para consultar la trazabilidad documental. La ingesta y la actualización se hacen desde la CLI (`iso-trace ingest`).

```bash
uv run iso-trace api serve          # http://127.0.0.1:8000 (ISO_API_HOST / ISO_API_PORT)
uv run iso-trace api openapi -o frontend/openapi.json   # o, en frontend/: npm run gen:api
```

La documentación interactiva queda en `/docs` (Swagger UI) y el esquema en `/openapi.json`.

## Conceptos

- **Grafo**: hay **un solo grafo** con todos los documentos. Las referencias y el impacto cruzan normas.
- **Norma**: cada carpeta raíz del directorio de documentos (por ejemplo `ISO 9001`) es una norma, que sirve para organizar y filtrar. El código es único dentro de cada norma: el mismo código en dos normas son dos documentos distintos.
- **Resolución de una cita**: `A` (norma N) cita el código C → el documento C de la norma N si existe; si no, el de la única otra norma que lo tenga (`cross_norma=true`); si está en varias otras normas, la cita queda pendiente y es **ambigua** (`candidate_normas`).
- **Id de nodo**: `"norma/código"` para un documento (`ISO 9001/MC-SGI-001`) y el código a secas para un citado sin documento.
- **Dirección**: una arista `A → B` significa **A cita a B**. Las rutas (`path`) siempre siguen ese sentido.
- **Impacto**: documentos que citan al consultado, directa o indirectamente. Son **posibles documentos a revisar**, no la confirmación de que deban modificarse; cada respuesta incluye ese aviso en `disclaimer`.
- **Dependencias**: lo que el documento cita, directa o indirectamente (la vista "Documento a modificar").
- **Código citado sin documento**: un código que alguien cita pero que no tiene documento (o que es ambiguo entre normas). Tiene referencias entrantes e impacto, pero no detalle (404).
- **Planilla** (`file_format` `xlsx`, `xlsm` o `xls`): documento con estado `not_applicable`; puede ser citado, pero no se analizan sus referencias.

## Convenciones

| Tema | Regla |
|---|---|
| Prefijo | Todas las rutas empiezan con `/api` |
| Códigos | Se normalizan a mayúsculas (`mc-sgg-435` = `MC-SGG-435`) |
| Parámetro `norma` | Obligatorio si el código es documento en más de una norma (409 `norma_required`); si está en una sola, se infiere. Un código citado sin documento no lleva norma |
| Paginación | `page` (desde 1) y `page_size` (1–200, por defecto 50). Respuesta: `{items, total, page, page_size}` |
| Profundidad | `depth` entre 1 y `ISO_MAX_DEPTH` (por defecto 10); si se omite, `ISO_DEFAULT_DEPTH` (2) |
| Listas | Parámetros repetibles: `?types=PR&types=PO`, `?groups=general` |
| Métodos | Solo `GET`. CORS solo para `ISO_CORS_ORIGINS` |

## Errores

Siempre con el mismo formato:

```json
{"error": {"code": "norma_required", "message": "MC-SGG-435 es un documento en varias normas; indicar ?norma=", "details": {"code": "MC-SGG-435", "normas": ["A", "B"]}}}
```

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `depth_out_of_range` | `depth` fuera de 1..máximo |
| 400 | `graph_too_large` | El grafo completo supera `ISO_GRAPH_FULL_MAX_NODES` |
| 404 | `document_not_found` | El código no es documento (de la norma indicada) ni está citado; en el detalle, también si solo está citado |
| 404 | `norma_not_found` | No existe la norma indicada |
| 404 | `not_found` | Ruta inexistente |
| 409 | `norma_required` | El código es documento en varias normas y falta `norma` |
| 422 | `validation_error` | Parámetros inválidos (`details.errors`) |
| 500 | `internal_error` | Error inesperado (sin trazas en la respuesta) |

## Endpoints

### General

| Ruta | Descripción |
|---|---|
| `GET /api/health` | `{status, database, schema_revision, graph_version, limits}`; `limits` trae `default_depth`, `max_depth`, `graph_max_nodes` y `graph_full_max_nodes` para la interfaz |
| `GET /api/normas` | Normas: `[{name, documents, references, unresolved, cross_norma}]` (`cross_norma`: citas resueltas hacia otra norma) |
| `GET /api/stats` | Totales por norma, estado y tipo; referencias, pendientes, incidencias abiertas y última corrida |
| `GET /api/ingestion/runs` | Historial paginado de corridas: contadores, `references_count`, `occurrences_count`, `duplicate_references_count`, `unresolved_count` y `log_path` |

### Documentos

| Ruta | Parámetros | Respuesta |
|---|---|---|
| `GET /api/documents` | `query` (código o título), `norma`, `type`, `system`, `folder`, `status`, `active` (por defecto `true`), `sort` (`norma` —por norma y nombre, por defecto—, `code`, `title`, `updated_at`), `page`, `page_size` | `Page[DocumentSummary]` con norma, formato y conteos de salientes y entrantes |
| `GET /api/documents/{code}` | `norma` | `DocumentDetail`: metadatos, versión, archivo, formato, estado, `references_stale`, conteos e incidencias abiertas |
| `GET /api/documents/{code}/references` | `norma`, `group` | `{norma, outgoing, unresolved, incoming}`. `outgoing`: documentos que cita (con su `norma` y `cross_norma`); `unresolved`: códigos que cita sin documento o ambiguos (`candidate_normas`); `incoming`: documentos que lo citan. Cada ítem trae su evidencia (`occurrences`: página, tabla, párrafo, extracto) |
| `GET /api/documents/{code}/impact` | `norma`, `depth`, `types`, `groups` | `{root, disclaimer, depth, direct, indirect, summary}`. `root` y cada ítem: `code, norma, node_id, title, …`; los ítems traen además `depth, relation, path, resolved` |
| `GET /api/documents/{code}/impact.csv` | los mismos | CSV para Excel: UTF-8 con BOM, separador `;`, primera fila con el aviso; columnas `norma_modificado`, `documento_modificado`, …, `norma`, `codigo`, … |
| `GET /api/documents/{code}/dependencies` | `norma`, `depth`, `types`, `groups` | Lo que el documento cita, directa o indirectamente (misma forma que el impacto) |

`types` solo **oculta** resultados: el recorrido pasa igual por todos los documentos, y las rutas siguen siendo completas. `groups` sí limita las relaciones que se recorren.

### Grafo

| Ruta | Parámetros | Respuesta |
|---|---|---|
| `GET /api/graph` | `code` (obligatorio), `norma`, `depth`, `direction` (`in`: quienes lo citan; `out`: lo que cita; `both`), `types`, `groups`, `include_unresolved`, `max_nodes` | Subgrafo de vecindad para Cytoscape.js: `{root, depth, direction, truncated, nodes, edges}` (`root` es el id del nodo). Si supera `max_nodes` (tope `ISO_GRAPH_MAX_NODES`) se recorta por distancia y `truncated=true` |
| `GET /api/graph/full` | `include_unresolved` | Grafo completo, todas las normas: `{graph_version, normas, nodes, edges}`. Lo usa la vista "Documento a modificar" para resaltar lo que cita un documento (y, con el interruptor, quién lo cita, vía `/impact`). Acotado por `ISO_GRAPH_FULL_MAX_NODES` (400 `graph_too_large`) |
| `GET /api/graph/cycles` | `limit` | Referencias circulares (ids de nodo), también entre normas |

Nodos: `{id, code, norma, title, document_type, system_code, file_format, status, resolved, active}` (más `distance` e `is_root` en la vecindad). Aristas: `{id, source, target, group, occurrences, mixed_groups, cross_norma}`, donde `source` cita a `target`.

### Calidad

| Ruta | Parámetros | Respuesta |
|---|---|---|
| `GET /api/quality/issues` | `norma`, `type`, `severity`, `code`, `open` (por defecto `true`), `derived` (por defecto `true`), `page`, `page_size` | Incidencias de la ingesta (`source="stored"`) y calculadas sobre el estado actual (`source="derived"`: ciclos, documentos aislados, citas ambiguas entre normas, el mismo archivo en varias normas, títulos citados distintos, citas a inactivos, códigos parecidos) |
| `GET /api/references/unresolved` | `norma` (de quien cita), `query`, `page`, `page_size` | Códigos citados sin destino: `{target_code, title_hint, cited_by_count, cited_by, candidate_normas}`; `cited_by` son ids `norma/código`; `candidate_normas` no vacío = cita ambigua |

## Ejemplos

```bash
# Normas y totales
curl http://127.0.0.1:8000/api/normas

# Impacto de un cambio en ES-SGC-001, hasta 3 saltos (cruza normas)
curl -G http://127.0.0.1:8000/api/documents/ES-SGC-001/impact --data-urlencode "depth=3"

# Lo que cita el manual de ISO 9001 (directo)
curl -G http://127.0.0.1:8000/api/documents/MC-SGI-001/dependencies \
  --data-urlencode "norma=ISO 9001" --data-urlencode "depth=1"

# Subgrafo de quienes citan a PC-SGSA-914
curl -G http://127.0.0.1:8000/api/graph --data-urlencode "code=PC-SGSA-914" --data-urlencode "direction=in"
```

## Seguridad

- No hay autenticación en el MVP: la API escucha solo en `127.0.0.1`. Para exponerla en una red, ponerla detrás de un proxy inverso con autenticación.
- Nunca entrega los archivos originales, solo metadatos y extractos de evidencia.
- Todas las consultas usan el ORM con parámetros; no se arma SQL concatenando texto.
