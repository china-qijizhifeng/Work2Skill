"""Build a self-contained WorkRecorder.app distribution bundle.

The regular ``package_workrecorder_app.py`` script is optimized for local
development: it points the app at the working tree and its ``.venv``. This
script keeps that fast path, then produces a distributable app copy with a
minimal runtime embedded under ``Contents/Resources/runtime`` so another Mac
does not need the source repository next to the app.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

try:
    from scripts import package_workrecorder_app
    from scripts.package_verify import DISTRIBUTION_INSTALL_SECRET_PLACEHOLDER
except ModuleNotFoundError:  # pragma: no cover - direct script execution path.
    import package_workrecorder_app  # type: ignore[import-not-found,no-redef]
    from package_verify import DISTRIBUTION_INSTALL_SECRET_PLACEHOLDER  # type: ignore[import-not-found,no-redef]


APP_NAME = package_workrecorder_app.APP_NAME
APP_BUNDLE_NAME = f"{APP_NAME}.app"
DEFAULT_OUTPUT_DIR = Path("dist") / "distribution"
RUNTIME_RELATIVE_REPO_ROOT = "runtime/repo"
RUNTIME_DIR_NAME = "runtime"
EMBEDDED_PYTHON_DIR_NAME = "python"
EMBEDDED_VENV_HOME = "../../python/bin"
ArchiveMode = Literal["none", "zip", "dmg", "both"]


@dataclass(frozen=True)
class PythonRuntimeInfo:
    """Resolved paths for the active virtualenv and its base interpreter.

    Attributes:
        version: Python major/minor version string.
        base_prefix: uv-managed base interpreter prefix.
        virtualenv: Repository virtualenv copied into the app runtime.
    """

    version: str
    base_prefix: Path
    virtualenv: Path


@dataclass(frozen=True)
class DistributionResult:
    """Artifacts produced by the distribution packager.

    Attributes:
        app_dir: Built app bundle directory.
        zip_path: Optional zip archive path.
        dmg_path: Optional dmg archive path.
    """

    app_dir: Path
    zip_path: Path | None
    dmg_path: Path | None


def main() -> int:
    """CLI entrypoint for the self-contained distribution packager.

    Returns:
        Process status code for shell callers.
    """

    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_dir = (repo_root / args.output_dir).resolve()
    result = build_distribution(
        repo_root=repo_root,
        output_dir=output_dir,
        dev=args.dev,
        verify=args.verify,
        skip_app_build=args.skip_app_build,
        skip_extension_build=args.skip_extension_build,
        archive=args.archive,
        adhoc_sign=args.adhoc_sign,
    )
    print(f"Built self-contained app: {result.app_dir}")
    if result.zip_path:
        print(f"Built zip archive: {result.zip_path}")
    if result.dmg_path:
        print(f"Built dmg image: {result.dmg_path}")
    return 0


def build_distribution(
    *,
    repo_root: Path,
    output_dir: Path,
    dev: bool,
    verify: bool,
    skip_app_build: bool,
    skip_extension_build: bool,
    archive: ArchiveMode,
    adhoc_sign: bool,
) -> DistributionResult:
    """Build a relocatable WorkRecorder.app and optional archive artifacts.

    Args:
        repo_root: Repository root containing source and build scripts.
        output_dir: Directory where the distributable app is written.
        dev: Whether to build a development app bundle.
        verify: Whether to run runtime verification after packaging.
        skip_app_build: Reuse an existing base app bundle when true.
        skip_extension_build: Skip browser extension build for dev packaging.
        archive: Archive mode for zip/dmg outputs.
        adhoc_sign: Whether to apply ad-hoc codesigning.

    Returns:
        Paths for the app bundle and optional archives.

    Raises:
        SystemExit: Raised when prerequisites, build, or verification fail.
    """

    _ensure_distribution_prerequisites(repo_root)
    if not skip_app_build:
        _build_base_app(repo_root=repo_root, dev=dev, skip_extension_build=skip_extension_build)

    source_app = repo_root / "dist" / APP_BUNDLE_NAME
    if not source_app.exists():
        raise SystemExit(f"Base app bundle is missing: {source_app}")

    app_dir = output_dir / APP_BUNDLE_NAME
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    shutil.copytree(source_app, app_dir, symlinks=False, ignore=_app_copy_ignore)

    runtime_root = app_dir / "Contents" / "Resources" / RUNTIME_DIR_NAME
    repo_runtime = runtime_root / "repo"
    python_runtime = runtime_root / EMBEDDED_PYTHON_DIR_NAME
    python_info = discover_python_runtime(repo_root)

    _copy_runtime_repo(repo_root=repo_root, target=repo_runtime)
    _copy_python_base(source=python_info.base_prefix, target=python_runtime)
    _copy_virtualenv(source=python_info.virtualenv, target=repo_runtime / ".venv")
    rewrite_embedded_virtualenv(repo_runtime / ".venv", python_version=python_info.version)
    _write_distribution_runtime_config(app_dir=app_dir, repo_root_relative=RUNTIME_RELATIVE_REPO_ROOT)
    _write_distribution_manifest(app_dir=app_dir, repo_root=repo_root, python_info=python_info)
    _remove_python_bytecode(app_dir)

    _sign_distribution_bundle(app_dir=app_dir, adhoc=adhoc_sign)
    if verify:
        verify_distribution_app(app_dir)

    zip_path: Path | None = None
    dmg_path: Path | None = None
    if archive in {"zip", "both"}:
        zip_path = _create_zip(app_dir=app_dir, output_dir=output_dir)
    if archive in {"dmg", "both"}:
        dmg_path = _create_dmg(app_dir=app_dir, output_dir=output_dir)
    return DistributionResult(app_dir=app_dir, zip_path=zip_path, dmg_path=dmg_path)


def discover_python_runtime(repo_root: Path) -> PythonRuntimeInfo:
    """Discover the active virtualenv and uv-managed base Python runtime.

    Args:
        repo_root: Repository root containing the `.venv` directory.

    Returns:
        Resolved Python runtime paths.

    Raises:
        SystemExit: Raised when the expected Python runtime is missing.
    """

    python = repo_root / ".venv" / "bin" / "python"
    if not python.exists():
        raise SystemExit(f"Cannot build distribution; missing virtualenv Python: {python}")
    completed = subprocess.run(
        [
            str(python),
            "-c",
            (
                "import json, sys; "
                "print(json.dumps({'version': f'{sys.version_info.major}.{sys.version_info.minor}', "
                "'base_prefix': sys.base_prefix, 'prefix': sys.prefix}))"
            ),
        ],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"Cannot inspect Python runtime:\n{completed.stderr.strip()}")
    payload = json.loads(completed.stdout)
    base_prefix = Path(str(payload["base_prefix"])).resolve()
    versioned_python = base_prefix / "bin" / f"python{payload['version']}"
    if not versioned_python.exists():
        raise SystemExit(f"Cannot find Python base runtime executable under: {base_prefix}")
    return PythonRuntimeInfo(
        version=str(payload["version"]),
        base_prefix=base_prefix,
        virtualenv=(repo_root / ".venv").resolve(),
    )


def rewrite_embedded_virtualenv(venv_dir: Path, *, python_version: str) -> None:
    """Make the copied virtualenv use the app-embedded Python base runtime.

    Args:
        venv_dir: Copied virtualenv directory inside the app runtime.
        python_version: Embedded interpreter major/minor version.

    Raises:
        SystemExit: Raised when the virtualenv directory is missing.
    """

    if not venv_dir.exists():
        raise SystemExit(f"Cannot rewrite missing virtualenv: {venv_dir}")
    pyvenv = venv_dir / "pyvenv.cfg"
    pyvenv.write_text(
        "\n".join(
            [
                f"home = {EMBEDDED_VENV_HOME}",
                "implementation = CPython",
                f"version_info = {python_version}",
                "include-system-site-packages = false",
                "prompt = workrecorder",
                "",
            ]
        ),
        encoding="utf-8",
    )
    bin_dir = venv_dir / "bin"
    versioned_name = f"python{python_version}"
    for name in ("python", "python3", versioned_name):
        target = bin_dir / name
        if target.exists() or target.is_symlink():
            target.unlink()
    (bin_dir / "python").symlink_to(f"../../../python/bin/{versioned_name}")
    (bin_dir / "python3").symlink_to("python")
    (bin_dir / versioned_name).symlink_to("python")
    _rewrite_bin_shebangs(bin_dir=bin_dir)
    _write_distribution_cli_wrappers(bin_dir=bin_dir)


def _write_distribution_cli_wrappers(*, bin_dir: Path) -> None:
    wrappers = {
        "workrecorder": "apps.cli.main",
        "workrecorder-daemon": "services.context_daemon.main",
    }
    for script_name, module in wrappers.items():
        script = bin_dir / script_name
        script.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    'SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"',
                    'REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"',
                    'export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"',
                    f'exec "$SCRIPT_DIR/python" -m {module} "$@"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | 0o755)


def verify_distribution_app(app_dir: Path) -> None:
    """Verify the app can launch its embedded daemon runtime.

    Args:
        app_dir: Distribution app bundle directory to verify.

    Raises:
        SystemExit: Raised when embedded runtime verification fails.

    Import checks catch missing Python modules, but they do not prove the
    shipped daemon can bind a local port, initialize settings, create storage
    directories, and answer ``/health`` after relocation. The extra smoke below
    launches the embedded runtime on an ephemeral loopback port, exactly the
    failure mode users see as "daemon exited before health check passed".
    """

    package_workrecorder_app._verify_bundle(app_dir, verify_signature=False)
    package_workrecorder_app._verify_codesign_on_sanitized_copy(app_dir)
    resources = app_dir / "Contents" / "Resources"
    runtime_config = json.loads((resources / "runtime-config.json").read_text(encoding="utf-8"))
    repo_root = resources / str(runtime_config["repo_root"])
    python = repo_root / ".venv" / "bin" / "python"
    checks = [
        "import services.context_daemon.main",
        "import apps.cli.main",
        (
            "from packages.enrichment.visual_ocr.apple_vision import apple_vision_unavailable_reason; "
            "reason = apple_vision_unavailable_reason(); "
            "raise SystemExit(0 if reason is None else reason)"
        ),
        "import fastapi, pydantic, uvicorn",
    ]
    completed = subprocess.run(
        [str(python), "-c", "; ".join(checks)],
        cwd=repo_root,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "WorkRecorder distribution runtime import check failed:\n"
            f"{completed.stdout.strip()}\n{completed.stderr.strip()}".strip()
        )
    _verify_embedded_cli(app_dir=app_dir, repo_root=repo_root)
    _verify_embedded_daemon_health(app_dir=app_dir, repo_root=repo_root, python=python)


def _verify_embedded_cli(*, app_dir: Path, repo_root: Path) -> None:
    script = repo_root / ".venv" / "bin" / "workrecorder"
    completed = subprocess.run(
        [str(script), "--help"],
        cwd=app_dir.parent,
        env=_distribution_runtime_env(repo_root=repo_root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "WorkRecorder distribution CLI smoke failed:\n"
            f"{completed.stdout.strip()}\n{completed.stderr.strip()}".strip()
        )


def _distribution_runtime_env(*, repo_root: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": str(repo_root.parent / "pycache"),
        "PYTHONPATH": str(repo_root),
    }


def _verify_embedded_daemon_health(*, app_dir: Path, repo_root: Path, python: Path) -> None:
    """Start the embedded daemon and require a healthy ``/health`` response."""

    port = _find_free_loopback_port()
    daemon_url = f"http://127.0.0.1:{port}"
    resources = app_dir / "Contents" / "Resources"
    runtime_config = json.loads((resources / "runtime-config.json").read_text(encoding="utf-8"))
    install_secret = str(runtime_config.get("install_secret", ""))
    if install_secret == DISTRIBUTION_INSTALL_SECRET_PLACEHOLDER:
        install_secret = "workrecorder_distribution_smoke_secret_abcdefghijklmnopqrstuvwxyz"
    provider_registration_secret = str(runtime_config.get("provider_registration_secret", ""))
    if provider_registration_secret == DISTRIBUTION_INSTALL_SECRET_PLACEHOLDER:
        provider_registration_secret = "workrecorder_provider_distribution_smoke_secret_abcdefghijklmnopqrstuvwxyz"
    native_capture_secret = str(runtime_config.get("native_capture_secret", ""))
    if not native_capture_secret or native_capture_secret == install_secret:
        native_capture_secret = "workrecorder_native_distribution_smoke_secret_abcdefghijklmnopqrstuvwxyz"
    with tempfile.TemporaryDirectory(prefix="workrecorder-dist-daemon-") as directory:
        root = Path(directory)
        env = {
            **_distribution_runtime_env(repo_root=repo_root),
            "WORKRECORDER_DAEMON_URL": daemon_url,
            "WORKRECORDER_DATABASE_PATH": str(root / "workrecorder.db"),
            "WORKRECORDER_ARTIFACT_STAGING_DIR": str(root / "staging"),
            "WORKRECORDER_ARTIFACT_VAULT_DIR": str(root / "vault"),
            "WORKRECORDER_INSTALL_SECRET": install_secret,
            "WORKRECORDER_PROVIDER_REGISTRATION_SECRET": provider_registration_secret,
            "WORKRECORDER_NATIVE_CAPTURE_SECRET": native_capture_secret,
        }
        process = subprocess.Popen(
            [str(python), "-m", "services.context_daemon.main"],
            cwd=repo_root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            if not _wait_for_health(daemon_url=daemon_url, timeout_seconds=15):
                output = _stop_process_and_collect(process)
                if process.poll() is None:
                    reason = "daemon did not become healthy before timeout"
                else:
                    reason = f"daemon exited with status {process.returncode}"
                raise SystemExit("WorkRecorder distribution daemon health smoke failed: " f"{reason}\n{output.strip()}")
        finally:
            if process.poll() is None:
                _stop_process_and_collect(process)


def _find_free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(*, daemon_url: str, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    health_url = f"{daemon_url}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=0.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("ok") is True:
                    return True
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(0.2)
    return False


def _stop_process_and_collect(process: subprocess.Popen[str]) -> str:
    if process.poll() is None:
        process.terminate()
        try:
            output, _ = process.communicate(timeout=5)
            return output
        except subprocess.TimeoutExpired:
            process.kill()
    output, _ = process.communicate(timeout=5)
    return output


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a self-contained WorkRecorder.app distribution package.")
    parser.add_argument(
        "--dev", action="store_true", help="Build the Swift app in debug mode before embedding runtime."
    )
    parser.add_argument("--verify", action="store_true", help="Run bundle and embedded-runtime verification.")
    parser.add_argument(
        "--skip-app-build", action="store_true", help="Reuse dist/WorkRecorder.app instead of rebuilding it."
    )
    parser.add_argument("--skip-extension-build", action="store_true", help="Skip npm build in the base app packager.")
    parser.add_argument(
        "--adhoc-sign",
        action="store_true",
        help=(
            "Use ad-hoc signing. This is only for local emergency builds; "
            "it is not recommended for sharing because macOS TCC permissions "
            "are tied to code identity."
        ),
    )
    parser.add_argument(
        "--archive",
        choices=("none", "zip", "dmg", "both"),
        default="zip",
        help="Archive format to create after packaging.",
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for the distribution app.")
    return parser.parse_args()


def _ensure_distribution_prerequisites(repo_root: Path) -> None:
    required = [
        repo_root / "services" / "context_daemon" / "main.py",
        repo_root / "packages" / "enrichment" / "visual_ocr" / "apple_vision_ocr.swift",
        repo_root / ".venv" / "bin" / "python",
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise SystemExit("Cannot build distribution; missing files:\n" + "\n".join(f"- {path}" for path in missing))


def _build_base_app(*, repo_root: Path, dev: bool, skip_extension_build: bool) -> None:
    command = [sys.executable, "scripts/package_workrecorder_app.py", "--verify"]
    if dev:
        command.append("--dev")
    if skip_extension_build:
        command.append("--skip-extension-build")
    _run(command, cwd=repo_root)


def _copy_runtime_repo(*, repo_root: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for directory in ("services", "packages"):
        shutil.copytree(repo_root / directory, target / directory, symlinks=False, ignore=_copy_ignore)
    shutil.copytree(
        repo_root / "scripts" / "benchmark",
        target / "scripts" / "benchmark",
        symlinks=False,
        ignore=_copy_ignore,
    )
    _build_apple_vision_ocr_helper(repo_root=repo_root, runtime_repo=target)
    apps_target = target / "apps"
    apps_target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_root / "apps" / "__init__.py", apps_target / "__init__.py")
    shutil.copytree(repo_root / "apps" / "cli", apps_target / "cli", symlinks=False, ignore=_copy_ignore)
    for file_name in ("pyproject.toml", "README.md"):
        source = repo_root / file_name
        if source.exists():
            shutil.copy2(source, target / file_name)


def _build_apple_vision_ocr_helper(*, repo_root: Path, runtime_repo: Path) -> None:
    source = repo_root / "packages" / "enrichment" / "visual_ocr" / "apple_vision_ocr.swift"
    output = runtime_repo / "packages" / "enrichment" / "visual_ocr" / "apple_vision_ocr_helper"
    if not source.exists():
        return
    swiftc = shutil.which("swiftc")
    if swiftc is None:
        raise SystemExit("Cannot build distribution; swiftc is required to compile the Apple Vision OCR helper")
    _run([swiftc, str(source), "-O", "-o", str(output)], cwd=repo_root)
    output.chmod(0o755)


def _copy_python_base(*, source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, symlinks=False, ignore=_copy_ignore)


def _copy_virtualenv(*, source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, symlinks=False, ignore=_copy_ignore)
    _remove_editable_install_artifacts(target)


def _remove_editable_install_artifacts(venv_dir: Path) -> None:
    site_packages_root = venv_dir / "lib"
    for site_packages in site_packages_root.glob("python*/site-packages"):
        for path in site_packages.glob("__editable__*"):
            path.unlink(missing_ok=True)
        for path in site_packages.glob("*editable*.pth"):
            path.unlink(missing_ok=True)
        for path in site_packages.glob("workrecorder*.pth"):
            path.unlink(missing_ok=True)


def _rewrite_bin_shebangs(*, bin_dir: Path) -> None:
    python_line = "#!/usr/bin/env python3\n"
    for path in bin_dir.iterdir():
        if not path.is_file() or path.name.startswith("python"):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if not data.startswith(b"#!"):
            continue
        newline = data.find(b"\n")
        if newline < 0:
            continue
        try:
            data[:newline].decode("utf-8")
        except UnicodeDecodeError:
            continue
        path.write_bytes(python_line.encode("utf-8") + data[newline + 1 :])
        path.chmod(path.stat().st_mode | 0o755)


def _write_distribution_runtime_config(*, app_dir: Path, repo_root_relative: str) -> None:
    config_path = app_dir / "Contents" / "Resources" / "runtime-config.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["repo_root"] = repo_root_relative
    payload["mode"] = "distribution"
    payload["install_secret"] = DISTRIBUTION_INSTALL_SECRET_PLACEHOLDER
    payload["provider_registration_secret"] = DISTRIBUTION_INSTALL_SECRET_PLACEHOLDER
    payload.pop("native_capture_secret", None)
    config_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_distribution_manifest(*, app_dir: Path, repo_root: Path, python_info: PythonRuntimeInfo) -> None:
    manifest = {
        "schema_version": 1,
        "bundle": APP_BUNDLE_NAME,
        "source_commit": _git_commit(repo_root),
        "python_version": python_info.version,
        "runtime_layout": {
            "repo_root": RUNTIME_RELATIVE_REPO_ROOT,
            "python": f"{RUNTIME_DIR_NAME}/{EMBEDDED_PYTHON_DIR_NAME}",
        },
    }
    path = app_dir / "Contents" / "Resources" / "distribution-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def _git_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def _create_zip(*, app_dir: Path, output_dir: Path) -> Path:
    zip_path = output_dir / "WorkRecorder-macos-self-contained.zip"
    if zip_path.exists():
        zip_path.unlink()
    _run(["ditto", "--noextattr", "--norsrc", "-c", "-k", "--keepParent", str(app_dir), str(zip_path)], cwd=output_dir)
    return zip_path


def _sign_distribution_bundle(*, app_dir: Path, adhoc: bool) -> None:
    """Sign a clean copy, then copy it back to the requested output path.

    Desktop/File Provider locations can reattach package-level xattrs to large
    bundles between copy and sign. Signing in a temporary non-FileProvider
    directory keeps the seal stable; verification already knows how to check a
    sanitized copy when Finder detritus is reattached after the signed app is
    copied back.
    """

    with tempfile.TemporaryDirectory(prefix="workrecorder-dist-sign-") as directory:
        temp_root = Path(directory)
        temp_app = temp_root / APP_BUNDLE_NAME
        _run(["ditto", "--noextattr", "--norsrc", str(app_dir), str(temp_app)], cwd=temp_root)
        package_workrecorder_app._sign_bundle(temp_app, adhoc=adhoc)
        shutil.rmtree(app_dir)
        _run(["ditto", "--noextattr", "--norsrc", str(temp_app), str(app_dir)], cwd=app_dir.parent)
        package_workrecorder_app._clear_bundle_xattrs(app_dir)


def _remove_python_bytecode(root: Path) -> None:
    """Remove Python bytecode caches before signing a sealed app bundle."""

    for path in sorted(root.rglob("__pycache__"), reverse=True):
        shutil.rmtree(path, ignore_errors=True)
    for path in root.rglob("*.py[co]"):
        path.unlink(missing_ok=True)


def _create_dmg(*, app_dir: Path, output_dir: Path) -> Path:
    if shutil.which("hdiutil") is None:
        raise SystemExit("Cannot build DMG; hdiutil is not available.")
    dmg_path = output_dir / "WorkRecorder-macos-self-contained.dmg"
    if dmg_path.exists():
        dmg_path.unlink()
    with tempfile.TemporaryDirectory(prefix="workrecorder-dmg-") as directory:
        staging = Path(directory) / "dmg-staging"
        staging.mkdir()
        staged_app = staging / APP_BUNDLE_NAME
        _run(["ditto", "--noextattr", "--norsrc", str(app_dir), str(staged_app)], cwd=output_dir)
        package_workrecorder_app._clear_bundle_xattrs(staged_app)
        _verify_staged_dmg_app(staged_app)
        applications = staging / "Applications"
        if applications.exists() or applications.is_symlink():
            applications.unlink()
        applications.symlink_to("/Applications")
        _run(
            [
                "hdiutil",
                "create",
                "-volname",
                "WorkRecorder",
                "-srcfolder",
                str(staging),
                "-ov",
                "-format",
                "UDZO",
                str(dmg_path),
            ],
            cwd=output_dir,
        )
    return dmg_path


def _verify_staged_dmg_app(app_dir: Path) -> None:
    """Verify the exact app copy that will be sealed into the DMG.

    Desktop/File Provider locations may attach Finder metadata after signing.
    The staging copy is the last chance to remove those xattrs before ``hdiutil``
    freezes them into the disk image.

    Args:
        app_dir: Staged ``WorkRecorder.app`` path.

    Raises:
        SystemExit: If strict codesign verification fails for the staged app.
    """

    completed = package_workrecorder_app._run_codesign_verify(app_dir)
    if completed.returncode != 0:
        raise SystemExit(f"WorkRecorder staged DMG app codesign verification failed:\n{completed.stderr.strip()}")


def _copy_ignore(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git", "dist", ".qa"}:
            ignored.add(name)
        elif name.endswith((".pyc", ".pyo", ".DS_Store")):
            ignored.add(name)
    if Path(directory).name == "site-packages":
        ignored.update(name for name in names if name.endswith((".dist-info/RECORD",)))
    return ignored


def _app_copy_ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name.endswith(".DS_Store")}


def _run(command: list[str], *, cwd: Path) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
