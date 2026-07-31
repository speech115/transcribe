"""Output folder naming helpers for transcribe CLIs."""

import re
from pathlib import Path

BAD_PATH_CHARS_RE = re.compile(r"[\x00-\x1f/:]+")


def safe_folder_name(name: str, fallback: str = "transcript") -> str:
    """Human-readable folder name, preserving media title where possible."""
    clean = BAD_PATH_CHARS_RE.sub(" - ", name or "")
    clean = re.sub(r"\s+", " ", clean).strip(" .-_")
    return clean[:180] or fallback


def unique_dir(path: Path) -> Path:
    """Return path, or path (2), path (3), ... when path already exists."""
    if not path.exists():
        return path
    parent = path.parent
    stem = path.name
    index = 2
    while True:
        candidate = parent / f"{stem} ({index})"
        if not candidate.exists():
            return candidate
        index += 1
