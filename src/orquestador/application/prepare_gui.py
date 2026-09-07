"""Validated GUI preparation with immutable imports."""
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from ..domain.config import (
    GenerationConfig,
    GenerationConfigError,
    merge_generation_mappings,
)
from ..domain.core import Chunk, Execution, ExecutionId, Project, ProjectId, WorkflowProfileRef
from ..persistence.sqlite import PersistenceError
from ..profiles.minimax_h3 import H3_PROFILE


class PreparationError(ValueError):
    pass


class PrepareGuiUseCase:
    def __init__(self, repository, root, snapshot):
        self.repository, self.root, self.snapshot = repository, Path(root).resolve(), snapshot

    def _src(self, value, label):
        if not isinstance(value, str) or not value.strip():
            raise PreparationError(f"{label} is required")
        path = Path(value.strip())
        path = path if path.is_absolute() else self.root / path
        try:
            path = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PreparationError(f"{label} does not exist or is inaccessible") from exc
        if not path.is_file():
            raise PreparationError(f"{label} must be a file")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise PreparationError(f"{label} is inaccessible") from exc
        return path, data

    def _updates(
        self,
        *,
        config=None,
        generation_config=None,
        initial_image=None,
        prompts=None,
        references=None,
        chunk_count=None,
        megapixels=None,
        length=None,
        steps=None,
        fps=None,
        ref_image_size=None,
        also_ref_first_frame=None,
        orchestration_timeout_seconds=None,
        extra=None,
    ):
        if config is not None and generation_config is not None:
            raise PreparationError("config and generation_config are mutually exclusive")
        source = generation_config if generation_config is not None else config
        if source is None:
            values = {}
        elif isinstance(source, GenerationConfig):
            values = source.to_mapping()
        elif isinstance(source, Mapping):
            try:
                values = merge_generation_mappings(source, strict=True)
            except GenerationConfigError as exc:
                raise PreparationError(str(exc)) from exc
        else:
            raise PreparationError("generation config must be a mapping or GenerationConfig")
        explicit = {
            "initial_image": initial_image,
            "prompts": prompts,
            "references": references,
            "chunk_count": chunk_count,
            "megapixels": megapixels,
            "length": length,
            "steps": steps,
            "fps": fps,
            "ref_image_size": ref_image_size,
            "also_ref_first_frame": also_ref_first_frame,
            "orchestration_timeout_seconds": orchestration_timeout_seconds,
        }
        values.update({key: value for key, value in explicit.items() if value is not None})
        if extra:
            try:
                values.update(merge_generation_mappings(extra, strict=True))
            except GenerationConfigError as exc:
                raise PreparationError(str(exc)) from exc
        return values

    def __call__(
        self,
        project_id=None,
        execution_id=None,
        initial_image=None,
        prompts=None,
        references=None,
        chunk_count=None,
        config=None,
        generation_config=None,
        megapixels=None,
        length=None,
        steps=None,
        fps=None,
        ref_image_size=None,
        also_ref_first_frame=None,
        orchestration_timeout_seconds=None,
        **extra,
    ):
        updates = self._updates(
            config=config,
            generation_config=generation_config,
            initial_image=initial_image,
            prompts=prompts,
            references=references,
            chunk_count=chunk_count,
            megapixels=megapixels,
            length=length,
            steps=steps,
            fps=fps,
            ref_image_size=ref_image_size,
            also_ref_first_frame=also_ref_first_frame,
            orchestration_timeout_seconds=orchestration_timeout_seconds,
            extra=extra,
        )
        pid = ProjectId(project_id.strip()) if isinstance(project_id, str) and project_id.strip() else ProjectId(str(uuid4()))
        eid = ExecutionId(execution_id.strip()) if isinstance(execution_id, str) and execution_id.strip() else ExecutionId(str(uuid4()))
        try:
            project, executions = self.repository.load(pid)
        except PersistenceError as exc:
            if str(exc).strip().lower() != "project not found":
                raise PreparationError(f"project load failed: {exc}") from exc
            project, executions = Project(pid), []
        matches = [item for item in executions if str(item.id) == str(eid)]
        if len(matches) > 1:
            raise PreparationError("execution selection is ambiguous")
        existing = matches[0] if matches else None
        scopes = [project.defaults]
        if existing is not None:
            scopes.append(existing.defaults)
        scopes.append(updates)
        try:
            values = merge_generation_mappings(*scopes)
        except GenerationConfigError as exc:
            raise PreparationError(str(exc)) from exc
        prompts_value = values.get("prompts", ())
        refs_value = values.get("references", ())
        count_value = values.get("chunk_count")
        if count_value is None and isinstance(prompts_value, (list, tuple)):
            count_value = len(prompts_value)
        if not isinstance(prompts_value, (list, tuple)):
            raise PreparationError("prompts must be a sequence")
        if not isinstance(refs_value, (list, tuple)):
            raise PreparationError("references must be a sequence")
        prompts_value = list(prompts_value)
        refs_value = list(refs_value)
        if type(count_value) is not int or count_value not in (2, 3):
            raise PreparationError("chunk count must be two or three")
        if len(prompts_value) != count_value or any(
            not isinstance(value, str) or not value.strip() for value in prompts_value
        ):
            raise PreparationError("one nonblank prompt is required per chunk")
        if len(refs_value) != 6:
            raise PreparationError("exactly six H3 references are required")
        source = [self._src(values.get("initial_image"), "initial image")]
        source.extend(self._src(value, f"reference slot {index}") for index, value in enumerate(refs_value))
        relative = []
        for path, data in source:
            base = (Path("inputs") / path.name).as_posix()
            target = self.root / base
            try:
                conflict = target.exists() and (not target.is_file() or target.read_bytes() != data)
            except OSError as exc:
                raise PreparationError(f"collision check failed for {base}") from exc
            if conflict:
                base = (Path("inputs") / (sha256(data).hexdigest() + "_" + path.name)).as_posix()
            relative.append(base)
        for relative_path, (_, data) in zip(relative, source):
            target = self.root / relative_path
            try:
                conflict = target.exists() and (not target.is_file() or target.read_bytes() != data)
            except OSError as exc:
                raise PreparationError(f"destination check failed for {relative_path}") from exc
            if conflict:
                raise PreparationError(f"import collision for {relative_path}")
        values.update(
            {
                "profile_ref": values.get("profile_ref", H3_PROFILE.name),
                "initial_image": relative[0],
                "prompts": prompts_value,
                "references": relative[1:],
                "chunk_count": count_value,
            }
        )
        try:
            generation = GenerationConfig.from_mapping(values, strict=True)
        except GenerationConfigError as exc:
            raise PreparationError(str(exc)) from exc
        if generation.profile_ref != H3_PROFILE.name:
            raise PreparationError("execution is not prepared for minimax-h3-ui")
        if existing is not None:
            if existing.project_id != project.id or existing.workflow_profile_ref is None or existing.workflow_profile_ref.value != H3_PROFILE.name:
                raise PreparationError("existing execution conflicts with preparation")
            try:
                existing_generation = GenerationConfig.from_scopes(project.defaults, existing.defaults)
            except GenerationConfigError as exc:
                raise PreparationError(f"existing execution configuration is invalid: {exc}") from exc
            if existing_generation != generation or len(existing.chunks) != count_value:
                raise PreparationError("existing execution conflicts with preparation")
        else:
            existing = Execution(
                project.id,
                eid,
                defaults=generation.to_mapping(),
                workflow_profile_ref=WorkflowProfileRef(H3_PROFILE.name),
            )
            for index in range(count_value):
                existing.add_chunk(Chunk(order=index))
        made, made_dirs = [], []
        previous_defaults = existing.defaults
        try:
            for relative_path, (_, data) in zip(relative, source):
                target = self.root / relative_path
                if not target.exists():
                    missing, parent = [], target.parent
                    while parent != self.root and not parent.exists():
                        missing.append(parent)
                        parent = parent.parent
                    target.parent.mkdir(parents=True, exist_ok=True)
                    made_dirs.extend(missing)
                    target.write_bytes(data)
                    made.append(target)
            if dict(existing.defaults) != generation.to_mapping():
                existing.defaults = generation.to_mapping()
            if not matches:
                self.repository.save(project, [*executions, existing])
            else:
                self.repository.save(project, executions)
        except Exception as exc:
            existing.defaults = previous_defaults
            for target in made:
                try:
                    target.unlink()
                except OSError:
                    pass
            for parent in sorted(set(made_dirs), key=lambda value: len(value.parts), reverse=True):
                try:
                    if parent != self.root and parent.exists() and not any(parent.iterdir()):
                        parent.rmdir()
                except OSError:
                    pass
            if isinstance(exc, PersistenceError):
                raise PreparationError(f"persistence save failed: {exc}") from exc
            raise PreparationError(f"import failed: {exc}") from exc
        return self.snapshot(str(project.id), str(existing.id))
