"""Explicit trusted-root validation for already-correlated output descriptors."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .outputs import OutputDescriptor


class PhysicalOutputStatus(str, Enum):
    EXISTS = "exists"
    MISSING = "missing"
    NOT_FILE = "not_file"
    UNREADABLE = "unreadable"
    OUTSIDE_ROOT = "outside_root"
    INVALID_ROOT = "invalid_root"


@dataclass(frozen=True)
class PhysicalOutputEvidence:
    descriptor: OutputDescriptor
    status: PhysicalOutputStatus
    trusted_root: Path
    resolved_path: Path | None = None
    reason: str | None = None


def _contained(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def validate_physical_output(
    descriptor: OutputDescriptor, trusted_root: str | Path
) -> PhysicalOutputEvidence:
    """Validate one descriptor against only the caller-supplied trusted root."""
    root_input = Path(trusted_root)
    try:
        root = root_input.resolve(strict=True)
        if not root.is_dir():
            return PhysicalOutputEvidence(descriptor, PhysicalOutputStatus.INVALID_ROOT, root, reason="trusted root is not a directory")
    except (OSError, RuntimeError, ValueError) as exc:
        return PhysicalOutputEvidence(descriptor, PhysicalOutputStatus.INVALID_ROOT, root_input, reason=str(exc))

    candidate_input = root / descriptor.subfolder / descriptor.filename
    try:
        candidate = candidate_input.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return PhysicalOutputEvidence(descriptor, PhysicalOutputStatus.OUTSIDE_ROOT, root, reason=str(exc))
    if not _contained(root, candidate):
        return PhysicalOutputEvidence(descriptor, PhysicalOutputStatus.OUTSIDE_ROOT, root, candidate)
    if not candidate.exists():
        return PhysicalOutputEvidence(descriptor, PhysicalOutputStatus.MISSING, root, candidate)
    if not candidate.is_file():
        return PhysicalOutputEvidence(descriptor, PhysicalOutputStatus.NOT_FILE, root, candidate)
    try:
        with candidate.open("rb") as handle:
            handle.read(1)
    except (OSError, IOError) as exc:
        return PhysicalOutputEvidence(descriptor, PhysicalOutputStatus.UNREADABLE, root, candidate, str(exc))
    return PhysicalOutputEvidence(descriptor, PhysicalOutputStatus.EXISTS, root, candidate)
