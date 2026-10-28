"""Orquestación de una corrida de ingesta.

Orden (SKILL §4): primero se escanea, se calcula el hash y se extrae todo **sin tocar la
base**; después se decide qué publicar (duplicados, movidos, formatos alternativos) y cada
documento se escribe en **su propia transacción**. Una falla en un documento no afecta a
los demás ni borra sus referencias vigentes. Todo queda registrado en el log de la corrida
(``services/run_log.py``).
"""

import logging
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, aliased

from app.db.session import session_scope
from app.ingestion.config import ExtractionConfig
from app.ingestion.extractor import extract_document
from app.ingestion.fingerprint import extraction_fingerprint
from app.ingestion.readers import detect_format
from app.ingestion.types import ExtractionResult, Issue
from app.models import (
    Document,
    DocumentReference,
    ExtractionStatus,
    IngestionRun,
    QualityIssue,
    RunMode,
    RunStatus,
    Severity,
)
from app.models.base import utcnow
from app.services import sync
from app.services.editions import Edition, choose_edition
from app.services.resolution import ResolutionChange, active_candidates, reresolve_code
from app.services.run_log import RunLogger, prune_logs
from app.services.scanner import ScannedFile, describe_file, resolve_within, scan, sha256_of

STALE_RUN_AFTER = timedelta(hours=6)
ERROR_STATUSES = frozenset({ExtractionStatus.ERROR, ExtractionStatus.SOURCE_CODE_UNRESOLVED})
_ISSUE_LEVELS = {
    Severity.INFO: logging.INFO,
    Severity.WARNING: logging.WARNING,
    Severity.ERROR: logging.ERROR,
}


class IngestionLockedError(RuntimeError):
    """Ya hay otra ingesta en curso."""


class UnsupportedFileError(ValueError):
    """El archivo pedido no es un PDF/DOCX/planilla Excel procesable."""


@dataclass(frozen=True, slots=True)
class IngestOptions:
    incremental: bool = False
    retry_failed: bool = False
    dry_run: bool = False
    replace: bool = False
    code_override: str | None = None
    force_unlock: bool = False


@dataclass(slots=True)
class FileReport:
    rel_path: str
    action: str  # created, updated, skipped, superseded, blocked, unpublished, error, planned
    status: ExtractionStatus | None = None
    code: str | None = None
    references: int = 0
    message: str | None = None
    stats: sync.ReferenceStats | None = None  # solo si se publicaron sus referencias


@dataclass(slots=True)
class IngestReport:
    run_id: int | None
    mode: RunMode
    status: RunStatus | None
    files: list[FileReport] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    unsupported_count: int = 0
    root_files: list[str] = field(default_factory=list)  # sueltos en la raíz, sin norma
    warning_count: int = 0
    log_path: str | None = None
    # Estado del grafo completo al terminar (las referencias se re-resuelven durante la corrida).
    graph_state: "GraphState | None" = None

    def count(self, *actions: str) -> int:
        return sum(1 for f in self.files if f.action in actions)

    @property
    def error_count(self) -> int:
        return self.count("blocked", "error") + sum(
            1 for f in self.files if f.action == "unpublished" and f.status in ERROR_STATUSES
        )

    def _stats_sum(self, attribute: str) -> int:
        return sum(getattr(f.stats, attribute) for f in self.files if f.stats is not None)

    @property
    def references_count(self) -> int:
        return self._stats_sum("total")

    @property
    def occurrences_count(self) -> int:
        return self._stats_sum("occurrences")

    @property
    def duplicate_references_count(self) -> int:
        return self._stats_sum("duplicates")

    @property
    def unresolved_count(self) -> int:
        """Referencias pendientes en todo el grafo al terminar la corrida."""
        return self.graph_state.unresolved if self.graph_state else 0


