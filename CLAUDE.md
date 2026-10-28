# ISO Trace — instrucciones para Claude Code

## Objetivo
Construir una aplicación de trazabilidad de documentos de calidad ISO. A partir de cientos de documentos PDF, DOCX y planillas Excel, identificar las referencias explícitas de la sección **REFERENCIAS**, persistir sus relaciones y permitir consultar dependencias e impacto ante cambios documentales.

## Stack obligatorio
- Python 3.12+; FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, Typer, NetworkX, pytest, Ruff.
- SQLite como única fuente de verdad (activar `PRAGMA foreign_keys=ON`; usar WAL donde corresponda).
- DOCX: python-docx. PDF con texto: PyMuPDF. XLSX/XLSM: openpyxl; XLS binario: solo el nombre del archivo (las planillas solo aportan identidad: se pueden citar, no se analizan sus referencias). PDF escaneado: detectar y reportar; OCR no es requisito del MVP.
- React + TypeScript + Vite, Cytoscape.js para grafos interactivos; Vitest para pruebas.
- No usar LLM, embeddings, RAG, Neo4j ni LangChain en el MVP.

## Reglas fundamentales
1. La ingesta y sincronización se ejecutan mediante CLI. La aplicación web es de consulta en el MVP.
2. Cada documento tiene un código estable y único; nunca inferirlo silenciosamente de una referencia saliente. Usar metadatos confiables o nombre del archivo cuando cumpla la convención; si hay ambigüedad, emitir incidencia.
3. Una arista `A -> B` significa **A cita o referencia a B**. Para saber quién podría requerir revisión si B cambia, recorrer las aristas **entrantes** de B, directa o transitivamente.
4. Una referencia encontrada puede apuntar a un código todavía no incorporado: conservar `target_code` y `target_document_id=NULL` hasta resolverlo.
5. Separar tipo por prefijo (`PR`, `PO`, etc.) de grupo de aparición (`general`, `procedimientos`). No asumir que todas las referencias `PR-` están en subsección Procedimientos.
6. Las actualizaciones deben ser incrementales por hash SHA-256, idempotentes y transaccionales **por documento**. Una falla de lectura/parsing no debe borrar las referencias vigentes.
7. Distinguir entre la relación lógica única (origen, código destino) y sus ocurrencias/evidencias (página, tabla, párrafo, sección). Los duplicados no crean aristas múltiples.
8. No declarar un documento “sin referencias” si no se pudo identificar con suficiente certeza la sección REFERENCIAS. Registrar advertencia y preservar el estado anterior.
9. Registrar documentos sin sección REFERENCIAS, códigos inválidos, referencias no resueltas, duplicados y posibles autorreferencias.
10. Análisis de impacto = **posibles documentos a revisar**, no certeza de necesidad de modificación.
11. **Un solo grafo, organizado por norma**: cada carpeta de primer nivel del directorio de documentos es una **norma** (`documents.norma`), no un grafo aparte; hay un único grafo y las referencias e impacto cruzan normas. El código es único **dentro** de cada norma (`UNIQUE(norma, code)`): el mismo código en dos normas son documentos distintos. Resolución de `A (norma N) -> C`: (1) el documento C de la norma N, si existe; (2) si no, el de la única otra norma que lo tenga (referencia cruzada); (3) si está en varias otras normas, queda pendiente y se informa `ambiguous_reference`. La resolución se recalcula por código cada vez que un documento con ese código aparece, se reactiva, se da de baja o se reemplaza. Los archivos sueltos en la raíz se informan y no se procesan.
12. **Varias ediciones del mismo código en una norma**: copias idénticas (mismo SHA-256) se reconocen como copia; vigente = mayor versión siempre que ninguna versión menor sea más reciente por fecha de modificación (a igual versión, PDF antes que DOCX); si versión y fecha no coinciden, no publicar ninguna y emitir `ambiguous_editions`. Prioridad de formato: PDF, DOCX, XLSX.
13. **Planillas Excel** (`.xlsx`, `.xlsm`, `.xls`): se identifican por nombre de archivo (o propiedad `Referencia` en XLSX/XLSM), quedan como nodos con estado `not_applicable` y pueden ser citadas; no se analiza su contenido. Prioridad de formato en ediciones: PDF > DOCX > XLSX > XLSM > XLS.
14. **Log de cada corrida**: toda ingesta (también `ingest-file` y `--dry-run`) escribe un archivo en `ISO_LOG_DIR` (`ingest-NNNNN-fecha.log`) con inicio, escaneo, una línea por documento (acción, estado, referencias, ocurrencias), referencias duplicadas, incidencias, errores con traceback, re-resoluciones y un resumen con totales; los contadores también quedan en `ingestion_runs`. Al terminar cada corrida se depuran los logs viejos (`ISO_LOG_KEEP`, `ISO_LOG_MAX_AGE_DAYS`), nunca el de la corrida en curso.

