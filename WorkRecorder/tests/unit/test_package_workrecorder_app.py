from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import package_workrecorder_app


def test_package_verify_validates_recording_runtime_bundle(tmp_path: Path) -> None:
    app_dir = _bundle(tmp_path, daemon_url="http://127.0.0.1:8765")

    package_workrecorder_app._verify_bundle(app_dir, verify_signature=False)


def test_default_bundle_is_english_workrecorder(tmp_path: Path) -> None:
    contents = tmp_path / "WorkRecorder.app" / "Contents"
    contents.mkdir(parents=True)
    info_path = contents / "Info.plist"

    package_workrecorder_app._write_info_plist(
        info_path,
        bundle=package_workrecorder_app.WORKRECORDER_BUNDLE,
    )

    package_workrecorder_app._verify_info_plist(
        info_path,
        bundle=package_workrecorder_app.WORKRECORDER_BUNDLE,
    )
    import plistlib

    with info_path.open("rb") as handle:
        info = plistlib.load(handle)
    assert info["CFBundleIdentifier"] == "app.workrecorder.local"
    assert info["CFBundleDisplayName"] == "WorkRecorder"
    assert info["CFBundleExecutable"] == "WorkRecorder"
    assert info["CFBundleDevelopmentRegion"] == "en"
    assert info["WorkRecorderUILanguage"] == "en"


def test_package_verify_rejects_invalid_daemon_url(tmp_path: Path) -> None:
    app_dir = _bundle(tmp_path, daemon_url="http://127.0.0.1")

    with pytest.raises(SystemExit, match="daemon_url is invalid"):
        package_workrecorder_app._verify_bundle(app_dir, verify_signature=False)


def test_package_verify_rejects_default_install_secret(tmp_path: Path) -> None:
    app_dir = _bundle(tmp_path, daemon_url="http://127.0.0.1:8765", install_secret="dev-install-secret")

    with pytest.raises(SystemExit, match="generated per-bundle secret"):
        package_workrecorder_app._verify_bundle(app_dir, verify_signature=False)


def test_package_verify_rejects_missing_native_capture_secret(tmp_path: Path) -> None:
    app_dir = _bundle(tmp_path, daemon_url="http://127.0.0.1:8765")
    runtime_config = app_dir / "Contents" / "Resources" / "runtime-config.json"
    payload = json.loads(runtime_config.read_text(encoding="utf-8"))
    payload.pop("native_capture_secret")
    runtime_config.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SystemExit, match="native_capture_secret"):
        package_workrecorder_app._verify_bundle(app_dir, verify_signature=False)


def test_package_verify_rejects_missing_apple_vision_helper(tmp_path: Path) -> None:
    app_dir = _bundle(tmp_path, daemon_url="http://127.0.0.1:8765")
    helper = tmp_path / package_workrecorder_app.APPLE_VISION_HELPER_RELATIVE_PATH
    helper.unlink()

    with pytest.raises(SystemExit, match="Apple Vision OCR helper"):
        package_workrecorder_app._verify_bundle(app_dir, verify_signature=False)


def test_package_verify_resolves_relative_runtime_repo_root(tmp_path: Path) -> None:
    app_dir = _bundle(tmp_path, daemon_url="http://127.0.0.1:8765")
    resources = app_dir / "Contents" / "Resources"
    relative_repo = resources / "runtime" / "repo"
    helper = tmp_path / package_workrecorder_app.APPLE_VISION_HELPER_RELATIVE_PATH
    relative_helper = relative_repo / package_workrecorder_app.APPLE_VISION_HELPER_RELATIVE_PATH
    relative_helper.parent.mkdir(parents=True)
    relative_helper.write_text(helper.read_text(encoding="utf-8"), encoding="utf-8")
    (resources / "runtime-config.json").write_text(
        json.dumps(
            {
                "repo_root": "runtime/repo",
                "daemon_url": "http://127.0.0.1:8765",
                "install_secret": "workrecorder_" + ("c" * 32),
                "provider_registration_secret": "workrecorder_provider_" + ("e" * 32),
                "native_capture_secret": "workrecorder_native_" + ("d" * 32),
            }
        ),
        encoding="utf-8",
    )
    package_workrecorder_app._verify_bundle(app_dir, verify_signature=False)


