"""F13.10 UI-safe projection and delegation for the durable product queue.

The dashboard deliberately composes the F13.7 operation boundary with the
durable Execution aggregate and the read-only scheduler runtime status.  It
never claims, starts, reconciles, or submits work itself: those authorities
remain with F13.8/F13.9.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ..persistence.sqlite import PersistenceError
from .queue_operations import QueueOperationError, QueueOperationsUseCase


class QueueDashboardError(ValueError):
    """A queue projection or delegated operation could not be completed safely."""


@dataclass(frozen=True)
class QueueRuntimeSnapshot:
    """Read-only runtime facts made available to the queue presentation."""

    running: bool
    outcome: str | None = None
    queue_item_id: str | None = None
    execution_id: str | None = None
    reason: str = ""
    recovery_outcome: str | None = None
    issue: str = ""


@dataclass(frozen=True)
class QueueDashboardEntry:
    """One durable QueueItem enriched only with presentation context."""

    queue_item_id: str
    project_id: str
    execution_id: str
    execution_number: int | None
    position: int
    queue_state: str
    execution_state: str
    presentation_state: str
    detail: str = ""
    terminal_reason: str | None = None
    is_active: bool = False
    can_open: bool = True
    can_move_up: bool = False
    can_move_down: bool = False
    can_remove: bool = False
    can_skip: bool = False
    can_duplicate: bool = False


@dataclass(frozen=True)
class QueueDashboardSnapshot:
    """Immutable queue view consumed by the Qt panel."""

    entries: tuple[QueueDashboardEntry, ...]
    paused: bool
    active_queue_item_id: str | None
    revision: int
    state: str
    detail: str
    scheduler_running: bool


@dataclass(frozen=True)
class QueueDashboardAction:
    """Result of a delegated queue operation with a fresh durable snapshot."""

    snapshot: QueueDashboardSnapshot
    selection: QueueDashboardEntry | None = None
    detail: Any = None


class QueueDashboardUseCase:
    """Expose F13.7/F13.8/F13.9 queue facts through one UI-safe seam.

    The mutating methods below only delegate to ``QueueOperationsUseCase``.
    The scheduler is observed through an injected read-only callable so the
    UI can accurately explain recovery/manual-review states without owning or
    driving the scheduler thread.
    """

    def __init__(self, repository, *, scheduler_status: Callable[[], Any] | None = None):
        if repository is None:
            raise QueueDashboardError("queue dashboard repository is required")
        if scheduler_status is not None and not callable(scheduler_status):
            raise QueueDashboardError("scheduler status reader must be callable")
        self.repository = repository
        self.operations = QueueOperationsUseCase(repository)
        self.scheduler_status = scheduler_status

    @staticmethod
    def _value(value):
        return getattr(value, "value", value)

    @staticmethod
    def _id(value, label):
        if not isinstance(value, str) or not value.strip():
            raise QueueDashboardError(f"{label} id must be nonblank")
        return value.strip()

    @staticmethod
    def _failure(operation, exc):
        if isinstance(exc, QueueDashboardError):
            raise exc
        raise QueueDashboardError(f"queue dashboard {operation} failed: {exc}") from exc

    def _runtime(self):
        if self.scheduler_status is None:
            return QueueRuntimeSnapshot(False)
        try:
            raw = self.scheduler_status()
        except Exception as exc:
            return QueueRuntimeSnapshot(False, issue=f"scheduler status unavailable: {exc}")
        if raw is None:
            return QueueRuntimeSnapshot(False)
        if isinstance(raw, Mapping):
            get = raw.get
        else:
            get = lambda key, default=None: getattr(raw, key, default)
        result = get("last_result")
        outcome = self._value(getattr(result, "outcome", None)) if result is not None else None
        queue_item_id = getattr(result, "queue_item_id", None) if result is not None else None
        execution_id = getattr(result, "execution_id", None) if result is not None else None
        reason = getattr(result, "reason", "") if result is not None else ""
        recovery_outcome = (
            getattr(result, "recovery_outcome", None) if result is not None else None
        )
        return QueueRuntimeSnapshot(
            bool(get("running", False)),
            None if outcome is None else str(outcome),
            None if queue_item_id is None else str(queue_item_id),
            None if execution_id is None else str(execution_id),
            str(reason or ""),
            None if recovery_outcome is None else str(recovery_outcome),
            str(get("startup_error", "") or ""),
        )

    def _execution_context(self, record):
        try:
            project_id = str(self.repository.execution_project_id(record.execution_id))
            project, executions = self.repository.load(project_id)
            if str(project.id) != project_id:
                raise QueueDashboardError("queue execution project identity is inconsistent")
            matches = [
                execution
                for execution in executions
                if str(execution.id) == str(record.execution_id)
            ]
            if len(matches) != 1:
                raise QueueDashboardError("queue execution selection is missing or ambiguous")
            execution = matches[0]
            execution_state = str(self._value(getattr(execution, "state", "unknown")))
            number = getattr(execution, "execution_number", None)
            if number is not None and type(number) is not int:
                raise QueueDashboardError("queue execution number is invalid")
            return project_id, execution_state, number
        except (
            PersistenceError,
            OSError,
            TypeError,
            ValueError,
            AttributeError,
        ) as exc:
            self._failure("execution projection", exc)

    @staticmethod
    def _dashboard_state(records, control, runtime, contexts):
        active_id = control.active_queue_item_id
        active = next((record for record in records if record.id == active_id), None)
        if control.paused:
            return (
                "paused",
                "La cola está pausada: no iniciará otro item y no cancela el activo.",
            )
        if active is not None:
            if runtime.issue:
                return "blocked", runtime.issue
            matches_active = runtime.queue_item_id == active.id
            if matches_active and runtime.outcome == "blocked":
                return "blocked", runtime.reason or "La reconciliación activa quedó bloqueada."
            if matches_active and runtime.outcome == "recovery_required":
                if runtime.recovery_outcome == "manual_review":
                    return (
                        "manual_review",
                        runtime.reason
                        or "El item activo requiere revisión manual antes de continuar.",
                    )
                return (
                    "recovery",
                    runtime.reason
                    or "El item activo se está reconciliando antes de continuar.",
                )
            execution_state = contexts[active.id][1]
            if execution_state == "running":
                return "running", "Hay una ejecución activa; no se iniciará otra."
            if execution_state in {"succeeded", "failed", "cancelled"}:
                return "finishing", "La ejecución activa es terminal y espera finalizar su item."
            return "starting", "El item activo está iniciando o recuperando su ejecución durable."
        if runtime.issue:
            return "blocked", runtime.issue
        if runtime.outcome == "blocked":
            return "blocked", runtime.reason or "El scheduler no puede procesar la cola."
        queued_count = sum(record.state == "queued" for record in records)
        if queued_count:
            return "idle", f"Sin ejecución activa; {queued_count} item(s) esperan el scheduler."
        return "idle", "Sin ejecución activa ni items en espera."

    @staticmethod
    def _entry_presentation(record, execution_state, dashboard_state, is_active):
        if record.state == "queued":
            return "queued", "En espera de su turno durable."
        if record.state == "active":
            if dashboard_state == "paused":
                return "paused", "Activo conservado mientras la cola está pausada."
            if dashboard_state == "manual_review":
                return "manual_review", "El activo bloquea el siguiente item hasta revisión manual."
            if dashboard_state == "recovery":
                return "recovery", "El activo se reconcilia antes de considerar el siguiente item."
            if dashboard_state == "blocked":
                return "blocked", "El activo quedó bloqueado y conserva la exclusividad de cola."
            if execution_state == "running":
                return "running", "Ejecución activa."
            if execution_state in {"succeeded", "failed", "cancelled"}:
                return "finishing", "Ejecución terminal pendiente de finalizar el item activo."
            return "starting", "Claim durable activo; la ejecución se inicia o recupera por el scheduler."
        if record.state == "finished":
            return "finished", f"Item terminado; ejecución {execution_state}."
        if record.state == "removed":
            return "removed", "Item removido antes de iniciar."
        if record.state == "skipped":
            return "skipped", "Item omitido explícitamente antes de iniciar."
        return str(record.state), "Estado de cola no reconocido."

    def snapshot(self):
        try:
            durable = self.operations.snapshot()
            records = tuple(durable.items)
            control = durable.control
            if control.active_queue_item_id is not None and not any(
                record.id == control.active_queue_item_id and record.state == "active"
                for record in records
            ):
                raise QueueDashboardError("queue active control is inconsistent")
            contexts = {record.id: self._execution_context(record) for record in records}
            runtime = self._runtime()
            dashboard_state, dashboard_detail = self._dashboard_state(
                records, control, runtime, contexts
            )
            queued = [record for record in records if record.state == "queued"]
            queued_ids = tuple(record.id for record in queued)
            entries = []
            for record in records:
                project_id, execution_state, execution_number = contexts[record.id]
                is_active = record.id == control.active_queue_item_id
                presentation_state, detail = self._entry_presentation(
                    record, execution_state, dashboard_state, is_active
                )
                queued_index = queued_ids.index(record.id) if record.id in queued_ids else -1
                mutable = record.state == "queued"
                entries.append(
                    QueueDashboardEntry(
                        record.id,
                        project_id,
                        record.execution_id,
                        execution_number,
                        record.position,
                        record.state,
                        execution_state,
                        presentation_state,
                        detail,
                        record.terminal_reason,
                        is_active,
                        True,
                        mutable and queued_index > 0,
                        mutable and queued_index >= 0 and queued_index < len(queued_ids) - 1,
                        mutable,
                        mutable,
                        mutable,
                    )
                )
            return QueueDashboardSnapshot(
                tuple(entries),
                control.paused,
                control.active_queue_item_id,
                control.revision,
                dashboard_state,
                dashboard_detail,
                runtime.running,
            )
        except QueueOperationError as exc:
            self._failure("snapshot", exc)
        except (PersistenceError, OSError, TypeError, ValueError, AttributeError) as exc:
            self._failure("snapshot", exc)

    @staticmethod
    def _entry(snapshot, queue_item_id):
        ident = str(queue_item_id)
        matches = [entry for entry in snapshot.entries if entry.queue_item_id == ident]
        if len(matches) != 1:
            raise QueueDashboardError("queue item selection is missing or ambiguous")
        return matches[0]

    def _action(self, detail=None, *, selection_id=None):
        snapshot = self.snapshot()
        selection = (
            self._entry(snapshot, selection_id) if selection_id is not None else None
        )
        return QueueDashboardAction(snapshot, selection, detail)

    def select(self, queue_item_id):
        ident = self._id(queue_item_id, "queue item")
        try:
            detail = self.operations.select(ident)
            return self._action(detail, selection_id=ident)
        except QueueOperationError as exc:
            self._failure("selection", exc)

    def enqueue(self, project_id, execution_id):
        try:
            detail = self.operations.enqueue(project_id, execution_id)
            return self._action(detail, selection_id=detail.id)
        except QueueOperationError as exc:
            self._failure("enqueue", exc)

    def reorder(self, queue_item_ids, *, selection_id=None):
        try:
            detail = self.operations.reorder(queue_item_ids)
            return self._action(detail, selection_id=selection_id)
        except QueueOperationError as exc:
            self._failure("reorder", exc)

    def remove(self, queue_item_id, *, reason=None):
        ident = self._id(queue_item_id, "queue item")
        try:
            detail = self.operations.remove(ident, reason=reason)
            return self._action(detail, selection_id=ident)
        except QueueOperationError as exc:
            self._failure("remove", exc)

    def skip(self, queue_item_id, *, reason=None):
        ident = self._id(queue_item_id, "queue item")
        try:
            detail = self.operations.skip(ident, reason=reason)
            return self._action(detail, selection_id=ident)
        except QueueOperationError as exc:
            self._failure("skip", exc)

    def pause(self, *, expected_revision=None, selection_id=None):
        try:
            detail = self.operations.pause(expected_revision=expected_revision)
            return self._action(detail, selection_id=selection_id)
        except QueueOperationError as exc:
            self._failure("pause", exc)

    def resume(self, *, expected_revision=None, selection_id=None):
        try:
            detail = self.operations.resume(expected_revision=expected_revision)
            return self._action(detail, selection_id=selection_id)
        except QueueOperationError as exc:
            self._failure("resume", exc)

    def duplicate(self, queue_item_id):
        ident = self._id(queue_item_id, "queue item")
        try:
            detail = self.operations.duplicate(ident)
            return self._action(detail, selection_id=detail.queue_item.id)
        except QueueOperationError as exc:
            self._failure("duplicate", exc)


__all__ = [
    "QueueDashboardAction",
    "QueueDashboardEntry",
    "QueueDashboardError",
    "QueueDashboardSnapshot",
    "QueueDashboardUseCase",
    "QueueRuntimeSnapshot",
]
