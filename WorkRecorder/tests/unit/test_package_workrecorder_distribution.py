from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import package_workrecorder_app, package_workrecorder_distribution


def test_rewrite_embedded_virtualenv_uses_relative_python_runtime(tmp_path: Path) -> None:
    venv = tmp_path / "runtime" / "repo" / ".venv"
    bin_dir = venv / "bin"
    bin_dir.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /old/python/bin\n", encoding="utf-8")
    for name in ("python", "python3", "python3.12"):
        (bin_dir / name).write_text("old", encoding="utf-8")
    script = bin_dir / "workrecorder"
    script.write_text("#!/old/repo/.venv/bin/python\nprint('ok')\n", encoding="utf-8")

    package_workrecorder_distribution.rewrite_embedded_virtualenv(venv, python_version="3.14")

    assert "home = ../../python/bin" in (venv / "pyvenv.cfg").read_text(encoding="utf-8")
    assert (bin_dir / "python").is_symlink()
    assert "version_info = 3.14" in (venv / "pyvenv.cfg").read_text(encoding="utf-8")
    assert (bin_dir / "python").readlink() == Path("../../../python/bin/python3.14")
    assert (bin_dir / "python3").readlink() == Path("python")
    assert (bin_dir / "python3.14").readlink() == Path("python")
    assert script.read_text(encoding="utf-8").startswith("#!/bin/sh\n")
    assert "-m apps.cli.main" in script.read_text(encoding="utf-8")
    assert "PYTHONPATH" in script.read_text(encoding="utf-8")


def test_copy_virtualenv_removes_editable_install_pointers(tmp_path: Path) -> None:
    source = tmp_path / "source-venv"
    site_packages = source / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "__editable__.workrecorder-0.1.0.pth").write_text("/repo\n", encoding="utf-8")
    (site_packages / "workrecorder-local-editable.pth").write_text("/repo\n", encoding="utf-8")
    (site_packages / "typer").mkdir()

    target = tmp_path / "target-venv"
    package_workrecorder_distribution._copy_virtualenv(source=source, target=target)

    target_site_packages = target / "lib" / "python3.12" / "site-packages"
    assert not (target_site_packages / "__editable__.workrecorder-0.1.0.pth").exists()
    assert not (target_site_packages / "workrecorder-local-editable.pth").exists()
    assert (target_site_packages / "typer").exists()


def test_copy_runtime_repo_includes_cli_package(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    for directory in (
        repo_root / "services" / "context_daemon",
        repo_root / "packages" / "contracts",
        repo_root / "apps" / "cli",
        repo_root / "scripts" / "benchmark",
    ):
        directory.mkdir(parents=True)
        (directory / "__init__.py").write_text("", encoding="utf-8")
    (repo_root / "apps" / "__init__.py").write_text("", encoding="utf-8")
    (repo_root / "apps" / "cli" / "main.py").write_text("print('workrecorder')\n", encoding="utf-8")

    target = tmp_path / "runtime" / "repo"
    package_workrecorder_distribution._copy_runtime_repo(repo_root=repo_root, target=target)

    assert (target / "apps" / "__init__.py").exists()
    assert (target / "apps" / "cli" / "main.py").exists()
    assert (target / "scripts" / "benchmark" / "__init__.py").exists()


def test_discover_python_runtime_reports_current_virtualenv() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    info = package_workrecorder_distribution.discover_python_runtime(repo_root)

    assert info.virtualenv == (repo_root / ".venv").resolve()
    expected_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert info.version == expected_version
    assert (info.base_prefix / "bin" / f"python{expected_version}").exists()


def test_staged_dmg_app_verify_rejects_codesign_detritus(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app_dir = tmp_path / "WorkRecorder.app"

    def fail_verify(_app_dir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["codesign"],
            returncode=1,
            stderr="resource fork, Finder information, or similar detritus not allowed",
        )

    monkeypatch.setattr(package_workrecorder_app, "_run_codesign_verify", fail_verify)

    with pytest.raises(SystemExit, match="staged DMG app codesign verification failed"):
        package_workrecorder_distribution._verify_staged_dmg_app(app_dir)


def test_embedded_daemon_health_smoke_reports_early_exit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app_dir = _distribution_app(tmp_path)
    repo_root = app_dir / "Contents" / "Resources" / "runtime" / "repo"
    python = repo_root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")

    class FakeProcess:
        returncode = 17

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def poll(self) -> int:
            return 17

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            pass

        def communicate(self, timeout: int | None = None) -> tuple[str, None]:
            return ("ModuleNotFoundError: No module named 'services'\n", None)

    monkeypatch.setattr(package_workrecorder_distribution.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(package_workrecorder_distribution, "_wait_for_health", lambda **_: False)

    with pytest.raises(SystemExit, match="ModuleNotFoundError"):
        package_workrecorder_distribution._verify_embedded_daemon_health(
            app_dir=app_dir,
            repo_root=repo_root,
            python=python,
        )


def test_embedded_daemon_health_smoke_stops_healthy_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app_dir = _distribution_app(tmp_path)
    repo_root = app_dir / "Contents" / "Resources" / "runtime" / "repo"
    python = repo_root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nsleep 10\n", encoding="utf-8")
    calls: list[str] = []

    class FakeProcess:
        returncode = None

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            calls.append("terminate")
            self.returncode = 0

        def kill(self) -> None:
            calls.append("kill")

        def communicate(self, timeout: int | None = None) -> tuple[str, None]:
            return ("", None)

    monkeypatch.setattr(package_workrecorder_distribution.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(package_workrecorder_distribution, "_wait_for_health", lambda **_: True)

    package_workrecorder_distribution._verify_embedded_daemon_health(
        app_dir=app_dir,
        repo_root=repo_root,
        python=python,
    )

    assert calls == ["terminate"]


def _distribution_app(tmp_path: Path) -> Path:
    app_dir = tmp_path / "WorkRecorder.app"
    resources = app_dir / "Contents" / "Resources"
    resources.mkdir(parents=True)
    (resources / "runtime-config.json").write_text(
        '{"repo_root": "runtime/repo", "daemon_url": "http://127.0.0.1:8765", '
        '"install_secret": "workrecorder_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}',
        encoding="utf-8",
    )
    return app_dir
