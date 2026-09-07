from collections.abc import Mapping
from pathlib import Path
import hashlib

from ..domain.config import (
    GenerationConfig,
    GenerationConfigError,
    merge_chunk_overrides,
    merge_generation_mappings,
)
from ..profiles.minimax_h3 import (
    FAST_E2E_CONFIG,
    H3_PROFILE,
    bind_inputs,
    configure_fast_e2e,
    load_api_template,
    rebind_first_frame,
)


class StartPreparationError(ValueError):
    pass


def _effective_upload_ref(value):
    if (
        not isinstance(value, dict)
        or value.get("type") != "input"
        or not isinstance(value.get("name"), str)
        or not value["name"].strip()
        or not isinstance(value.get("subfolder", ""), str)
    ):
        raise StartPreparationError("static upload response is malformed")
    subfolder = value.get("subfolder", "").strip().strip("/")
    name = value["name"].strip()
    if (
        not name
        or any(char in name for char in ("/", "\\"))
        or ".." in name.split("/")
        or ":" in name
        or any(char in subfolder for char in ("\\", ":"))
        or ".." in subfolder.split("/")
    ):
        raise StartPreparationError("static upload response is unsafe")
    return (subfolder + "/" if subfolder else "") + name


class StaticInputMaterializer:
    def __init__(self, client, root):
        self.client, self.root = client, Path(root).resolve()

    def __call__(self, paths):
        out = []
        for index, raw in enumerate(paths):
            if not isinstance(raw, str) or Path(raw).is_absolute():
                raise StartPreparationError("prepared static path is invalid")
            path = (self.root / raw).resolve()
            if not path.is_relative_to(self.root) or not path.is_file():
                raise StartPreparationError("prepared static file is missing")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            suffix = path.suffix.lower() if path.suffix else ".png"
            requested = f"{'initial' if index == 0 else f'ref-{index}'}-{digest}{suffix}"
            try:
                value = self.client.upload_image(
                    path,
                    subfolder="orquestador/static",
                    overwrite=False,
                    requested_filename=requested,
                )
            except Exception as exc:
                raise StartPreparationError(f"static upload failed: {exc}") from exc
            out.append(_effective_upload_ref(value))
        return out


