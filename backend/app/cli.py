"""CLI ``iso-trace``: ingesta y mantenimiento (la aplicación web es solo de consulta)."""

import json
import logging
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import migrate
from app.db.session import get_engine, session_scope
from app.ingestion.config import load_extraction_config
from app.ingestion.extractor import extract_document
from app.ingestion.readers import detect_format
from app.ingestion.types import ExtractionResult
from app.models.enums import ExtractionStatus
from app.services import catalog, golden, queries
from app.services import graph as graph_service
from app.services.impact import (
    DepthOutOfRangeError,
    TraversalResult,
    impact_to_csv,
    impacted_by,
)
from app.services.ingest import (
    IngestionLockedError,
    IngestionService,
    IngestOptions,
    IngestReport,
    UnsupportedFileError,
)
from app.services.scanner import PathOutsideRootError, is_ignored
from app.services.validation import validate as validate_database

app = typer.Typer(help="ISO Trace: trazabilidad de referencias entre documentos ISO.")
db_app = typer.Typer(help="Administración de la base de datos.", no_args_is_help=True)
issues_app = typer.Typer(help="Incidencias de calidad.", no_args_is_help=True)
runs_app = typer.Typer(help="Historial de ingestas.", no_args_is_help=True)
graph_app = typer.Typer(
    help="Grafo de trazabilidad único (cada carpeta raíz es una norma).", no_args_is_help=True
)
app.add_typer(db_app, name="db")
app.add_typer(graph_app, name="graph")
api_app = typer.Typer(help="API REST de consulta.", no_args_is_help=True)
app.add_typer(api_app, name="api")
app.add_typer(issues_app, name="issues")
app.add_typer(runs_app, name="runs")
golden_app = typer.Typer(
    help="Set de referencia anotado a mano: precisión y recall.", no_args_is_help=True
)
app.add_typer(golden_app, name="golden")


@app.callback()
def main() -> None:
    """ISO Trace: trazabilidad de referencias entre documentos ISO."""
    _use_utf8_output()


