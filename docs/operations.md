# ISO Trace — Operación

Guía para instalar, cargar los documentos, mantener la base al día e interpretar las incidencias.

## Instalación

Requisitos: Python 3.13 con [uv](https://docs.astral.sh/uv/) y Node.js 22 o posterior.

```bash
uv sync                      # backend
cd frontend && npm ci        # interfaz
cp .env.example .env         # y ajustar
```

| Variable | Por defecto | Uso |
|---|---|---|
| `ISO_DATABASE_URL` | `sqlite:///data/iso.db` | Base SQLite. **En un disco local**: WAL no funciona bien en carpetas de red |
| `ISO_DOCUMENTS_DIR` | `data/documents` | Raíz de documentos; no se lee nada fuera de ella |
| `ISO_MAX_DEPTH` / `ISO_DEFAULT_DEPTH` | `10` / `2` | Profundidad del impacto y del grafo |
| `ISO_GRAPH_MAX_NODES` | `300` | Tope de nodos de un subgrafo |
| `ISO_GRAPH_FULL_MAX_NODES` | `3000` | Tope de nodos del grafo completo (vista "Documento a modificar") |
| `ISO_LOG_DIR` | `data/logs` | Carpeta de los logs de ingesta (un archivo por corrida). Vacía = sin archivo |
| `ISO_LOG_LEVEL` | `INFO` | Nivel mínimo del log de ingesta |
| `ISO_LOG_KEEP` | `200` | Logs a conservar: al terminar cada corrida se borran los más viejos (0 = sin límite) |
| `ISO_LOG_MAX_AGE_DAYS` | `0` | Antigüedad máxima de los logs en días (0 = sin límite) |
| `ISO_API_HOST` / `ISO_API_PORT` | `127.0.0.1` / `8000` | Dónde escucha la API |
| `ISO_CORS_ORIGINS` | `http://localhost:5173` | Orígenes del frontend |
| `ISO_EXTRACTION_CONFIG` | — | TOML opcional con alias de encabezados, terminadores y subgrupos |

## Organización de los documentos

```text
data/documents/
  SGSA ISO 20000/          ← norma "SGSA ISO 20000"
    08 - Operación/...     ← las subcarpetas son libres
  SGSI ISO 27001/          ← norma "SGSI ISO 27001"
  suelto.pdf               ← no pertenece a ninguna norma: se informa y no se procesa
```

- Hay **un solo grafo**: cada carpeta de primer nivel es una norma, que organiza los documentos, y las referencias pueden cruzar de una norma a otra.
- El código es único dentro de cada norma: el mismo código en dos normas son dos documentos distintos. Una cita se resuelve primero en la norma de quien cita; si allí no existe, en la única otra norma que lo tenga. Si lo tienen varias otras normas, la cita queda pendiente y se informa `ambiguous_reference`.
- Nombre de archivo esperado: `CODIGO-VV Título.ext` (por ejemplo `PO-SGS-400-01 Política.pdf`). El código también se lee de la portada (`Referencia/Versión : CODIGO/VV`), del encabezado de página o de las propiedades del documento. Si las fuentes se contradicen, el documento no se publica (`source_code_conflict`).
- Se procesan `.pdf`, `.docx`, `.xlsx`, `.xlsm` y `.xls`; las demás extensiones (`.dotx`, `.pptx`, `Thumbs.db`…) se cuentan y se omiten.
- Las planillas se identifican por el nombre (`RG-SGC-100-01 Lista maestra.xlsx`) y quedan como documentos que se pueden citar; no se analiza su contenido. Del `.xls` (formato anterior a 2007) solo se usa el nombre.

## Operación diaria

```bash
uv run iso-trace db init                 # una vez, y después de actualizar el sistema
uv run iso-trace ingest                  # primera carga completa
uv run iso-trace ingest --incremental    # después: solo lo nuevo o modificado
uv run iso-trace validate                # resumen de calidad de todo el grafo
uv run iso-trace api serve               # API en 127.0.0.1:8000
cd frontend && npm run dev               # interfaz en 127.0.0.1:5173
```

| Situación | Comando |
|---|---|
| Ver qué se extraería de un archivo, sin tocar la base | `iso-trace extract RUTA --json` |
| Reprocesar un archivo aunque no haya cambiado | `iso-trace ingest-file RUTA` |
| El código no se identifica bien | `iso-trace ingest-file RUTA --code PO-SGS-400` |
| Reintentar los que fallaron | `iso-trace ingest --incremental --retry-failed` |
| Simular una corrida | `iso-trace ingest --dry-run` |
| Una corrida quedó colgada | `iso-trace ingest --force-unlock` (se libera sola después de 6 h) |
| Borrar definitivamente los documentos faltantes | `iso-trace prune --missing` (pide confirmación; `--yes` para omitirla) |
| Ver el detalle de una ingesta | `iso-trace runs show N` (incluye la ruta del log) o abrir el archivo en `ISO_LOG_DIR` |
| Seguir una ingesta en pantalla | `iso-trace ingest -v` (cada evento del log también en consola) |
| Impacto para control de cambios | `iso-trace impact CODIGO --norma N --depth 3 --format csv -o impacto.csv` (`--norma` solo si el código está en varias normas) |
| Totales por norma | `iso-trace graph list` |
| Exportar el grafo | `iso-trace graph export --format graphml -o export/grafo.graphml` (un solo archivo, con la norma de cada nodo) |

La ingesta es **idempotente**: repetirla sin cambios no modifica nada. Un archivo modificado solo cambia sus propias relaciones. Si un archivo no se puede leer, o su sección REFERENCIAS no se delimita con certeza, sus referencias anteriores se conservan y la interfaz avisa que pueden estar desactualizadas.

La detección de faltantes solo ocurre al ingerir la raíz completa (`iso-trace ingest`, con o sin `--incremental`), nunca con `ingest-file` ni con una subcarpeta.

`--incremental` también vuelve a procesar los archivos sin cambios cuando cambiaron las reglas de extracción: una actualización del extractor o del TOML de `ISO_EXTRACTION_CONFIG`. Cada documento guarda la huella de las reglas con que se procesó; el log lo informa como `reglas_cambiadas`. Por eso, la primera corrida incremental después de actualizar el sistema puede tardar lo mismo que una completa.

## Mantener la base al día automáticamente

Lo recomendado es **programar la ingesta incremental de la raíz completa**, no vigilar la carpeta:

- **Nada que reprocesar en cadena:** un documento nuevo conecta solo las citas que lo esperaban, en cualquier norma (`re_resolucion` en el log), sin reprocesar a quienes lo citan. Un documento modificado solo reemplaza sus propias referencias, y el impacto se calcula al consultar. La API ve los cambios sin reiniciarse.
- **Carpetas de red y OneDrive:** los avisos de cambios en carpetas de red y OneDrive se pierden o llegan con archivos a medio copiar (`~$*.docx`). Un barrido periódico por hash no depende de ellos.
- **Bajas y ediciones:** solo la raíz completa detecta los archivos borrados, y varias ediciones copiadas juntas se resuelven en la misma corrida.

En Windows, desde la carpeta del proyecto:

```powershell
.\scripts
egister-ingest-task.ps1                    # cada 30 min + reintento los domingos 03:15
.\scripts
egister-ingest-task.ps1 -IntervalMinutes 60 -NoWeeklyRetry
.\scripts
egister-ingest-task.ps1 -Unregister        # quitar las tareas
```

Crea en la carpeta **ISO Trace** del Programador de tareas una tarea que ejecuta `uv run iso-trace ingest --incremental`, y otra semanal con `--retry-failed`. Las dos corren desde la carpeta del proyecto, así que usan su `.env`.

- **Corridas superpuestas:** si una corrida sigue en curso, no se inicia otra. La base además lo impide con su propio bloqueo.
- **Ventana y sesión:** las tareas corren sin ventana y solo mientras el usuario tiene la sesión iniciada, que es lo que necesitan OneDrive y las unidades de red mapeadas. Para que corran sin sesión, cambiar la tarea a "Ejecutar tanto si el usuario inició sesión como si no" y usar en `ISO_DOCUMENTS_DIR` una ruta UNC (`\\servidor\recurso`), no una letra de unidad.
- **Resultado de cada corrida:** el "Último resultado" del Programador de tareas no sirve, porque siempre es 0. El resultado real está en `iso-trace runs list` (`completed_with_errors`, `failed`) y en el log de `ISO_LOG_DIR`.
- **Algo urgente:** no hace falta esperar a la tarea. Ejecutar `iso-trace ingest --incremental` a mano, o `iso-trace ingest-file RUTA` para un solo archivo.

Precauciones:

- **La base en disco local:** `ISO_DATABASE_URL` va en un disco local, nunca en el recurso de red ni en OneDrive.
- **OneDrive con "Archivos a petición":** calcular el hash descarga cada archivo. Marcar la carpeta de documentos como "Mantener siempre en este dispositivo".
- **Carpeta de red:** cada corrida lee todos los archivos para calcular el hash. Con cientos de documentos es aceptable. Una corrida sin cambios sobre 500 documentos locales tarda menos de un segundo.

## Log de cada ingesta

Cada corrida (también `ingest-file` y `--dry-run`) escribe `ISO_LOG_DIR/ingest-NNNNN-AAAAMMDD-HHMMSS.log` (las simulaciones, `ingest-simulacion-…`). Cada línea es `fecha nivel evento clave=valor`, para leerla o filtrarla con `grep`:

| Evento | Contenido |
|---|---|
| `inicio` | Corrida, modo, ruta, opciones y `huella` (los primeros 12 caracteres de la huella de extracción) |
| `escaneo` | Archivos por formato y por norma, no soportados, sueltos en la raíz (`archivo_sin_norma`, uno por archivo) |
| `sin_cambios` | Archivos omitidos en modo incremental |
| `reglas_cambiadas` | Archivo sin cambios que se vuelve a procesar porque cambiaron las reglas de extracción |
| `extraido` | Código, versión, estado, referencias y ocurrencias leídas de cada archivo |
| `documento` | Acción (`created`, `updated`, `superseded`, `blocked`, `unpublished`, `error`), estado y referencias: en la misma norma, a otra norma, pendientes, ambiguas, nuevas y eliminadas. Nivel ERROR si el archivo falló |
| `referencia_duplicada` | WARNING: un código citado más de una vez en la misma sección, con las páginas |
| `incidencia` | Cada incidencia del archivo con tipo, severidad y mensaje (duplicados de archivos, ediciones, sección, códigos inválidos…) |
| `error_extraccion`, `error_guardado`, `corrida_fallida` | ERROR con el traceback completo |
| `re_resolucion` | Una cita que cambió de destino (de pendiente a resuelta, a la copia de la propia norma, o a ambigua) |
| `faltante` | Documento cuyo archivo desapareció |
| `resumen` | Duración, procesados, nuevos, actualizados, errores, avisos, faltantes, referencias, ocurrencias, duplicadas y el estado del grafo al terminar (`grafo_pendientes`, `grafo_otra_norma`, `grafo_ambiguas`) |

Los totales también quedan en la base (`iso-trace runs list|show`, pestaña **Ingestas** de Calidad). Los logs contienen nombres de documentos internos: `data/` está fuera de Git; si `ISO_LOG_DIR` apunta a otro lugar, protegerlo igual.

Al terminar cada corrida se borran los logs más viejos: se conservan los últimos `ISO_LOG_KEEP` (200) y ninguno de más de `ISO_LOG_MAX_AGE_DAYS` días (si se configura). El de la corrida en curso nunca se borra, y la depuración queda registrada en él (`logs_depurados`). Los totales de las corridas siguen en la base; `iso-trace runs show` avisa si el log ya no existe.

## Incidencias

Se consultan con `iso-trace issues list`, `iso-trace validate` o la pantalla **Calidad**.

### De la ingesta (almacenadas)

| Tipo | Severidad | Qué hacer |
|---|---|---|
| `ambiguous_editions` | error | Hay varias ediciones del mismo código en la misma norma y la versión contradice la fecha: dejar solo la vigente en la carpeta o corregir los nombres |
| `source_code_conflict`, `source_code_missing`, `source_code_changed` | error | El código del nombre del archivo no coincide con la portada o no se encuentra. Corregir el nombre o la portada, o usar `ingest-file --code` |
| `read_error`, `encrypted`, `sync_error` | error | Archivo dañado, protegido con contraseña o error al guardar. Revisar el archivo y reintentar con `--retry-failed` |
| `requires_ocr` | advertencia | PDF escaneado: el MVP no hace OCR. Conseguir la versión con texto |
| `section_ambiguous`, `section_end_uncertain`, `unknown_subheading`, `bookmark_mismatch` | advertencia | No se pudo delimitar REFERENCIAS con certeza. Revisar con `extract --json`; si la plantilla usa otros títulos, agregarlos en `ISO_EXTRACTION_CONFIG` |
| `section_lost` | advertencia | Un documento que tenía referencias ya no tiene sección: probablemente un error de edición. Se conservan las anteriores |
| `invalid_reference_candidate`, `unbracketed_code` | advertencia | Parece un código mal escrito dentro de REFERENCIAS; no se crea relación |
| `self_reference` | advertencia | El documento se cita a sí mismo; no se crea arista |
| `version_mismatch`, `textbox_content`, `reading_order_ambiguous` | advertencia | Revisar el documento; la extracción continuó |
| `file_missing` | advertencia | El archivo desapareció: el documento queda inactivo y sus citas entrantes pasan a la copia de otra norma (si es la única) o quedan pendientes |
| `duplicate_copy`, `superseded_version`, `alternate_format` | info | Copias, versiones anteriores o el mismo documento en otro formato; se publica solo la vigente |
| `duplicate_in_section`, `mixed_groups`, `unbracketed_reference`, `file_moved` | info | Informativas |

### Calculadas sobre el estado actual (derivadas)

| Tipo | Severidad | Significado |
|---|---|---|
| `ambiguous_reference` | advertencia | Se cita un código que no está en la norma de quien cita y existe en varias otras normas: no se puede saber a cuál se refiere. Renombrar o mover el documento, o corregir la cita |
| `cited_title_mismatch` | advertencia | Se cita con un título distinto del real: posible referencia desactualizada |
| `duplicate_across_normas` | info | El mismo archivo (mismo SHA-256) está en varias normas, por ejemplo un manual integrado: al modificarlo hay que actualizar todas las copias, o dejar una sola y citarla desde las demás normas |
| `inconsistent_cited_titles` | advertencia | Dos documentos citan el mismo código con títulos distintos |
| `reference_to_inactive` | advertencia | Se cita un documento cuyo archivo ya no existe |
| `unresolved_similar_code` | advertencia | Código sin documento parecido a uno existente (`RG-SGSA-928` → `LC-SGSA-928`). Es solo una sugerencia; nunca se corrige automáticamente |
| `cycle` | info | Referencias circulares |
| `isolated_document` | info | Ni cita ni es citado |

Los documentos sin sección REFERENCIAS (`no_section`) y las planillas (`not_applicable`) no generan incidencia: se cuentan en cada corrida y se filtran por estado en la búsqueda.

## Medir la calidad de la extracción (set de referencia)

```bash
uv run iso-trace golden draft samples -o golden/borrador.csv   # lo que extrae hoy el sistema
# Revisar el borrador contra los documentos y guardarlo como golden/expected.csv.
uv run iso-trace golden evaluate golden/expected.csv --samples samples
ISO_REAL_SAMPLES_DIR=samples ISO_GOLDEN_SET=golden/expected.csv uv run pytest -m real_docs
```

- **Formato del CSV:** UTF-8, separador `;`, columnas `file;target_code;group;note`, una fila por relación esperada. Un `target_code` vacío declara un documento sin referencias.
- **Filas marcadas `REVISAR`:** el sistema no publicaría nada para ese archivo. Hay que anotarlas a mano.
- **Umbrales:** el objetivo del MVP es precisión ≥ 99 % y recall ≥ 98 %. `evaluate` sale con código 1 si no se alcanzan.

> El borrador **no** es un set de referencia: evaluarlo sin corregir mide la extracción contra sí misma.

## Copia de seguridad

La base es un solo archivo. Con WAL activo no alcanza con copiar `iso.db`, porque los cambios recientes pueden estar en `iso.db-wal`. Para obtener una copia consistente, sin una ingesta en curso:

```bash
mkdir -p backup   # VACUUM INTO no crea la carpeta ni sobrescribe un archivo existente
uv run python -c "import sqlite3; sqlite3.connect('data/iso.db').execute(\"VACUUM INTO 'backup/iso-2026-10-24.db'\")"
```

Para restaurar, reemplazar `data/iso.db` por la copia (con la API detenida) y ejecutar `iso-trace db init` para aplicar las migraciones que falten. Como todo se reconstruye desde los documentos, otra opción siempre válida es borrar la base y repetir `db init` + `ingest`; solo se pierde el historial de corridas e incidencias.

## Seguridad y confidencialidad

- **Red:** la API no tiene autenticación en el MVP y escucha solo en `127.0.0.1`. Para exponerla en una red, ponerla detrás de un proxy inverso con autenticación y TLS, y ajustar `ISO_CORS_ORIGINS`.
- **Archivos:** la API nunca entrega los documentos originales; solo metadatos y extractos de evidencia, que también son confidenciales.
- **Git:** `samples/`, `data/` (incluidos los logs), `golden/` y los `*.db` están en `.gitignore`. No versionar documentos internos, logs ni sets de referencia.

## Rendimiento de referencia

Con 500 documentos sintéticos (`uv run pytest -m benchmark -s`), en la estación de desarrollo:

| Medición | Resultado | Objetivo |
|---|---|---|
| Ingesta completa | 9,4 s (19 ms por documento) | < 5 min |
| Incremental sin cambios | 0,8 s | < 30 s |
| Impacto, profundidad 3, p95 | 14 ms | < 200 ms |
| Subgrafo, profundidad 2, p95 | 17 ms | < 200 ms |

Los documentos reales son más largos que los sintéticos: la extracción de las 118 muestras de `samples/` tarda unos 12 s.
