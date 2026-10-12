"""Verification helpers for the local WorkRecorder.app packager."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

APPLE_VISION_HELPER_RELATIVE_PATH = Path("packages/enrichment/visual_ocr/apple_vision_ocr.swift")
APPLE_VISION_HELPER_BINARY_RELATIVE_PATH = Path("packages/enrichment/visual_ocr/apple_vision_ocr_helper")
DISTRIBUTION_INSTALL_SECRET_PLACEHOLDER = "__workrecorder_generate_on_first_launch__"


def verify_runtime_config(path: Path) -> dict[str, object]:
    """Validate runtime config and return its JSON payload.

    Args:
        path: Runtime config path inside ``WorkRecorder.app`` resources.

    Returns:
        Parsed runtime config payload.

    Raises:
        SystemExit: If the config points at an invalid local runtime.
    """

    payload = json.loads(path.read_text(encoding="utf-8"))
    repo_root_raw = Path(str(payload.get("repo_root", "")))
    repo_root = repo_root_raw if repo_root_raw.is_absolute() else (path.parent / repo_root_raw).resolve()
    daemon_url = str(payload.get("daemon_url", ""))
    install_secret = str(payload.get("install_secret", ""))
    provider_registration_secret = payload.get("provider_registration_secret")
    native_capture_secret = payload.get("native_capture_secret")
    mode = str(payload.get("mode", ""))
    parsed = urlparse(daemon_url)
    if not repo_root.exists():
        raise SystemExit(f"WorkRecorder.app runtime repo_root does not exist: {repo_root}")
    if parsed.scheme not in {"http", "https"} or parsed.hostname != "127.0.0.1" or not parsed.port:
        raise SystemExit(f"WorkRecorder.app runtime daemon_url is invalid: {daemon_url}")
    placeholder_allowed = mode == "distribution" and install_secret == DISTRIBUTION_INSTALL_SECRET_PLACEHOLDER
    if not placeholder_allowed and (install_secret == "dev-install-secret" or len(install_secret) < 32):
        raise SystemExit("WorkRecorder.app runtime install_secret must be a generated per-bundle secret")
    provider_placeholder_allowed = (
        mode == "distribution" and provider_registration_secret == DISTRIBUTION_INSTALL_SECRET_PLACEHOLDER
    )
    if not provider_placeholder_allowed:
        provider_secret = str(provider_registration_secret or "")
        if provider_secret == "dev-provider-secret" or len(provider_secret) < 32:
            raise SystemExit(
                "WorkRecorder.app runtime provider_registration_secret must be a generated provider-only secret"
            )
        if provider_secret == install_secret:
            raise SystemExit("WorkRecorder.app runtime provider_registration_secret must differ from install_secret")
    native_missing_allowed = mode == "distribution" and native_capture_secret in {None, ""}
    if not native_missing_allowed:
        native_secret = str(native_capture_secret or "")
        if len(native_secret) < 32:
            raise SystemExit("WorkRecorder.app runtime native_capture_secret must be a generated native-only secret")
        if native_secret == install_secret:
            raise SystemExit("WorkRecorder.app runtime native_capture_secret must differ from install_secret")
    payload["repo_root"] = str(repo_root)
    return payload


def verify_python_runtime_assets(repo_root: Path) -> None:
    """Check Python-side runtime files that the app-owned daemon imports.

    Args:
        repo_root: Repository root referenced by app runtime config.

    Raises:
        SystemExit: If a required Python-side runtime asset is missing or not importable.
    """

    helper = repo_root / APPLE_VISION_HELPER_RELATIVE_PATH
    helper_binary = repo_root / APPLE_VISION_HELPER_BINARY_RELATIVE_PATH
    if not helper.exists() and not helper_binary.exists():
        raise SystemExit("WorkRecorder.app runtime is missing Apple Vision OCR helper: " f"{helper} or {helper_binary}")
    python = repo_root / ".venv" / "bin" / "python"
    if not python.exists():
        return
    completed = subprocess.run(
        [
            str(python),
            "-c",
            (
                "from packages.enrichment.visual_ocr.apple_vision import apple_vision_unavailable_reason; "
                "reason = apple_vision_unavailable_reason(); "
                "raise SystemExit(0 if reason is None else reason)"
            ),
        ],
        cwd=repo_root,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "WorkRecorder.app runtime cannot import Apple Vision OCR helper:\n"
            f"{completed.stdout.strip()}\n{completed.stderr.strip()}".strip()
        )


def verify_extension_manifest(extension_dir: Path) -> None:
    """Validate copied browser extension resources.

    Args:
        extension_dir: Copied browser extension directory inside app resources.

    Raises:
        SystemExit: If the manifest or declared scripts are missing/invalid.
    """

    manifest = json.loads((extension_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != 3:
        raise SystemExit("WorkRecorder browser extension manifest must be MV3")
    worker = manifest.get("background", {}).get("service_worker")
    if not worker or not (extension_dir / worker).exists():
        raise SystemExit(f"Browser extension service worker is missing: {worker}")
    for script in manifest.get("content_scripts", []):
        for js_file in script.get("js", []):
            if not (extension_dir / js_file).exists():
                raise SystemExit(f"Browser extension content script is missing: {js_file}")


def verify_extension_config(*, runtime_config: Path, extension_config: Path) -> None:
    """Ensure app runtime and extension configs share daemon URL and provider secret.

    Args:
        runtime_config: App runtime config path.
        extension_config: Copied browser extension runtime config path.

    Raises:
        SystemExit: If daemon URL or provider secret drift between configs.
    """

    runtime_payload = json.loads(runtime_config.read_text(encoding="utf-8"))
    extension_payload = json.loads(extension_config.read_text(encoding="utf-8"))
    if "install_secret" in extension_payload:
        raise SystemExit("WorkRecorder extension config must not include install_secret")
    if "native_capture_secret" in extension_payload:
        raise SystemExit("WorkRecorder extension config must not include native_capture_secret")
    for key in ("daemon_url", "provider_registration_secret"):
        if runtime_payload.get(key) != extension_payload.get(key):
            raise SystemExit(f"WorkRecorder extension config mismatch for {key}")
    placeholders = {
        extension_payload.get("provider_registration_secret"),
        runtime_payload.get("install_secret"),
    }
    placeholder_pair = placeholders == {DISTRIBUTION_INSTALL_SECRET_PLACEHOLDER}
    if not placeholder_pair and extension_payload.get("provider_registration_secret") == runtime_payload.get(
        "install_secret"
    ):
        raise SystemExit("WorkRecorder extension provider_registration_secret must differ from install_secret")
