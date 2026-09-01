"""Explicit trusted-root validation for already-correlated output descriptors."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import hashlib
import shutil

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

def import_project_output(source: str | Path, project_root: str | Path, relative_uri: str) -> Path:
    """Idempotently import a validated external output into project storage."""
    root = Path(project_root).resolve(strict=True)
    destination = (root / relative_uri).resolve(strict=False)
    if not _contained(root, destination) or destination == root:
        raise ValueError("project output escapes project root")
    source_path = Path(source).resolve(strict=True)
    if not source_path.is_file():
        raise ValueError("source output is not a file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_file():
            raise ValueError("project output collision is not a file")
        if _sha256(source_path) != _sha256(destination):
            raise ValueError("project output collision has different content")
        return destination
    temp = destination.with_name(destination.name + ".importing")
    if temp.exists():
        raise ValueError("project output import is already in progress")
    try:
        shutil.copy2(source_path, temp)
        if _sha256(source_path) != _sha256(temp):
            raise ValueError("imported output integrity mismatch")
        temp.replace(destination)
    finally:
        if temp.exists():
            temp.unlink()
    return destination

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
