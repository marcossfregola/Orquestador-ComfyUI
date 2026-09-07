"""Executable, serializable generation-configuration contract."""
from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Mapping
import json
import math

from .core import ORCHESTRATION_TIMEOUT_DEFAULT_SECONDS


CONFIG_VERSION = 1
CONFIG_VERSION_KEY = "config_version"
DEFAULT_PROFILE_REF = "minimax-h3-ui"
SUPPORTED_PROFILE_REFS = frozenset({DEFAULT_PROFILE_REF})
DEFAULT_MEGAPIXELS = 0.6
DEFAULT_LENGTH = 294
DEFAULT_STEPS = 20
DEFAULT_FPS = 24
DEFAULT_REF_IMAGE_SIZE = "match"
DEFAULT_ALSO_REF_FIRST_FRAME = False
DEFAULT_ORCHESTRATION_TIMEOUT_SECONDS = ORCHESTRATION_TIMEOUT_DEFAULT_SECONDS
SUPPORTED_REF_IMAGE_SIZES = frozenset({"match"})

SUPPORTED_CONFIG_KEYS = frozenset(
    {
        "profile_ref",
        "initial_image",
        "references",
        "chunk_count",
        "prompts",
        "megapixels",
        "length",
        "steps",
        "fps",
        "ref_image_size",
        "also_ref_first_frame",
        "orchestration_timeout_seconds",
    }
)
# A chunk may carry only scalar generation overrides that the profile can
# bind.  Inputs, chunk cardinality and the complete prompt plan remain owned
# by the execution snapshot; accepting those fields at chunk scope would
# create a second configuration model.
CHUNK_OVERRIDE_KEYS = frozenset(
    {
        "prompt",
        "megapixels",
        "length",
        "steps",
        "fps",
        "ref_image_size",
        "also_ref_first_frame",
        "orchestration_timeout_seconds",
    }
)
FORBIDDEN_CONFIG_KEYS = frozenset(
    {"width", "height", "seed", "sampler", "scheduler", "ai", "ia"}
)


class GenerationConfigError(ValueError):
    """Raised when a generation configuration is unsupported or invalid."""


