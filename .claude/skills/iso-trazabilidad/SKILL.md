---
name: iso-trazabilidad
description: Diseñar, implementar, depurar y probar extracción de referencias ISO en PDF/DOCX (y planillas Excel citables), ingesta incremental SQLite con log por corrida, grafo único NetworkX organizado por norma y análisis de impacto documental para ISO Trace.
---

# Skill: trazabilidad documental ISO

## Cuándo aplicar
Usar al crear o modificar lectores PDF/DOCX/planillas, detector de sección REFERENCIAS, parser de códigos, sincronizador SQLite, consultas NetworkX, API o visualización de dependencias. Respetar también `CLAUDE.md`.

## Contrato de extracción
Entrada: ruta de un PDF o DOCX, código del documento origen provisto o identificado de manera validada, y configuración de encabezados.
Salida estructurada: código origen, estado de extracción, lista de códigos de destino **únicos**, grupo de aparición y ocurrencias/evidencia, más incidencias detectadas.

### 1. Lectura
- PDF con texto: PyMuPDF, recorriendo páginas en orden; preservar número de página. Reconocer la posibilidad de orden de lectura defectuoso en columnas o tablas; emitir advertencia en casos ambiguos.
- DOCX: python-docx; leer párrafos y tablas en su orden documental (también celdas), no simplemente concatenar primero todos los párrafos y luego todas las tablas. Registrar párrafo/tabla/celda cuando sea viable.
- PDF escaneado o sin texto usable: `requires_ocr`, sin modificar referencias existentes.
- XLSX: openpyxl en modo solo lectura, **solo identidad** (propiedades del libro y `docProps/custom.xml`). No se busca sección REFERENCIAS ni se analizan las celdas, aunque contengan códigos. Con código identificado (nombre `CODE-VV Título.xlsx`, o nombre + propiedad `Referencia`) el estado es `not_applicable`: el documento es un nodo que puede ser citado. Sin código, `source_code_unresolved`. Protegido con contraseña (contenedor OLE): `encrypted`; ZIP inválido: `read_error`. XLSM: igual que XLSX. XLS binario (anterior a 2007): no se abre; se verifica la firma OLE (si no la tiene, `read_error`) y la identidad sale solo del nombre.
- Normalizar Unicode (NFKC), guiones Unicode equivalentes, espacios y saltos de línea, manteniendo el texto bruto disponible para auditoría.

### 2. Delimitación de la sección
- Detectar título de sección `REFERENCIAS` como encabezado o línea independiente, sin importar caso, tildes o espacios; no confundir una mención en texto corriente con el encabezado.
- La subsección `Procedimientos` cambia `group_name` a `procedimientos` y **no** termina REFERENCIAS.
- Al entrar a REFERENCIAS usar grupo `general` hasta subsección explícita.
- Terminar al siguiente encabezado del mismo nivel o superior o según lista configurable de encabezados finales (p. ej. ANEXOS, CONTROL DE CAMBIOS, APROBACIONES). Evitar reglas globales demasiado agresivas: si el límite es ambiguo, reportarlo.
- Si no aparece sección o el límite no es seguro, `needs_review`; no sincronizar con un conjunto de referencias vacío por defecto.
- Permitir secciones representadas en tablas y encabezados divididos entre spans/run de Word.

### 3. Identificación de códigos
Patrón base, configurable; exigir corchetes para la primera versión:

```python
import re
REFERENCE_PATTERN = re.compile(
    r"\[\s*([A-Z]{2,4}-[A-Z0-9]{2,5}-\d{3,5})\s*\]",
    re.IGNORECASE,
)
```

- Excepción (decidida el 2026-10-23 con documentos reales): **dentro de REFERENCIAS** también cuenta un código válido sin corchetes que ocupa una celda entera o empieza la línea (p. ej. tabla `ES-SGG-003 | Especificaciones…`). Se registra como `unbracketed_reference` (info). Fuera de la sección nunca se acepta.
- Normalizar código a mayúsculas y quitar espacios internos alrededor del código; considerar variantes de guion Unicode.
- Identificar `document_type` por prefijo (antes del primer `-`) sin equipararlo con el grupo de sección.
- No generar relaciones a partir de cualquier código que aparezca fuera de REFERENCIAS.
- Reunir múltiples ocurrencias del mismo código en **una** referencia lógica por par `(source_document, target_code)`; preservar evidencia y detectar si aparece en grupos diferentes.
- Si un texto parece código pero no coincide, emitir `invalid_reference_candidate` para revisión, sin inventar normalización.

