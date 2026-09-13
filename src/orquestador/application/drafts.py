"""F13.1 durable draft operations and read-only library projection.

A draft deliberately has no identity of its own: it is an editable-virgin
Execution with no durable queued/active QueueItem.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from uuid import uuid4

from ..domain.core import Chunk, Execution, ExecutionId, Lifecycle, Project, ProjectId, editable_virgin
from ..persistence.sqlite import PersistenceError


class DraftError(ValueError):
    """A selection or edit was not a safe F13.1 draft operation."""


@dataclass(frozen=True)
class DraftExecution:
    project_id: str
    execution_id: str
    execution_number: int
    defaults: Mapping
    chunks: tuple[Mapping, ...]


@dataclass(frozen=True)
class ExecutionListItem:
    project_id: str
    execution_id: str
    execution_number: int
    classification: str


class DraftUseCase:
    """Create, save, reopen and classify durable Execution-backed drafts."""

    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _id(value, kind):
        if not isinstance(value, str) or not value.strip():
            raise DraftError(f"{kind} id must be nonblank")
        return value.strip()

    @staticmethod
    def _mapping(value, label):
        if not isinstance(value, Mapping):
            raise DraftError(f"{label} must be a mapping")
        return dict(value)

    def _load(self, project_id):
        try:
            return self.repository.load(ProjectId(project_id))
        except PersistenceError as exc:
            if str(exc).strip().lower() == "project not found":
                return None, []
            raise DraftError(f"project load failed: {exc}") from exc

    def _live_queue(self, execution):
        try:
            return self.repository.has_live_queue_item(execution.id)
        except (PersistenceError, OSError, ValueError, AttributeError) as exc:
            raise DraftError(f"queue state read failed: {exc}") from exc

    @staticmethod
    def _has_recovery_evidence(execution):
        """Return durable runtime evidence that requires existing reconciliation."""
        return bool(execution.artifacts or execution.errors or any(
            chunk.attempts or chunk.first_frame is not None for chunk in execution.chunks
        ))

    def _require_draft(self, executions, execution_id):
        matches = [item for item in executions if str(item.id) == execution_id]
        if len(matches) != 1:
            raise DraftError("draft execution selection is missing or ambiguous")
        execution = matches[0]
        if not editable_virgin(execution) or self._live_queue(execution):
            raise DraftError("execution is not an editable draft")
        return execution

    @staticmethod
    def _apply_structure(execution, defaults, chunks):
        defaults = DraftUseCase._mapping(defaults, "execution defaults")
        if not isinstance(chunks, Sequence) or isinstance(chunks, (str, bytes)) or len(chunks) < 2:
            raise DraftError("draft chunks must contain at least two mappings")
        normalized = [DraftUseCase._mapping(chunk, f"draft chunk {index}") for index, chunk in enumerate(chunks)]
        execution.defaults = defaults
        execution.chunks = list(execution.chunks[:len(normalized)])
        for index, chunk_defaults in enumerate(normalized):
            if index == len(execution.chunks):
                execution.add_chunk(Chunk(order=index, defaults=chunk_defaults))
            else:
                execution.chunks[index].order = index
                execution.chunks[index].defaults = chunk_defaults

    @staticmethod
    def _record(execution):
        if execution.execution_number is None:
            raise DraftError("draft execution number was not assigned")
        return DraftExecution(
            str(execution.project_id), str(execution.id), execution.execution_number,
            dict(execution.defaults), tuple(dict(chunk.defaults) for chunk in execution.chunks),
        )

    def create(self, project_id, *, defaults, chunks, execution_id=None):
        project_key = self._id(project_id, "project")
        requested = None if execution_id is None else ExecutionId(self._id(execution_id, "execution"))
        project, executions = self._load(project_key)
        if project is None:
            project = Project(ProjectId(project_key))
        if requested is not None and any(str(item.id) == str(requested) for item in executions):
            raise DraftError("execution id already belongs to this project")
        execution = Execution(project.id, requested or ExecutionId(str(uuid4())))
        self._apply_structure(execution, defaults, chunks)
        try:
            self.repository.save(project, [*executions, execution])
        except PersistenceError as exc:
            raise DraftError(f"draft create failed: {exc}") from exc
        return self._record(execution)

    def save(self, project_id, execution_id, *, defaults, chunks):
        project_key = self._id(project_id, "project")
        execution_key = self._id(execution_id, "execution")
        project, executions = self._load(project_key)
        if project is None:
            raise DraftError("draft execution selection is missing or ambiguous")
        execution = self._require_draft(executions, execution_key)
        self._apply_structure(execution, defaults, chunks)
        try:
            self.repository.save_preparation_sequence(project, execution)
        except PersistenceError as exc:
            raise DraftError(f"draft save failed: {exc}") from exc
        return self._record(execution)

    def reopen(self, project_id, execution_id):
        project_key = self._id(project_id, "project")
        execution_key = self._id(execution_id, "execution")
        project, executions = self._load(project_key)
        if project is None:
            raise DraftError("draft execution selection is missing or ambiguous")
        return self._record(self._require_draft(executions, execution_key))

    def list_project_executions(self, project_id):
        project_key = self._id(project_id, "project")
        project, executions = self._load(project_key)
        if project is None:
            return []
        result = []
        for execution in executions:
            live = self._live_queue(execution)
            if live:
                # An active item is normal running only while its Execution is
                # running without durable runtime evidence.  Once evidence has
                # been persisted (or lifecycle disagrees), the existing recovery
                # contracts require reconciliation rather than a blind "running"
                # projection.  Neither spelling creates a new durable state.
                items = self.repository.list_queue_items()
                state = next((item.state.value for item in items if item.execution_id == execution.id and item.state.value in {"queued", "active"}), None)
                if state == "active":
                    classification = "running" if (
                        execution.state is Lifecycle.RUNNING
                        and not self._has_recovery_evidence(execution)
                    ) else "recovering"
                else:
                    classification = "queued"
            elif editable_virgin(execution):
                classification = "draft"
            elif execution.state is Lifecycle.RUNNING:
                classification = "running"
            elif execution.state in {Lifecycle.SUCCEEDED, Lifecycle.FAILED, Lifecycle.CANCELLED}:
                classification = execution.state.value
            else:
                classification = "attention_required"
            result.append(ExecutionListItem(str(project.id), str(execution.id), execution.execution_number, classification))
        return result

    def list_projects(self):
        try:
            project_ids = self.repository.list_project_ids()
        except (PersistenceError, AttributeError) as exc:
            raise DraftError(f"project list failed: {exc}") from exc
        return {str(project_id): self.list_project_executions(str(project_id)) for project_id in project_ids}
