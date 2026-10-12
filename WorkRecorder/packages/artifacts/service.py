"""Artifact access service with policy-aware P0 deny defaults."""

from __future__ import annotations

import hashlib
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from packages.artifacts.vault import ArtifactVaultError, LocalArtifactVault
from packages.contracts import AccessScope, ActorRef, Artifact, ErrorCode, EventStatus
from packages.contracts.api import ApiError
from packages.storage.artifact_repository import ArtifactRepository
from packages.storage.event_repository import ContextEventRepository


class ArtifactAccessService:
    """Resolve artifact metadata and enforce P0 raw-content boundaries."""

    def __init__(
        self,
        repository: ArtifactRepository,
        *,
        events: ContextEventRepository | None = None,
        vault: LocalArtifactVault | None = None,
    ) -> None:
        """Create an artifact access service.

        Args:
            repository: Artifact metadata repository.
            events: Optional event repository used to hide deleted/restricted
                parent events.
            vault: Optional vault used for text-like artifact reads.
        """

        self.repository = repository
        self.events = events
        self.vault = vault

    def get_metadata(self, artifact_id: str) -> Artifact | None:
        """Return artifact metadata without raw content.

        Args:
            artifact_id: Artifact identifier.

        Returns:
            Artifact metadata when found.
        """

        artifact = self.repository.get(artifact_id)
        if artifact is None or not self._parent_event_allows_artifact_reads(artifact):
            return None
        return artifact

    def read_content_stub(self, *, artifact: Artifact, actor: ActorRef, scope: AccessScope) -> ApiError:
        """Return the P0 error for raw or derived artifact content.

        Args:
            artifact: Artifact being requested.
            actor: Actor attempting access.
            scope: Requested access scope.

        Returns:
            Structured API error explaining either artifact-level denial or the
            P0 limitation.
        """

        if scope not in artifact.allowed_scopes:
            return ApiError(
                code=ErrorCode.POLICY_DENIED,
                message="Artifact scope is not available for this evidence.",
                details={"artifact_id": artifact.artifact_id, "actor_id": actor.actor_id, "scope": scope.value},
            )
        return ApiError(
            code=ErrorCode.NOT_IMPLEMENTED,
            message="Artifact content is not exposed by the P0 skeleton.",
            details={"artifact_id": artifact.artifact_id, "actor_id": actor.actor_id, "scope": scope.value},
        )

    def read_text_content(self, *, artifact: Artifact, actor: ActorRef, scope: AccessScope) -> str | ApiError:
        """Read redacted text-like artifact content when policy permits it.

        Args:
            artifact: Artifact metadata selected by the caller.
            actor: Actor attempting access, included in denial details.
            scope: Requested scope, usually ``read_text`` for Web evidence.

        Returns:
            UTF-8 artifact content, or a structured API error when policy,
            vault access, or content type blocks the read.
        """

        if scope not in artifact.allowed_scopes:
            return ApiError(
                code=ErrorCode.POLICY_DENIED,
                message="Artifact scope is not available for this evidence.",
                details={"artifact_id": artifact.artifact_id, "actor_id": actor.actor_id, "scope": scope.value},
            )
        if not self._parent_event_allows_artifact_reads(artifact):
            return ApiError(
                code=ErrorCode.NOT_FOUND,
                message="Artifact not found.",
                details={"artifact_id": artifact.artifact_id, "actor_id": actor.actor_id},
            )
        if self.vault is None or not (artifact.content_type or "").startswith(("text/", "application/json")):
            return self.read_content_stub(artifact=artifact, actor=actor, scope=scope)
        try:
            return self.vault.read(artifact.storage_uri).decode("utf-8")
        except (ArtifactVaultError, UnicodeDecodeError) as exc:
            return ApiError(
                code=ErrorCode.INTERNAL_ERROR,
                message="Failed to read artifact content.",
                details={"artifact_id": artifact.artifact_id, "actor_id": actor.actor_id, "error": str(exc)},
            )

    def read_thumbnail_content(self, *, artifact: Artifact, actor: ActorRef) -> bytes | ApiError:
        """Read a thumbnail-safe visual artifact payload.

        The thumbnail route intentionally returns a resized PNG derivative
        instead of the original screenshot bytes. Raw screenshot reads remain
        gated by the stricter raw artifact route.

        Args:
            artifact: Artifact metadata selected by the caller.
            actor: Actor attempting access, included in denial details.

        Returns:
            Image bytes, or a structured API error when policy or vault access
            blocks the read.
        """

        if AccessScope.READ_THUMBNAIL not in artifact.allowed_scopes:
            return ApiError(
                code=ErrorCode.POLICY_DENIED,
                message="Thumbnail scope is not available for this evidence.",
                details={
                    "artifact_id": artifact.artifact_id,
                    "actor_id": actor.actor_id,
                    "scope": AccessScope.READ_THUMBNAIL.value,
                },
            )
        if not self._parent_event_allows_artifact_reads(artifact):
            return ApiError(
                code=ErrorCode.NOT_FOUND,
                message="Artifact not found.",
                details={"artifact_id": artifact.artifact_id, "actor_id": actor.actor_id},
            )
        content_type = artifact.content_type or str(artifact.metadata.get("content_type") or "")
        if self.vault is None or not content_type.startswith("image/"):
            return self.read_content_stub(artifact=artifact, actor=actor, scope=AccessScope.READ_THUMBNAIL)
        try:
            original = self.vault.read(artifact.storage_uri)
            return self._render_png_thumbnail(original)
        except (ArtifactVaultError, UnidentifiedImageError, OSError) as exc:
            return ApiError(
                code=ErrorCode.INTERNAL_ERROR,
                message="Failed to read artifact thumbnail.",
                details={"artifact_id": artifact.artifact_id, "actor_id": actor.actor_id, "error": str(exc)},
            )

    def _render_png_thumbnail(self, content: bytes, *, max_edge: int = 360) -> bytes:
        with Image.open(BytesIO(content)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((max_edge, max_edge))
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA")
            output = BytesIO()
            image.save(output, format="PNG", optimize=True)
            return output.getvalue()

    def verify_integrity(self, artifact: Artifact) -> dict[str, object] | ApiError:
        """Recompute artifact hash without returning raw bytes.

        Args:
            artifact: Artifact metadata row whose vault blob should be verified.

        Returns:
            Integrity summary dictionary, or an API error when the blob cannot be checked.
        """

        if self.vault is None:
            return ApiError(
                code=ErrorCode.NOT_IMPLEMENTED,
                message="Artifact verification is unavailable without a vault.",
                details={"artifact_id": artifact.artifact_id},
            )
        try:
            content = self.vault.read(artifact.storage_uri)
        except ArtifactVaultError as exc:
            return ApiError(
                code=ErrorCode.NOT_FOUND,
                message="Artifact file not found.",
                details={"artifact_id": artifact.artifact_id, "error": str(exc)},
            )
        actual = hashlib.sha256(content).hexdigest()
        expected = artifact.sha256 or ""
        return {
            "artifact_id": artifact.artifact_id,
            "storage_uri": artifact.storage_uri,
            "expected_sha256": expected,
            "actual_sha256": actual,
            "byte_size": len(content),
            "ok": bool(expected) and actual == expected,
        }

    def _parent_event_allows_artifact_reads(self, artifact: Artifact) -> bool:
        if self.events is None:
            return True
        event = self.events.get(artifact.event_id)
        return event is not None and event.status not in {EventStatus.DELETED, EventStatus.RESTRICTED}
