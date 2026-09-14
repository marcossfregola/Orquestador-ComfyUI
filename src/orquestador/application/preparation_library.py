"""F13.6 application boundary for the preparation library.

The library deliberately projects existing durable aggregates.  It does not
introduce a second lifecycle, cache mutable configuration in the UI, or make
an execution depend dynamically on a global default, preset, or template.
"""
from __future__ import annotations

from dataclasses import dataclass

from .chunk_templates import ChunkTemplateError, ChunkTemplatesUseCase
from .clone_configuration import CloneConfigurationError, CloneConfigurationUseCase
from .drafts import DraftError, DraftUseCase
from .global_defaults import GlobalDefaultsError, GlobalDefaultsUseCase
from .technical_presets import TechnicalPresetError, TechnicalPresetsUseCase


class PreparationLibraryError(ValueError):
    """A library projection or delegated preparation operation was unsafe."""


@dataclass(frozen=True)
class LibraryExecution:
    """One visible execution, with technical identities kept for the caller only."""

    project_id: str
    execution_id: str
    execution_number: int
    classification: str
    can_open: bool
    can_edit: bool
    can_clone: bool


@dataclass(frozen=True)
class LibraryProject:
    project_id: str
    executions: tuple[LibraryExecution, ...]


@dataclass(frozen=True)
class LibraryTechnicalPreset:
    preset_id: str
    name: str
    mapping: tuple[tuple[str, object], ...]
    is_default: bool


@dataclass(frozen=True)
class LibraryChunkTemplate:
    template_id: str
    name: str
    prompts: tuple[str, ...]


@dataclass(frozen=True)
class PreparationLibrarySnapshot:
    """Immutable data consumed by the F13.6 presentation boundary."""

    projects: tuple[LibraryProject, ...]
    global_defaults: tuple[tuple[str, object], ...]
    technical_presets: tuple[LibraryTechnicalPreset, ...]
    chunk_templates: tuple[LibraryChunkTemplate, ...]


@dataclass(frozen=True)
class LibrarySelection:
    project_id: str
    execution_id: str
    execution_number: int
    classification: str
    can_open: bool
    can_edit: bool
    can_clone: bool


