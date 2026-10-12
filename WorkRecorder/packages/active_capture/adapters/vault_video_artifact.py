"""Vault-backed adapter for active capture video artifacts."""

from __future__ import annotations

import logging
from pathlib import Path

from packages.active_capture.ports.video_artifact import PreparedVideoArtifact
from packages.artifacts.vault import ArtifactVaultError, LocalArtifactVault
from packages.contracts import (
    AccessScope,
    ActiveCapturePolicyConfig,
    ActiveCaptureSession,
    Artifact,
    ArtifactIngestState,
    ArtifactRole,
    ArtifactType,
    RecordingVideoContentType,
    RecordingVideoMetadataKey,
    RecordingVideoSegmentRef,
    RedactionState,
    StagedVideoArtifactRef,
    VideoArtifactFailureReason,
    VideoArtifactRef,
    VideoArtifactState,
)
from packages.contracts.common import JsonScalar
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from packages.storage.artifact_repository import ArtifactRepository

logger = logging.getLogger(__name__)

RESERVED_VIDEO_METADATA_KEYS = frozenset(item.value for item in RecordingVideoMetadataKey)


class VaultVideoArtifactAdapter:
    """Promote a staged recording video through the daemon-owned vault."""

    def __init__(
        self,
        *,
        vault: LocalArtifactVault,
        artifacts: ArtifactRepository,
        ids: IdFactory,
        clock: Clock,
        config: ActiveCapturePolicyConfig,
    ) -> None:
        self.vault = vault
        self.artifacts = artifacts
        self.ids = ids
        self.clock = clock
        self.config = config

    def prepare_staged_video(
        self,
        *,
        session: ActiveCaptureSession,
        staged: StagedVideoArtifactRef,
    ) -> PreparedVideoArtifact:
        """Validate and prepare a staged MP4 artifact for atomic graph commit."""

        return self._prepare_staged_video(session=session, staged=staged, segment=None)

    def prepare_staged_segment_video(
        self,
        *,
        session: ActiveCaptureSession,
        segment: RecordingVideoSegmentRef,
        staged: StagedVideoArtifactRef,
    ) -> PreparedVideoArtifact:
        """Validate and prepare one pause/resume recording segment video."""

        return self._prepare_staged_video(session=session, staged=staged, segment=segment)

    def discard_staged_video(self, staged: StagedVideoArtifactRef) -> None:
        self.vault.discard_staged_video_file(Path(staged.local_path), max_bytes=self.config.video_max_bytes)

    def discard_prepared_video(self, prepared: PreparedVideoArtifact) -> None:
        """Best-effort cleanup for a prepared file whose DB graph failed."""

        if prepared.artifact is None:
            return
        if self.artifacts.count_by_storage_uri(prepared.artifact.storage_uri) > 0:
            return
        try:
            self.vault.discard_storage_uri(prepared.artifact.storage_uri)
        except ArtifactVaultError:
            logger.warning(
                "active capture prepared video cleanup failed",
                extra={"artifact_id": prepared.artifact.artifact_id},
                exc_info=True,
            )

    def _prepare_staged_video(
        self,
        *,
        session: ActiveCaptureSession,
        staged: StagedVideoArtifactRef,
        segment: RecordingVideoSegmentRef | None,
    ) -> PreparedVideoArtifact:
        if not self.config.video_enabled:
            return PreparedVideoArtifact(
                ref=VideoArtifactRef(
                    state=VideoArtifactState.NOT_RECORDED,
                    failure_reason=VideoArtifactFailureReason.VIDEO_DISABLED,
                )
            )
        if session.primary_event_id is None:
            raise ArtifactVaultError("video artifact requires a primary event-bound keyframe")
        existing = self._existing_video_ref(session, segment=segment)
        if existing is not None:
            logger.info(
                "active capture video artifact reused",
                extra={
                    "session_id": session.session_id,
                    "segment_id": segment.segment_id if segment is not None else None,
                    "artifact_id": existing.artifact_id,
                },
            )
            return PreparedVideoArtifact(ref=existing)
        if staged.content_type != RecordingVideoContentType.MP4:
            raise ArtifactVaultError(f"recording video must be {RecordingVideoContentType.MP4.value}")
        artifact_id = self.ids.new("art")
        now = self.clock.now()
        promoted = self.vault.copy_video(
            staged_path=Path(staged.local_path),
            artifact_id=artifact_id,
            created_at=now,
            max_bytes=self.config.video_max_bytes,
            expected_duration_ms=staged.duration_ms,
            duration_tolerance_ms=self.config.timeline_alignment_tolerance_ms,
        )
        if promoted.duration_ms is None:
            raise ArtifactVaultError("recording video duration could not be verified")
        producer_metadata = self._safe_producer_metadata(staged.metadata)
        video_metadata = self._video_metadata(
            session=session,
            segment=segment,
            duration_ms=promoted.duration_ms,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            event_id=session.primary_event_id,
            artifact_type=ArtifactType.RECORDING_VIDEO,
            role=ArtifactRole.RECORDING_VIDEO,
            storage_uri=promoted.storage_uri,
            redaction_state=RedactionState.QUARANTINED,
            allowed_scopes=(AccessScope.READ_METADATA,),
            content_type=staged.content_type.value,
            byte_size=promoted.byte_size,
            sha256=promoted.sha256,
            ingest_state=ArtifactIngestState.QUARANTINED,
            metadata={
                **producer_metadata,
                **video_metadata,
            },
            created_at=now,
        )
        logger.info(
            "active capture video artifact prepared",
            extra={
                "session_id": session.session_id,
                "segment_id": segment.segment_id if segment is not None else None,
                "artifact_id": artifact_id,
                "byte_size": promoted.byte_size,
            },
        )
        return PreparedVideoArtifact(
            ref=VideoArtifactRef(
                artifact_id=artifact_id,
                state=VideoArtifactState.AVAILABLE,
                content_type=staged.content_type,
                byte_size=promoted.byte_size,
                sha256=promoted.sha256,
                duration_ms=promoted.duration_ms,
                created_at=now,
                metadata=video_metadata,
            ),
            artifact=artifact,
        )

    def _existing_video_ref(
        self,
        session: ActiveCaptureSession,
        *,
        segment: RecordingVideoSegmentRef | None,
    ) -> VideoArtifactRef | None:
        if session.primary_event_id is None:
            return None
        for artifact in self.artifacts.list_for_event(session.primary_event_id):
            if artifact.artifact_type != ArtifactType.RECORDING_VIDEO:
                continue
            if artifact.metadata.get(RecordingVideoMetadataKey.SESSION_ID.value) != session.session_id:
                continue
            artifact_segment_id = artifact.metadata.get(RecordingVideoMetadataKey.SEGMENT_ID.value)
            if segment is None and artifact_segment_id is not None:
                continue
            if segment is not None and artifact_segment_id != segment.segment_id:
                continue
            if artifact.content_type is None:
                continue
            duration_value = artifact.metadata.get(RecordingVideoMetadataKey.DURATION_MS.value)
            duration_ms = (
                duration_value if isinstance(duration_value, int) and not isinstance(duration_value, bool) else None
            )
            return VideoArtifactRef(
                artifact_id=artifact.artifact_id,
                state=VideoArtifactState.AVAILABLE,
                content_type=RecordingVideoContentType(artifact.content_type),
                byte_size=artifact.byte_size,
                sha256=artifact.sha256,
                duration_ms=duration_ms,
                created_at=artifact.created_at,
                metadata=self._video_metadata(session=session, segment=segment, duration_ms=duration_ms),
            )
        return None

    def _video_metadata(
        self,
        *,
        session: ActiveCaptureSession,
        segment: RecordingVideoSegmentRef | None,
        duration_ms: int | None,
    ) -> dict[str, JsonScalar]:
        metadata: dict[str, JsonScalar] = {RecordingVideoMetadataKey.SESSION_ID.value: session.session_id}
        if duration_ms is not None:
            metadata[RecordingVideoMetadataKey.DURATION_MS.value] = duration_ms
        if segment is not None:
            metadata[RecordingVideoMetadataKey.SEGMENT_ID.value] = segment.segment_id
            metadata[RecordingVideoMetadataKey.SEGMENT_SEQUENCE_INDEX.value] = segment.sequence_index
        return metadata

    def _safe_producer_metadata(self, metadata: dict[str, JsonScalar]) -> dict[str, JsonScalar]:
        reserved = RESERVED_VIDEO_METADATA_KEYS.intersection(metadata)
        if reserved:
            keys = ", ".join(sorted(reserved))
            raise ArtifactVaultError(f"recording video metadata uses reserved keys: {keys}")
        if metadata:
            logger.info("active capture video producer metadata dropped", extra={"metadata_key_count": len(metadata)})
        return {}
