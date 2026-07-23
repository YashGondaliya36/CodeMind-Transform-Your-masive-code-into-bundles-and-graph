"""
codemind_okf/core/crawler.py — Repository File Crawler
========================================================
Walks a local directory and returns all analysable source files.
Standalone — no FastAPI dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from codemind_okf.core.file_utils import list_files


# ── Supported languages ───────────────────────────────────────────────────────
LANGUAGE_EXTENSIONS: dict[str, list[str]] = {
    "python":     [".py"],
    "javascript": [".js", ".jsx"],
    "typescript": [".ts", ".tsx"],
}

ALL_EXTENSIONS: list[str] = [ext for exts in LANGUAGE_EXTENSIONS.values() for ext in exts]

# ── Noise filters ─────────────────────────────────────────────────────────────
SKIP_DIRS = {
    ".git", ".github", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".env", "dist", "build", ".next", ".nuxt", "coverage",
    ".pytest_cache", ".mypy_cache", "eggs", ".tox", ".okf",
    "htmlcov", ".cache", "tmp", "temp", "logs",
}

SKIP_FILENAMES = {
    "setup.py", "conftest.py", "manage.py", "__init__.py",
}

MIN_FILE_SIZE_BYTES = 100


@dataclass
class CrawledFile:
    """Represents a single source file ready for analysis."""
    path: Path
    relative_path: str
    language: str
    size_bytes: int
    extension: str


@dataclass
class CrawlResult:
    """Full result of crawling a directory."""
    root: Path
    files: list[CrawledFile] = field(default_factory=list)
    skipped_count: int = 0
    total_scanned: int = 0

    @property
    def total_files(self) -> int:
        return len(self.files)


def crawl(root: Path, languages: list[str] | None = None) -> CrawlResult:
    """
    Walk a directory and collect all analysable source files.

    Args:
        root:      Absolute path to the project root.
        languages: Languages to include. None = all supported.

    Returns:
        CrawlResult with filtered CrawledFile objects.
    """
    if languages:
        extensions = []
        for lang in languages:
            extensions.extend(LANGUAGE_EXTENSIONS.get(lang.lower(), []))
    else:
        extensions = ALL_EXTENSIONS

    if not extensions:
        return CrawlResult(root=root)

    result = CrawlResult(root=root)
    all_files = list_files(root, extensions=extensions, recursive=True)
    result.total_scanned = len(all_files)

    for file_path in all_files:
        if _is_in_skip_dir(file_path, root):
            result.skipped_count += 1
            continue

        if file_path.name in SKIP_FILENAMES:
            result.skipped_count += 1
            continue

        size = file_path.stat().st_size
        if size < MIN_FILE_SIZE_BYTES:
            result.skipped_count += 1
            continue

        lang = _extension_to_language(file_path.suffix)
        rel = str(file_path.relative_to(root)).replace("\\", "/")

        result.files.append(CrawledFile(
            path=file_path,
            relative_path=rel,
            language=lang,
            size_bytes=size,
            extension=file_path.suffix,
        ))

    return result


def _is_in_skip_dir(file_path: Path, repo_root: Path) -> bool:
    try:
        parts = file_path.relative_to(repo_root).parts
    except ValueError:
        return False
    return any(part in SKIP_DIRS or part.endswith(".egg-info") for part in parts)


def _extension_to_language(ext: str) -> str:
    for lang, exts in LANGUAGE_EXTENSIONS.items():
        if ext.lower() in exts:
            return lang
    return "unknown"
