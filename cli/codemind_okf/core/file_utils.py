"""
codemind_okf/core/file_utils.py — Safe File I/O Helpers
=========================================================
Standalone version — no dependency on the FastAPI backend.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def safe_read(path: Path | str, encoding: str = "utf-8") -> Optional[str]:
    """Read a file and return its content. Returns None if missing."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return path.read_text(encoding=encoding, errors="replace")
    except Exception as e:
        raise IOError(f"Failed to read {path}: {e}") from e


def safe_write(path: Path | str, content: str, encoding: str = "utf-8") -> Path:
    """Write content to a file, creating parent directories if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding=encoding)
    return path


def list_files(
    directory: Path | str,
    extensions: Optional[list[str]] = None,
    recursive: bool = True,
) -> list[Path]:
    """List files in a directory, optionally filtered by extension."""
    directory = Path(directory)
    if not directory.is_dir():
        return []

    all_files = list(directory.rglob("*") if recursive else directory.iterdir())
    all_files = [p for p in all_files if p.is_file()]

    if extensions:
        normalised = {ext if ext.startswith(".") else f".{ext}" for ext in extensions}
        all_files = [f for f in all_files if f.suffix.lower() in normalised]

    return sorted(all_files)
