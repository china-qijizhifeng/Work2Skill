"""Local artifact vault for staged capture files."""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

MAX_CAPTURE_ARTIFACT_BYTES = 50 * 1024 * 1024
MAX_GENERATED_ARTIFACT_BYTES = 10 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MP4_BRAND_OFFSET = 4
MP4_BRAND_MAGIC = b"ftyp"
MP4_BOX_HEADER_BYTES = 8
MP4_BOX_EXTENDED_SIZE_BYTES = 16
MP4_VERSION_AND_FLAGS_BYTES = 4
MP4_MVHD_V0_TIMESCALE_OFFSET = 8
MP4_MVHD_V0_DURATION_OFFSET = 12
MP4_MVHD_V1_TIMESCALE_OFFSET = 16
MP4_MVHD_V1_DURATION_OFFSET = 20


class ArtifactVaultError(Exception):
    """Raised when a staged artifact cannot be safely promoted."""


class ArtifactVaultTransientError(ArtifactVaultError):
    """Raised when promotion may succeed on retry without changing input."""


@dataclass(frozen=True)
class PromotedArtifactFile:
    """File metadata produced by local artifact vault promotion.

    Attributes:
        storage_uri: Local vault URI stored in artifact metadata.
        local_path: Absolute path to the promoted vault file.
        byte_size: File size in bytes.
        sha256: Hex-encoded SHA-256 hash of the promoted file.
        duration_ms: Optional MP4 duration parsed during video promotion.
    """

    storage_uri: str
    local_path: Path
    byte_size: int
    sha256: str
    duration_ms: int | None = None


@dataclass(frozen=True)
class MP4VideoMetadata:
    """Container metadata parsed from a staged MP4 file.

    Attributes:
        duration_ms: Duration parsed from the MP4 movie header.
    """

    duration_ms: int


