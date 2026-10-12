"""Build a local, signed WorkRecorder.app for manual testing.

This packager intentionally targets the dev/local path first. It uses a stable
local development signing identity when possible so macOS TCC permissions do
not churn on every rebuild. It does not notarize or produce a DMG.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import plistlib
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Callable, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_local_package_verify() -> ModuleType:
    """Load package verification helpers from this checkout.

    ``scripts`` is a namespace package in local development, and editable
    installs from a sibling checkout can otherwise win module resolution when
    this file is executed directly as ``scripts/package_workrecorder_app.py``.
    """

    module_path = REPO_ROOT / "scripts" / "package_verify.py"
    spec = importlib.util.spec_from_file_location("_workrecorder_local_package_verify", module_path)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(f"cannot load package verifier from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_package_verify = _load_local_package_verify()
from scripts import macos_codesign

APPLE_VISION_HELPER_RELATIVE_PATH = cast(Path, getattr(_package_verify, "APPLE_VISION_HELPER_RELATIVE_PATH"))
verify_python_runtime_assets = cast(Callable[..., None], getattr(_package_verify, "verify_python_runtime_assets"))
verify_runtime_config = cast(Callable[..., dict[str, object]], getattr(_package_verify, "verify_runtime_config"))

APP_NAME = "WorkRecorder"
DISPLAY_NAME = APP_NAME
PRODUCT_NAME = "WorkRecorderCapture"
BUNDLE_ID = "app.workrecorder.local"


@dataclass(frozen=True)
class BundleSpec:
    app_name: str
    executable_name: str
    display_name: str
    bundle_id: str
    development_region: str
    ui_language: str


WORKRECORDER_BUNDLE = BundleSpec(
    app_name=APP_NAME,
    executable_name=APP_NAME,
    display_name=DISPLAY_NAME,
    bundle_id=BUNDLE_ID,
    development_region="en",
    ui_language="en",
)
_clear_bundle_xattrs = macos_codesign._clear_bundle_xattrs
_materialize_strict_verified_artifact = macos_codesign._materialize_strict_verified_artifact
_sign_bundle = macos_codesign._sign_bundle
_sign_bundle_on_sanitized_copy = macos_codesign._sign_bundle_on_sanitized_copy
_run_codesign_sign = macos_codesign._run_codesign_sign
_run_codesign_verify = macos_codesign._run_codesign_verify
_verify_codesign = macos_codesign._verify_codesign
_verify_codesign_on_sanitized_copy = macos_codesign._verify_codesign_on_sanitized_copy


def main() -> int:
    """Package the local dev app bundle and return a shell-friendly status code.

    Returns:
        Zero when the bundle is built and verified successfully.
    """

    args = _parse_args()
    repo_root = REPO_ROOT
    bundle = WORKRECORDER_BUNDLE
    app_dir = repo_root / "dist" / f"{bundle.app_name}.app"
    build_mode = "debug" if args.dev else "release"

    _ensure_repo_ready(repo_root)
    binary_path = _build_swift(repo_root=repo_root, mode=build_mode)
    _create_bundle(repo_root=repo_root, app_dir=app_dir, binary_path=binary_path, dev=args.dev, bundle=bundle)
    # The signing helpers retain default arguments for existing callers and
    # tests. Set their per-process identity before signing this bundle variant.
    macos_codesign.APP_NAME = bundle.executable_name
    macos_codesign.BUNDLE_ID = bundle.bundle_id
    _sign_bundle(app_dir, adhoc=args.adhoc_sign)
    verified_artifact = app_dir
    if args.verify:
        _verify_bundle(app_dir, bundle=bundle)
        verified_artifact = _materialize_strict_verified_artifact(app_dir)
    _clear_bundle_xattrs(app_dir)
    print(f"Built {app_dir}")
    if verified_artifact != app_dir:
        print(f"Strict-verified artifact {verified_artifact}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package WorkRecorder.app for local macOS testing.")
    parser.add_argument("--dev", action="store_true", help="Build debug Swift binary and dev runtime config.")
    parser.add_argument("--verify", action="store_true", help="Verify expected bundle files exist after packaging.")
    parser.add_argument(
        "--skip-extension-build",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--adhoc-sign",
        action="store_true",
        help="Use ad-hoc signing instead of the stable local development identity.",
    )
    return parser.parse_args()


def _ensure_repo_ready(repo_root: Path) -> None:
    required = [
        repo_root / "apps" / "macos_capture" / "Package.swift",
        repo_root / "services" / "context_daemon" / "main.py",
        repo_root / APPLE_VISION_HELPER_RELATIVE_PATH,
        repo_root / ".venv" / "bin" / "python",
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        details = "\n".join(f"- {path}" for path in missing)
        raise SystemExit(f"Cannot package WorkRecorder.app; missing required files:\n{details}")


def _build_swift(*, repo_root: Path, mode: str) -> Path:
    package_root = repo_root / "apps" / "macos_capture"
    configuration = "debug" if mode == "debug" else "release"
    _run(["swift", "build", "--disable-sandbox", "-c", configuration, "--product", PRODUCT_NAME], cwd=package_root)
    bin_dir = _run_capture(
        ["swift", "build", "--disable-sandbox", "-c", configuration, "--show-bin-path"],
        cwd=package_root,
    )
    binary = Path(bin_dir.strip()) / PRODUCT_NAME
    if not binary.exists():
        raise SystemExit(f"Swift build finished but binary is missing: {binary}")
    return binary


def _create_bundle(
    *,
    repo_root: Path,
    app_dir: Path,
    binary_path: Path,
    dev: bool,
    bundle: BundleSpec = WORKRECORDER_BUNDLE,
) -> None:
    if app_dir.exists():
        shutil.rmtree(app_dir)
    contents = app_dir / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)

    executable = macos / bundle.executable_name
    shutil.copy2(binary_path, executable)
    executable.chmod(0o755)

    install_secret = _load_or_create_install_secret()
    provider_registration_secret = _load_or_create_provider_registration_secret()
    native_capture_secret = _load_or_create_native_capture_secret()
    daemon_url = os.environ.get("WORKRECORDER_DAEMON_URL", "http://127.0.0.1:8765")
    _write_info_plist(contents / "Info.plist", bundle=bundle)
    _write_runtime_config(
        repo_root=repo_root,
        resources=resources,
        dev=dev,
        install_secret=install_secret,
        provider_registration_secret=provider_registration_secret,
        native_capture_secret=native_capture_secret,
        daemon_url=daemon_url,
    )
    _create_app_icon(repo_root=repo_root, resources=resources)


def _load_or_create_install_secret() -> str:
    override = os.getenv("WORKRECORDER_INSTALL_SECRET")
    if override and override != "dev-install-secret" and len(override) >= 32:
        return override

    secret_path = Path.home() / ".workrecorder" / "app-dev" / "install-secret"
    if secret_path.exists():
        secret = secret_path.read_text(encoding="utf-8").strip()
        if secret != "dev-install-secret" and len(secret) >= 32:
            return secret

    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret = f"workrecorder_{secrets.token_urlsafe(32)}"
    secret_path.write_text(secret + "\n", encoding="utf-8")
    secret_path.chmod(0o600)
    return secret


def _load_or_create_native_capture_secret() -> str:
    override = os.getenv("WORKRECORDER_NATIVE_CAPTURE_SECRET")
    if override and len(override) >= 32:
        return override

    secret_path = Path.home() / ".workrecorder" / "app-dev" / "native-capture-secret"
    if secret_path.exists():
        secret = secret_path.read_text(encoding="utf-8").strip()
        if len(secret) >= 32:
            return secret

    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret = f"workrecorder_native_{secrets.token_urlsafe(32)}"
    secret_path.write_text(secret + "\n", encoding="utf-8")
    secret_path.chmod(0o600)
    return secret


def _load_or_create_provider_registration_secret() -> str:
    override = os.getenv("WORKRECORDER_PROVIDER_REGISTRATION_SECRET")
    if override and override != "dev-provider-secret" and len(override) >= 32:
        return override

    secret_path = Path.home() / ".workrecorder" / "app-dev" / "provider-registration-secret"
    if secret_path.exists():
        secret = secret_path.read_text(encoding="utf-8").strip()
        if secret != "dev-provider-secret" and len(secret) >= 32:
            return secret

    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret = f"workrecorder_provider_{secrets.token_urlsafe(32)}"
    secret_path.write_text(secret + "\n", encoding="utf-8")
    secret_path.chmod(0o600)
    return secret


def _write_info_plist(path: Path, *, bundle: BundleSpec = WORKRECORDER_BUNDLE) -> None:
    info = {
        "CFBundleDevelopmentRegion": bundle.development_region,
        "CFBundleDisplayName": bundle.display_name,
        "CFBundleExecutable": bundle.executable_name,
        "CFBundleIdentifier": bundle.bundle_id,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleIconFile": "AppIcon",
        "CFBundleName": bundle.display_name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "13.0",
        "LSUIElement": False,
        "NSHighResolutionCapable": True,
        "NSAppleEventsUsageDescription": "WorkRecorder opens local pages needed for recording setup.",
        "NSCameraUsageDescription": "WorkRecorder does not use the camera.",
        "NSMicrophoneUsageDescription": "WorkRecorder does not use the microphone.",
        "NSHumanReadableCopyright": "Copyright © 2026 WorkRecorder contributors.",
        "WorkRecorderUILanguage": bundle.ui_language,
    }
    with path.open("wb") as handle:
        plistlib.dump(info, handle)


def _write_runtime_config(
    *,
    repo_root: Path,
    resources: Path,
    dev: bool,
    install_secret: str,
    provider_registration_secret: str,
    native_capture_secret: str,
    daemon_url: str,
) -> None:
    payload = {
        "schema_version": 1,
        "repo_root": str(repo_root),
        "daemon_url": daemon_url,
        "install_secret": install_secret,
        "provider_registration_secret": provider_registration_secret,
        "native_capture_secret": native_capture_secret,
        "mode": "dev" if dev else "local",
    }
    (resources / "runtime-config.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _create_app_icon(*, repo_root: Path, resources: Path) -> None:
    icon_png = repo_root / "site" / "assets" / "app-icon.png"
    favicon = repo_root / "site" / "assets" / "favicon.svg"
    if not icon_png.exists() and not favicon.exists():
        raise SystemExit(f"Cannot package WorkRecorder.app; missing app icon source: {icon_png} or {favicon}")
    if not shutil.which("sips") or not shutil.which("iconutil"):
        raise SystemExit("Cannot package WorkRecorder.app icon; sips and iconutil are required on macOS.")
    if not icon_png.exists() and not shutil.which("qlmanage"):
        raise SystemExit("Cannot package WorkRecorder.app icon from SVG; qlmanage is required on macOS.")

    with tempfile.TemporaryDirectory(prefix="workrecorder-icon-") as directory:
        temp_dir = Path(directory)
        source_png = icon_png
        if not source_png.exists():
            completed = subprocess.run(
                ["qlmanage", "-t", "-s", "1024", "-o", str(temp_dir), str(favicon)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            rendered = sorted(temp_dir.glob("*.png"))
            if completed.returncode != 0 or not rendered:
                raise SystemExit(
                    "WorkRecorder.app icon render failed:\n"
                    f"{completed.stdout.strip()}\n{completed.stderr.strip()}".strip()
                )
            source_png = rendered[0]
        shutil.copy2(source_png, resources / "app-icon.png")
        iconset = temp_dir / "AppIcon.iconset"
        iconset.mkdir()
        for filename, size in (
            ("icon_16x16.png", 16),
            ("icon_16x16@2x.png", 32),
            ("icon_32x32.png", 32),
            ("icon_32x32@2x.png", 64),
            ("icon_128x128.png", 128),
            ("icon_128x128@2x.png", 256),
            ("icon_256x256.png", 256),
            ("icon_256x256@2x.png", 512),
            ("icon_512x512.png", 512),
            ("icon_512x512@2x.png", 1024),
        ):
            _run_quiet(["sips", "-z", str(size), str(size), str(source_png), "--out", str(iconset / filename)])
        try:
            _run_quiet(["iconutil", "-c", "icns", "-o", str(resources / "AppIcon.icns"), str(iconset)])
        except subprocess.CalledProcessError:
            # iconutil can be blocked by a caller's macOS sandbox even when the
            # generated iconset is valid. Pillow writes the same ICNS payload
            # without asking for broader system access.
            try:
                from PIL import Image
            except ImportError as error:
                raise SystemExit("WorkRecorder.app icon packaging requires iconutil or Pillow.") from error
            with Image.open(source_png) as image:
                image.convert("RGBA").save(resources / "AppIcon.icns", format="ICNS")


def _verify_bundle(
    app_dir: Path,
    *,
    verify_signature: bool = True,
    bundle: BundleSpec = WORKRECORDER_BUNDLE,
) -> None:
    required = [
        app_dir / "Contents" / "Info.plist",
        app_dir / "Contents" / "MacOS" / bundle.executable_name,
        app_dir / "Contents" / "Resources" / "runtime-config.json",
        app_dir / "Contents" / "Resources" / "AppIcon.icns",
        app_dir / "Contents" / "Resources" / "app-icon.png",
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        details = "\n".join(f"- {path}" for path in missing)
        raise SystemExit(f"WorkRecorder.app verification failed:\n{details}")
    executable = app_dir / "Contents" / "MacOS" / bundle.executable_name
    if not os.access(executable, os.X_OK):
        raise SystemExit(f"WorkRecorder.app executable bit is missing: {executable}")
    _verify_info_plist(app_dir / "Contents" / "Info.plist", bundle=bundle)
    runtime_payload = verify_runtime_config(app_dir / "Contents" / "Resources" / "runtime-config.json")
    verify_python_runtime_assets(Path(str(runtime_payload["repo_root"])))
    if verify_signature:
        _verify_codesign(app_dir)


def _verify_info_plist(path: Path, *, bundle: BundleSpec = WORKRECORDER_BUNDLE) -> None:
    with path.open("rb") as handle:
        payload = plistlib.load(handle)
    expected = {
        "CFBundleIdentifier": bundle.bundle_id,
        "CFBundleExecutable": bundle.executable_name,
        "CFBundleIconFile": "AppIcon",
        "CFBundlePackageType": "APPL",
        "LSUIElement": False,
        "WorkRecorderUILanguage": bundle.ui_language,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise SystemExit(f"WorkRecorder.app Info.plist invalid {key}: {payload.get(key)!r}")


def _run(command: list[str], *, cwd: Path) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _run_quiet(command: list[str]) -> None:
    subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


def _run_capture(command: list[str], *, cwd: Path) -> str:
    print(f"$ {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=sys.stderr, check=True)
    return completed.stdout


if __name__ == "__main__":
    raise SystemExit(main())