def _use_utf8_output() -> None:
    """En Windows, la salida redirigida usa cp1252 y falla con "→" o "≥": se pasa a UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        reconfigure = getattr(stream, "reconfigure", None)
        if encoding != "utf8" and reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


@db_app.command("init")
def db_init() -> None:
    """Crea la base o la migra a la última versión del esquema (idempotente)."""
    url = get_settings().database_url
    before = migrate.current_revision(url)
    migrate.upgrade(url)
    after = migrate.current_revision(url)
    if before == after:
        typer.echo(f"La base ya está en la versión {after}: {url}")
    else:
        typer.echo(f"Base migrada de {before or 'vacía'} a {after}: {url}")


@app.command("extract")
def extract(
    path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, readable=True, help="PDF, DOCX o XLSX")
    ],
    as_json: Annotated[bool, typer.Option("--json", help="Salida JSON completa")] = False,
    code: Annotated[
        str | None, typer.Option("--code", help="Código del documento (si no se identifica)")
    ] = None,
) -> None:
    """Muestra lo que se extraería de un archivo, sin tocar la base de datos."""
    config = load_extraction_config(get_settings().extraction_config)
    result = extract_document(path, code_override=code, config=config)
    if as_json:
        payload = {**asdict(result), "occurrence_count": result.occurrence_count}
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_extraction(result)
    if result.status is ExtractionStatus.ERROR:
        raise typer.Exit(code=1)


def _print_extraction(result: ExtractionResult) -> None:
    typer.echo(f"Archivo:  {result.file_path}")
    typer.echo(f"Código:   {result.source_code or '(no identificado)'} ({result.code_source})")
    typer.echo(f"Versión:  {result.version or '-'}")
    typer.echo(f"Título:   {result.title or '-'}")
    typer.echo(f"Estado:   {result.status}")
    if result.section:
        typer.echo(
            f"Sección:  págs. {result.section.start_page}-{result.section.end_page}, "
            f"cerrada por {result.section.terminator or 'fin del documento'}"
        )
    groups = Counter(ref.group for ref in result.references)
    typer.echo(
        f"Referencias: {len(result.references)} únicas, {result.occurrence_count} apariciones "
        f"{dict(groups) if groups else ''}"
    )
    for ref in result.references:
        pages = sorted({o.page_number for o in ref.occurrences if o.page_number})
        extra = f" ×{len(ref.occurrences)}" if len(ref.occurrences) > 1 else ""
        typer.echo(
            f"  {ref.code:14} {ref.group:15} {ref.title_hint or '':55.55} págs. {pages}{extra}"
        )
    if result.issues:
        typer.echo("Incidencias:")
        for issue in result.issues:
            typer.echo(f"  [{issue.severity}] {issue.type}: {issue.message}")


# ----------------------------------------------------------------------------- ingesta


def _migrated_engine() -> Engine:
    url = get_settings().database_url
    if migrate.current_revision(url) != migrate.head_revision(url):
        typer.echo(
            "La base no está inicializada o está desactualizada: ejecutar 'iso-trace db init'"
        )
        raise typer.Exit(code=2)
    return get_engine(url)


def _service() -> IngestionService:
    settings = get_settings()
    return IngestionService(
        _migrated_engine(),
        settings.documents_dir,
        load_extraction_config(settings.extraction_config),
        log_dir=settings.log_dir,
        log_level=settings.log_level,
    )


def _echo_log_events(verbose: bool) -> None:
    """Con --verbose, cada evento del log de la corrida también se muestra en consola."""
    if not verbose:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
    logger = logging.getLogger("iso_trace.ingest")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _run_ingestion(single_file: bool, path: Path, options: IngestOptions, verbose: bool) -> None:
    _echo_log_events(verbose)
    service = _service()
    try:
        if single_file:
            report = service.ingest_file(path, options)
        else:
            report = service.ingest_path(path, options)
    except (PathOutsideRootError, UnsupportedFileError) as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=2) from exc
    except IngestionLockedError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=1) from exc
    _print_ingest_report(report, options)


@app.command("ingest")
def ingest(
    path: Annotated[
        Path | None, typer.Argument(help="Carpeta o archivo (por defecto ISO_DOCUMENTS_DIR)")
    ] = None,
    incremental: Annotated[
        bool, typer.Option("--incremental", help="Solo archivos nuevos o modificados")
    ] = False,
    retry_failed: Annotated[
        bool, typer.Option("--retry-failed", help="Con --incremental, reintenta los fallidos")
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Simula sin escribir")] = False,
    force_unlock: Annotated[
        bool, typer.Option("--force-unlock", help="Libera una ingesta anterior colgada")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Muestra en consola cada evento del log")
    ] = False,
) -> None:
    """Ingesta de un directorio. Marca como faltantes los documentos que ya no están."""
    options = IngestOptions(
        incremental=incremental,
        retry_failed=retry_failed,
        dry_run=dry_run,
        force_unlock=force_unlock,
    )
    _run_ingestion(False, path or get_settings().documents_dir, options, verbose)


@app.command("ingest-file")
def ingest_file(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="PDF, DOCX o XLSX")],
    code: Annotated[
        str | None, typer.Option("--code", help="Código del documento (si no se identifica)")
    ] = None,
    replace: Annotated[
        bool,
        typer.Option("--replace", help="Reemplaza al documento que hoy ocupa ese código o ruta"),
    ] = False,
    force_unlock: Annotated[bool, typer.Option("--force-unlock")] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Muestra en consola cada evento del log")
    ] = False,
) -> None:
    """Reprocesa un archivo aunque no haya cambiado."""
    options = IngestOptions(code_override=code, replace=replace, force_unlock=force_unlock)
    _run_ingestion(True, path, options, verbose)


def _print_ingest_report(report: IngestReport, options: IngestOptions) -> None:
    title = "Simulación" if options.dry_run else f"Ingesta {report.run_id} ({report.status})"
    typer.echo(f"{title} — modo {report.mode}")
    typer.echo(
        f"  nuevos {report.count('created')} · actualizados {report.count('updated')} · "
        f"sin cambios {report.count('skipped')} · con errores {report.error_count} · "
        f"faltantes {len(report.missing)} · formatos no soportados {report.unsupported_count} · "
        f"avisos {report.warning_count}"
    )
    typer.echo(
        f"  referencias {report.references_count} · apariciones {report.occurrences_count} · "
        f"duplicadas {report.duplicate_references_count} · pendientes {report.unresolved_count}"
    )
    for item in report.files:
        if item.action == "skipped":
            continue
        line = f"  {item.action:11} {item.code or '(sin código)':13} {item.status or '':22}"
        line += f" refs={item.references:<3} {item.rel_path}"
        if item.message:
            line += f"  — {item.message}"
        typer.echo(line)
    for label in report.missing:
        typer.echo(f"  faltante    {label}")
    if report.root_files:
        typer.echo(
            f"  Aviso: {len(report.root_files)} archivo(s) sueltos en la raíz no pertenecen a "
            "ninguna norma y no se procesaron (cada carpeta raíz es una norma):"
        )
        for rel_path in report.root_files:
            typer.echo(f"    {rel_path}")
    if report.log_path:
        typer.echo(f"  Log de la corrida: {report.log_path}")


# ----------------------------------------------------------------------------- consultas


@app.command("validate")
def validate(
    output: Annotated[str, typer.Option("--format", help="table o json")] = "table",
    strict: Annotated[
        bool, typer.Option("--strict", help="Código de salida 1 si hay errores")
    ] = False,
    check_hashes: Annotated[
        bool, typer.Option("--hashes/--no-hashes", help="Compara el hash de cada archivo")
    ] = True,
) -> None:
    """Valida referencias pendientes, incidencias abiertas y archivos en disco."""
    with session_scope(_migrated_engine()) as session:
        report = validate_database(session, get_settings().documents_dir, check_hashes=check_hashes)
    if output == "json":
        typer.echo(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        typer.echo(f"Referencias pendientes: {len(report.unresolved)} códigos")
        for code, sources in report.unresolved.items():
            typer.echo(f"  {code:14} citado por {', '.join(sources)}")
        for issue in report.derived:
            typer.echo(f"[{issue.severity}] {issue.type}: {issue.message}")
        typer.echo(f"Documentos a revisar: {len(report.attention)}")
        for item in report.attention:
            label = f"{item['norma']}/{item['code']}"
            typer.echo(f"  {label:30} {item['status']:22} {item['file_path']}")
        typer.echo(f"Referencias desactualizadas: {', '.join(report.stale_references) or '-'}")
        typer.echo(f"Archivos faltantes: {', '.join(report.missing_files) or '-'}")
        typer.echo(f"Archivos modificados sin reingestar: {', '.join(report.hash_drift) or '-'}")
        typer.echo("Incidencias abiertas:")
        for issue_type, counts in sorted(report.open_issues.items()):
            detail = ", ".join(f"{severity} {n}" for severity, n in counts.items())
            typer.echo(f"  {issue_type:28} {detail}")
    if strict and report.has_errors:
        raise typer.Exit(code=1)


@app.command("prune")
def prune(
    missing: Annotated[
        bool, typer.Option("--missing", help="Borra los documentos cuyo archivo desapareció")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="No pedir confirmación")] = False,
) -> None:
    """Purga definitiva de documentos inactivos (no se puede deshacer)."""
    if not missing:
        typer.echo("Indicar qué purgar: --missing")
        raise typer.Exit(code=2)
    engine = _migrated_engine()
    if not yes:
        typer.confirm(
            "Se borrarán definitivamente los documentos inactivos. ¿Continuar?", abort=True
        )
    with session_scope(engine) as session:
        codes = queries.prune_missing(session)
    typer.echo(f"Documentos borrados: {', '.join(codes) or 'ninguno'}")


@issues_app.command("list")
def issues_list(
    issue_type: Annotated[str | None, typer.Option("--type")] = None,
    severity: Annotated[str | None, typer.Option("--severity")] = None,
    include_closed: Annotated[bool, typer.Option("--all", help="Incluye las cerradas")] = False,
    limit: Annotated[int, typer.Option("--limit")] = 200,
) -> None:
    """Lista incidencias registradas durante la ingesta."""
    with session_scope(_migrated_engine()) as session:
        issues = queries.list_issues(
            session,
            issue_type=issue_type,
            severity=severity,
            open_only=not include_closed,
            limit=limit,
        )
        for issue in issues:
            state = "cerrada" if issue.resolved_at else "abierta"
            typer.echo(
                f"{issue.id:5} {issue.severity:7} {issue.issue_type:28} {issue.code or '-':13} "
                f"{state:8} {issue.message}"
            )


@runs_app.command("list")
def runs_list(limit: Annotated[int, typer.Option("--limit")] = 20) -> None:
    """Últimas corridas de ingesta."""
    with session_scope(_migrated_engine()) as session:
        for run in queries.list_runs(session, limit):
            typer.echo(
                f"{run.id:4} {run.started_at:%Y-%m-%d %H:%M} {run.mode:11} {run.status:22} "
                f"procesados {run.processed_count} · sin cambios {run.skipped_count} · "
                f"errores {run.error_count} · nuevos {run.new_count} · "
                f"faltantes {run.missing_count} · referencias {run.references_count}"
            )


@runs_app.command("show")
def runs_show(run_id: Annotated[int, typer.Argument(help="Número de corrida")]) -> None:
    """Resumen de una corrida y la ruta de su log."""
    from app.models import IngestionRun

    with session_scope(_migrated_engine()) as session:
        run = session.get(IngestionRun, run_id)
        if run is None:
            typer.echo(f"Error: no existe la corrida {run_id}")
            raise typer.Exit(code=2)
        summary = catalog.run_out(run)
    for key, value in summary.model_dump().items():
        typer.echo(f"{key:28} {'-' if value is None else value}")


@app.command("stats")
def stats() -> None:
    """Totales de documentos, referencias e incidencias."""
    with session_scope(_migrated_engine()) as session:
        typer.echo(json.dumps(queries.stats(session), ensure_ascii=False, indent=2))


# ----------------------------------------------------------------------------- grafos e impacto


def _node_for(session: Session, code: str, norma: str | None) -> str:
    """Nodo del documento en la norma indicada, o en la única norma donde existe el código."""
    try:
        return catalog.resolve_node(session, catalog.normalize_code(code), norma)
    except catalog.UnknownNormaError as exc:
        names = graph_service.norma_names(session)
        typer.echo(f"Error: {exc}. Normas: {', '.join(names) or '-'}")
        raise typer.Exit(code=2) from exc
    except catalog.NormaRequiredError as exc:
        typer.echo(
            f"Error: {exc.code} es un documento en varias normas ({', '.join(exc.normas)}); "
            "usar --norma"
        )
        raise typer.Exit(code=2) from exc
    except catalog.CodeNotFoundError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=2) from exc


@app.command("impact")
def impact(
    code: Annotated[str, typer.Argument(help="Código del documento que cambia")],
    norma: Annotated[
        str | None, typer.Option("--norma", "-n", help="Norma (si el código está en varias)")
    ] = None,
    depth: Annotated[int | None, typer.Option("--depth", "-d", help="Profundidad")] = None,
    output: Annotated[str, typer.Option("--format", help="table, json o csv")] = "table",
    destination: Annotated[
        Path | None, typer.Option("--output", "-o", help="Archivo de salida")
    ] = None,
    types: Annotated[
        list[str] | None, typer.Option("--type", help="Mostrar solo estos tipos (PR, PO…)")
    ] = None,
    groups: Annotated[
        list[str] | None, typer.Option("--group", help="Solo relaciones de estos grupos")
    ] = None,
) -> None:
    """Posibles documentos a revisar si cambia CODE (quienes lo citan, directa o indirectamente)."""
    settings = get_settings()
    depth = depth or settings.default_depth
    with session_scope(_migrated_engine()) as session:
        node = _node_for(session, code, norma)
        filters = graph_service.GraphFilters(groups=frozenset(groups) if groups else None)
        nx_graph = graph_service.build_graph(session, filters)
    try:
        result = impacted_by(
            nx_graph,
            node,
            depth,
            max_depth=settings.max_depth,
            types=frozenset(t.upper() for t in types) if types else None,
        )
    except (DepthOutOfRangeError, graph_service.DocumentNotInGraphError) as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=2) from exc

    if output == "csv":
        text = impact_to_csv(result)
    elif output == "json":
        payload = {
            **asdict(result),
            "direct": [asdict(i) for i in result.direct],
            "indirect": [asdict(i) for i in result.indirect],
            "summary": result.summary(),
        }
        payload.pop("items")
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        text = _impact_table(result)
    if destination is not None:
        destination.write_text(text, encoding="utf-8", newline="")
        typer.echo(f"Impacto guardado en {destination}")
    else:
        typer.echo(text.lstrip("﻿"))


def _impact_table(result: TraversalResult) -> str:
    lines = [
        f"Cambio en {result.root_norma + '/' if result.root_norma else ''}{result.root_code}"
        f"{'' if result.root_resolved else ' (código citado, sin documento)'}"
        f" — profundidad {result.depth}",
        result.disclaimer,
        f"Directos: {len(result.direct)} · indirectos: {len(result.indirect)}",
    ]
    for item in result.items:
        lines.append(
            f"  {item.depth}  {item.code:14} {(item.norma or '-')[:20]:20} "
            f"{(item.title or '')[:45]:45} {' → '.join(item.path)}"
        )
    return "\n".join(lines)


@graph_app.command("list")
def graph_list() -> None:
    """Normas del grafo con sus totales."""
    with session_scope(_migrated_engine()) as session:
        summaries = graph_service.list_normas(session)
    for summary in summaries:
        typer.echo(
            f"{summary.name:40} documentos {summary.documents:4} · referencias "
            f"{summary.references:4} · a otra norma {summary.cross_norma:4} · "
            f"pendientes {summary.unresolved}"
        )
    typer.echo(
        f"{'Total':40} documentos {sum(s.documents for s in summaries):4} · referencias "
        f"{sum(s.references for s in summaries):4} · a otra norma "
        f"{sum(s.cross_norma for s in summaries):4} · "
        f"pendientes {sum(s.unresolved for s in summaries)}"
    )


@graph_app.command("export")
def graph_export(
    output_format: Annotated[str, typer.Option("--format", help="graphml o json")] = "graphml",
    destination: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Archivo (por defecto data/export/grafo.FORMATO)"),
    ] = None,
) -> None:
    """Exporta el grafo completo (todas las normas) a un único archivo."""
    if output_format not in ("graphml", "json"):
        typer.echo("Error: --format debe ser graphml o json")
        raise typer.Exit(code=2)
    writer = (
        graph_service.export_graphml if output_format == "graphml" else graph_service.export_json
    )
    path = destination or Path("data/export") / f"grafo.{output_format}"
    with session_scope(_migrated_engine()) as session:
        graph = graph_service.build_graph(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer(graph, path)
    typer.echo(f"{graph.number_of_nodes()} nodos, {graph.number_of_edges()} aristas -> {path}")


# ----------------------------------------------------------------------------- API


@api_app.command("serve")
def api_serve(
    reload: Annotated[bool, typer.Option("--reload", help="Recarga al cambiar el código")] = False,
) -> None:
    """Levanta la API en ISO_API_HOST:ISO_API_PORT (por defecto solo localhost)."""
    import uvicorn

    _migrated_engine()
    settings = get_settings()
    uvicorn.run("app.api.main:app", host=settings.api_host, port=settings.api_port, reload=reload)


@api_app.command("openapi")
def api_openapi(
    destination: Annotated[
        Path | None, typer.Option("--output", "-o", help="Archivo JSON (por defecto, salida)")
    ] = None,
) -> None:
    """Esquema OpenAPI (para generar los tipos TypeScript del frontend)."""
    from app.api.main import create_app

    schema = json.dumps(create_app().openapi(), ensure_ascii=False, indent=2)
    if destination is None:
        typer.echo(schema)
    else:
        destination.write_text(schema, encoding="utf-8")
        typer.echo(f"Esquema OpenAPI guardado en {destination}")


# ----------------------------------------------------------------------------- golden


def _extractor():  # type: ignore[no-untyped-def]
    config = load_extraction_config(get_settings().extraction_config)
    return lambda path: extract_document(path, config=config)


@golden_app.command("draft")
def golden_draft(
    samples: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="Carpeta")],
    destination: Annotated[Path, typer.Option("--output", "-o", help="CSV a generar")],
) -> None:
    """Borrador del set de referencia con lo que extrae hoy el sistema, para revisar a mano."""
    if destination.exists():
        typer.echo(f"Error: {destination} ya existe; no se sobrescribe un set anotado")
        raise typer.Exit(code=2)
    extract = _extractor()
    files = sorted(
        path
        for path in samples.rglob("*")
        if path.is_file() and detect_format(path) and not is_ignored(path)
    )
    rows = golden.draft_rows(
        (path.relative_to(samples).as_posix(), extract(path)) for path in files
    )
    golden.write_rows(rows, destination)
    to_review = sum(1 for row in rows if row["note"].startswith("REVISAR"))
    typer.echo(
        f"Borrador con {len(files)} archivos y {len(rows)} filas en {destination}; "
        f"{to_review} filas marcadas REVISAR. Corregirlo a mano antes de evaluar."
    )


@golden_app.command("evaluate")
def golden_evaluate(
    golden_csv: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="CSV anotado")],
    samples: Annotated[Path, typer.Option("--samples", exists=True, file_okay=False)],
    min_precision: Annotated[float, typer.Option(help="Precisión mínima")] = 0.99,
    min_recall: Annotated[float, typer.Option(help="Recall mínimo")] = 0.98,
) -> None:
    """Compara la extracción con el set de referencia; sale con código 1 bajo el umbral."""
    try:
        expected = golden.load_golden(golden_csv)
    except golden.GoldenFormatError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=2) from exc
    report = golden.evaluate(expected, samples, _extractor())
    for item in report.files:
        problems = []
        if item.false_negatives:
            problems.append(f"faltan {', '.join(sorted(item.false_negatives))}")
        if item.false_positives:
            problems.append(f"sobran {', '.join(sorted(item.false_positives))}")
        if item.group_mismatches:
            problems.append(f"grupo distinto {', '.join(sorted(item.group_mismatches))}")
        if problems:
            typer.echo(f"  {item.file} [{item.status}]: {'; '.join(problems)}")
    typer.echo(
        f"Archivos {len(report.files)} · relaciones esperadas "
        f"{report.true_positives + report.false_negatives} · "
        f"precisión {report.precision:.2%} · recall {report.recall:.2%} · "
        f"grupo correcto {report.group_accuracy:.2%}"
    )
    if not report.meets(min_precision, min_recall):
        typer.echo(f"Bajo el umbral (precisión ≥ {min_precision:.0%}, recall ≥ {min_recall:.0%})")
        raise typer.Exit(code=1)