### 4. Reconciliación e ingesta
- Calcular SHA-256 del archivo; omitir los no modificados en modo incremental, salvo que se hayan procesado con otra huella de extracción (`ingestion/fingerprint.py`: código de `app/ingestion` + configuración). Todo cambio en el paquete `app/ingestion` cambia la huella y reprocesa todo en la siguiente corrida incremental.
- Validar identificación del código fuente: metadata/nombre de archivo bajo convención; si falta o entra en conflicto, no publicar relaciones automáticamente.
- Primero parsear y validar; **luego** abrir transacción: upsert documento, reemplazar su conjunto de referencias/ocurrencias, actualizar hash y estado; rollback ante cualquier error.
- Si una referencia sale del archivo actualizado, eliminar solamente la relación correspondiente a ese origen.
- La carpeta de primer nivel es la **norma** del documento; el código es único dentro de la norma.
- Resolver `target_document_id` a partir de `target_code` en todo el grafo: primero la norma del documento que cita; si no está, la única otra norma que lo tenga; si está en varias otras, dejarlo pendiente (`ambiguous_reference`, derivada). Mantener el código si no existe. Al ingresar, reactivar, dar de baja o reemplazar un documento, recalcular la resolución de todas las referencias a su código (`services/resolution.py`).
- Log de ejecución por corrida (`services/run_log.py`, un archivo en `ISO_LOG_DIR`): inicio y opciones, escaneo (por formato y por norma, sueltos en la raíz), una línea por documento con acción, estado, referencias (misma norma / otra norma / pendientes / ambiguas) y ocurrencias, referencias duplicadas en la sección, cada incidencia con su severidad, errores con traceback, re-resoluciones, faltantes y un resumen con totales de la corrida y del grafo. Al terminar se depuran los logs viejos (`prune_logs`: `ISO_LOG_KEEP`, `ISO_LOG_MAX_AGE_DAYS`), nunca el de la corrida en curso. No borrar referencias existentes si falla la extracción, si falta la sección o si el PDF requiere OCR.

### 5. Semántica del grafo
- Crear un único `nx.DiGraph()` desde SQLite con todas las normas; nodo de documento = `"norma/código"`, nodo virtual de un citado sin documento = el código; arista `A -> B` = A cita B, con `cross_norma` si une normas distintas.
- Documentos faltantes: opcionalmente nodos virtuales con `resolved=false` para visualización, sin simular archivos presentes.
- Dependencias **salientes** de A: documentos citados por A (`successors(A)`).
- Impacto si cambia B: documentos que citan B (`predecessors(B)`) y predecesores transitivos, con recorrido BFS inverso hasta `depth` y protección contra ciclos.
- Devolver distancia mínima (1=directo, >1=indirecto), códigos y rutas de evidencia opcionales; no incluir el nodo raíz en sus propios resultados aunque exista un ciclo.
- No prometer “documentos obligatoriamente afectados”: devolver “potenciales candidatos a revisión”.

## Caso de aceptación: ejemplo de referencias
Texto de prueba dentro de `REFERENCIAS`, seguido de subsección `Procedimientos`:

```text
REFERENCIAS
[PO-SGS-400]
[PO-SGS-615]
[ES-SGC-001]
[AL-SGS-401]
[AL-SGSA-911]
[PC-SGSA-914]
[LC-SGSA-915]
[ES-SGSA-919]
[AX-SGC-002]
[ES-SGS-404]
[ES-SGS-407]
[ES-SGS-416]
[ES-SGS-525]
[ES-SGS-546]
[ES-SGG-547]
[ES-SGG-597]
[ES-COM-001]
[ES-SGC-002]
[ES-SGC-100]
[ES-AFP-001]
[ES-SOP-001]
[LC-SGG-050]
[ES-SGC-210]
[AX-SGC-001]
[FC-SGC-100]
[LC-SGC-500]
[LC-SGS-849]
Procedimientos
[PR-SGG-000]
[PR-SGG-101]
[PR-SGG-004]
[PR-SGG-005]
[PR-SGC-006]
[PR-SGG-007]
[PR-SGG-101]
[PR-SGG-102]
[PR-SGS-402]
```

Resultados esperados:
- 36 apariciones totales, 35 códigos únicos.
- 27 códigos en grupo general; 8 códigos únicos en grupo procedimientos.
- `PR-SGG-101` ocurre 2 veces, se almacena como 1 relación lógica y 2 evidencias.
- No hay relaciones extraídas de secciones anteriores o posteriores.

## Casos de prueba obligatorios
1. DOCX con sección en tabla; PDF con salto de página dentro de REFERENCIAS.
2. Variantes de mayúsculas, espacios, Unicode y guiones.
3. Código duplicado, referencias pendientes, autorreferencia, relaciones cíclicas.
4. Cambio incremental que quita una referencia; documento sin cambios no reprocesado.
5. Documento sin sección; título ambiguo; PDF escaneado: preservar referencias anteriores.
6. Impacto: si A->B y C->A, al modificar B aparecen A (profundidad 1) y C (profundidad 2).
7. Un código aparece fuera de REFERENCIAS y no debe extraerse.
8. Prueba de rollback de transacción cuando falla la persistencia.

## Contrato de interfaz recomendado
Proveer `GET /api/documents/{code}/references` con `outgoing`, `incoming`, `unresolved`; `GET /api/documents/{code}/impact?depth=N` con niveles, y `GET /api/graph?code=...&depth=N` con nodos/aristas para Cytoscape.js. API y UI deben respetar el sentido real de las flechas.

## Criterios de finalización
Código tipado, format/lint y tests ejecutados; casos problemáticos registrados; documentación del algoritmo, límites de PDF/DOCX y comandos reproducibles. No incorporar inferencia probabilística sin necesidad comprobada.