def validate_prompt(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GenerationConfigError("prompt must be nonblank")
    return value


def validate_parameter(name: str, value):
    """Validate one public parameter without depending on a workflow profile."""
    if name == "megapixels":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GenerationConfigError("megapixels must be numeric")
        if not math.isfinite(float(value)) or float(value) <= 0:
            raise GenerationConfigError("megapixels must be finite and positive")
        return float(value)
    if name in {"length", "steps", "fps", "orchestration_timeout_seconds"}:
        if type(value) is not int or value <= 0:
            raise GenerationConfigError(f"{name} must be a positive integer")
        return value
    if name == "ref_image_size":
        if not isinstance(value, str) or value not in SUPPORTED_REF_IMAGE_SIZES:
            raise GenerationConfigError("unsupported ref_image_size")
        return value
    if name == "also_ref_first_frame":
        if type(value) is not bool:
            raise GenerationConfigError("also_ref_first_frame must be boolean")
        return value
    raise GenerationConfigError(f"unsupported generation parameter: {name}")


def merge_generation_mappings(*scopes, strict: bool = False) -> dict:
    """Merge supported keys using project → execution → chunk precedence.

    Unknown keys in legacy project/execution defaults are ignored when
    ``strict`` is false because those mappings may contain unrelated domain
    defaults. Explicit configuration payloads should use ``strict=True``;
    unsupported public keys are rejected in either mode.
    """
    merged: dict = {}
    for scope in scopes:
        if scope is None:
            continue
        if not isinstance(scope, Mapping):
            raise GenerationConfigError("configuration scope must be a mapping")
        for key, value in scope.items():
            if not isinstance(key, str):
                raise GenerationConfigError("configuration keys must be strings")
            if key == CONFIG_VERSION_KEY:
                if type(value) is not int or value != CONFIG_VERSION:
                    raise GenerationConfigError("unsupported generation config version")
                continue
            if key in FORBIDDEN_CONFIG_KEYS or (key not in SUPPORTED_CONFIG_KEYS and strict):
                raise GenerationConfigError(f"unsupported generation config key: {key}")
            if key in SUPPORTED_CONFIG_KEYS:
                merged[key] = value
    return merged


def merge_chunk_overrides(*scopes, strict: bool = True) -> dict:
    """Merge the deliberately narrow override surface for one chunk.

    ``Chunk.defaults`` predates F11 and can contain unrelated F5/F6 values,
    so this helper is explicit rather than reusing the full execution schema.
    The singular ``prompt`` is accepted because a chunk owns its prompt;
    complete input lists and execution-level fields are rejected.
    """
    merged: dict = {}
    for scope in scopes:
        if scope is None:
            continue
        if not isinstance(scope, Mapping):
            raise GenerationConfigError("chunk configuration scope must be a mapping")
        for key, value in scope.items():
            if not isinstance(key, str):
                raise GenerationConfigError("chunk configuration keys must be strings")
            if key == CONFIG_VERSION_KEY:
                if type(value) is not int or value != CONFIG_VERSION:
                    raise GenerationConfigError("unsupported generation config version")
                continue
            if key in CHUNK_OVERRIDE_KEYS:
                if key == "prompt":
                    validate_prompt(value)
                merged[key] = value
                continue
            if key in FORBIDDEN_CONFIG_KEYS or strict:
                raise GenerationConfigError(f"unsupported chunk override: {key}")
    return merged


@dataclass(frozen=True, slots=True)
class GenerationConfig:
    """The single F11.1 configuration representation.

    Inputs and prompts are immutable tuples in memory and become JSON lists
    through :meth:`to_mapping`. The persisted mapping is intentionally flat so
    it can live in the existing ``Execution.defaults`` JSON column.
    """

    profile_ref: str = DEFAULT_PROFILE_REF
    initial_image: str = ""
    references: tuple[str, ...] = ()
    chunk_count: int | None = None
    prompts: tuple[str, ...] = ()
    megapixels: float = DEFAULT_MEGAPIXELS
    length: int = DEFAULT_LENGTH
    steps: int = DEFAULT_STEPS
    fps: int = DEFAULT_FPS
    ref_image_size: str = DEFAULT_REF_IMAGE_SIZE
    also_ref_first_frame: bool = DEFAULT_ALSO_REF_FIRST_FRAME
    orchestration_timeout_seconds: int = DEFAULT_ORCHESTRATION_TIMEOUT_SECONDS

    def __post_init__(self):
        if (
            not isinstance(self.profile_ref, str)
            or not self.profile_ref.strip()
            or self.profile_ref.strip() not in SUPPORTED_PROFILE_REFS
        ):
            raise GenerationConfigError("unsupported profile_ref")
        if not isinstance(self.initial_image, str) or not self.initial_image.strip():
            raise GenerationConfigError("initial_image is required")
        if not isinstance(self.references, (list, tuple)):
            raise GenerationConfigError("references must be a sequence")
        refs = tuple(self.references)
        if len(refs) != 6 or any(not isinstance(x, str) or not x.strip() for x in refs):
            raise GenerationConfigError("exactly six nonblank references are required")
        if not isinstance(self.prompts, (list, tuple)):
            raise GenerationConfigError("prompts must be a sequence")
        prompts = tuple(validate_prompt(value) for value in self.prompts)
        chunk_count = self.chunk_count
        if chunk_count is None:
            chunk_count = len(prompts)
        if type(chunk_count) is not int or chunk_count not in (2, 3):
            raise GenerationConfigError("chunk_count must be two or three")
        if len(prompts) != chunk_count:
            raise GenerationConfigError("one nonblank prompt is required per chunk")
        megapixels = validate_parameter("megapixels", self.megapixels)
        length = validate_parameter("length", self.length)
        steps = validate_parameter("steps", self.steps)
        fps = validate_parameter("fps", self.fps)
        ref_image_size = validate_parameter("ref_image_size", self.ref_image_size)
        also_ref_first_frame = validate_parameter(
            "also_ref_first_frame", self.also_ref_first_frame
        )
        timeout = validate_parameter(
            "orchestration_timeout_seconds", self.orchestration_timeout_seconds
        )
        object.__setattr__(self, "profile_ref", self.profile_ref.strip())
        object.__setattr__(self, "initial_image", self.initial_image.strip())
        object.__setattr__(self, "references", refs)
        object.__setattr__(self, "chunk_count", chunk_count)
        object.__setattr__(self, "prompts", prompts)
        object.__setattr__(self, "megapixels", megapixels)
        object.__setattr__(self, "length", length)
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "fps", fps)
        object.__setattr__(self, "ref_image_size", ref_image_size)
        object.__setattr__(self, "also_ref_first_frame", also_ref_first_frame)
        object.__setattr__(self, "orchestration_timeout_seconds", timeout)

    @classmethod
    def from_mapping(cls, mapping: Mapping, *, strict: bool = True) -> "GenerationConfig":
        if not isinstance(mapping, Mapping):
            raise GenerationConfigError("generation config must be a mapping")
        values = merge_generation_mappings(mapping, strict=strict)
        # Legacy executions stored prompts but not an explicit chunk count.
        # Infer only the unambiguous two/three-chunk shape; all other cases
        # still fail through the central constructor validation below.
        if "chunk_count" not in values and isinstance(values.get("prompts"), (list, tuple)):
            values["chunk_count"] = len(values["prompts"])
        return cls(**values)

    @classmethod
    def from_scopes(cls, *scopes) -> "GenerationConfig":
        return cls.from_mapping(merge_generation_mappings(*scopes), strict=True)

    @classmethod
    def from_json(cls, value: str) -> "GenerationConfig":
        try:
            mapping = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise GenerationConfigError("generation config JSON is invalid") from exc
        return cls.from_mapping(mapping)

    def to_mapping(self) -> dict:
        return {
            CONFIG_VERSION_KEY: CONFIG_VERSION,
            "profile_ref": self.profile_ref,
            "initial_image": self.initial_image,
            "references": list(self.references),
            "chunk_count": self.chunk_count,
            "prompts": list(self.prompts),
            "megapixels": self.megapixels,
            "length": self.length,
            "steps": self.steps,
            "fps": self.fps,
            "ref_image_size": self.ref_image_size,
            "also_ref_first_frame": self.also_ref_first_frame,
            "orchestration_timeout_seconds": self.orchestration_timeout_seconds,
        }

    def to_dict(self) -> dict:
        return self.to_mapping()

    def to_json(self) -> str:
        return json.dumps(self.to_mapping(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def with_updates(self, **updates) -> "GenerationConfig":
        unsupported = set(updates).difference(SUPPORTED_CONFIG_KEYS)
        if unsupported:
            raise GenerationConfigError(
                f"unsupported generation config key: {sorted(unsupported)[0]}"
            )
        return replace(self, **updates)


__all__ = [
    "CONFIG_VERSION",
    "CONFIG_VERSION_KEY",
    "DEFAULT_PROFILE_REF",
    "SUPPORTED_PROFILE_REFS",
    "DEFAULT_MEGAPIXELS",
    "DEFAULT_LENGTH",
    "DEFAULT_STEPS",
    "DEFAULT_FPS",
    "DEFAULT_REF_IMAGE_SIZE",
    "DEFAULT_ALSO_REF_FIRST_FRAME",
    "DEFAULT_ORCHESTRATION_TIMEOUT_SECONDS",
    "SUPPORTED_CONFIG_KEYS",
    "CHUNK_OVERRIDE_KEYS",
    "FORBIDDEN_CONFIG_KEYS",
    "GenerationConfigError",
    "validate_prompt",
    "GenerationConfig",
    "merge_generation_mappings",
    "merge_chunk_overrides",
    "validate_parameter",
]
