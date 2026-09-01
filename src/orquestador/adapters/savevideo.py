"""Strict resolver for the adopted ComfyUI SaveVideo history contract."""
from __future__ import annotations

from typing import Any, Mapping
from .outputs import (OutputCorrelationResult, OutputCorrelationStatus, OutputDescriptor,
                      _basename, _subfolder)
from .http import HistoryResult, HistoryState
from ..domain.core import BackendJobRef


def resolve_savevideo_output(history: HistoryResult, job_ref: BackendJobRef,
                             expected_node_id: str = "92") -> OutputCorrelationResult:
    """Resolve exactly one SaveVideo ``images`` descriptor for the bound node.

    SaveVideo metadata is intentionally ignored; only the explicit output-bearing
    ``images`` list participates in correlation.
    """
    if not isinstance(job_ref, BackendJobRef) or history.prompt_id != job_ref:
        return OutputCorrelationResult(job_ref, OutputCorrelationStatus.UNKNOWN, reason="job reference mismatch")
    if history.state is not HistoryState.SUCCEEDED or not isinstance(history.raw, Mapping):
        return OutputCorrelationResult(job_ref, OutputCorrelationStatus.UNKNOWN, reason="history is not usable")
    outputs = history.raw.get("outputs")
    if not isinstance(outputs, Mapping):
        return OutputCorrelationResult(job_ref, OutputCorrelationStatus.NO_OUTPUTS if outputs is None else OutputCorrelationStatus.MALFORMED)
    node = outputs.get(expected_node_id)
    if not isinstance(expected_node_id, str) or not expected_node_id or not isinstance(node, Mapping):
        return OutputCorrelationResult(job_ref, OutputCorrelationStatus.NO_OUTPUTS)
    images = node.get("images")
    if not isinstance(images, list):
        return OutputCorrelationResult(job_ref, OutputCorrelationStatus.MALFORMED, reason="images must be a list")
    if len(images) != 1:
        return OutputCorrelationResult(job_ref, OutputCorrelationStatus.AMBIGUOUS if len(images) > 1 else OutputCorrelationStatus.NO_OUTPUTS)
    item = images[0]
    if (not isinstance(item, Mapping) or set(item) != {"filename", "subfolder", "type"}
            or not _basename(item.get("filename")) or not _subfolder(item.get("subfolder"))
            or item.get("type") != "output" or not str(item["filename"]).lower().endswith(".mp4")):
        return OutputCorrelationResult(job_ref, OutputCorrelationStatus.MALFORMED, reason="invalid SaveVideo descriptor")
    descriptor = OutputDescriptor(job_ref, expected_node_id, item["filename"], item["subfolder"], item["type"])
    return OutputCorrelationResult(job_ref, OutputCorrelationStatus.VALID, (descriptor,))


# Plural alias keeps the adapter discoverable alongside generic correlation APIs.
resolve_savevideo_outputs = resolve_savevideo_output
