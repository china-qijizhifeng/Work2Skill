"""Context share contracts for Feishu and local import/export flows."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import ContractModel
from .common import JsonScalar, UserRef
from .enums import (
    ContextShareStatus,
    ShareAuditAction,
    ShareImportSourceKind,
    ShareImportStatus,
    SharePublishStatus,
    ShareScope,
    ShareTargetKind,
    ShareVisibility,
)
from .responses import SearchResultCard


class ContextShareCreateRequest(ContractModel):
    """Request to create a share from an existing local event."""

    event_id: str = Field(min_length=1)
    target: ShareTargetKind = ShareTargetKind.FEISHU_DRIVE
    scope: ShareScope = ShareScope.AGENT_CONTEXT_WITH_SCREENSHOT
    purpose: str = Field(default="context_share", min_length=1, max_length=160)
    expires_in_seconds: int | None = Field(default=604800, ge=60)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class ContextShare(ContractModel):
    """Durable share grant independent from event ids and Feishu URLs."""

    share_id: str
    event_id: str
    created_by: UserRef
    user: UserRef
    status: ContextShareStatus
    scope: ShareScope
    target: ShareTargetKind
    token_hash: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    current_revision_id: str | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class ShareSnapshot(ContractModel):
    """Frozen safe payload used to render and publish a share revision."""

    snapshot_id: str
    share_id: str
    event_id: str
    revision: int
    payload_hash: str
    payload_json: dict[str, object] = Field(default_factory=dict)
    delivered_fields: tuple[str, ...] = Field(default_factory=tuple)
    screenshot_artifact_id: str | None = None
    screenshot_sha256: str | None = None
    disclosure_policy_version: str = "disclosure_policy_v1"
    redaction_policy_version: str = "redaction_policy_v1"
    created_at: datetime


class SharePackageManifest(ContractModel):
    """Hashes and file names for a generated share package."""

    share_id: str
    event_id: str
    revision: int
    html_filename: str
    json_filename: str
    screenshot_filename: str | None = None
    manifest_filename: str
    html_sha256: str
    json_sha256: str
    manifest_sha256: str
    screenshot_sha256: str | None = None
    created_at: datetime


class ShareRevision(ContractModel):
    """One immutable published-or-publishable share revision."""

    revision_id: str
    share_id: str
    event_id: str
    revision: int
    snapshot_id: str
    manifest: SharePackageManifest
    status: SharePublishStatus
    created_at: datetime
    published_at: datetime | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class ExternalShareTarget(ContractModel):
    """Publication status for one external share target such as Feishu Drive."""

    target_id: str
    share_id: str
    revision_id: str
    target: ShareTargetKind
    status: SharePublishStatus
    provider_file_token: str | None = None
    provider_url: str | None = None
    visibility: ShareVisibility = ShareVisibility.TENANT_READABLE
    retry_count: int = 0
    last_error_code: str | None = None
    last_error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class ShareSyncJob(ContractModel):
    """Durable publication/retry job for a share revision."""

    job_id: str
    share_id: str
    revision_id: str
    target: ShareTargetKind
    status: SharePublishStatus
    retry_count: int = 0
    last_error_code: str | None = None
    last_error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class ShareResolveResponse(ContractModel):
    """Safe share preview returned to users and agents."""

    share: ContextShare
    revision: ShareRevision | None = None
    card: SearchResultCard
    safe_context: dict[str, object] = Field(default_factory=dict)
    available_fields: tuple[str, ...] = Field(default_factory=tuple)
    hidden_materials: tuple[str, ...] = Field(default_factory=tuple)
    screenshot_artifact_id: str | None = None
    external_url: str | None = None
    copyable_url: str | None = None


class ShareImportRequest(ContractModel):
    """Request to import a share URL or local package."""

    source: str = Field(min_length=1)
    purpose: str = Field(default="share_import", min_length=1, max_length=160)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class ShareImportResponse(ContractModel):
    """Result of importing a share into the local context library."""

    imported_event_id: str | None = None
    share_id: str | None = None
    status: ShareImportStatus
    message: str
    duplicate: bool = False
    revision: int | None = None
    source_kind: ShareImportSourceKind = ShareImportSourceKind.UNKNOWN


class FeishuShareConfig(ContractModel):
    """Runtime config needed to publish share packages to Feishu Drive."""

    app_id: str = Field(min_length=1)
    folder_token: str = Field(min_length=1)
    tenant_base_url: str = "https://open.feishu.cn"


class ShareAuditEvent(ContractModel):
    """Share-specific audit event with no raw payload or secrets."""

    share_audit_id: str
    share_id: str
    event_id: str | None = None
    actor: UserRef | None = None
    action: ShareAuditAction
    success: bool
    details: dict[str, JsonScalar] = Field(default_factory=dict)
    created_at: datetime