class StartGuiChainUseCase:
    def __init__(self, repository, root, chain, template=None, materializer=None, transition_materializer=None):
        self.repository, self.root, self.chain, self.template = repository, Path(root).resolve(), chain, template
        self.materializer, self.transition_materializer = materializer, transition_materializer

    def _updates(
        self,
        *,
        config=None,
        generation_config=None,
        prompts=None,
        initial_image=None,
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
            raise StartPreparationError("config and generation_config are mutually exclusive")
        source = generation_config if generation_config is not None else config
        if source is None:
            values = {}
        elif isinstance(source, GenerationConfig):
            values = source.to_mapping()
        elif isinstance(source, Mapping):
            try:
                values = merge_generation_mappings(source, strict=True)
            except GenerationConfigError as exc:
                raise StartPreparationError(str(exc)) from exc
        else:
            raise StartPreparationError("generation config must be a mapping or GenerationConfig")
        explicit = {
            "prompts": prompts,
            "initial_image": initial_image,
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
                raise StartPreparationError(str(exc)) from exc
        return values

    def _effective_chunk_configs(self, execution, selected):
        """Resolve the narrow chunk scope over the execution snapshot.

        The execution carries the complete durable snapshot.  A chunk can
        only override the explicitly authorized scalar bindings (and its own
        prompt); arbitrary defaults, inputs, profile changes and chunk-plan
        changes are rejected before any materialization or submit.
        """
        resolved = []
        for index, chunk in enumerate(execution.chunks):
            if chunk.order != index or chunk.execution_id not in (None, execution.id):
                raise StartPreparationError("chunk ordering or ownership is invalid")
            try:
                overrides = merge_chunk_overrides(chunk.defaults, strict=True)
                values = selected.to_mapping()
                prompt = overrides.pop("prompt", None)
                if prompt is not None:
                    prompts = list(selected.prompts)
                    prompts[index] = prompt
                    values["prompts"] = prompts
                values.update(overrides)
                resolved.append(GenerationConfig.from_mapping(values, strict=True))
            except GenerationConfigError as exc:
                raise StartPreparationError(
                    f"chunk {index} generation configuration is invalid: {exc}"
                ) from exc
        return tuple(resolved)

    def __call__(
        self,
        project_id,
        execution_id,
        prompts=None,
        initial_image=None,
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
        fast_e2e=False,
        **extra,
    ):
        if type(fast_e2e) is not bool:
            raise StartPreparationError("fast_e2e must be a boolean")
        updates = self._updates(
            config=config,
            generation_config=generation_config,
            prompts=prompts,
            initial_image=initial_image,
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
        try:
            project, executions = self.repository.load(project_id)
        except Exception as exc:
            raise StartPreparationError(f"project load failed: {exc}") from exc
        matches = [item for item in executions if str(item.id) == str(execution_id)]
        if len(matches) != 1:
            raise StartPreparationError("execution selection is missing or ambiguous")
        execution = matches[0]
        if execution.workflow_profile_ref is None or execution.workflow_profile_ref.value != H3_PROFILE.name:
            raise StartPreparationError("execution is not prepared for minimax-h3-ui")
        try:
            persisted = GenerationConfig.from_scopes(project.defaults, execution.defaults)
        except GenerationConfigError as exc:
            raise StartPreparationError(f"persisted generation configuration is invalid: {exc}") from exc
        if persisted.profile_ref != H3_PROFILE.name:
            raise StartPreparationError("execution generation profile is unsupported")
        if len(execution.chunks) != persisted.chunk_count:
            raise StartPreparationError("persisted chunk count does not match execution")
        if initial_image is not None and initial_image != persisted.initial_image:
            raise StartPreparationError("initial image override is not a prepared durable path")
        if references is not None:
            if not isinstance(references, (list, tuple)) or list(references) != list(persisted.references):
                raise StartPreparationError("references must match prepared durable paths")
        try:
            selected = GenerationConfig.from_mapping(
                {**persisted.to_mapping(), **updates}, strict=True
            )
        except GenerationConfigError as exc:
            raise StartPreparationError(str(exc)) from exc
        if selected != persisted:
            raise StartPreparationError(
                "start configuration must match the durable snapshot; prepare it first"
            )
        if selected.profile_ref != H3_PROFILE.name:
            raise StartPreparationError("execution generation profile is unsupported")
        if (
            selected.initial_image != persisted.initial_image
            or list(selected.references) != list(persisted.references)
            or selected.chunk_count != len(execution.chunks)
        ):
            raise StartPreparationError("generation inputs must match prepared durable paths and chunks")
        chunk_configs = self._effective_chunk_configs(execution, selected)
        paths = [selected.initial_image, *selected.references]
        if any(
            not isinstance(value, str)
            or Path(value).is_absolute()
            or not (self.root / value).resolve().is_relative_to(self.root)
            or not (self.root / value).is_file()
            for value in paths
        ):
            raise StartPreparationError("prepared image/reference file is missing or invalid")
        if self.materializer is not None:
            try:
                materialized = list(self.materializer(paths))
            except StartPreparationError:
                raise
            except Exception as exc:
                raise StartPreparationError(f"static upload failed: {exc}") from exc
            if len(materialized) != 7 or any(not isinstance(value, str) or not value for value in materialized):
                raise StartPreparationError("static materialization is incomplete")
            image, refs = materialized[0], materialized[1:]
        else:
            image, refs = selected.initial_image, list(selected.references)
        template = load_api_template(self.template)
        if fast_e2e:
            template = configure_fast_e2e(template)
        bound = []
        for index, chunk_config in enumerate(chunk_configs):
            if fast_e2e:
                chunk_values = {
                    "megapixels": FAST_E2E_CONFIG["megapixels"],
                    "length": FAST_E2E_CONFIG["length"],
                    "steps": FAST_E2E_CONFIG["steps"],
                }
            else:
                chunk_values = {
                    "megapixels": chunk_config.megapixels,
                    "length": chunk_config.length,
                    "steps": chunk_config.steps,
                }
            chunk_values.update(
                {
                    "fps": chunk_config.fps,
                    "ref_image_size": chunk_config.ref_image_size,
                    "also_ref_first_frame": chunk_config.also_ref_first_frame,
                }
            )
            bound.append(
                bind_inputs(
                    template,
                    prompt=chunk_config.prompts[index],
                    first_frame=image if index == 0 else None,
                    references=refs,
                    **chunk_values,
                )
            )
        # Legacy executions may be missing newly introduced default keys.  A
        # canonical rewrite is safe here because ``selected`` is exactly the
        # durable configuration, never a transient start override.
        if dict(execution.defaults) != selected.to_mapping():
            previous_defaults = execution.defaults
            execution.defaults = selected.to_mapping()
            try:
                self.repository.save(project, executions)
            except Exception as exc:
                execution.defaults = previous_defaults
                raise StartPreparationError(f"generation configuration save failed: {exc}") from exc
        return self.chain.run(
            project,
            execution,
            bound,
            transition_rebinder=rebind_first_frame,
            transition_materializer=self.transition_materializer,
        )