class PreparationLibraryUseCase:
    """Expose existing F13 authorities through one UI-safe application seam.

    All configuration actions delegate to their owning use cases.  In
    particular, apply/clone operations remain by-value operations and their
    draft/queue guards continue to live below this convenience boundary.
    """

    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _id(value, label):
        if not isinstance(value, str) or not value.strip():
            raise PreparationLibraryError(f"{label} id must be nonblank")
        return value.strip()

    @staticmethod
    def _execution(item):
        classification = str(item.classification)
        # Opening is a read operation for every correctly projected row.
        # Editing remains exclusive to the existing, derived draft state.
        # CloneConfigurationUseCase owns the final source validation; all
        # ordinary lifecycle states can be a useful configuration source.
        return LibraryExecution(
            str(item.project_id),
            str(item.execution_id),
            int(item.execution_number),
            classification,
            True,
            classification == "draft",
            classification != "attention_required",
        )

    @staticmethod
    def _preset(item):
        return LibraryTechnicalPreset(
            str(item.id),
            str(item.name),
            tuple((str(key), value) for key, value in sorted(item.mapping.items())),
            bool(item.is_default),
        )

    @staticmethod
    def _template(item):
        return LibraryChunkTemplate(str(item.id), str(item.name), tuple(item.prompts))

    @staticmethod
    def _failure(operation, exc):
        if isinstance(exc, PreparationLibraryError):
            raise exc
        raise PreparationLibraryError(f"preparation library {operation} failed: {exc}") from exc

    def snapshot(self):
        """Build a fresh immutable projection from the authoritative cases."""
        try:
            drafts = DraftUseCase(self.repository)
            by_project = drafts.list_projects()
            projects = tuple(
                LibraryProject(
                    project_id,
                    tuple(self._execution(item) for item in items),
                )
                for project_id, items in sorted(by_project.items())
            )
            defaults = GlobalDefaultsUseCase(self.repository).read().to_mapping()
            presets = tuple(
                self._preset(item)
                for item in TechnicalPresetsUseCase(self.repository).list()
            )
            templates = tuple(
                self._template(item)
                for item in ChunkTemplatesUseCase(self.repository).list()
            )
            return PreparationLibrarySnapshot(
                projects,
                tuple((str(key), value) for key, value in sorted(defaults.items())),
                presets,
                templates,
            )
        except (
            DraftError,
            GlobalDefaultsError,
            TechnicalPresetError,
            ChunkTemplateError,
            OSError,
            TypeError,
            ValueError,
            AttributeError,
        ) as exc:
            self._failure("snapshot", exc)

    def _selected_execution(self, project_id, execution_id):
        project_key = self._id(project_id, "project")
        execution_key = self._id(execution_id, "execution")
        try:
            rows = DraftUseCase(self.repository).list_project_executions(project_key)
            matches = [
                self._execution(item)
                for item in rows
                if item.execution_id == execution_key
            ]
        except (DraftError, OSError, TypeError, ValueError, AttributeError) as exc:
            self._failure("selection", exc)
        if len(matches) != 1:
            raise PreparationLibraryError("library execution selection is missing or ambiguous")
        item = matches[0]
        return LibrarySelection(
            item.project_id,
            item.execution_id,
            item.execution_number,
            item.classification,
            item.can_open,
            item.can_edit,
            item.can_clone,
        )

    def select(self, project_id, execution_id):
        """Resolve one visible row without exposing repository access to a widget."""
        return self._selected_execution(project_id, execution_id)

    def create_draft(self, project_id):
        """Create the initial editable F13 draft through its existing owner.

        A new library draft deliberately contains only the technical snapshot
        captured by ``DraftUseCase`` and two editable prompt placeholders.
        The established Prepare flow remains responsible for materializing
        images and finalising a runnable generation configuration.
        """
        project_key = self._id(project_id, "project")
        try:
            created = DraftUseCase(self.repository).create(
                project_key,
                defaults={},
                chunks=({"prompt": ""}, {"prompt": ""}),
            )
            return self._selected_execution(created.project_id, created.execution_id)
        except (DraftError, OSError, TypeError, ValueError) as exc:
            self._failure("draft create", exc)

    def clone(self, project_id, execution_id):
        """Create a fresh configuration-only draft through the canonical F13.2 case."""
        source = self._selected_execution(project_id, execution_id)
        if not source.can_clone:
            raise PreparationLibraryError("selected execution cannot be cloned safely")
        try:
            cloned = CloneConfigurationUseCase(self.repository)(
                source.project_id, source.execution_id
            )
            return self._selected_execution(cloned.project_id, cloned.execution_id)
        except (CloneConfigurationError, DraftError, OSError, TypeError, ValueError) as exc:
            self._failure("clone", exc)

    # Global Defaults -------------------------------------------------
    def update_global_defaults(self, mapping):
        try:
            return GlobalDefaultsUseCase(self.repository).update(mapping)
        except (GlobalDefaultsError, OSError, TypeError, ValueError) as exc:
            self._failure("global defaults update", exc)

    # Technical Presets -----------------------------------------------
    def create_preset(self, name, mapping, *, is_default=False):
        try:
            return TechnicalPresetsUseCase(self.repository).create(
                name, mapping, is_default=is_default
            )
        except (TechnicalPresetError, OSError, TypeError, ValueError) as exc:
            self._failure("preset create", exc)

    def update_preset(self, preset_id, mapping):
        try:
            return TechnicalPresetsUseCase(self.repository).update(preset_id, mapping)
        except (TechnicalPresetError, OSError, TypeError, ValueError) as exc:
            self._failure("preset update", exc)

    def rename_preset(self, preset_id, name):
        try:
            return TechnicalPresetsUseCase(self.repository).rename(preset_id, name)
        except (TechnicalPresetError, OSError, TypeError, ValueError) as exc:
            self._failure("preset rename", exc)

    def delete_preset(self, preset_id):
        try:
            return TechnicalPresetsUseCase(self.repository).delete(preset_id)
        except (TechnicalPresetError, OSError, TypeError, ValueError) as exc:
            self._failure("preset delete", exc)

    def set_default_preset(self, preset_id):
        try:
            return TechnicalPresetsUseCase(self.repository).set_default(preset_id)
        except (TechnicalPresetError, OSError, TypeError, ValueError) as exc:
            self._failure("preset default", exc)

    def clear_default_preset(self):
        try:
            return TechnicalPresetsUseCase(self.repository).clear_default()
        except (TechnicalPresetError, OSError, TypeError, ValueError) as exc:
            self._failure("preset default clear", exc)

    def apply_preset(self, preset_id, project_id, execution_id):
        try:
            return TechnicalPresetsUseCase(self.repository).apply(
                preset_id,
                self._id(project_id, "project"),
                self._id(execution_id, "execution"),
            )
        except (TechnicalPresetError, OSError, TypeError, ValueError) as exc:
            self._failure("preset application", exc)

    # Chunk Templates -------------------------------------------------
    def create_template(self, name, prompts):
        try:
            return ChunkTemplatesUseCase(self.repository).create(name, prompts)
        except (ChunkTemplateError, OSError, TypeError, ValueError) as exc:
            self._failure("template create", exc)

    def update_template(self, template_id, prompts):
        try:
            return ChunkTemplatesUseCase(self.repository).update(template_id, prompts)
        except (ChunkTemplateError, OSError, TypeError, ValueError) as exc:
            self._failure("template update", exc)

    def rename_template(self, template_id, name):
        try:
            return ChunkTemplatesUseCase(self.repository).rename(template_id, name)
        except (ChunkTemplateError, OSError, TypeError, ValueError) as exc:
            self._failure("template rename", exc)

    def duplicate_template(self, template_id, name):
        try:
            return ChunkTemplatesUseCase(self.repository).duplicate(template_id, name)
        except (ChunkTemplateError, OSError, TypeError, ValueError) as exc:
            self._failure("template duplicate", exc)

    def delete_template(self, template_id):
        try:
            return ChunkTemplatesUseCase(self.repository).delete(template_id)
        except (ChunkTemplateError, OSError, TypeError, ValueError) as exc:
            self._failure("template delete", exc)

    def apply_template(self, template_id, project_id, execution_id):
        try:
            return ChunkTemplatesUseCase(self.repository).apply(
                template_id,
                self._id(project_id, "project"),
                self._id(execution_id, "execution"),
            )
        except (ChunkTemplateError, OSError, TypeError, ValueError) as exc:
            self._failure("template application", exc)


__all__ = [
    "PreparationLibraryError",
    "LibraryExecution",
    "LibraryProject",
    "LibraryTechnicalPreset",
    "LibraryChunkTemplate",
    "PreparationLibrarySnapshot",
    "LibrarySelection",
    "PreparationLibraryUseCase",
]
