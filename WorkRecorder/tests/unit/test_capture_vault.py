from __future__ import annotations

from datetime import UTC, datetime

import pytest

from packages.artifacts.vault import ArtifactVaultError, LocalArtifactVault


def test_local_vault_promotes_staged_file(tmp_path):
    staging = tmp_path / "staging"
    vault_dir = tmp_path / "vault"
    staging.mkdir()
    staged = staging / "capture.png"
    staged.write_bytes(b"\x89PNG\r\n\x1a\nworkrecorder")
    vault = LocalArtifactVault(staging_dir=staging, vault_dir=vault_dir)

    promoted = vault.promote(
        staged_path=staged,
        artifact_id="art_test",
        created_at=datetime(2026, 5, 14, tzinfo=UTC),
    )

    assert promoted.local_path.is_file()
    assert promoted.byte_size == len(b"\x89PNG\r\n\x1a\nworkrecorder")
    assert promoted.storage_uri.startswith("local-artifact://blobs/")
    assert promoted.storage_uri.endswith(".png")
    assert not staged.exists()


def test_local_vault_rejects_paths_outside_staging(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"workrecorder")
    vault = LocalArtifactVault(staging_dir=staging, vault_dir=tmp_path / "vault")

    with pytest.raises(ArtifactVaultError):
        vault.validate_staged_file(outside)


def test_local_vault_rejects_non_png_bytes(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    staged = staging / "capture.png"
    staged.write_bytes(b"workrecorder")
    vault = LocalArtifactVault(staging_dir=staging, vault_dir=tmp_path / "vault")

    with pytest.raises(ArtifactVaultError):
        vault.validate_staged_file(staged)


def test_local_vault_rejects_symlink(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    target = staging / "target.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\nworkrecorder")
    symlink = staging / "capture.png"
    symlink.symlink_to(target)
    vault = LocalArtifactVault(staging_dir=staging, vault_dir=tmp_path / "vault")

    with pytest.raises(ArtifactVaultError):
        vault.validate_staged_file(symlink)
