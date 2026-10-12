"""Policy-before-index services for redaction and fail-closed suppression.

The module owns reusable strategies for detecting sensitive surfaces, rejecting
raw materials, redacting approved text, and emitting auditable typed projections
before any feature writes documents into the search index.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Protocol

from packages.contracts import (
    ArtifactType,
    IndexPolicyDecisionStatus,
    IndexSuppressionReason,
    RedactionState,
    SearchFieldKind,
    SensitiveSurfaceType,
)
from packages.evidence.redaction import SensitiveTextRedactor
from packages.shared.ids import IdFactory

from .contracts import (
    IndexableTextSource,
    IndexPolicyAuditSummary,
    IndexPolicyDecision,
    SafeIndexPolicyConfig,
    SafeIndexProjection,
    SafeIndexProjectionBatch,
)

logger = logging.getLogger(__name__)


class TextRedactionStrategy(Protocol):
    """Redaction strategy used by policy-before-index."""

    def redact(self, text: str) -> str: ...


class SensitiveSurfaceDetector:
    """Detect source-level sensitive surfaces before indexing text."""

    def __init__(self, *, config: SafeIndexPolicyConfig | None = None) -> None:
        self.config = config or SafeIndexPolicyConfig()

    def detect(self, source: IndexableTextSource) -> SensitiveSurfaceType:
        """Return the effective sensitive surface for a source."""

        if source.sensitive_surface_type != SensitiveSurfaceType.NONE:
            return source.sensitive_surface_type
        title = source.event.source_binding.source_ref.title.lower()
        app = (source.event.source_binding.source_ref.app_name or "").lower()
        text = f"{title} {app}"
        if any(fragment.lower() in text for fragment in self.config.sensitive_title_fragments):
            return SensitiveSurfaceType.UNKNOWN_SENSITIVE
        return SensitiveSurfaceType.NONE


class SuppressionPolicy:
    """Fail-closed suppression policy for unsafe index sources."""

    _raw_artifacts = {
        ArtifactType.SCREENSHOT,
        ArtifactType.OS_REGION_SCREENSHOT,
        ArtifactType.OS_REGION_CROP,
        ArtifactType.BROWSER_FULL_DOM,
        ArtifactType.A11Y_TREE,
        ArtifactType.VISUAL_OCR_RESULT,
        ArtifactType.RECORDING_VIDEO,
    }

    _supported_fields = {
        SearchFieldKind.SAFE_METADATA,
        SearchFieldKind.USER_NOTE,
        SearchFieldKind.SELECTION_TEXT,
        SearchFieldKind.VISUAL_OCR_TEXT,
        SearchFieldKind.CANONICAL_TEXT,
        SearchFieldKind.CLEAN_PAGE_TEXT,
        SearchFieldKind.KEYFRAME_CONTEXT_TEXT,
        SearchFieldKind.ACTIVE_CAPTURE_SUMMARY,
        SearchFieldKind.RECORDING_TIMELINE,
        SearchFieldKind.HUMAN_DEMO_SUMMARY,
    }

    def reason(self, source: IndexableTextSource, *, surface_type: SensitiveSurfaceType) -> IndexSuppressionReason:
        """Return why this source must be suppressed, or NONE."""

        if not source.text.strip():
            return IndexSuppressionReason.EMPTY_TEXT
        if source.field_kind not in self._supported_fields:
            return IndexSuppressionReason.UNSUPPORTED_FIELD
        if source.artifact_type in self._raw_artifacts:
            return IndexSuppressionReason.RAW_MATERIAL
        if source.redaction_state in {RedactionState.BLOCKED, RedactionState.QUARANTINED}:
            return IndexSuppressionReason.BLOCKED_REDACTION_STATE
        if surface_type != SensitiveSurfaceType.NONE:
            return IndexSuppressionReason.SENSITIVE_SURFACE
        return IndexSuppressionReason.NONE


class SafeTextProjectionBuilder:
    """Build redacted safe text from an allowed source."""

    def __init__(self, *, redactor: TextRedactionStrategy, config: SafeIndexPolicyConfig | None = None) -> None:
        self.redactor = redactor
        self.config = config or SafeIndexPolicyConfig()

    def build(self, source: IndexableTextSource) -> tuple[str, IndexPolicyDecisionStatus, RedactionState]:
        """Return safe text and its effective redaction status."""

        original = source.text.strip()[: self.config.max_text_chars]
        redacted = self.redactor.redact(original)
        if redacted != original:
            return redacted, IndexPolicyDecisionStatus.REDACTED, RedactionState.REDACTED
        return original, IndexPolicyDecisionStatus.ALLOWED, source.redaction_state


class SafeIndexProjectionService:
    """Turn raw candidate text sources into safe index projections."""

    def __init__(
        self,
        *,
        ids: IdFactory,
        surface_detector: SensitiveSurfaceDetector | None = None,
        suppression_policy: SuppressionPolicy | None = None,
        text_builder: SafeTextProjectionBuilder | None = None,
        config: SafeIndexPolicyConfig | None = None,
        policy_version: str | None = None,
    ) -> None:
        self.config = config or SafeIndexPolicyConfig(policy_version=policy_version or "index_policy_v1")
        self.ids = ids
        self.surface_detector = surface_detector or SensitiveSurfaceDetector(config=self.config)
        self.suppression_policy = suppression_policy or SuppressionPolicy()
        self.text_builder = text_builder or SafeTextProjectionBuilder(
            redactor=SensitiveTextRedactor(),
            config=self.config,
        )
        self.policy_version = self.config.policy_version

    def project(
        self,
        *,
        event_id: str,
        sources: tuple[IndexableTextSource, ...],
        capture_run_id: str | None = None,
        replace_event: bool = True,
    ) -> SafeIndexProjectionBatch:
        """Return policy-before-index projections for a set of sources."""

        projections = tuple(self._project_source(source) for source in sources)
        audit = IndexPolicyAuditSummary(
            allowed_count=sum(1 for item in projections if item.decision.status == IndexPolicyDecisionStatus.ALLOWED),
            redacted_count=sum(1 for item in projections if item.decision.status == IndexPolicyDecisionStatus.REDACTED),
            suppressed_count=sum(
                1 for item in projections if item.decision.status == IndexPolicyDecisionStatus.SUPPRESSED
            ),
            policy_version=self.policy_version,
        )
        logger.info(
            "safe index projection built",
            extra={
                "event_id": event_id,
                "allowed_count": audit.allowed_count,
                "redacted_count": audit.redacted_count,
                "suppressed_count": audit.suppressed_count,
            },
        )
        return SafeIndexProjectionBatch(
            event_id=event_id,
            capture_run_id=capture_run_id,
            projections=projections,
            replace_event=replace_event,
            audit=audit,
        )

    def _project_source(self, source: IndexableTextSource) -> SafeIndexProjection:
        surface_type = self.surface_detector.detect(source)
        suppression_reason = self.suppression_policy.reason(source, surface_type=surface_type)
        source_hash = self._hash(source.text)
        if suppression_reason != IndexSuppressionReason.NONE:
            decision = IndexPolicyDecision(
                decision_id=self.ids.new("idxpol"),
                status=IndexPolicyDecisionStatus.SUPPRESSED,
                suppression_reason=suppression_reason,
                sensitive_surface_type=surface_type,
                source_text_hash=source_hash,
                redaction_state=source.redaction_state,
                agent_visible_fields=source.agent_visible_fields,
                policy_version=self.policy_version,
            )
            logger.info(
                "index source suppressed",
                extra={
                    "event_id": source.event.event_id,
                    "field_kind": source.field_kind.value,
                    "reason": suppression_reason.value,
                    "surface_type": surface_type.value,
                },
            )
            return SafeIndexProjection(source=source, decision=decision)
        text, status, redaction_state = self.text_builder.build(source)
        decision = IndexPolicyDecision(
            decision_id=self.ids.new("idxpol"),
            status=status,
            suppression_reason=IndexSuppressionReason.NONE,
            sensitive_surface_type=surface_type,
            source_text_hash=source_hash,
            output_text_hash=self._hash(text),
            redaction_state=redaction_state,
            agent_visible_fields=source.agent_visible_fields,
            policy_version=self.policy_version,
        )
        return SafeIndexProjection(source=source, decision=decision, text=text)

    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
