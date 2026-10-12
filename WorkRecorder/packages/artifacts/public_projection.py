"""Public artifact projections for sensitive artifact categories."""

from __future__ import annotations

from packages.contracts import (
    Artifact,
    ArtifactIntegrityPublicSummary,
    ArtifactPublicSummary,
    ArtifactType,
)


class ArtifactPublicProjector:
    """Project artifact metadata without raw vault handles or sensitive hashes."""

    def project(self, artifact: Artifact) -> ArtifactPublicSummary:
        """Return a safe public artifact view.

        Raw storage, hashes, source URIs, provider session ids, and command ids
        are intentionally excluded from all public metadata routes. Raw content
        and integrity details stay behind their explicit audited endpoints.
        """

        return ArtifactPublicSummary(
            artifact_id=artifact.artifact_id,
            event_id=artifact.event_id,
            artifact_type=artifact.artifact_type,
            role=artifact.role,
            redaction_state=artifact.redaction_state,
            allowed_scopes=artifact.allowed_scopes,
            content_type=artifact.content_type,
            byte_size=artifact.byte_size,
            ingest_state=artifact.ingest_state,
            metadata={} if artifact.artifact_type == ArtifactType.RECORDING_VIDEO else dict(artifact.metadata),
            created_at=artifact.created_at,
            evidence_id=artifact.evidence_id,
            capture_run_id=artifact.capture_run_id,
            provider_key=artifact.provider_key,
            evidence_kind=artifact.evidence_kind,
        )

    def project_integrity(self, artifact: Artifact, result: dict[str, object]) -> dict[str, object]:
        """Hide hash values for recording-video verification responses."""

        if artifact.artifact_type != ArtifactType.RECORDING_VIDEO:
            return result
        byte_size = result.get("byte_size")
        return ArtifactIntegrityPublicSummary(
            artifact_id=artifact.artifact_id,
            byte_size=byte_size if isinstance(byte_size, int) and not isinstance(byte_size, bool) else 0,
            ok=bool(result.get("ok")),
        ).model_dump(mode="json")
