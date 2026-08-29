"""Deterministic, logical correlation of generic ComfyUI history outputs."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping
import ntpath
import posixpath

from ..domain.core import BackendJobRef
from .http import HistoryResult, HistoryState


class OutputCorrelationStatus(str, Enum):
    VALID = "valid"
    NO_OUTPUTS = "no_outputs"
    MALFORMED = "malformed"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class OutputDescriptor:
    prompt_id: BackendJobRef
    node_id: str
    filename: str
    subfolder: str
    output_type: str


@dataclass(frozen=True)
class OutputCorrelationResult:
    prompt_id: BackendJobRef
    status: OutputCorrelationStatus
    descriptors: tuple[OutputDescriptor, ...] = ()
    reason: str | None = None


_FIELDS = {"filename", "subfolder", "type"}


def _basename(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value:
        return False
    if value in {".", ".."} or "/" in value or "\\" in value:
        return False
    drive, tail = ntpath.splitdrive(value)
    if drive or ntpath.isabs(value) or posixpath.isabs(value) or tail in {".", ".."}:
        return False
    return True


def _subfolder(value: Any) -> bool:
    if not isinstance(value, str) or "\x00" in value:
        return False
    if not value:
        return True
    drive, _ = ntpath.splitdrive(value)
    if drive or ntpath.isabs(value) or posixpath.isabs(value):
        return False
    parts = value.replace("\\", "/").split("/")
    return all(part not in {".", ".."} for part in parts)


def correlate_outputs(history: HistoryResult, job_ref: BackendJobRef) -> OutputCorrelationResult:
    """Correlate only the supplied job's terminal history entry, fail-closed."""
    # History may be reconstructed independently from durable persistence;
    # correlate by the value-object's semantic equality, while retaining the
    # caller-owned reference in every returned object.
    if not isinstance(job_ref, BackendJobRef) or history.prompt_id != job_ref:
        return OutputCorrelationResult(job_ref, OutputCorrelationStatus.UNKNOWN, reason="job reference mismatch")
    if history.state is not HistoryState.SUCCEEDED or not isinstance(history.raw, Mapping):
        return OutputCorrelationResult(job_ref, OutputCorrelationStatus.UNKNOWN, reason="history is not usable")
    outputs = history.raw.get("outputs")
    if outputs is None:
        return OutputCorrelationResult(job_ref, OutputCorrelationStatus.NO_OUTPUTS, reason="outputs absent")
    if not isinstance(outputs, Mapping):
        return OutputCorrelationResult(job_ref, OutputCorrelationStatus.MALFORMED, reason="outputs must be an object")
    found: list[OutputDescriptor] = []
    malformed = False

    def walk(node_id: Any, value: Any) -> None:
        nonlocal malformed
        if isinstance(value, Mapping):
            present = _FIELDS.intersection(value.keys())
            if present:
                if present != _FIELDS or not isinstance(node_id, str) or not node_id:
                    malformed = True
                elif (_basename(value.get("filename")) and _subfolder(value.get("subfolder"))
                      and isinstance(value.get("type"), str) and bool(value["type"])):
                    found.append(OutputDescriptor(job_ref, node_id, value["filename"], value["subfolder"], value["type"]))
                else:
                    malformed = True
                return
            for key in sorted(value, key=lambda x: str(x)):
                walk(node_id, value[key])
        elif isinstance(value, list):
            for item in value:
                walk(node_id, item)
        else:
            malformed = True

    for node_id in sorted(outputs, key=lambda x: str(x)):
        walk(node_id, outputs[node_id])
    if malformed:
        return OutputCorrelationResult(job_ref, OutputCorrelationStatus.MALFORMED, reason="malformed output descriptor")
    if not found:
        return OutputCorrelationResult(job_ref, OutputCorrelationStatus.NO_OUTPUTS)
    ordered = tuple(sorted(found, key=lambda d: (d.node_id, d.subfolder, d.filename, d.output_type)))
    # The logical artifact identity is its output descriptor, even if repeated
    # by distinct node/container locations; never silently deduplicate it.
    logical = [(d.filename, d.subfolder, d.output_type) for d in ordered]
    if len(set(logical)) != len(logical):
        return OutputCorrelationResult(job_ref, OutputCorrelationStatus.AMBIGUOUS, reason="duplicate descriptor")
    return OutputCorrelationResult(job_ref, OutputCorrelationStatus.VALID, ordered)