def test_package_verify_accepts_distribution_first_launch_secret_placeholder(tmp_path: Path) -> None:
    app_dir = _bundle(tmp_path, daemon_url="http://127.0.0.1:8765")
    resources = app_dir / "Contents" / "Resources"
    relative_repo = resources / "runtime" / "repo"
    helper = tmp_path / package_workrecorder_app.APPLE_VISION_HELPER_RELATIVE_PATH
    relative_helper = relative_repo / package_workrecorder_app.APPLE_VISION_HELPER_RELATIVE_PATH
    relative_helper.parent.mkdir(parents=True)
    relative_helper.write_text(helper.read_text(encoding="utf-8"), encoding="utf-8")
    placeholder = "__workrecorder_generate_on_first_launch__"
    (resources / "runtime-config.json").write_text(
        json.dumps(
            {
                "repo_root": "runtime/repo",
                "daemon_url": "http://127.0.0.1:8765",
                "install_secret": placeholder,
                "provider_registration_secret": placeholder,
                "mode": "distribution",
            }
        ),
        encoding="utf-8",
    )
    package_workrecorder_app._verify_bundle(app_dir, verify_signature=False)


def test_package_sign_uses_adhoc_identity_and_clears_detritus(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    xattr_calls: list[list[str]] = []

    def fake_sign(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    def fake_subprocess_run(command: list[str], **_: object) -> object:
        xattr_calls.append(command)

    monkeypatch.setattr(
        package_workrecorder_app.macos_codesign,
        "_run_codesign_sign",
        lambda path, *, signing_identity: fake_sign(
            [
                "codesign",
                "--force",
                "--deep",
                "--sign",
                "-",
                "--identifier",
                package_workrecorder_app.BUNDLE_ID,
                str(path),
            ],
            cwd=path.parent,
        ),
    )
    monkeypatch.setattr(
        package_workrecorder_app.macos_codesign.shutil,
        "which",
        lambda name: "/usr/bin/xattr" if name == "xattr" else None,
    )
    monkeypatch.setattr(package_workrecorder_app.macos_codesign.subprocess, "run", fake_subprocess_run)
    app_dir = tmp_path / "WorkRecorder.app"
    app_dir.mkdir()

    package_workrecorder_app._sign_bundle(app_dir, adhoc=True)

    assert calls == [
        [
            "codesign",
            "--force",
            "--deep",
            "--sign",
            "-",
            "--identifier",
            package_workrecorder_app.BUNDLE_ID,
            str(app_dir),
        ]
    ]
    assert ["xattr", "-rd", "com.apple.FinderInfo", str(app_dir)] in xattr_calls
    assert ["xattr", "-rd", "com.apple.fileprovider.fpfs#P", str(app_dir)] in xattr_calls


def test_run_codesign_sign_pins_bundle_identifier(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app_dir = tmp_path / "WorkRecorder.app"
    app_dir.mkdir()
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(package_workrecorder_app.macos_codesign.subprocess, "run", fake_run)

    package_workrecorder_app.macos_codesign._run_codesign_sign(app_dir, signing_identity=None)

    assert calls == [
        [
            "codesign",
            "--force",
            "--deep",
            "--sign",
            "-",
            "--identifier",
            package_workrecorder_app.BUNDLE_ID,
            str(app_dir),
        ]
    ]


def test_package_sign_uses_sanitized_copy_when_fileprovider_xattrs_reappear(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app_dir = tmp_path / "WorkRecorder.app"
    app_dir.mkdir()
    sign_calls: list[Path] = []
    sanitized_calls: list[Path] = []

    def fake_sign(path: Path, *, signing_identity: object) -> subprocess.CompletedProcess[str]:
        sign_calls.append(path)
        return subprocess.CompletedProcess(
            args=["codesign"],
            returncode=1,
            stderr="resource fork, Finder information, or similar detritus not allowed: com.apple.FinderInfo",
        )

    monkeypatch.setattr(package_workrecorder_app.macos_codesign, "_run_codesign_sign", fake_sign)
    monkeypatch.setattr(
        package_workrecorder_app.macos_codesign,
        "_sign_bundle_on_sanitized_copy",
        lambda path, *, signing_identity: sanitized_calls.append(path),
    )

    package_workrecorder_app._sign_bundle(app_dir, adhoc=True)

    assert sign_calls == [app_dir, app_dir]
    assert sanitized_calls == [app_dir]


def test_package_materializes_strict_verified_temp_artifact(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app_dir = tmp_path / "WorkRecorder.app"
    app_dir.mkdir()
    verified_paths: list[Path] = []
    ditto_targets: list[Path] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if command[0] == "ditto":
            target = Path(command[-1])
            target.mkdir(parents=True)
            ditto_targets.append(target)
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:3] == ["codesign", "-dv", "--verbose=4"]:
            return subprocess.CompletedProcess(command, 0, "", f"Identifier={package_workrecorder_app.BUNDLE_ID}")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        package_workrecorder_app.macos_codesign.shutil,
        "which",
        lambda name: "/usr/bin/ditto" if name == "ditto" else None,
    )
    monkeypatch.setattr(package_workrecorder_app.macos_codesign.subprocess, "run", fake_run)
    monkeypatch.setattr(
        package_workrecorder_app.macos_codesign,
        "_run_codesign_verify",
        lambda path: verified_paths.append(path) or subprocess.CompletedProcess(["codesign"], 0, "", ""),
    )
    artifact = package_workrecorder_app._materialize_strict_verified_artifact(app_dir)

    assert artifact != app_dir
    assert artifact.name == "WorkRecorder-strict-verified.app"
    assert ditto_targets == [artifact]
    assert verified_paths == [artifact]


def test_package_verify_accepts_sanitized_codesign_when_worktree_xattrs_reappear(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app_dir = tmp_path / "WorkRecorder.app"
    app_dir.mkdir()
    sanitized_calls: list[Path] = []

    monkeypatch.setattr(
        package_workrecorder_app.macos_codesign,
        "_run_codesign_verify",
        lambda path: subprocess.CompletedProcess(
            ["codesign"],
            1,
            "",
            "resource fork, Finder information, or similar detritus not allowed: com.apple.FinderInfo",
        ),
    )
    monkeypatch.setattr(
        package_workrecorder_app.macos_codesign,
        "_verify_codesign_on_sanitized_copy",
        lambda path: sanitized_calls.append(path),
    )

    package_workrecorder_app._verify_codesign(app_dir)

    assert sanitized_calls == [app_dir]


def _bundle(tmp_path: Path, *, daemon_url: str, install_secret: str = "workrecorder_" + ("a" * 32)) -> Path:
    app_dir = tmp_path / f"{package_workrecorder_app.APP_NAME}.app"
    contents = app_dir / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    helper = tmp_path / package_workrecorder_app.APPLE_VISION_HELPER_RELATIVE_PATH
    helper.parent.mkdir(parents=True)
    helper.write_text("// helper placeholder\n", encoding="utf-8")
    executable = macos / package_workrecorder_app.APP_NAME
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    package_workrecorder_app._write_info_plist(contents / "Info.plist")
    (resources / "runtime-config.json").write_text(
        json.dumps(
            {
                "repo_root": str(tmp_path),
                "daemon_url": daemon_url,
                "install_secret": install_secret,
                "provider_registration_secret": "workrecorder_provider_" + ("e" * 32),
                "native_capture_secret": "workrecorder_native_" + ("d" * 32),
            }
        ),
        encoding="utf-8",
    )
    (resources / "AppIcon.icns").write_bytes(b"icns-test-placeholder")
    (resources / "app-icon.png").write_bytes(b"png-test-placeholder")
    return app_dir
