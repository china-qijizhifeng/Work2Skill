"""macOS codesign helpers for WorkRecorder local app packaging."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

APP_NAME = "WorkRecorder"
BUNDLE_ID = "app.workrecorder.local"
LOCAL_SIGNING_IDENTITY = "WorkRecorder Local Development"
LOCAL_SIGNING_PASSWORD = "workrecorder-local"


def _sign_bundle(app_dir: Path, *, adhoc: bool = False) -> None:
    """Sign ``app_dir`` for local macOS testing.

    Uses a stable local identity unless ad-hoc signing is explicitly requested,
    and falls back to a sanitized copy if FileProvider metadata breaks signing.
    """

    _clear_bundle_xattrs(app_dir)
    signing_identity = None if adhoc or _adhoc_requested() else _ensure_local_signing_identity()
    completed = _run_codesign_sign(app_dir, signing_identity=signing_identity)
    if completed.returncode != 0 and "resource fork" in completed.stderr:
        _clear_bundle_xattrs(app_dir)
        completed = _run_codesign_sign(app_dir, signing_identity=signing_identity)
        if completed.returncode != 0 and "resource fork" in completed.stderr:
            _sign_bundle_on_sanitized_copy(app_dir, signing_identity=signing_identity)
            return
    if completed.returncode != 0:
        raise SystemExit(f"WorkRecorder.app codesign failed:\n{completed.stderr.strip()}")
    _clear_bundle_xattrs(app_dir)


def _sign_bundle_on_sanitized_copy(app_dir: Path, *, signing_identity: tuple[str, Path] | None) -> None:
    """Sign a no-extattr temporary copy and replace ``app_dir`` with it.

    This preserves the app bundle contents while removing Finder/FileProvider
    metadata that codesign treats as sealed-resource detritus.
    """

    if shutil.which("ditto") is None:
        raise SystemExit("WorkRecorder.app codesign failed and ditto is unavailable for sanitized signing")
    with tempfile.TemporaryDirectory(prefix="workrecorder-app-sign-") as directory:
        clean_app = Path(directory) / app_dir.name
        subprocess.run(["ditto", "--noextattr", "--norsrc", str(app_dir), str(clean_app)], check=True)
        completed = _run_codesign_sign(clean_app, signing_identity=signing_identity)
        if completed.returncode != 0:
            raise SystemExit(f"WorkRecorder.app sanitized codesign failed:\n{completed.stderr.strip()}")
        shutil.rmtree(app_dir)
        subprocess.run(["ditto", "--noextattr", "--norsrc", str(clean_app), str(app_dir)], check=True)
        _clear_bundle_xattrs(app_dir)


def _verify_codesign(app_dir: Path) -> None:
    """Run strict codesign verification and identity checks for ``app_dir``.

    A sanitized temporary verification is allowed only as a local filesystem
    workaround; any real signature or bundle identity failure still aborts.
    """

    _clear_bundle_xattrs(app_dir)
    completed = _run_codesign_verify(app_dir)
    if completed.returncode != 0 and "resource fork" in completed.stderr:
        _clear_bundle_xattrs(app_dir)
        completed = _run_codesign_verify(app_dir)
        if completed.returncode != 0 and "resource fork" in completed.stderr:
            _verify_codesign_on_sanitized_copy(app_dir)
            return
    if completed.returncode != 0:
        raise SystemExit(f"WorkRecorder.app codesign verification failed:\n{completed.stderr.strip()}")
    _verify_codesign_identity(app_dir, label="WorkRecorder.app codesign")
    _clear_bundle_xattrs(app_dir)


def _materialize_strict_verified_artifact(app_dir: Path) -> Path:
    """Return a stable strict-verified app artifact for manual E2E runs.

    The returned path may be a sanitized temp bundle when the source worktree can
    reacquire Finder metadata after a successful verification.
    """

    if shutil.which("ditto") is None:
        return app_dir
    verified_app = Path(tempfile.gettempdir()) / f"{APP_NAME}-strict-verified.app"
    if verified_app.exists():
        shutil.rmtree(verified_app)
    subprocess.run(["ditto", "--noextattr", "--norsrc", str(app_dir), str(verified_app)], check=True)
    completed = _run_codesign_verify(verified_app)
    if completed.returncode != 0:
        raise SystemExit(f"WorkRecorder.app strict verified artifact failed codesign:\n{completed.stderr.strip()}")
    _verify_codesign_identity(verified_app, label="WorkRecorder.app strict verified artifact")
    return verified_app


def _verify_codesign_identity(app_dir: Path, *, label: str) -> None:
    """Verify that ``app_dir`` carries WorkRecorder's expected bundle identity."""

    details = subprocess.run(
        ["codesign", "-dv", "--verbose=4", str(app_dir)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if details.returncode != 0:
        raise SystemExit(f"{label} details failed:\n{details.stderr.strip()}")
    if f"Identifier={BUNDLE_ID}" not in details.stderr:
        raise SystemExit(f"{label} identifier mismatch:\n{details.stderr.strip()}")


def _verify_codesign_on_sanitized_copy(app_dir: Path) -> None:
    """Verify a clean temporary copy when source-folder xattrs reappear."""

    if shutil.which("ditto") is None:
        raise SystemExit("WorkRecorder.app codesign verification failed and ditto is unavailable for sanitized verify")
    with tempfile.TemporaryDirectory(prefix="workrecorder-app-verify-") as directory:
        clean_app = Path(directory) / app_dir.name
        subprocess.run(["ditto", "--noextattr", "--norsrc", str(app_dir), str(clean_app)], check=True)
        completed = _run_codesign_verify(clean_app)
        if completed.returncode != 0:
            raise SystemExit(f"WorkRecorder.app sanitized codesign verification failed:\n{completed.stderr.strip()}")
        _verify_codesign_identity(clean_app, label="WorkRecorder.app sanitized codesign")


def _run_codesign_verify(app_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run strict ``codesign --verify`` and return the raw completed process."""

    return subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app_dir)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _run_codesign_sign(
    app_dir: Path,
    *,
    signing_identity: tuple[str, Path] | None,
) -> subprocess.CompletedProcess[str]:
    """Run ``codesign --sign`` with either ad-hoc or local identity signing."""

    if signing_identity is None:
        command = [
            "codesign",
            "--force",
            "--deep",
            "--sign",
            "-",
            "--identifier",
            BUNDLE_ID,
            str(app_dir),
        ]
    else:
        identity, keychain = signing_identity
        command = [
            "codesign",
            "--force",
            "--deep",
            "--sign",
            identity,
            "--keychain",
            str(keychain),
            "--identifier",
            BUNDLE_ID,
            str(app_dir),
        ]
    print(f"$ {' '.join(command)}", flush=True)
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def _clear_bundle_xattrs(app_dir: Path) -> None:
    """Remove Finder/FileProvider xattrs from a bundle tree when possible."""

    if shutil.which("xattr") is None:
        return
    subprocess.run(["xattr", "-cr", str(app_dir)], check=False)
    for attribute in ("com.apple.FinderInfo", "com.apple.fileprovider.fpfs#P"):
        subprocess.run(["xattr", "-rd", attribute, str(app_dir)], check=False, stderr=subprocess.DEVNULL)
        subprocess.run(["xattr", "-d", attribute, str(app_dir)], check=False, stderr=subprocess.DEVNULL)
    subprocess.run(["xattr", "-c", str(app_dir)], check=False)
    for root, directories, files in os.walk(app_dir):
        for name in [*directories, *files]:
            subprocess.run(["xattr", "-c", str(Path(root) / name)], check=False, stderr=subprocess.DEVNULL)
    subprocess.run(["xattr", "-c", str(app_dir)], check=False)


def _adhoc_requested() -> bool:
    return os.environ.get("WORKRECORDER_APP_ADHOC_SIGN") == "1"


def _ensure_local_signing_identity() -> tuple[str, Path] | None:
    if shutil.which("security") is None or shutil.which("openssl") is None:
        return None
    root = Path.home() / ".workrecorder" / "codesign"
    keychain = root / "WorkRecorderLocal.keychain-db"
    cert = root / "workrecorder-local.crt"
    key = root / "workrecorder-local.key"
    p12 = root / "workrecorder-local.p12"
    config = root / "workrecorder-cert.cnf"
    root.mkdir(parents=True, exist_ok=True)
    _write_local_certificate_config(config)
    if not cert.exists() or not key.exists() or not p12.exists():
        _create_local_certificate(config=config, cert=cert, key=key, p12=p12)
    if not keychain.exists():
        _run_security(["security", "create-keychain", "-p", LOCAL_SIGNING_PASSWORD, str(keychain)])
    _unlock_or_recreate_keychain(keychain)
    _ensure_keychain_in_search_list(keychain)
    if not _has_valid_identity(keychain):
        # OpenSSL 3 defaults to PBES2/AES-256 for PKCS#12 files, which the
        # macOS `security import` command reports as a MAC verification error.
        # Re-export the existing key pair with Apple-compatible algorithms
        # before importing it into the dedicated local signing keychain.
        _create_local_pkcs12(cert=cert, key=key, p12=p12)
        _run_security(
            [
                "security",
                "import",
                str(p12),
                "-k",
                str(keychain),
                "-P",
                LOCAL_SIGNING_PASSWORD,
                "-T",
                "/usr/bin/codesign",
            ],
            allow_failure=True,
        )
        _run_security(
            ["security", "add-trusted-cert", "-r", "trustRoot", "-p", "codeSign", "-k", str(keychain), str(cert)],
            allow_failure=True,
        )
    return (LOCAL_SIGNING_IDENTITY, keychain) if _has_valid_identity(keychain) else None


def _unlock_or_recreate_keychain(keychain: Path) -> None:
    completed = _run_security(
        ["security", "unlock-keychain", "-p", LOCAL_SIGNING_PASSWORD, str(keychain)],
        allow_failure=True,
    )
    if completed.returncode == 0:
        return
    _run_security(["security", "delete-keychain", str(keychain)], allow_failure=True)
    keychain.unlink(missing_ok=True)
    _run_security(["security", "create-keychain", "-p", LOCAL_SIGNING_PASSWORD, str(keychain)])
    _run_security(["security", "unlock-keychain", "-p", LOCAL_SIGNING_PASSWORD, str(keychain)])


def _ensure_keychain_in_search_list(keychain: Path) -> None:
    completed = _run_security(["security", "list-keychains", "-d", "user"])
    existing = [line.strip().strip('"') for line in completed.stdout.splitlines() if line.strip()]
    keychain_path = str(keychain)
    if keychain_path not in existing:
        _run_security(["security", "list-keychains", "-d", "user", "-s", keychain_path, *existing])


def _write_local_certificate_config(path: Path) -> None:
    path.write_text(
        textwrap.dedent(f"""
            [ req ]
            distinguished_name = dn
            x509_extensions = v3_req
            prompt = no
            [ dn ]
            CN = {LOCAL_SIGNING_IDENTITY}
            [ v3_req ]
            keyUsage = critical,digitalSignature
            extendedKeyUsage = critical,codeSigning
            basicConstraints = critical,CA:false
            subjectKeyIdentifier = hash
            """).strip() + "\n",
        encoding="utf-8",
    )


def _create_local_certificate(*, config: Path, cert: Path, key: Path, p12: Path) -> None:
    _run_security(
        [
            "openssl",
            "req",
            "-new",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "3650",
            "-config",
            str(config),
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ]
    )
    _create_local_pkcs12(cert=cert, key=key, p12=p12)
    key.chmod(0o600)
    p12.chmod(0o600)


def _create_local_pkcs12(*, cert: Path, key: Path, p12: Path) -> None:
    _run_security(
        [
            "openssl",
            "pkcs12",
            "-export",
            "-out",
            str(p12),
            "-inkey",
            str(key),
            "-in",
            str(cert),
            "-name",
            LOCAL_SIGNING_IDENTITY,
            "-keypbe",
            "PBE-SHA1-3DES",
            "-certpbe",
            "PBE-SHA1-3DES",
            "-macalg",
            "sha1",
            "-password",
            f"pass:{LOCAL_SIGNING_PASSWORD}",
        ]
    )
    p12.chmod(0o600)


def _has_valid_identity(keychain: Path) -> bool:
    completed = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning", str(keychain)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return completed.returncode == 0 and LOCAL_SIGNING_IDENTITY in completed.stdout


def _run_security(command: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0 and not allow_failure:
        raise SystemExit(f"Local signing setup failed while running {' '.join(command)}:\n{completed.stderr.strip()}")
    return completed
