"""F13.2 creation of an independent draft from reusable configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ..domain.config import GenerationConfig, GenerationConfigError, merge_chunk_overrides
from ..domain.core import Chunk, Execution, ExecutionId, Project, ProjectId, WorkflowProfileRef
from ..persistence.sqlite import PersistenceError


class CloneConfigurationError(ValueError):
    """The selected source cannot safely produce a new reusable draft."""


@dataclass(frozen=True)
class ClonedDraft:
    project_id: str
    execution_id: str
    execution_number: int


class CloneConfigurationUseCase:
    """Copy only the editable configuration surface into new aggregates.

    Runtime evidence is deliberately not represented in the new objects: new
    chunks have fresh identities, pending lifecycle and no attempts/frames.
    A single repository save makes creation of the Project and Execution
    atomic.
    """

    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _id(value, label):
        if not isinstance(value, str) or not value.strip():
            raise CloneConfigurationError(f"{label} id must be nonblank")
        return value.strip()

    def _load_source(self, project_id, execution_id):
        try:
            project, executions = self.repository.load(ProjectId(project_id))
        except PersistenceError as exc:
            raise CloneConfigurationError(f"source load failed: {exc}") from exc
        matches = [item for item in executions if str(item.id) == execution_id]
        if len(matches) != 1:
            raise CloneConfigurationError("source execution selection is missing or ambiguous")
        return project, matches[0]

    def _contained_input(self, value):
        if not isinstance(value, str) or not value.strip():
            raise CloneConfigurationError("source input path must be nonblank")
        path = Path(value)
        root = getattr(self.repository, "root", None)
        if root is None or path.is_absolute() or os.path.splitdrive(value)[0] or ".." in path.parts:
            raise CloneConfigurationError("source input path must be project-relative and contained")
        try:
            root = Path(root).resolve(strict=True)
            resolved = (root / path).resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            raise CloneConfigurationError("source input path must be project-relative and contained") from None
        if not resolved.is_file():
            raise CloneConfigurationError("source input path must be an existing regular file")
        return path.as_posix()

    def _build_clone(self, source_project_id, source_execution_id):
        """Materialize a fresh configuration-only aggregate without persisting it.

        Queue operations reuse this boundary so a selected queue item can be
        cloned and enqueued in the same SQLite transaction.  The public call
        below retains the original standalone clone behavior.
        """
        source_project = self._id(source_project_id, "source project")
        source_execution = self._id(source_execution_id, "source execution")
        project, execution = self._load_source(source_project, source_execution)
        if execution.workflow_profile_ref is None:
            raise CloneConfigurationError("source execution has no workflow profile")
        try:
            generation = GenerationConfig.from_scopes(project.defaults, execution.defaults)
        except GenerationConfigError as exc:
            raise CloneConfigurationError(f"source execution configuration is invalid: {exc}") from exc
        if generation.profile_ref != execution.workflow_profile_ref.value:
            raise CloneConfigurationError("source execution profile conflicts with configuration")
        if len(execution.chunks) != generation.chunk_count or [chunk.order for chunk in execution.chunks] != list(range(generation.chunk_count)):
            raise CloneConfigurationError("source chunk sequence conflicts with configuration")
        inputs = [self._contained_input(generation.initial_image)]
        inputs.extend(self._contained_input(value) for value in generation.references)
        values = generation.to_mapping()
        values["initial_image"], values["references"] = inputs[0], inputs[1:]

        target_project = Project(ProjectId(str(uuid4())))
        target_execution = Execution(
            target_project.id,
            ExecutionId(str(uuid4())),
            defaults=values,
            workflow_profile_ref=WorkflowProfileRef(generation.profile_ref),
        )
        try:
            for source_chunk in execution.chunks:
                # This also fail-closes legacy/private chunk fields rather than
                # smuggling them into the new public editable surface.
                overrides = merge_chunk_overrides(source_chunk.defaults, strict=True)
                target_execution.add_chunk(Chunk(order=source_chunk.order, defaults=overrides))
        except GenerationConfigError as exc:
            raise CloneConfigurationError(f"source chunk overrides are invalid: {exc}") from exc
        return target_project, target_execution

    def __call__(self, source_project_id, source_execution_id):
        target_project, target_execution = self._build_clone(
            source_project_id, source_execution_id
        )
        try:
            self.repository.save(target_project, [target_execution])
        except PersistenceError as exc:
            raise CloneConfigurationError(f"clone persistence failed: {exc}") from exc
        if target_execution.execution_number is None:
            raise CloneConfigurationError("clone execution number was not assigned")
        return ClonedDraft(str(target_project.id), str(target_execution.id), target_execution.execution_number)
