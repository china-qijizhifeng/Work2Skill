"""File discovery helpers for the repository quality audit."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from .constants import DEFAULT_EXCLUDED_DIRS


def iter_python_files(repo_root: Path, *, paths: Sequence[str]) -> Iterable[Path]:
    """Yield Python source files below selected paths.

    Args:
        repo_root: Repository root.
        paths: Relative paths that should be recursively scanned.

    Returns:
        Iterator of sorted Python source paths.
    """

    discovered: list[Path] = []
    for raw_path in paths:
        target = (repo_root / raw_path).resolve()
        if not target.exists():
            continue
        if target.is_file() and target.suffix == ".py":
            discovered.append(target)
            continue
        if target.is_dir():
            for path in target.rglob("*.py"):
                if _is_excluded(path, repo_root):
                    continue
                discovered.append(path)
    return tuple(sorted(set(discovered)))


def _is_excluded(path: Path, repo_root: Path) -> bool:
    try:
        relative_parts = path.relative_to(repo_root).parts
    except ValueError:
        return True
    return any(part in DEFAULT_EXCLUDED_DIRS for part in relative_parts)