@dataclass(frozen=True, slots=True)
class GraphState:
    references: int
    unresolved: int
    cross_norma: int
    ambiguous: int  # pendientes cuyo código existe en varias normas

    @classmethod
    def of(cls, session: Session) -> "GraphState":
        source, target = aliased(Document), aliased(Document)
        total, unresolved, cross = session.execute(
            select(
                func.count(),
                func.count().filter(DocumentReference.target_document_id.is_(None)),
                func.count().filter(target.norma != source.norma),
            )
            .select_from(DocumentReference)
            .join(source, DocumentReference.source_document_id == source.id)
            .outerjoin(target, DocumentReference.target_document_id == target.id)
            .where(source.is_active.is_(True))
        ).one()
        pending = session.scalars(
            select(DocumentReference.target_code)
            .join(source, DocumentReference.source_document_id == source.id)
            .where(DocumentReference.target_document_id.is_(None), source.is_active.is_(True))
        ).all()
        candidates = active_candidates(session, set(pending))
        ambiguous = sum(1 for code in pending if len(candidates.get(code, [])) > 1)
        return cls(total, unresolved, cross, ambiguous)


@dataclass(slots=True)
class _Pending:
    file: ScannedFile
    sha256: str
    result: ExtractionResult
    batch_issue: Issue | None = None  # bloqueado o relegado por otro archivo del mismo lote


