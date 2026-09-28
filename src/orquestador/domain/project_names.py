"""Canonical human-readable project-name normalization."""
from __future__ import annotations

import unicodedata
from uuid import UUID


def normalize_project_name(value):
    """Return the display spelling and comparison key for a project name."""
    if not isinstance(value, str):
        raise ValueError("project name must be text")
    display = unicodedata.normalize("NFC", value.strip())
    if not display:
        raise ValueError("project name must be nonblank")
    return display, display.casefold()


def initial_project_name(project_id):
    """Choose the honest initial display name for a legacy/technical key."""
    value = str(project_id)
    try:
        short_id = UUID(value).hex[:8]
    except (ValueError, AttributeError, TypeError):
        return value
    return f"Proyecto generado {short_id}"


def unique_project_name(base, used_name_keys):
    """Allocate the first deterministic ``(N)`` spelling not already used."""
    display, key = normalize_project_name(base)
    if key not in used_name_keys:
        return display, key
    suffix = 2
    while True:
        candidate, candidate_key = normalize_project_name(f"{display} ({suffix})")
        if candidate_key not in used_name_keys:
            return candidate, candidate_key
        suffix += 1
