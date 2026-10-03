"""Final-video publication naming and destination snapshot helpers."""
from __future__ import annotations

from pathlib import Path
import re
import unicodedata

FINAL_OUTPUT_FOLDER_KEY = "_final_output_folder"
FINAL_OUTPUT_FILENAME_KEY = "_final_output_filename"
FINAL_OUTPUT_NAME_MODE_KEY = "_final_output_name_mode"

_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_MAX_BASENAME = 180


class FinalOutputConfigError(ValueError):
    pass


def _without_mp4(value: str) -> str:
    return value[:-4] if value.lower().endswith(".mp4") else value


def _reserved(value: str) -> bool:
    return value.split(".", 1)[0].upper() in _RESERVED


def _validate_explicit_name(value: str) -> str:
    display = unicodedata.normalize("NFC", value.strip())
    if not display:
        raise FinalOutputConfigError("final video name must be nonblank")
    display = _without_mp4(display)
    if not display or display in {".", ".."}:
        raise FinalOutputConfigError("final video name is invalid")
    if _INVALID_FILENAME.search(display):
        raise FinalOutputConfigError("final video name contains invalid Windows filename characters")
    if display[-1] in {" ", "."}:
        raise FinalOutputConfigError("final video name cannot end with a space or dot")
    if _reserved(display):
        raise FinalOutputConfigError("final video name is reserved by Windows")
    if len(display) > _MAX_BASENAME:
        raise FinalOutputConfigError("final video name is too long")
    return display + ".mp4"


def _safe_project_name(value: str) -> str:
    display = unicodedata.normalize("NFC", str(value or "").strip())
    display = _without_mp4(display)
    display = _INVALID_FILENAME.sub("_", display).rstrip(" .")
    if not display:
        display = "video-final"
    if _reserved(display):
        display += "_"
    display = display[:_MAX_BASENAME].rstrip(" .") or "video-final"
    return display + ".mp4"


def final_output_filename(project_name: str, requested_name: str | None = None) -> str:
    """Resolve one Windows-safe MP4 filename.

    Explicit operator input is validated fail-closed.  The automatic default
    is derived deterministically from the project name so legacy names with a
    Windows-forbidden character still have a usable publication filename.
    """
    if isinstance(requested_name, str) and requested_name.strip():
        return _validate_explicit_name(requested_name)
    return _safe_project_name(project_name)


def final_output_folder(value, *, project_root) -> Path:
    """Resolve an existing absolute publication folder, defaulting to project root."""
    root = Path(project_root).expanduser().resolve()
    raw = str(value or "").strip()
    target = root if not raw else Path(raw).expanduser()
    if not target.is_absolute():
        raise FinalOutputConfigError("final video folder must be an absolute path")
    try:
        target = target.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise FinalOutputConfigError("final video folder does not exist or is inaccessible") from exc
    if not target.is_dir():
        raise FinalOutputConfigError("final video folder must be a directory")
    return target


def final_output_snapshot(project_name, requested_name, folder, *, project_root) -> dict:
    resolved_folder = final_output_folder(folder, project_root=project_root)
    resolved_name = final_output_filename(project_name, requested_name)
    target = resolved_folder / resolved_name
    if len(str(target)) > 1024:
        raise FinalOutputConfigError("final video path is too long")
    return {
        FINAL_OUTPUT_FOLDER_KEY: str(resolved_folder),
        FINAL_OUTPUT_FILENAME_KEY: resolved_name,
        FINAL_OUTPUT_NAME_MODE_KEY: (
            "custom"
            if isinstance(requested_name, str) and requested_name.strip()
            else "project"
        ),
    }


def requested_final_output_name(defaults):
    """Return the editable custom name, or None when project-name mode is active."""
    mapping = dict(defaults or {})
    mode = mapping.get(FINAL_OUTPUT_NAME_MODE_KEY)
    if mode == "project":
        return None
    name = mapping.get(FINAL_OUTPUT_FILENAME_KEY)
    if mode == "custom":
        return name if isinstance(name, str) and name.strip() else None
    # Compatibility for snapshots created before the mode marker existed.
    return name if isinstance(name, str) and name.strip() else None


def final_output_target(defaults, *, project_name, project_root, fallback_folder=None) -> Path:
    mapping = dict(defaults or {})
    folder = mapping.get(FINAL_OUTPUT_FOLDER_KEY, fallback_folder)
    name = mapping.get(FINAL_OUTPUT_FILENAME_KEY)
    resolved_folder = final_output_folder(folder, project_root=project_root)
    resolved_name = (
        _validate_explicit_name(name)
        if isinstance(name, str) and name.strip()
        else final_output_filename(project_name)
    )
    return (resolved_folder / resolved_name).resolve()
