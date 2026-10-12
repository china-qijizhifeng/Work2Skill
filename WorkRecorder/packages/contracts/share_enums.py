"""Context-share and identity enums used by share/import contracts."""

from __future__ import annotations

from enum import StrEnum


class IdentityProvider(StrEnum):
    """Identity provider that established a user reference."""

    LOCAL = "local"
    FEISHU = "feishu"
    IMPORTED = "imported"


class ContextShareStatus(StrEnum):
    """Lifecycle state for a share grant."""

    PENDING = "pending"
    READY = "ready"
    LOCAL_READY = "local_ready"
    FAILED = "failed"
    REVOKED = "revoked"
    EXPIRED = "expired"


class ShareImportStatus(StrEnum):
    """Result of importing or linking a shared context."""

    LINKED_EXISTING_EVENT = "linked_existing_event"
    IMPORTED = "imported"
    UPDATED_EXISTING_EVENT = "updated_existing_event"
    UNSUPPORTED_SOURCE = "unsupported_source"
    PERMISSION_REQUIRED = "permission_required"
    INVALID_PACKAGE = "invalid_package"
    FAILED = "failed"


class ShareImportSourceKind(StrEnum):
    """Share source families supported by the import pipeline."""

    LOCAL_REFERENCE = "local_reference"
    FEISHU_DRIVE_URL = "feishu_drive_url"
    UNKNOWN = "unknown"


class ShareScope(StrEnum):
    """What a share package is allowed to disclose."""

    AGENT_CONTEXT_WITH_SCREENSHOT = "agent_context_with_screenshot"


class ShareTargetKind(StrEnum):
    """Where a share revision is published."""

    FEISHU_DRIVE = "feishu_drive"
    LOCAL_BUNDLE = "local_bundle"


class ShareVisibility(StrEnum):
    """External link visibility controlled by the share publisher."""

    TENANT_READABLE = "tenant_readable"
    TENANT_EDITABLE = "tenant_editable"
    ANYONE_READABLE = "anyone_readable"
    CLOSED = "closed"


class SharePublishStatus(StrEnum):
    """External share publication status."""

    PENDING = "pending"
    UPLOADING = "uploading"
    PUBLISHED = "published"
    FAILED = "failed"
    REVOKED = "revoked"


class ShareAuditAction(StrEnum):
    """Audit action names inside the context-share ledger."""

    SHARE_CREATED = "share_created"
    SNAPSHOT_FROZEN = "snapshot_frozen"
    SHARE_RESOLVED = "share_resolved"
    SHARE_IMPORTED = "share_imported"
    SHARE_REVOKED = "share_revoked"
    SHARE_SYNC_STARTED = "share_sync_started"
    SHARE_SYNC_COMPLETED = "share_sync_completed"
    SHARE_SYNC_FAILED = "share_sync_failed"
