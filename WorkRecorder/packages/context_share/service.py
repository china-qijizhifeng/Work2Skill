"""Context share orchestration independent from capture and UI layers."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlsplit, urlunsplit

from packages.artifacts.vault import LocalArtifactVault
from packages.contracts import (
    ActorRef,
    ContextShare,
    ContextShareCreateRequest,
    ContextShareStatus,
    ErrorCode,
    EventStatus,
    ExternalShareTarget,
    ShareAuditAction,
    ShareAuditEvent,
    ShareImportRequest,
    ShareImportResponse,
    SharePublishStatus,
    ShareResolveResponse,
    ShareRevision,
    ShareScope,
    ShareSnapshot,
    ShareSyncJob,
    UserFilter,
    UserRef,
)
from packages.integrations.feishu import FeishuDriveClient
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from packages.storage.artifact_repository import ArtifactRepository
from packages.storage.event_repository import ContextEventRepository
from packages.storage.share_repository import ContextShareRepository

from .errors import ShareAccessError
from .import_service import ContextShareImportService
from .importers import FeishuDriveShareImporter, SharePackageParser, ShareSourceClassifier
from .package import SharePackage, SharePackageBuilder
from .ports import SharePublisherRegistry
from .snapshot import ShareSnapshotComposer
from .tokens import new_share_token, token_hash

if TYPE_CHECKING:
    from packages.disclosure import DisclosurePolicyService
    from packages.indexing.service import IndexingService


class ContextShareService:
    """Create, publish, resolve, revoke, and import context shares."""

    def __init__(
        self,
        *,
        shares: ContextShareRepository,
        events: ContextEventRepository,
        artifacts: ArtifactRepository,
        disclosure: "DisclosurePolicyService",
        vault: LocalArtifactVault,
        ids: IdFactory,
        clock: Clock,
        package_builder: SharePackageBuilder,
        package_parser: SharePackageParser | None = None,
        publishers: SharePublisherRegistry | None = None,
        feishu_drive: FeishuDriveClient | None = None,
        indexing: "IndexingService | None" = None,
    ) -> None:
        self.shares = shares
        self.events = events
        self.artifacts = artifacts
        self.vault = vault
        self.ids = ids
        self.clock = clock
        self.publishers = publishers or SharePublisherRegistry()
        self.indexing = indexing
        self.source_classifier = ShareSourceClassifier()
        self.package_parser = package_parser or SharePackageParser()
        self.feishu_importer = (
            FeishuDriveShareImporter(drive=feishu_drive, parser=self.package_parser)
            if feishu_drive is not None
            else None
        )
        self.imports = ContextShareImportService(
            shares=shares,
            events=events,
            artifacts=artifacts,
            vault=vault,
            ids=ids,
            clock=clock,
            source_classifier=self.source_classifier,
            feishu_importer=self.feishu_importer,
            indexing=indexing,
        )
        self.snapshot_composer = ShareSnapshotComposer(
            disclosure=disclosure,
            artifacts=artifacts,
            vault=vault,
            ids=ids,
            clock=clock,
            package_builder=package_builder,
        )

    def create(self, *, request: ContextShareCreateRequest, actor: ActorRef) -> ShareResolveResponse:
        """Create a frozen share snapshot and try to publish it immediately.

        Args:
            request: Share creation request from CLI, app, or daemon API.
            actor: Authenticated actor creating the share.

        Returns:
            Safe resolve response for the newly created share.

        Raises:
            ShareAccessError: If the event cannot be shared or scope is unsupported.
        """

        event = self.events.get(request.event_id)
        if event is None or event.status in {EventStatus.DELETED, EventStatus.RESTRICTED}:
            raise ShareAccessError("Event cannot be shared.", code=ErrorCode.NOT_FOUND)
        if request.scope != ShareScope.AGENT_CONTEXT_WITH_SCREENSHOT:
            raise ShareAccessError("Unsupported share scope.")
        now = self.clock.now()
        share_id = self.ids.new("shr")
        token = new_share_token()
        user = event.user or UserRef.from_actor(event.trigger.actor)
        share = ContextShare(
            share_id=share_id,
            event_id=event.event_id,
            created_by=UserRef.from_actor(actor),
            user=user,
            status=ContextShareStatus.PENDING,
            scope=request.scope,
            target=request.target,
            token_hash=token_hash(token),
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(seconds=request.expires_in_seconds) if request.expires_in_seconds else None,
            metadata={"purpose": request.purpose, **request.metadata},
        )
        self.shares.save_share(share)
        snapshot, package = self._build_snapshot_and_package(share=share, actor=actor, revision_number=1)
        revision = self._save_revision(
            share=share, snapshot=snapshot, package=package, status=SharePublishStatus.PENDING
        )
        target = self._publish(share=share, revision=revision, package=package)
        published = target is not None and target.status == SharePublishStatus.PUBLISHED
        revision = revision.model_copy(
            update={
                "status": target.status if target is not None else SharePublishStatus.FAILED,
                "published_at": self.clock.now() if target and target.status == SharePublishStatus.PUBLISHED else None,
            }
        )
        self.shares.save_revision(revision)
        share = self.shares.mark_share_status(
            share=share,
            status=ContextShareStatus.READY if published else ContextShareStatus.LOCAL_READY,
            updated_at=self.clock.now(),
            current_revision_id=revision.revision_id,
        )
        self._audit(
            share=share,
            actor=UserRef.from_actor(actor),
            action=ShareAuditAction.SHARE_CREATED,
            success=True,
            details={"target": request.target.value, "published": published},
        )
        return self._resolve_share(share=share, actor=actor)

    def resolve(self, *, link_or_share_id: str, actor: ActorRef) -> ShareResolveResponse:
        """Resolve a local share id or WorkRecorder share link.

        Args:
            link_or_share_id: Local share id, workrecorder URL, or known provider URL.
            actor: Actor resolving the link for audit.

        Returns:
            Safe share card, available fields, and copyable URL.

        Raises:
            ShareAccessError: If the share is missing, expired, or revoked.
        """

        share = self._share_from_reference(link_or_share_id)
        self._assert_resolvable(share)
        self._audit(
            share=share,
            actor=UserRef.from_actor(actor),
            action=ShareAuditAction.SHARE_RESOLVED,
            success=True,
            details={"by": "share_id"},
        )
        return self._resolve_share(share=share, actor=actor)

    def list(self, *, user: UserFilter | None = None, limit: int = 50) -> tuple[ContextShare, ...]:
        """List recent share records.

        Args:
            user: Optional typed owner/importer filter.
            limit: Maximum number of rows to return.

        Returns:
            Recent share ledger rows ordered by creation time.
        """

        return self.shares.list_shares(user=user, limit=limit)

    def revoke(self, *, share_id: str, actor: ActorRef) -> ContextShare:
        """Mark a share as revoked and close any published external link.

        Args:
            share_id: Share record to revoke.
            actor: Actor requesting the revoke operation.

        Returns:
            Updated revoked share record.

        Raises:
            ShareAccessError: If the share is missing or external revoke fails.
        """

        share = self.shares.get_share(share_id)
        if share is None:
            raise ShareAccessError("Share not found.", code=ErrorCode.NOT_FOUND)
        target = self.shares.latest_target(share.share_id)
        if target is not None and target.status == SharePublishStatus.PUBLISHED:
            publisher = self.publishers.get(target.target)
            if publisher is not None:
                revoked_target = publisher.revoke(target=target)
                self.shares.save_target(revoked_target)
                if revoked_target.status != SharePublishStatus.REVOKED:
                    self._audit(
                        share=share,
                        actor=UserRef.from_actor(actor),
                        action=ShareAuditAction.SHARE_REVOKED,
                        success=False,
                        details={"target": target.target.value, "reason": revoked_target.last_error_code},
                    )
                    raise ShareAccessError("External share revoke failed.", code=ErrorCode.INTERNAL_ERROR)
        revoked = self.shares.mark_share_status(
            share=share,
            status=ContextShareStatus.REVOKED,
            updated_at=self.clock.now(),
            revoked_at=self.clock.now(),
        )
        self._audit(
            share=revoked,
            actor=UserRef.from_actor(actor),
            action=ShareAuditAction.SHARE_REVOKED,
            success=True,
            details={},
        )
        return revoked

    def sync(self, *, share_id: str, actor: ActorRef) -> ShareResolveResponse:
        """Create and publish a new revision for an existing share.

        Args:
            share_id: Existing share whose safe snapshot should be refreshed.
            actor: Actor requesting the sync operation.

        Returns:
            Resolve response for the latest share revision.

        Raises:
            ShareAccessError: If the share cannot be found or resolved.
        """

        share = self.shares.get_share(share_id)
        if share is None:
            raise ShareAccessError("Share not found.", code=ErrorCode.NOT_FOUND)
        self._assert_resolvable(share, allow_pending=True)
        latest = self.shares.latest_revision(share.share_id)
        next_revision = (latest.revision if latest else 0) + 1
        snapshot, package = self._build_snapshot_and_package(
            share=share,
            actor=actor,
            revision_number=next_revision,
        )
        revision = self._save_revision(
            share=share, snapshot=snapshot, package=package, status=SharePublishStatus.PENDING
        )
        target = self._publish(share=share, revision=revision, package=package)
        published = target is not None and target.status == SharePublishStatus.PUBLISHED
        revision = revision.model_copy(
            update={
                "status": target.status if target is not None else SharePublishStatus.FAILED,
                "published_at": self.clock.now() if target and target.status == SharePublishStatus.PUBLISHED else None,
            }
        )
        self.shares.save_revision(revision)
        share = self.shares.mark_share_status(
            share=share,
            status=ContextShareStatus.READY if published else ContextShareStatus.LOCAL_READY,
            updated_at=self.clock.now(),
            current_revision_id=revision.revision_id,
        )
        self._audit(
            share=share,
            actor=UserRef.from_actor(actor),
            action=ShareAuditAction.SHARE_SYNC_COMPLETED if published else ShareAuditAction.SHARE_SYNC_FAILED,
            success=published,
            details={"revision": next_revision, "published": published},
        )
        return self._resolve_share(share=share, actor=actor)

    def import_share(self, *, request: ShareImportRequest, actor: ActorRef) -> ShareImportResponse:
        """Import or link a WorkRecorder share reference.

        Args:
            request: Import source and optional import metadata.
            actor: Actor linking the shared context into the local ledger.

        Returns:
            Import result produced by the dedicated import service.
        """

        self.imports.feishu_importer = self.feishu_importer
        return self.imports.import_share(request=request, actor=actor)

    def jobs(self, *, share_id: str) -> tuple[ShareSyncJob, ...]:
        """Return publish/retry jobs for one share.

        Args:
            share_id: Share whose sync jobs should be listed.

        Returns:
            Durable job rows ordered with newest first.
        """

        return self.shares.list_jobs(share_id)

    def _build_snapshot_and_package(
        self,
        *,
        share: ContextShare,
        actor: ActorRef,
        revision_number: int,
    ) -> tuple[ShareSnapshot, SharePackage]:
        event = self.events.get(share.event_id)
        if event is None:
            raise ShareAccessError("Event cannot be shared.", code=ErrorCode.NOT_FOUND)
        snapshot, package = self.snapshot_composer.build(
            share=share,
            event=event,
            actor=actor,
            revision_number=revision_number,
        )
        self.shares.save_snapshot(snapshot)
        return snapshot, package

    def _save_revision(
        self,
        *,
        share: ContextShare,
        snapshot: ShareSnapshot,
        package: SharePackage,
        status: SharePublishStatus,
    ) -> ShareRevision:
        revision = ShareRevision(
            revision_id=self.ids.new("shr_rev"),
            share_id=share.share_id,
            event_id=share.event_id,
            revision=snapshot.revision,
            snapshot_id=snapshot.snapshot_id,
            manifest=package.manifest,
            status=status,
            created_at=self.clock.now(),
        )
        self.shares.save_revision(revision)
        return revision

    def _publish(
        self,
        *,
        share: ContextShare,
        revision: ShareRevision,
        package: SharePackage,
    ) -> ExternalShareTarget | None:
        job = ShareSyncJob(
            job_id=self.ids.new("shr_job"),
            share_id=share.share_id,
            revision_id=revision.revision_id,
            target=share.target,
            status=SharePublishStatus.UPLOADING,
            created_at=self.clock.now(),
            updated_at=self.clock.now(),
        )
        self.shares.save_job(job)
        publisher = self.publishers.get(share.target)
        if publisher is None:
            failed = job.model_copy(
                update={
                    "status": SharePublishStatus.FAILED,
                    "updated_at": self.clock.now(),
                    "last_error_code": "target_unsupported",
                    "last_error_message": "No publisher is configured for this share target.",
                }
            )
            self.shares.save_job(failed)
            return None
        target = publisher.publish(share_id=share.share_id, revision=revision, html=package.html)
        self.shares.save_target(target)
        self.shares.save_job(
            job.model_copy(
                update={
                    "status": target.status,
                    "retry_count": target.retry_count,
                    "last_error_code": target.last_error_code,
                    "last_error_message": target.last_error_message,
                    "updated_at": self.clock.now(),
                }
            )
        )
        return target

    def _resolve_share(self, *, share: ContextShare, actor: ActorRef) -> ShareResolveResponse:
        del actor
        snapshot = self.shares.latest_snapshot(share.share_id)
        revision = self.shares.latest_revision(share.share_id)
        target = self.shares.latest_target(share.share_id)
        if snapshot is None:
            raise ShareAccessError("Share snapshot not found.", code=ErrorCode.NOT_FOUND)
        payload = snapshot.payload_json
        card_payload = payload.get("summary_card")
        if not isinstance(card_payload, dict):
            raise ShareAccessError("Share snapshot is malformed.", code=ErrorCode.INTERNAL_ERROR)
        from packages.contracts import SearchResultCard

        card = SearchResultCard.model_validate(card_payload)
        available_raw = payload.get("available_fields")
        hidden_raw = payload.get("hidden_materials")
        available = available_raw if isinstance(available_raw, list) else []
        hidden = hidden_raw if isinstance(hidden_raw, list) else []
        return ShareResolveResponse(
            share=share,
            revision=revision,
            card=card,
            safe_context=payload,
            available_fields=tuple(str(item) for item in available),
            hidden_materials=tuple(str(item) for item in hidden),
            screenshot_artifact_id=snapshot.screenshot_artifact_id,
            external_url=(
                target.provider_url if target is not None and target.status == SharePublishStatus.PUBLISHED else None
            ),
            copyable_url=(
                target.provider_url
                if target is not None and target.status == SharePublishStatus.PUBLISHED and target.provider_url
                else None
            ),
        )

    def _share_from_reference(self, value: str) -> ContextShare:
        text = value.strip()
        if text.startswith("workrecorder://share/"):
            parsed = urlparse(text)
            share_id = parsed.path.strip("/").split("/", 1)[0] if parsed.netloc == "share" else parsed.netloc
        elif text.startswith("http://") or text.startswith("https://"):
            share = self.shares.get_share_by_provider_url(_sanitize_external_url(text))
            if share is None:
                raise ShareAccessError(
                    "External share URL import requires OAuth resolve.", code=ErrorCode.NOT_IMPLEMENTED
                )
            return share
        else:
            share_id = text
        share = self.shares.get_share(share_id)
        if share is None:
            raise ShareAccessError("Share not found.", code=ErrorCode.NOT_FOUND)
        return share

    def _assert_resolvable(self, share: ContextShare, *, allow_pending: bool = False) -> None:
        now = self.clock.now()
        if share.status == ContextShareStatus.REVOKED:
            raise ShareAccessError("Share has been revoked.", code=ErrorCode.NOT_FOUND)
        if share.expires_at is not None and share.expires_at <= now:
            raise ShareAccessError("Share has expired.", code=ErrorCode.NOT_FOUND)
        allowed = {ContextShareStatus.READY, ContextShareStatus.LOCAL_READY}
        if allow_pending:
            allowed.add(ContextShareStatus.PENDING)
            allowed.add(ContextShareStatus.FAILED)
        if share.status not in allowed:
            raise ShareAccessError("Share is not ready.", code=ErrorCode.NOT_FOUND)

    def _audit(
        self,
        *,
        share: ContextShare,
        actor: UserRef,
        action: ShareAuditAction,
        success: bool,
        details: dict[str, object],
    ) -> None:
        safe_details = {
            key: value for key, value in details.items() if isinstance(value, (str, int, float, bool)) or value is None
        }
        self.shares.record_audit(
            ShareAuditEvent(
                share_audit_id=self.ids.new("shr_aud"),
                share_id=share.share_id,
                event_id=share.event_id,
                actor=actor,
                action=action,
                success=success,
                details=safe_details,
                created_at=self.clock.now(),
            )
        )


def _sanitize_external_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if not parts.scheme:
        return value.strip()
    return urlunsplit((parts.scheme, _safe_netloc(parts), parts.path, "", ""))


def _safe_netloc(parts: object) -> str:
    host = getattr(parts, "hostname", None) or ""
    try:
        port = getattr(parts, "port", None)
    except ValueError:
        port = None
    return f"{host}:{port}" if port is not None else host
