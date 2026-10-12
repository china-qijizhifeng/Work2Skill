"""Repair local editable-install ``.pth`` files for generated entrypoints."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PTH_NAME = "workrecorder-local-editable.pth"
ENTRYPOINTS = ("workrecorder", "workrecorder-daemon")
ENTRYPOINT_MARKER = "# workrecorder local editable path"


def _site_packages_dir(repo_root: Path) -> Path | None:
    """Return the local virtualenv site-packages directory when it exists."""

    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    direct = repo_root / ".venv" / "lib" / version / "site-packages"
    if direct.exists():
        return direct
    candidates = sorted((repo_root / ".venv").glob("lib/python*/site-packages"))
    return candidates[0] if candidates else None


def ensure_local_editable_pth(repo_root: Path = REPO_ROOT) -> bool:
    """Ensure generated console scripts can import repository packages.

    Some local developer environments can have generated entrypoints such as
    ``.venv/bin/workrecorder`` without an editable-install ``.pth`` file. In that state
    the entrypoint works only when Python happens to have the repository root
    on ``sys.path``. The skill and packaged app both need the CLI to work from
    any current working directory, so we create a tiny deterministic ``.pth``
    pointing at the repository root when the virtualenv exists.

    Args:
        repo_root: Repository root containing the local ``.venv`` directory.

    Returns:
        Whether a ``.pth`` file was created or updated.
    """

    site_packages = _site_packages_dir(repo_root)
    if site_packages is None:
        return False
    for existing in site_packages.glob("*.pth"):
        try:
            lines = existing.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        if any(Path(line).expanduser() == repo_root for line in lines if line.strip()):
            return False
    pth_path = site_packages / PTH_NAME
    desired = f"{repo_root}\n"
    if pth_path.exists() and pth_path.read_text(encoding="utf-8") == desired:
        return False
    pth_path.write_text(desired, encoding="utf-8")
    return True


def repair_generated_entrypoints(repo_root: Path = REPO_ROOT) -> int:
    """Patch local generated entrypoints so they work even when ``.pth`` is skipped.

    Python on macOS can skip ``.pth`` files carrying Finder hidden flags. That
    makes console scripts fail before any application code can run. The local
    virtualenv entrypoints are generated files, so adding a small ``sys.path``
    fallback is a safe dev-environment repair and keeps the agent-facing ``workrecorder``
    command usable from any current working directory.

    Args:
        repo_root: Repository root containing generated virtualenv entrypoints.

    Returns:
        Number of entrypoint files updated.
    """

    bin_dir = repo_root / ".venv" / "bin"
    updated = 0
    for name in ENTRYPOINTS:
        entrypoint = bin_dir / name
        if not entrypoint.exists():
            continue
        content = entrypoint.read_text(encoding="utf-8")
        if ENTRYPOINT_MARKER in content:
            continue
        needle = "import sys\n"
        if needle not in content:
            continue
        injection = f"import sys\n{ENTRYPOINT_MARKER}\nsys.path.insert(0, {str(repo_root)!r})\n"
        entrypoint.write_text(content.replace(needle, injection, 1), encoding="utf-8")
        updated += 1
    return updated


def repair_macos_hidden_pth_files(repo_root: Path = REPO_ROOT) -> int:
    """Clear Finder hidden flags that make Python skip editable ``.pth`` files.

    On macOS, uv/setuptools editable installs can leave ``.pth`` files with the
    ``UF_HIDDEN`` flag. Python's ``site`` module intentionally skips hidden
    ``.pth`` files, which breaks generated console scripts such as ``workrecorder``.

    Args:
        repo_root: Repository root that owns the local ``.venv``.

    Returns:
        Number of ``.pth`` files passed to ``chflags``. Returns ``0`` on
        non-macOS platforms or when no local virtual environment exists.
    """

    ensure_local_editable_pth(repo_root)
    repair_generated_entrypoints(repo_root)
    if platform.system() != "Darwin":
        return 0
    chflags = shutil.which("chflags")
    if chflags is None:
        return 0
    candidates = tuple((repo_root / ".venv").glob("lib/python*/site-packages/*.pth"))
    if not candidates:
        return 0
    subprocess.run((chflags, "nohidden", *(str(path) for path in candidates)), check=False)
    return len(candidates)


def main() -> int:
    """Run the repair helper as a standalone command.

    Returns:
        Process exit status.
    """

    ensure_local_editable_pth()
    repair_generated_entrypoints()
    repair_macos_hidden_pth_files()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
