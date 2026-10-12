"""Import WorkRecorder share packages into the local event ledger."""

from __future__ import annotations

import hashlib
import json
import threading
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError

from packages.artifacts.vault import LocalArtifactVault
from packages.contracts import (
    ActorRef,
    ArtifactType,
    ContextShare,
    ContextShareStatus,
    ExternalShareTarget,
    IdentityProvider,
    ShareAuditAction,
    ShareAuditEvent,
    ShareImportRequest,
    ShareImportResponse,
    ShareImportSourceKind,
    ShareImportStatus,
    SharePublishStatus,
    ShareRevision,
    ShareScope,
    ShareSnapshot,
    ShareTargetKind,
    UserRef,
)
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from packages.storage.artifact_repository import ArtifactRepository
from packages.storage.event_repository import ContextEventRepository
from packages.storage.share_repository import ContextShareRepository

from .errors import ShareAccessError
from .import_materials import ShareImportMaterializer
from .importers import FeishuDriveShareImporter, ImportedSharePackage, ShareImportError, ShareSourceClassifier
from .tokens import token_hash

if TYPE_CHECKING:
    from packages.indexing.service import IndexingService


class ContextShareImportService:
    """Import external share packages without coupling UI or capture code."""

    def __init__(
        self,
        *,
        shares: ContextShareRepository,
        events: ContextEventRepository,
        artifacts: ArtifactRepository,
        vault: LocalArtifactVault,
        ids: IdFactory,
        clock: Clock,
        source_classifier: ShareSourceClassifier,
        feishu_importer: FeishuDriveShareImporter | None,
        indexing: "IndexingService | None" = None,
    ) -> None:
        self.shares = shares
        self.events = events
        self.artifacts = artifacts
        self.vault = vault
        self.ids = ids
        self.clock = clock
        self.source_classifier = source_classifier
        self.feishu_importer = feishu_importer
        self.indexing = indexing
        self.materials = ShareImportMaterializer(vault=vault, ids=ids, clock=clock)
        self._import_lock_guard = threading.Lock()
        self._import_locks: dict[str, threading.RLock] = {}

    def import_share(self, *, request: ShareImportRequest, actor: ActorRef) -> ShareImportResponse:
        """Import one local or Feishu WorkRecorder share reference.

        Args:
            request: User-provided share link or share id plus purpose metadata.
            actor: Authenticated local actor importing the context.

        Returns:
            A typed import result. Duplicate links return the existing event
            instead of creating a second card.
        """

        source_kind = self.source_classifier.classify(request.source)
        if source_kind == ShareImportSourceKind.LOCAL_REFERENCE:
            existing = self._local_reference(request.source)
            if existing is not None:
                return self._link_existing_share(
                    existing, actor=actor, source_kind=ShareImportSourceKind.LOCAL_REFERENCE
                )
        if source_kind == ShareImportSourceKind.FEISHU_DRIVE_URL:
            if self.feishu_importer is None:
                return ShareImportResponse(
                    imported_event_id=None,
                    share_id=None,
                    status=ShareImportStatus.PERMISSION_REQUIRED,
                    message="飞书导入尚未配置应用权限，无法读取这个链接。",
                    source_kind=source_kind,
                )
            try:
                package = self.feishu_importer.import_url(request.source)
            except ShareImportError as exc:
                return self._import_error_response(exc)
            return self._import_package(package=package, actor=actor, request=request)
        return ShareImportResponse(
            imported_event_id=None,
            share_id=None,
            status=ShareImportStatus.UNSUPPORTED_SOURCE,
            message="这个链接不是 WorkRecorder 分享链接，也不是可识别的飞书分享文件。",
            source_kind=source_kind,
        )

    def _local_reference(self, source: str) -> ContextShare | None:
        try:
            share = self._share_from_reference(source)
            self._assert_resolvable(share)
        except ShareAccessError:
            return None
        return share

    def _link_existing_share(
        self,
        share: ContextShare,
        *,
        actor: ActorRef,
        source_kind: ShareImportSourceKind,
    ) -> ShareImportResponse:
        latest = self.shares.latest_revision(share.share_id)
        self._audit(
            share=share,
            actor=UserRef.from_actor(actor),
            action=ShareAuditAction.SHARE_IMPORTED,
            success=True,
            details={"mode": "duplicate", "source_kind": source_kind.value},
        )
        return ShareImportResponse(
            imported_event_id=share.event_id,
            share_id=share.share_id,
            status=ShareImportStatus.LINKED_EXISTING_EVENT,
            message="本地已经有这条上下文，可以直接搜索和查看。",
            duplicate=True,
            revision=latest.revision if latest else None,
            source_kind=source_kind,
        )

    def _import_package(
        self,
        *,
        package: ImportedSharePackage,
        actor: ActorRef,
        request: ShareImportRequest,
    ) -> ShareImportResponse:
        lock = self._lock_for_package(package)
        lock.acquire()
        try:
            duplicate = self._duplicate_for_package(package)
            if duplicate is not None:
                share, reason = duplicate
                updated = self._update_existing_import_if_newer(
                    share=share,
                    duplicate_reason=reason,
                    package=package,
                    actor=actor,
                    request=request,
                )
                if updated is not None:
                    return updated
                return self._link_existing_share(share, actor=actor, source_kind=package.source_kind)
            share_id_collision = self.shares.get_share(package.share_id)
            if share_id_collision is not None:
                updated = self._update_existing_import_if_newer(
                    share=share_id_collision,
                    duplicate_reason="share_id",
                    package=package,
                    actor=actor,
                    request=request,
                )
                if updated is not None:
                    return updated
                if _same_import_identity(share_id_collision, package):
                    return self._link_existing_share(
                        share_id_collision,
                        actor=actor,
                        source_kind=package.source_kind,
                    )
                return ShareImportResponse(
                    imported_event_id=None,
                    share_id=None,
                    status=ShareImportStatus.INVALID_PACKAGE,
                    message="这个分享包和本地已有分享标识冲突，已停止导入。",
                    duplicate=False,
                    revision=package.revision,
                    source_kind=package.source_kind,
                )
            event = self.materials.event_from_package(package=package, actor=actor, request=request)
            saved_event = self.events.save(event)
            imported_artifacts = self.materials.artifacts_from_package(package=package, event_id=saved_event.event_id)
            for artifact in imported_artifacts:
                self.artifacts.save(artifact)
            if self.indexing is not None:
                self.indexing.index_imported_event(event=saved_event, artifacts=tuple(imported_artifacts))
            share = self._save_imported_share(
                package=package, event_id=saved_event.event_id, actor=actor, request=request
            )
            self._audit(
                share=share,
                actor=UserRef.from_actor(actor),
                action=ShareAuditAction.SHARE_IMPORTED,
                success=True,
                details={"mode": "imported_package", "source_kind": package.source_kind.value},
            )
            return ShareImportResponse(
                imported_event_id=saved_event.event_id,
                share_id=share.share_id,
                status=ShareImportStatus.IMPORTED,
                message="上下文已导入本地，可以搜索和查看。",
                duplicate=False,
                revision=package.revision,
                source_kind=package.source_kind,
            )
        finally:
            lock.release()

    def _duplicate_for_package(self, package: ImportedSharePackage) -> tuple[ContextShare, str] | None:
        if package.provider_url:
            by_url = self.shares.get_share_by_provider_url(_sanitize_external_url(package.provider_url))
            if by_url is not None:
                return by_url, "provider_url"
            by_hash = self.shares.get_share_by_package_hash(package.package_hash)
            if by_hash is not None:
                return by_hash, "package_hash"
        return None

    def _lock_for_package(self, package: ImportedSharePackage) -> threading.RLock:
        key = package.share_id or package.package_hash
        with self._import_lock_guard:
            lock = self._import_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._import_locks[key] = lock
            return lock

    def _update_existing_import_if_newer(
        self,
        *,
        share: ContextShare,
        duplicate_reason: str,
        package: ImportedSharePackage,
        actor: ActorRef,
        request: ShareImportRequest,
    ) -> ShareImportResponse | None:
        if duplicate_reason not in {"provider_url", "share_id"}:
            return None
        if duplicate_reason in {"provider_url", "share_id"} and not _same_import_identity(share, package):
            return ShareImportResponse(
                imported_event_id=None,
                share_id=None,
                status=ShareImportStatus.INVALID_PACKAGE,
                message="这个分享链接的来源身份发生变化，已停止导入。",
                duplicate=False,
                revision=package.revision,
                source_kind=package.source_kind,
            )
        if share.share_id != package.share_id:
            return ShareImportResponse(
                imported_event_id=None,
                share_id=None,
                status=ShareImportStatus.INVALID_PACKAGE,
                message="这个飞书链接的分享标识发生变化，已停止导入。",
                duplicate=False,
                revision=package.revision,
                source_kind=package.source_kind,
            )
        latest = self.shares.latest_revision(share.share_id)
        if latest is not None and package.revision <= latest.revision:
            return None
        existing_event = self.events.get(share.event_id)
        if existing_event is None:
            return ShareImportResponse(
                imported_event_id=None,
                share_id=None,
                status=ShareImportStatus.FAILED,
                message="本地已有分享记录，但对应保存记录不可用。",
                duplicate=False,
                revision=package.revision,
                source_kind=package.source_kind,
            )
        now = self.clock.now()
        replacement = self.materials.event_from_package(package=package, actor=actor, request=request).model_copy(
            update={"event_id": existing_event.event_id, "created_at": existing_event.created_at, "updated_at": now}
        )
        self.artifacts.delete_for_event_by_provider(
            event_id=existing_event.event_id, provider_key="context_share.import"
        )
        saved_event = self.events.save(replacement)
        imported_artifacts = self.materials.artifacts_from_package(package=package, event_id=saved_event.event_id)
        for artifact in imported_artifacts:
            self.artifacts.save(artifact)
        if self.indexing is not None:
            self.indexing.index_imported_event(event=saved_event, artifacts=tuple(imported_artifacts))
        updated_share = self._save_imported_share(
            package=package,
            event_id=saved_event.event_id,
            actor=actor,
            request=request,
            existing_share=share,
        )
        self._audit(
            share=updated_share,
            actor=UserRef.from_actor(actor),
            action=ShareAuditAction.SHARE_IMPORTED,
            success=True,
            details={
                "mode": "updated_imported_revision",
                "source_kind": package.source_kind.value,
                "previous_revision": latest.revision if latest else None,
            },
        )
        return ShareImportResponse(
            imported_event_id=saved_event.event_id,
            share_id=updated_share.share_id,
            status=ShareImportStatus.UPDATED_EXISTING_EVENT,
            message="分享内容已更新到本地，可以搜索和查看。",
            duplicate=False,
            revision=package.revision,
            source_kind=package.source_kind,
        )

    def _save_imported_share(
        self,
        *,
        package: ImportedSharePackage,
        event_id: str,
        actor: ActorRef,
        request: ShareImportRequest,
        existing_share: ContextShare | None = None,
    ) -> ContextShare:
        now = self.clock.now()
        creator_payload = _dict(package.safe_context.get("created_by"))
        user_payload = _dict(package.safe_context.get("user"))
        created_by = (
            existing_share.created_by
            if existing_share is not None
            else _user_ref(creator_payload)
            or UserRef(
                user_id="imported_unknown",
                display_name="分享者",
                identity_provider=IdentityProvider.IMPORTED,
            )
        )
        share_user = existing_share.user if existing_share is not None else _user_ref(user_payload) or created_by
        share = ContextShare(
            share_id=package.share_id,
            event_id=event_id,
            created_by=created_by,
            user=share_user,
            status=ContextShareStatus.LOCAL_READY,
            scope=ShareScope.AGENT_CONTEXT_WITH_SCREENSHOT,
            target=(
                ShareTargetKind.FEISHU_DRIVE
                if package.source_kind == ShareImportSourceKind.FEISHU_DRIVE_URL
                else ShareTargetKind.LOCAL_BUNDLE
            ),
            token_hash=token_hash(f"import:{package.share_id}:{package.package_hash}"),
            created_at=existing_share.created_at if existing_share is not None else now,
            updated_at=now,
            current_revision_id=None,
            metadata={
                "purpose": request.purpose,
                "imported_by": actor.actor_id,
                "source_kind": package.source_kind.value,
                "original_event_id": package.original_event_id,
                "provider_url": package.provider_url,
                "package_hash": package.package_hash,
            },
        )
        self.shares.save_share(share)
        payload_json = json.dumps(package.safe_context, ensure_ascii=False, sort_keys=True).encode("utf-8")
        screenshot_sha = hashlib.sha256(package.screenshot_png).hexdigest() if package.screenshot_png else None
        screenshot_artifact_id = next(
            (
                artifact.artifact_id
                for artifact in self.artifacts.list_for_event(event_id)
                if artifact.artifact_type == ArtifactType.SCREENSHOT
            ),
            None,
        )
        snapshot = ShareSnapshot(
            snapshot_id=self.ids.new("shr_snap"),
            share_id=share.share_id,
            event_id=event_id,
            revision=package.revision,
            payload_hash=hashlib.sha256(payload_json).hexdigest(),
            payload_json=package.safe_context,
            delivered_fields=tuple(sorted(package.safe_context.keys())),
            screenshot_artifact_id=screenshot_artifact_id,
            screenshot_sha256=screenshot_sha,
            created_at=now,
        )
        self.shares.save_snapshot(snapshot)
        manifest = self.materials.manifest_from_import(
            package=package, event_id=event_id, screenshot_sha=screenshot_sha
        )
        revision = ShareRevision(
            revision_id=self.ids.new("shr_rev"),
            share_id=share.share_id,
            event_id=event_id,
            revision=package.revision,
            snapshot_id=snapshot.snapshot_id,
            manifest=manifest,
            status=SharePublishStatus.PUBLISHED if package.provider_url else SharePublishStatus.FAILED,
            created_at=now,
            published_at=now if package.provider_url else None,
        )
        self.shares.save_revision(revision)
        if package.provider_url:
            self.shares.save_target(
                ExternalShareTarget(
                    target_id=self.ids.new("shr_tgt"),
                    share_id=share.share_id,
                    revision_id=revision.revision_id,
                    target=ShareTargetKind.FEISHU_DRIVE,
                    status=SharePublishStatus.PUBLISHED,
                    provider_file_token=None,
                    provider_url=_sanitize_external_url(package.provider_url),
                    created_at=now,
                    updated_at=now,
                )
            )
        return self.shares.mark_share_status(
            share=share,
            status=ContextShareStatus.LOCAL_READY,
            updated_at=now,
            current_revision_id=revision.revision_id,
        )

    def _import_error_response(self, error: ShareImportError) -> ShareImportResponse:
        status_by_code = {
            "config_missing": ShareImportStatus.PERMISSION_REQUIRED,
            "secret_missing": ShareImportStatus.PERMISSION_REQUIRED,
            "download_http_403": ShareImportStatus.PERMISSION_REQUIRED,
            "feishu_99991663": ShareImportStatus.PERMISSION_REQUIRED,
            "feishu_99991672": ShareImportStatus.PERMISSION_REQUIRED,
            "feishu_1061004": ShareImportStatus.PERMISSION_REQUIRED,
            "download_http_404": ShareImportStatus.FAILED,
            "download_too_large": ShareImportStatus.INVALID_PACKAGE,
            "safe_context_too_large": ShareImportStatus.INVALID_PACKAGE,
            "screenshot_too_large": ShareImportStatus.INVALID_PACKAGE,
            "invalid_size": ShareImportStatus.INVALID_PACKAGE,
            "signature_verification_unconfigured": ShareImportStatus.PERMISSION_REQUIRED,
            "signature_missing": ShareImportStatus.INVALID_PACKAGE,
            "signature_mismatch": ShareImportStatus.INVALID_PACKAGE,
        }
        status = status_by_code.get(error.code, ShareImportStatus.INVALID_PACKAGE)
        if error.code.startswith("download_http_5") or error.code in {
            "download_http",
            "download_http_429",
            "feishu_99991400",
        }:
            status = ShareImportStatus.FAILED
        return ShareImportResponse(
            imported_event_id=None,
            share_id=None,
            status=status,
            message=str(error),
            source_kind=error.source_kind,
        )

    def _share_from_reference(self, value: str) -> ContextShare:
        text = value.strip()
        if text.startswith("workrecorder://share/"):
            parsed = urlsplit(text)
            share_id = parsed.path.strip("/").split("/", 1)[0] if parsed.netloc == "share" else parsed.netloc
        elif text.startswith("http://") or text.startswith("https://"):
            share = self.shares.get_share_by_provider_url(_sanitize_external_url(text))
            if share is None:
                raise ShareAccessError("External share URL is not known locally.")
            return share
        else:
            share_id = text
        share = self.shares.get_share(share_id)
        if share is None:
            raise ShareAccessError("Share not found.")
        return share

    def _assert_resolvable(self, share: ContextShare) -> None:
        now = self.clock.now()
        if share.status == ContextShareStatus.REVOKED:
            raise ShareAccessError("Share has been revoked.")
        if share.expires_at is not None and share.expires_at <= now:
            raise ShareAccessError("Share has expired.")
        if share.status not in {ContextShareStatus.READY, ContextShareStatus.LOCAL_READY}:
            raise ShareAccessError("Share is not ready.")

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


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _user_ref(value: dict[str, object]) -> UserRef | None:
    if not value:
        return None
    try:
        return UserRef.model_validate(value)
    except ValidationError:
        user_id = _string(value.get("user_id"))
        if not user_id:
            return None
        return UserRef(user_id=user_id, display_name=_string(value.get("display_name")) or None)


def _same_import_identity(share: ContextShare, package: ImportedSharePackage) -> bool:
    metadata = _dict(share.metadata)
    return _string(metadata.get("original_event_id")) == package.original_event_id


def _safe_netloc(parts: object) -> str:
    host = getattr(parts, "hostname", None) or ""
    try:
        port = getattr(parts, "port", None)
    except ValueError:
        port = None
    return f"{host}:{port}" if port is not None else host