class IngestionService:
    def __init__(
        self,
        engine: Engine,
        documents_dir: Path,
        config: ExtractionConfig,
        *,
        log_dir: Path | None = None,
        log_level: str = "INFO",
        log_keep: int = 0,
        log_max_age_days: int = 0,
    ) -> None:
        self.engine = engine
        self.root = documents_dir.resolve()
        self.config = config
        self.fingerprint = extraction_fingerprint(config)
        self.log_dir = log_dir
        self.log_level = log_level
        self.log_keep = log_keep
        self.log_max_age_days = log_max_age_days

    # ------------------------------------------------------------------ API pública

    def ingest_path(self, path: Path, options: IngestOptions) -> IngestReport:
        scanned = scan(path, self.root)
        mode = RunMode.INCREMENTAL if options.incremental else RunMode.FULL
        full_tree = resolve_within(path, self.root) == self.root
        return self._run(
            mode,
            path,
            scanned.files,
            scanned.unsupported_count,
            options,
            full_tree,
            root_files=scanned.root_files,
        )

    def ingest_file(self, path: Path, options: IngestOptions) -> IngestReport:
        """Reprocesa un archivo siempre (sin comparar hash) y nunca marca faltantes."""
        described = describe_file(path, self.root)
        if described is None:
            raise UnsupportedFileError(f"{path} no es un PDF/DOCX/planilla Excel procesable")
        if described.norma is None:
            raise UnsupportedFileError(
                f"{path} está suelto en la raíz: debe estar dentro de una carpeta (norma)"
            )
        forced = IngestOptions(
            replace=options.replace,
            code_override=options.code_override,
            dry_run=options.dry_run,
            force_unlock=options.force_unlock,
        )
        return self._run(RunMode.SINGLE, path, [described], 0, forced, full_tree=False)

    # ------------------------------------------------------------------ corrida

    def _run(
        self,
        mode: RunMode,
        path: Path,
        files: list[ScannedFile],
        unsupported: int,
        options: IngestOptions,
        full_tree: bool,
        root_files: list[str] | None = None,
    ) -> IngestReport:
        root_files = root_files or []
        run_id = None if options.dry_run else self._start_run(mode, path, options)
        log = RunLogger(self.log_dir, run_id=run_id, level=self.log_level)
        report = IngestReport(
            run_id,
            mode,
            None,
            unsupported_count=unsupported,
            root_files=root_files,
            log_path=str(log.path) if log.path else None,
        )
        started = time.monotonic()
        try:
            log.info(
                "inicio",
                corrida=run_id,
                simulacion=options.dry_run or None,
                modo=mode.value,
                ruta=str(path),
                incremental=options.incremental,
                huella=self.fingerprint[:12],
                reintentar_fallidos=options.retry_failed,
                reemplazar=options.replace,
                codigo_manual=options.code_override,
            )
            _log_scan(log, files, unsupported, root_files)
            if options.dry_run:
                return self._dry_run(files, options, report, log, started)
            assert run_id is not None
            try:
                pending = self._extract_all(files, options, report, log)
                self._resolve_editions(pending)
                for item in pending:
                    report.files.append(self._publish_one(item, run_id, options, log))
                if full_tree:
                    report.missing = self._mark_missing({f.rel_path for f in files}, run_id, log)
            except Exception as exc:
                log.exception("corrida_fallida", exc, corrida=run_id)
                self._finish_run(run_id, report, RunStatus.FAILED)
                _log_summary(log, report, started)
                raise
            status = (
                RunStatus.COMPLETED if report.error_count == 0 else RunStatus.COMPLETED_WITH_ERRORS
            )
            self._finish_run(run_id, report, status)
            _log_summary(log, report, started)
            return report
        finally:
            self._prune_logs(log)
            log.close()

    def _prune_logs(self, log: RunLogger) -> None:
        if self.log_dir is None:
            return
        deleted = prune_logs(
            self.log_dir,
            keep=self.log_keep,
            max_age_days=self.log_max_age_days,
            exclude=log.path,
        )
        if deleted:
            log.info(
                "logs_depurados",
                cantidad=len(deleted),
                conservar=self.log_keep or None,
                max_dias=self.log_max_age_days or None,
            )

    def _start_run(self, mode: RunMode, path: Path, options: IngestOptions) -> int:
        with session_scope(self.engine) as session:
            now = utcnow()
            running = session.scalars(
                select(IngestionRun).where(IngestionRun.status == RunStatus.RUNNING)
            ).all()
            for other in running:
                if options.force_unlock or now - _as_utc(other.started_at) > STALE_RUN_AFTER:
                    other.status = RunStatus.INTERRUPTED
                    other.ended_at = now
                else:
                    raise IngestionLockedError(
                        f"La ingesta {other.id} está en curso desde "
                        f"{other.started_at:%Y-%m-%d %H:%M}"
                        " (usar --force-unlock si quedó colgada)"
                    )
            run = IngestionRun(
                mode=mode,
                root_path=str(path),
                status=RunStatus.RUNNING,
                options_json={
                    "incremental": options.incremental,
                    "retry_failed": options.retry_failed,
                    "replace": options.replace,
                    "code_override": options.code_override,
                },
            )
            session.add(run)
            session.flush()
            return run.id

    def _finish_run(self, run_id: int, report: IngestReport, status: RunStatus) -> None:
        with session_scope(self.engine) as session:
            run = session.get(IngestionRun, run_id)
            assert run is not None
            report.status = status
            report.graph_state = GraphState.of(session)
            report.warning_count = (
                session.scalar(
                    select(func.count())
                    .select_from(QualityIssue)
                    .where(QualityIssue.run_id == run_id, QualityIssue.severity == Severity.WARNING)
                )
                or 0
            )
            run.status = status
            run.ended_at = utcnow()
            run.processed_count = len(report.files) - report.count("skipped")
            run.skipped_count = report.count("skipped")
            run.error_count = report.error_count
            run.warning_count = report.warning_count
            run.new_count = report.count("created")
            run.updated_count = report.count("updated")
            run.missing_count = len(report.missing)
            run.no_section_count = _no_section_count(report)
            run.unsupported_skipped_count = report.unsupported_count
            run.root_files_count = len(report.root_files)
            run.references_count = report.references_count
            run.occurrences_count = report.occurrences_count
            run.duplicate_references_count = report.duplicate_references_count
            run.unresolved_count = report.unresolved_count
            run.log_path = report.log_path

    # ------------------------------------------------------------------ extracción

    def _extract_all(
        self,
        files: list[ScannedFile],
        options: IngestOptions,
        report: IngestReport,
        log: RunLogger,
    ) -> list[_Pending]:
        pending = []
        with session_scope(self.engine) as session:
            known = {
                doc.file_path: doc
                for doc in session.scalars(
                    select(Document).where(Document.file_path.in_([f.rel_path for f in files]))
                )
            }
            for file in files:
                digest = sha256_of(file.path)
                if options.incremental and _unchanged(known.get(file.rel_path), digest, options):
                    document = known[file.rel_path]
                    if document.extraction_fingerprint == self.fingerprint:
                        code = document.code
                        report.files.append(FileReport(file.rel_path, "skipped", code=code))
                        log.info("sin_cambios", ruta=file.rel_path, norma=file.norma, codigo=code)
                        continue
                    # Mismo archivo, pero se procesó con otro extractor u otra configuración.
                    log.info(
                        "reglas_cambiadas",
                        ruta=file.rel_path,
                        norma=file.norma,
                        codigo=document.code,
                    )
                result = self._extract(file, options, log)
                pending.append(_Pending(file, digest, result))
        return pending

    def _extract(
        self, file: ScannedFile, options: IngestOptions, log: RunLogger
    ) -> ExtractionResult:
        try:
            result = extract_document(
                file.path, code_override=options.code_override, config=self.config
            )
        except Exception as exc:  # noqa: BLE001 - un archivo no debe frenar la corrida
            log.exception("error_extraccion", exc, ruta=file.rel_path, norma=file.norma)
            result = ExtractionResult(
                file_path=str(file.path),
                file_format=detect_format(file.path),
                source_code=None,
                code_source=None,
                version=None,
                title=None,
                status=ExtractionStatus.ERROR,
                issues=[Issue("extraction_error", Severity.ERROR, f"Error al extraer: {exc}")],
            )
        log.info(
            "extraido",
            ruta=file.rel_path,
            norma=file.norma,
            formato=file.file_format.value,
            codigo=result.source_code,
            origen_codigo=result.code_source.value if result.code_source else None,
            version=result.version,
            estado=result.status.value,
            referencias=len(result.references),
            ocurrencias=result.occurrence_count,
        )
        return result

    def _resolve_editions(self, pending: list[_Pending]) -> None:
        """Mismo código varias veces en una norma dentro del lote (ver services/editions.py)."""
        by_code: dict[tuple[str, str], list[_Pending]] = defaultdict(list)
        for item in pending:
            if item.result.source_code and item.file.norma:
                by_code[(item.file.norma, item.result.source_code)].append(item)
        for (_, code), items in by_code.items():
            if len(items) < 2:
                continue
            choice = choose_edition(code, [_edition_of(item) for item in items])
            for item in items:
                item.batch_issue = choice.issues.get(item.file.rel_path)

    # ------------------------------------------------------------------ publicación

    def _publish_one(
        self, item: _Pending, run_id: int, options: IngestOptions, log: RunLogger
    ) -> FileReport:
        try:
            with session_scope(self.engine) as session:
                report, changes = self._decide_and_write(session, item, run_id, options)
        except Exception as exc:  # noqa: BLE001 - un documento no debe frenar la corrida
            log.exception(
                "error_guardado", exc, ruta=item.file.rel_path, codigo=item.result.source_code
            )
            with session_scope(self.engine) as session:
                sync.record_issues(
                    session,
                    [Issue("sync_error", Severity.ERROR, f"No se pudo guardar: {exc}")],
                    run_id=run_id,
                    document_id=None,
                    file_path=item.file.rel_path,
                    code=item.result.source_code,
                )
            return FileReport(
                item.file.rel_path,
                "error",
                item.result.status,
                item.result.source_code,
                0,
                str(exc),
            )
        _log_document(log, item, report)
        _log_resolution_changes(log, changes)
        return report

    def _decide_and_write(
        self, session: Session, item: _Pending, run_id: int, options: IngestOptions
    ) -> tuple[FileReport, list[ResolutionChange]]:
        file, result = item.file, item.result
        code = result.source_code

        def unpublished(action: str, *extra: Issue) -> tuple[FileReport, list[ResolutionChange]]:
            sync.mark_unpublished(
                session,
                file=file,
                sha256=item.sha256,
                fingerprint=self.fingerprint,
                result=result,
                run_id=run_id,
                extra_issues=extra,
            )
            message = extra[0].message if extra else None
            return FileReport(file.rel_path, action, result.status, code, 0, message), []

        if code is None:
            return unpublished("unpublished")
        if item.batch_issue is not None:
            blocked = item.batch_issue.severity is Severity.ERROR
            return unpublished("blocked" if blocked else "superseded", item.batch_issue)

        changes: list[ResolutionChange] = []
        by_path = sync.find_by_path(session, file.rel_path)
        if by_path is not None and by_path.code != code:
            if not options.replace:
                return unpublished("blocked", _code_changed_issue(by_path.code, code))
            # --replace explícito: el código anterior deja de existir y quienes lo citaban
            # se re-resuelven (otra norma con ese código, o pendientes).
            previous_code = by_path.code
            session.delete(by_path)
            session.flush()
            changes += reresolve_code(session, previous_code)

        assert file.norma is not None
        target = sync.find_by_code(session, file.norma, code)
        extra: list[Issue] = []
        if target is not None and target.file_path != file.rel_path:
            other_exists = (self.root / target.file_path).exists()
            if target.is_active and other_exists and not options.replace:
                registered = Edition(
                    target.file_path,
                    target.version,
                    target.file_format,
                    _as_utc(target.file_mtime),
                    target.sha256,
                )
                choice = choose_edition(code, [registered, _edition_of(item)])
                if choice.current is None:
                    return unpublished("blocked", choice.issues[file.rel_path])
                if choice.current is registered:
                    return unpublished("superseded", choice.issues[file.rel_path])
                # El archivo nuevo es la edición vigente: el documento pasa a apuntar a él.
                extra.append(choice.issues[target.file_path])
            else:
                extra.append(
                    Issue(
                        "file_moved",
                        Severity.INFO,
                        f"{code} pasó de {target.file_path} a {file.rel_path}",
                        {"from": target.file_path, "to": file.rel_path},
                    )
                )

        outcome = sync.publish(
            session,
            file=file,
            sha256=item.sha256,
            fingerprint=self.fingerprint,
            result=result,
            run_id=run_id,
            document=target,
            extra_issues=extra,
        )
        changes += outcome.resolution_changes
        report = FileReport(
            file.rel_path,
            "created" if outcome.created else "updated",
            result.status,
            code,
            len(result.references),
            stats=outcome.references,
        )
        return report, changes

    def _mark_missing(self, seen: set[str], run_id: int, log: RunLogger) -> list[str]:
        missing = []
        with session_scope(self.engine) as session:
            active = session.scalars(select(Document).where(Document.is_active.is_(True))).all()
            for document in active:
                if document.file_path in seen or (self.root / document.file_path).exists():
                    continue
                changes = sync.deactivate_missing(session, document, run_id)
                label = f"{document.norma}/{document.code}"
                missing.append(label)
                log.warning("faltante", documento=label, ruta=document.file_path)
                _log_resolution_changes(log, changes)
        return missing

    # ------------------------------------------------------------------ simulación

    def _dry_run(
        self,
        files: list[ScannedFile],
        options: IngestOptions,
        report: IngestReport,
        log: RunLogger,
        started: float,
    ) -> IngestReport:
        for item in self._extract_all(files, options, report, log):
            report.files.append(
                FileReport(
                    item.file.rel_path,
                    "planned",
                    item.result.status,
                    item.result.source_code,
                    len(item.result.references),
                )
            )
            _log_document(log, item, report.files[-1])
        _log_summary(log, report, started)
        return report