## Estructura de proyecto
```text
iso-trazabilidad/
  CLAUDE.md
  .claude/skills/iso-trazabilidad/SKILL.md
  backend/app/{api,models,schemas,services,ingestion,db}/
  backend/app/cli.py
  backend/tests/
  backend/migrations/
  frontend/src/{api,components,pages,types}/
  data/documents/
  data/iso.db
  docs/{architecture,data-model,api}.md
  .env.example
  pyproject.toml
```

## Modelo de datos mínimo
- `documents`: id, norma, code, UNIQUE(norma, code), title, file_path, file_format (pdf/docx/xlsx/xlsm/xls), sha256, version (opcional), extraction_status, updated_at.
- `document_references`: id, source_document_id, target_code, target_document_id NULL, group_name, UNIQUE(source_document_id, target_code). Guardar grupo predominante, y en ocurrencias los grupos observados si difieren.
- `reference_occurrences`: id, reference_id, group_name, page_number NULL, paragraph_index NULL, table_index NULL, evidence_excerpt NULL.
- `ingestion_runs`: id, start_at, end_at, status, processed_count, skipped_count, error_count, references_count, occurrences_count, duplicate_references_count, unresolved_count, log_path.
Usar claves externas e índices sobre code, target_code y source_document_id. Resolver referencias previamente pendientes cuando se incorpora su documento destino (en cualquier norma, según la regla 11).

## API y CLI esperadas
- CLI: `iso-trace db init`, `iso-trace ingest PATH [--incremental] [-v]`, `iso-trace ingest-file PATH`, `iso-trace validate`, `iso-trace impact CODE --norma N --depth N`, `iso-trace graph list` (totales por norma), `iso-trace graph export --format graphml` (un archivo con el grafo completo), `iso-trace runs list|show ID`.
- API: `GET /api/normas`, `GET /api/documents?query=&norma=`, `GET /api/documents/{code}`, `GET /api/documents/{code}/references`, `GET /api/documents/{code}/impact?depth=2`, `GET /api/documents/{code}/dependencies?depth=1`, `GET /api/graph?depth=2&code=...`, `GET /api/graph/full`, `GET /api/quality/issues`. Las rutas por documento llevan `norma=` (obligatorio si el código es documento en más de una norma: 409 `norma_required`).
- Respuestas JSON tipadas con Pydantic. Paginación en listados, manejo de errores y profundidad máxima configurable.

## Frontend
- Búsqueda por código y título organizada por norma y nombre, detalle documental, listas separadas de referencias salientes y entrantes, análisis de impacto directo/indirecto, grafo interactivo por vecindad, panel de incidencias.
- **Documento a modificar** (`/modify`): lista de los documentos que cita (directos; con más profundidad, indirectos) y los mismos resaltados sobre el grafo completo, con cada norma como recuadro y el resto atenuado. Un interruptor (`citers=1`) agrega quienes lo citan (posibles documentos a revisar), en lista y en otro color. Layout fcose (calidad completa hasta 400 nodos, `draft` por encima) con posiciones cacheadas por `graph_version`.
- Cytoscape.js con flechas orientadas según la semántica `origen -> citado`. Diferenciar referencias no resueltas.
- Por defecto, solicitar subgrafos de vecindad. El grafo completo se carga solo en la vista de documento a modificar, acotado por `ISO_GRAPH_FULL_MAX_NODES`.

## Calidad y seguridad
- Type hints, funciones pequeñas, responsabilidades separadas; rutas a documentos y base configurables por entorno; no hardcodear secretos.
- Usar ORM y queries parametrizadas; sanitizar rutas y restringir acceso al directorio configurado de documentos.
- Pruebas unitarias (extractor, normalizador, grafo), integración (SQLite, API, CLI) y frontend. Fixtures DOCX/PDF sintéticos; jamás registrar documentos internos en Git.
- Antes de implementar una fase: describir el plan, supuestos y criterios de aceptación. Ejecutar tests y lint; no afirmar que pasan si no se ejecutaron.
- El archivo `.claude/skills/iso-trazabilidad/SKILL.md` define el contrato detallado del extractor. Leerlo antes de modificar el pipeline documental.

## Etapas recomendadas
1. Esquema SQLite + migraciones + fixtures + extracción validada.
2. Ingesta CLI completa e incremental + resolución de códigos pendientes.
3. Servicio NetworkX + API REST.
4. React + Cytoscape.js + pruebas end-to-end del flujo.
