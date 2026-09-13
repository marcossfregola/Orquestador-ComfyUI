"""F13.7 durable product-queue operations, deliberately without a scheduler."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from ..domain.core import QueueControl, QueueItem, QueueItemState
from ..persistence.sqlite import PersistenceError
from .clone_configuration import CloneConfigurationError, CloneConfigurationUseCase


class QueueOperationError(ValueError):
    """A requested queue operation was not safe or could not persist."""


@dataclass(frozen=True)
class QueueEntry:
    id: str
    execution_id: str
    position: int
    state: str
    created_at: datetime
    updated_at: datetime
    terminal_reason: str | None


@dataclass(frozen=True)
class QueueControlSnapshot:
    paused: bool
    active_queue_item_id: str | None
    revision: int


@dataclass(frozen=True)
class QueueSnapshot:
    items: tuple[QueueEntry, ...]
    control: QueueControlSnapshot


@dataclass(frozen=True)
class QueuedClone:
    source_queue_item_id: str
    project_id: str
    execution_id: str
    execution_number: int
    queue_item: QueueEntry


class QueueOperationsUseCase:
    """Application boundary for F13.7's manual queue administration.

    The case of use never claims, starts, submits, finishes, or recovers an
    item.  Those transitions belong to F13.8/F13.9.  It only admits an
    editable virgin execution, maintains order among ``queued`` items and
    terminalizes explicitly selected pending work.
    """

    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _id(value, label):
        if not isinstance(value, str) or not value.strip():
            raise QueueOperationError(f"{label} id must be nonblank")
        return value.strip()

    @staticmethod
    def _reason(value, fallback):
        value = fallback if value is None else value
        if not isinstance(value, str) or not value.strip():
            raise QueueOperationError("queue terminal reason must be nonblank")
        return value.strip()

    @staticmethod
    def _record(item):
        if not isinstance(item, QueueItem):
            raise QueueOperationError("invalid durable queue item")
        return QueueEntry(
            str(item.id),
            str(item.execution_id),
            item.position,
            item.state.value,
            item.created_at,
            item.updated_at,
            item.terminal_reason,
        )

    @staticmethod
    def _control(control):
        if not isinstance(control, QueueControl):
            raise QueueOperationError("invalid durable queue control")
        return QueueControlSnapshot(
            control.paused,
            str(control.active_queue_item_id) if control.active_queue_item_id else None,
            control.revision,
        )

    @staticmethod
    def _failure(operation, exc):
        if isinstance(exc, QueueOperationError):
            raise exc
        raise QueueOperationError(f"queue {operation} failed: {exc}") from exc

    def list(self):
        try:
            return tuple(self._record(item) for item in self.repository.list_queue_items())
        except (PersistenceError, OSError, ValueError, TypeError, AttributeError) as exc:
            self._failure("list", exc)

    def read(self, queue_item_id):
        ident = self._id(queue_item_id, "queue item")
        try:
            item = self.repository.get_queue_item(ident)
        except (PersistenceError, OSError, ValueError, TypeError, AttributeError) as exc:
            self._failure("read", exc)
        if item is None:
            raise QueueOperationError("queue item selection is missing or ambiguous")
        return self._record(item)

    def select(self, queue_item_id):
        """Validate and resolve one durable selection without changing it."""
        return self.read(queue_item_id)

    def control(self):
        try:
            return self._control(self.repository.get_queue_control())
        except (PersistenceError, OSError, ValueError, TypeError, AttributeError) as exc:
            self._failure("control read", exc)

    def snapshot(self):
        try:
            items, control = self.repository.load_queue_state()
            return QueueSnapshot(
                tuple(self._record(item) for item in items), self._control(control)
            )
        except (PersistenceError, OSError, ValueError, TypeError, AttributeError) as exc:
            self._failure("snapshot", exc)

    def enqueue(self, project_id, execution_id, *, queue_item_id=None):
        project_key = self._id(project_id, "project")
        execution_key = self._id(execution_id, "execution")
        item_key = None if queue_item_id is None else self._id(queue_item_id, "queue item")
        try:
            if str(self.repository.execution_project_id(execution_key)) != project_key:
                raise QueueOperationError("execution selection is missing or ambiguous")
            return self._record(
                self.repository.enqueue_execution(execution_key, queue_item_id=item_key)
            )
        except (PersistenceError, OSError, ValueError, TypeError, AttributeError) as exc:
            self._failure("enqueue", exc)

    def reorder(self, queue_item_ids):
        if not isinstance(queue_item_ids, Sequence) or isinstance(
            queue_item_ids, (str, bytes, bytearray)
        ):
            raise QueueOperationError("queue order must be a sequence of queue item ids")
        order = tuple(self._id(item_id, "queue item") for item_id in queue_item_ids)
        try:
            return tuple(
                self._record(item) for item in self.repository.reorder_queue_items(order)
            )
        except (PersistenceError, OSError, ValueError, TypeError, AttributeError) as exc:
            self._failure("reorder", exc)

    def remove(self, queue_item_id, *, reason=None):
        ident = self._id(queue_item_id, "queue item")
        message = self._reason(reason, "operator removed")
        try:
            return self._record(
                self.repository.terminalize_queued_queue_item(
                    ident, QueueItemState.REMOVED, message
                )
            )
        except (PersistenceError, OSError, ValueError, TypeError, AttributeError) as exc:
            self._failure("remove", exc)

    def skip(self, queue_item_id, *, reason=None):
        ident = self._id(queue_item_id, "queue item")
        message = self._reason(reason, "operator skipped")
        try:
            return self._record(
                self.repository.terminalize_queued_queue_item(
                    ident, QueueItemState.SKIPPED, message
                )
            )
        except (PersistenceError, OSError, ValueError, TypeError, AttributeError) as exc:
            self._failure("skip", exc)

    def pause(self, *, expected_revision=None):
        try:
            return self._control(
                self.repository.set_queue_paused(True, expected_revision=expected_revision)
            )
        except (PersistenceError, OSError, ValueError, TypeError, AttributeError) as exc:
            self._failure("pause", exc)

    def resume(self, *, expected_revision=None):
        try:
            return self._control(
                self.repository.set_queue_paused(False, expected_revision=expected_revision)
            )
        except (PersistenceError, OSError, ValueError, TypeError, AttributeError) as exc:
            self._failure("resume", exc)

    def duplicate(self, queue_item_id, *, new_queue_item_id=None):
        """Clone a selected pending item and enqueue the fresh execution atomically."""
        source = self.select(queue_item_id)
        if source.state != QueueItemState.QUEUED.value:
            raise QueueOperationError("only queued items may be duplicated")
        item_key = (
            None
            if new_queue_item_id is None
            else self._id(new_queue_item_id, "new queue item")
        )
        try:
            source_project_id = self.repository.execution_project_id(source.execution_id)
            target_project, target_execution = CloneConfigurationUseCase(
                self.repository
            )._build_clone(str(source_project_id), source.execution_id)
            item = self.repository.save_new_execution_and_enqueue(
                target_project,
                target_execution,
                queue_item_id=item_key,
                expected_source_queue_item_id=source.id,
            )
        except (CloneConfigurationError, PersistenceError, OSError, ValueError, TypeError, AttributeError) as exc:
            self._failure("duplicate", exc)
        if target_execution.execution_number is None:
            raise QueueOperationError("queued clone execution number was not assigned")
        return QueuedClone(
            source.id,
            str(target_project.id),
            str(target_execution.id),
            target_execution.execution_number,
            self._record(item),
        )