# ----------------------------------------------------------------------------- log


def _log_scan(
    log: RunLogger, files: list[ScannedFile], unsupported: int, root_files: list[str]
) -> None:
    log.info(
        "escaneo",
        archivos=len(files),
        por_formato=dict(Counter(f.file_format.value for f in files)),
        por_norma=dict(Counter(f.norma for f in files)),
        no_soportados=unsupported,
        sueltos_en_raiz=len(root_files),
    )
    for rel_path in root_files:
        log.warning("archivo_sin_norma", ruta=rel_path, accion="no se procesa")


def _log_document(log: RunLogger, item: _Pending, report: FileReport) -> None:
    result, stats = item.result, report.stats
    level = (
        logging.ERROR
        if report.action in ("error", "blocked") or report.status in ERROR_STATUSES
        else logging.INFO
    )
    log.log(
        level,
        "documento",
        ruta=report.rel_path,
        norma=item.file.norma,
        codigo=report.code,
        formato=item.file.file_format.value,
        accion=report.action,
        estado=report.status.value if report.status else None,
        referencias=len(result.references),
        ocurrencias=result.occurrence_count,
        misma_norma=stats.same_norma if stats else None,
        otra_norma=stats.cross_norma if stats else None,
        pendientes=stats.unresolved if stats else None,
        ambiguas=stats.ambiguous or None if stats else None,
        nuevas=stats.added if stats else None,
        eliminadas=stats.removed if stats else None,
        motivo=report.message,
    )
    for hit in result.references:
        if len(hit.occurrences) > 1:
            log.warning(
                "referencia_duplicada",
                ruta=report.rel_path,
                origen=report.code,
                destino=hit.code,
                veces=len(hit.occurrences),
                paginas=[o.page_number for o in hit.occurrences if o.page_number] or None,
            )
    issues = [*result.issues, *([item.batch_issue] if item.batch_issue else [])]
    for issue in issues:
        log.log(
            _ISSUE_LEVELS[issue.severity],
            "incidencia",
            ruta=report.rel_path,
            codigo=report.code,
            tipo=issue.type,
            severidad=issue.severity.value,
            mensaje=issue.message,
        )