class LocalArtifactVault:
    """Promote capture shell files from staging into daemon-owned storage."""

    def __init__(self, *, staging_dir: Path, vault_dir: Path) -> None:
        """Create a local artifact vault.

        Args:
            staging_dir: Directory where native capture shells stage files.
            vault_dir: Directory owned by the daemon for durable artifacts.
        """

        self.staging_dir = staging_dir
        self.vault_dir = vault_dir

    def promote(self, *, staged_path: Path, artifact_id: str, created_at: datetime) -> PromotedArtifactFile:
        """Move a staged file into the durable local vault.

        Args:
            staged_path: Path produced by the capture shell.
            artifact_id: Artifact id used as the durable file stem.
            created_at: Creation time used to shard artifact paths.

        Returns:
            Promoted artifact metadata.

        Raises:
            ArtifactVaultError: When the file is missing, outside staging, or
                cannot be moved safely.
        """

        source = self.validate_staged_file(staged_path)
        return self._promote_validated_source(source)

    def promote_video(
        self,
        *,
        staged_path: Path,
        artifact_id: str,
        created_at: datetime,
        max_bytes: int,
    ) -> PromotedArtifactFile:
        """Move a staged MP4 recording into the durable local vault."""

        del artifact_id, created_at
        source = self.validate_staged_video_file(staged_path, max_bytes=max_bytes)
        video_metadata = self.inspect_mp4_video_metadata(source)
        promoted = self._promote_validated_source(source)
        return PromotedArtifactFile(
            storage_uri=promoted.storage_uri,
            local_path=promoted.local_path,
            byte_size=promoted.byte_size,
            sha256=promoted.sha256,
            duration_ms=video_metadata.duration_ms,
        )

    def copy_video(
        self,
        *,
        staged_path: Path,
        artifact_id: str,
        created_at: datetime,
        max_bytes: int,
        expected_duration_ms: int | None = None,
        duration_tolerance_ms: int = 0,
    ) -> PromotedArtifactFile:
        """Copy a staged MP4 into durable storage while leaving staging retryable."""

        del artifact_id, created_at
        source = self.validate_staged_video_file(staged_path, max_bytes=max_bytes)
        return self._copy_validated_video_source(
            source,
            max_bytes=max_bytes,
            expected_duration_ms=expected_duration_ms,
            duration_tolerance_ms=duration_tolerance_ms,
        )

    def _promote_validated_source(self, source: Path) -> PromotedArtifactFile:
        """Move an already validated staged file into content-addressed storage."""

        suffix = source.suffix if source.suffix else ".bin"
        sha256, byte_size = self._hash_file(source)
        target = self._content_addressed_path(sha256=sha256, suffix=suffix)
        vault_root = self.vault_dir.expanduser().resolve()
        if not target.is_relative_to(vault_root):
            raise ArtifactVaultError("artifact target is outside the configured vault directory")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp_target = target.with_suffix(f"{target.suffix}.tmp")
        try:
            if target.exists():
                source.unlink(missing_ok=True)
            else:
                shutil.move(str(source), str(temp_target))
                os.replace(temp_target, target)
        except Exception as exc:
            if temp_target.exists():
                temp_target.unlink(missing_ok=True)
            raise ArtifactVaultError("failed to promote staged artifact") from exc
        return PromotedArtifactFile(
            storage_uri=f"local-artifact://{target.relative_to(self.vault_dir.resolve())}",
            local_path=target,
            byte_size=byte_size,
            sha256=sha256,
        )

    def _copy_validated_source(self, source: Path) -> PromotedArtifactFile:
        """Copy an already validated staged file into content-addressed storage."""

        suffix = source.suffix if source.suffix else ".bin"
        vault_root = self.vault_dir.expanduser().resolve()
        temp_root = (vault_root / "tmp").resolve()
        if not temp_root.is_relative_to(vault_root):
            raise ArtifactVaultError("artifact temp target is outside the configured vault directory")
        temp_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp_target = temp_root / f"{uuid.uuid4().hex}{suffix}.tmp"
        try:
            shutil.copy2(source, temp_target)
            sha256, byte_size = self._hash_file(temp_target)
            target = self._content_addressed_path(sha256=sha256, suffix=suffix)
            if not target.is_relative_to(vault_root):
                raise ArtifactVaultError("artifact target is outside the configured vault directory")
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not target.exists():
                os.replace(temp_target, target)
            else:
                temp_target.unlink(missing_ok=True)
        except Exception as exc:
            if temp_target.exists():
                temp_target.unlink(missing_ok=True)
            raise ArtifactVaultTransientError("failed to copy staged artifact") from exc
        return PromotedArtifactFile(
            storage_uri=f"local-artifact://{target.relative_to(self.vault_dir.resolve())}",
            local_path=target,
            byte_size=byte_size,
            sha256=sha256,
        )

    def _copy_validated_video_source(
        self,
        source: Path,
        *,
        max_bytes: int,
        expected_duration_ms: int | None,
        duration_tolerance_ms: int,
    ) -> PromotedArtifactFile:
        """Copy a validated MP4 only after probing the copied bytes."""

        suffix = source.suffix if source.suffix else ".mp4"
        vault_root = self.vault_dir.expanduser().resolve()
        temp_root = (vault_root / "tmp").resolve()
        if not temp_root.is_relative_to(vault_root):
            raise ArtifactVaultError("artifact temp target is outside the configured vault directory")
        temp_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp_target = temp_root / f"{uuid.uuid4().hex}{suffix}.tmp"
        try:
            shutil.copy2(source, temp_target)
            byte_size = temp_target.stat().st_size
            if byte_size <= 0:
                raise ArtifactVaultError("staged video is empty")
            if byte_size > max_bytes:
                raise ArtifactVaultError("staged video exceeds the maximum size")
            video_metadata = self.inspect_mp4_video_metadata(temp_target)
            if expected_duration_ms is not None:
                delta_ms = abs(video_metadata.duration_ms - expected_duration_ms)
                if delta_ms > duration_tolerance_ms:
                    raise ArtifactVaultError("recording video duration hint does not match MP4 metadata")
            sha256, byte_size = self._hash_file(temp_target)
            target = self._content_addressed_path(sha256=sha256, suffix=suffix)
            if not target.is_relative_to(vault_root):
                raise ArtifactVaultError("artifact target is outside the configured vault directory")
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not target.exists():
                os.replace(temp_target, target)
            else:
                temp_target.unlink(missing_ok=True)
            return PromotedArtifactFile(
                storage_uri=f"local-artifact://{target.relative_to(self.vault_dir.resolve())}",
                local_path=target,
                byte_size=byte_size,
                sha256=sha256,
                duration_ms=video_metadata.duration_ms,
            )
        except ArtifactVaultError:
            if temp_target.exists():
                temp_target.unlink(missing_ok=True)
            raise
        except Exception as exc:
            if temp_target.exists():
                temp_target.unlink(missing_ok=True)
            raise ArtifactVaultTransientError("failed to copy staged artifact") from exc

    def write_generated(
        self,
        *,
        artifact_id: str,
        created_at: datetime,
        content: bytes,
        suffix: str,
    ) -> PromotedArtifactFile:
        """Write daemon/provider generated artifact content into the vault.

        Args:
            artifact_id: Durable artifact id used as the file stem.
            created_at: Creation time used to shard artifact paths.
            content: Serialized artifact bytes to persist.
            suffix: File suffix, including the leading dot.

        Returns:
            Vault URI, local path, size, and content hash for the artifact.

        Raises:
            ArtifactVaultError: When suffix, size, target path, or write
                operation fails vault safety checks.
        """

        if not suffix.startswith("."):
            raise ArtifactVaultError("generated artifact suffix must start with a dot")
        if not content:
            raise ArtifactVaultError("generated artifact is empty")
        if len(content) > MAX_GENERATED_ARTIFACT_BYTES:
            raise ArtifactVaultError("generated artifact exceeds the maximum size")
        sha256 = hashlib.sha256(content).hexdigest()
        target = self._content_addressed_path(sha256=sha256, suffix=suffix)
        vault_root = self.vault_dir.expanduser().resolve()
        if not target.is_relative_to(vault_root):
            raise ArtifactVaultError("artifact target is outside the configured vault directory")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp_target = target.with_suffix(f"{target.suffix}.tmp")
        try:
            if not target.exists():
                temp_target.write_bytes(content)
                os.replace(temp_target, target)
            byte_size = len(content)
        except Exception as exc:
            temp_target.unlink(missing_ok=True)
            raise ArtifactVaultError("failed to write generated artifact") from exc
        return PromotedArtifactFile(
            storage_uri=f"local-artifact://{target.relative_to(self.vault_dir.resolve())}",
            local_path=target,
            byte_size=byte_size,
            sha256=sha256,
        )

    def read(self, storage_uri: str) -> bytes:
        """Read a local artifact URI from the daemon-owned vault.

        Args:
            storage_uri: ``local-artifact://`` URI stored on artifact metadata.

        Returns:
            Raw artifact bytes.

        Raises:
            ArtifactVaultError: When the URI scheme or resolved path is not
                supported by the local vault.
        """

        return self.resolve_local_path(storage_uri).read_bytes()

    def resolve_local_path(self, storage_uri: str) -> Path:
        """Resolve a local artifact URI to a vault-owned file path.

        The returned path is only intended for trusted local handoff paths that
        have already passed raw-access policy checks; public projections must
        not expose it.
        """

        prefix = "local-artifact://"
        if not storage_uri.startswith(prefix):
            raise ArtifactVaultError("unsupported artifact storage URI")
        relative = Path(storage_uri.removeprefix(prefix))
        target = (self.vault_dir / relative).resolve()
        vault_root = self.vault_dir.expanduser().resolve()
        if not target.is_relative_to(vault_root):
            raise ArtifactVaultError("artifact path is outside the configured vault directory")
        if not target.is_file():
            raise ArtifactVaultError("artifact file not found")
        return target

    def discard_staged_file(self, staged_path: Path) -> None:
        """Delete a validated staged file that should not be persisted.

        Args:
            staged_path: Screenshot path created by the native shell.
        """

        source = self.validate_staged_file(staged_path)
        source.unlink(missing_ok=True)

    def discard_staged_video_file(self, staged_path: Path, *, max_bytes: int) -> None:
        """Delete a validated staged video after the metadata graph commits."""

        source = self.validate_staged_video_file(staged_path, max_bytes=max_bytes)
        source.unlink(missing_ok=True)

    def discard_storage_uri(self, storage_uri: str) -> None:
        """Delete an unreferenced local-artifact URI during rollback cleanup."""

        prefix = "local-artifact://"
        if not storage_uri.startswith(prefix):
            raise ArtifactVaultError("unsupported artifact storage URI")
        relative = Path(storage_uri.removeprefix(prefix))
        target = (self.vault_dir / relative).resolve()
        vault_root = self.vault_dir.expanduser().resolve()
        if not target.is_relative_to(vault_root):
            raise ArtifactVaultError("artifact path is outside the configured vault directory")
        target.unlink(missing_ok=True)

    def write_sidecar(self, *, artifact_id: str, content: bytes) -> Path:
        """Write a per-artifact manifest sidecar into the local vault.

        Args:
            artifact_id: Artifact identifier used for the sidecar file name.
            content: Canonical JSON bytes.

        Returns:
            Absolute sidecar path.

        Raises:
            ArtifactVaultError: If the computed sidecar path escapes the vault root.
        """

        target_dir = (self.vault_dir / "manifests").resolve()
        vault_root = self.vault_dir.expanduser().resolve()
        if not target_dir.is_relative_to(vault_root):
            raise ArtifactVaultError("sidecar target is outside the configured vault directory")
        target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = target_dir / f"{artifact_id}.json"
        target.write_bytes(content)
        return target

    def validate_staged_file(self, staged_path: Path) -> Path:
        """Validate that a staged file exists under the staging directory.

        Args:
            staged_path: Candidate staged file path.

        Returns:
            Resolved file path.

        Raises:
            ArtifactVaultError: When the file cannot be trusted.
        """

        candidate = staged_path.expanduser()
        if candidate.is_symlink():
            raise ArtifactVaultError("staged artifact must be a regular file")
        source = candidate.resolve()
        staging_root = self.staging_dir.expanduser().resolve()
        if not source.is_relative_to(staging_root):
            raise ArtifactVaultError("staged artifact is outside the configured staging directory")
        if not source.is_file() or source.is_symlink():
            raise ArtifactVaultError("staged artifact does not exist")
        if source.suffix.lower() != ".png":
            raise ArtifactVaultError("staged screenshot must be a PNG file")
        byte_size = source.stat().st_size
        if byte_size <= 0:
            raise ArtifactVaultError("staged screenshot is empty")
        if byte_size > MAX_CAPTURE_ARTIFACT_BYTES:
            raise ArtifactVaultError("staged screenshot exceeds the maximum size")
        with source.open("rb") as artifact_file:
            if artifact_file.read(len(PNG_MAGIC)) != PNG_MAGIC:
                raise ArtifactVaultError("staged screenshot is not a PNG file")
        return source

    def validate_staged_video_file(self, staged_path: Path, *, max_bytes: int) -> Path:
        """Validate a staged MP4 recording without widening screenshot rules."""

        candidate = staged_path.expanduser()
        if candidate.is_symlink():
            raise ArtifactVaultError("staged video must be a regular file")
        source = candidate.resolve()
        staging_root = self.staging_dir.expanduser().resolve()
        if not source.is_relative_to(staging_root):
            raise ArtifactVaultError("staged video is outside the configured staging directory")
        if not source.is_file() or source.is_symlink():
            raise ArtifactVaultError("staged video does not exist")
        if source.suffix.lower() != ".mp4":
            raise ArtifactVaultError("staged video must be an MP4 file")
        byte_size = source.stat().st_size
        if byte_size <= 0:
            raise ArtifactVaultError("staged video is empty")
        if byte_size > max_bytes:
            raise ArtifactVaultError("staged video exceeds the maximum size")
        with source.open("rb") as artifact_file:
            artifact_file.seek(MP4_BRAND_OFFSET)
            if artifact_file.read(len(MP4_BRAND_MAGIC)) != MP4_BRAND_MAGIC:
                raise ArtifactVaultError("staged video is not an MP4 file")
        return source

    def inspect_mp4_video_metadata(self, source: Path) -> MP4VideoMetadata:
        """Parse server-trusted MP4 container metadata needed for timeline bounds."""

        file_size = source.stat().st_size
        with source.open("rb") as artifact_file:
            moov = self._find_box(artifact_file, start=0, end=file_size, box_type=b"moov")
            if moov is None:
                raise ArtifactVaultError("staged video is missing MP4 movie metadata")
            mvhd = self._find_box(artifact_file, start=moov[0], end=moov[1], box_type=b"mvhd")
            if mvhd is None:
                raise ArtifactVaultError("staged video is missing MP4 duration metadata")
            duration_ms = self._parse_mvhd_duration_ms(
                artifact_file,
                payload_start=mvhd[0],
                payload_end=mvhd[1],
            )
        return MP4VideoMetadata(duration_ms=duration_ms)

    def _hash_file(self, path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        byte_size = 0
        with path.open("rb") as artifact_file:
            while chunk := artifact_file.read(1024 * 1024):
                byte_size += len(chunk)
                digest.update(chunk)
        return digest.hexdigest(), byte_size

    def _content_addressed_path(self, *, sha256: str, suffix: str) -> Path:
        return (self.vault_dir / "blobs" / sha256[:2] / f"{sha256}{suffix}").resolve()

    def _find_box(
        self,
        artifact_file: BinaryIO,
        *,
        start: int,
        end: int,
        box_type: bytes,
    ) -> tuple[int, int] | None:
        position = start
        while position + MP4_BOX_HEADER_BYTES <= end:
            artifact_file.seek(position)
            header = artifact_file.read(MP4_BOX_HEADER_BYTES)
            if len(header) != MP4_BOX_HEADER_BYTES:
                return None
            box_size = int.from_bytes(header[:4], byteorder="big")
            current_box_type = header[4:8]
            header_size = MP4_BOX_HEADER_BYTES
            if box_size == 1:
                extended_size = artifact_file.read(8)
                if len(extended_size) != 8:
                    return None
                box_size = int.from_bytes(extended_size, byteorder="big")
                header_size = MP4_BOX_EXTENDED_SIZE_BYTES
            elif box_size == 0:
                box_size = end - position
            if box_size < header_size:
                raise ArtifactVaultError("staged video has invalid MP4 box sizing")
            box_end = position + box_size
            if box_end > end:
                raise ArtifactVaultError("staged video has invalid MP4 box bounds")
            if current_box_type == box_type:
                return position + header_size, box_end
            position = box_end
        return None

    def _parse_mvhd_duration_ms(
        self,
        artifact_file: BinaryIO,
        *,
        payload_start: int,
        payload_end: int,
    ) -> int:
        artifact_file.seek(payload_start)
        version_and_flags = artifact_file.read(MP4_VERSION_AND_FLAGS_BYTES)
        if len(version_and_flags) != MP4_VERSION_AND_FLAGS_BYTES:
            raise ArtifactVaultError("staged video has invalid MP4 duration metadata")
        version = version_and_flags[0]
        payload = artifact_file.read(payload_end - payload_start - MP4_VERSION_AND_FLAGS_BYTES)
        if version == 0:
            timescale_offset = MP4_MVHD_V0_TIMESCALE_OFFSET
            duration_offset = MP4_MVHD_V0_DURATION_OFFSET
            duration_size = 4
        elif version == 1:
            timescale_offset = MP4_MVHD_V1_TIMESCALE_OFFSET
            duration_offset = MP4_MVHD_V1_DURATION_OFFSET
            duration_size = 8
        else:
            raise ArtifactVaultError("staged video uses unsupported MP4 movie header version")
        if len(payload) < duration_offset + duration_size:
            raise ArtifactVaultError("staged video has truncated MP4 duration metadata")
        timescale = int.from_bytes(payload[timescale_offset : timescale_offset + 4], byteorder="big")
        duration = int.from_bytes(payload[duration_offset : duration_offset + duration_size], byteorder="big")
        if timescale <= 0 or duration <= 0:
            raise ArtifactVaultError("staged video has invalid MP4 duration metadata")
        return round(duration * 1000 / timescale)