def _log_resolution_changes(log: RunLogger, changes: list[ResolutionChange]) -> None:
    for change in changes:
        log.log(
            logging.WARNING if change.ambiguous_normas else logging.INFO,
            "re_resolucion",
            origen=change.source,
            codigo=change.target_code,
            antes=change.before or "pendiente",
            despues=change.after or "pendiente",
            normas_candidatas=list(change.ambiguous_normas) or None,
        )


def _log_summary(log: RunLogger, report: IngestReport, started: float) -> None:
    state = report.graph_state
    log.log(
        logging.ERROR if report.status is RunStatus.FAILED else logging.INFO,
        "resumen",
        corrida=report.run_id,
        estado=report.status.value if report.status else "simulacion",
        duracion_s=round(time.monotonic() - started, 2),
        archivos=len(report.files),
        procesados=len(report.files) - report.count("skipped"),
        sin_cambios=report.count("skipped"),
        nuevos=report.count("created"),
        actualizados=report.count("updated"),
        relegados=report.count("superseded"),
        bloqueados=report.count("blocked"),
        no_publicados=report.count("unpublished"),
        errores=report.error_count,
        avisos=report.warning_count,
        faltantes=len(report.missing),
        sin_seccion=_no_section_count(report),
        no_soportados=report.unsupported_count,
        sueltos_en_raiz=len(report.root_files),
        referencias=report.references_count,
        ocurrencias=report.occurrences_count,
        duplicadas=report.duplicate_references_count,
        # Estado de todo el grafo al terminar (incluye documentos no procesados en esta corrida).
        grafo_referencias=state.references if state else None,
        grafo_pendientes=state.unresolved if state else None,
        grafo_otra_norma=state.cross_norma if state else None,
        grafo_ambiguas=state.ambiguous if state else None,
    )


def _no_section_count(report: IngestReport) -> int:
    return sum(
        1
        for f in report.files
        if f.action in ("created", "updated") and f.status is ExtractionStatus.NO_SECTION
    )


def _unchanged(document: Document | None, digest: str, options: IngestOptions) -> bool:
    if document is None or not document.is_active or document.sha256 != digest:
        return False
    return not (options.retry_failed and document.extraction_status in sync.RETRYABLE)


def _as_utc(value: datetime) -> datetime:
    # SQLite no guarda la zona horaria: los valores vuelven "naive" pero se escribieron en UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _edition_of(item: _Pending) -> Edition:
    return Edition(
        item.file.rel_path, item.result.version, item.file.file_format, item.file.mtime, item.sha256
    )


def _code_changed_issue(previous: str, current: str) -> Issue:
    return Issue(
        "source_code_changed",
        Severity.ERROR,
        f"El archivo era {previous} y ahora declara {current}; usar --replace para confirmarlo",
        {"previous": previous, "current": current},
    )
