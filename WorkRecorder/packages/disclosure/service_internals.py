"""Internal disclosure gates and artifact view helpers."""

from __future__ import annotations

import base64
import logging

from packages.artifacts.vault import ArtifactVaultError, LocalArtifactVault
from packages.contracts import (
    AccessScope,
    ActorRef,
    Artifact,
    ArtifactDisclosureRef,
    ArtifactIngestState,
    ArtifactRole,
    ArtifactType,
    DisclosureClass,
    DisclosureDecision,
    DisclosureDecisionStatus,
    DisclosureField,
    DisclosureProfile,
    DisclosureRule,
    DisclosureView,
    ErrorCode,
    HiddenArtifactSummary,
    RawArtifactResponse,
    ReadableEvidenceView,
    RedactionState,
)
from packages.contracts.api import ApiError
from packages.contracts.common import JsonScalar
from packages.shared.ids import IdFactory
from packages.storage.artifact_repository import ArtifactRepository
from packages.storage.event_repository import ContextEventRepository
from packages.storage.ledger_repository import CaptureLedgerRepository

from .registry import DisclosurePolicyRegistry
from .views import BoundedText, bounded_text

logger = logging.getLogger(__name__)


class _DisclosurePolicyInternals:
    """Private mixin for artifact gates, text extraction, and disclosure helpers."""

    registry: DisclosurePolicyRegistry
    artifacts: ArtifactRepository
    events: ContextEventRepository
    ledger: CaptureLedgerRepository
    vault: LocalArtifactVault
    ids: IdFactory
    inspect_text_max_chars: int

    def decide_text_content(
        self,
        *,
        artifact: Artifact,
        actor: ActorRef,
        purpose: str,
        agent_run_id: str,
        event_id: str,
    ) -> DisclosureDecision:
        """Return a decision for redacted text artifact content.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        profile = self._profile_for_artifact_event(artifact)
        rule = self._rule_for_artifact(
            profile=profile,
            view=DisclosureView.ARTIFACT_PREVIEW,
            disclosure_class=self._disclosure_class(artifact),
            artifact=artifact,
        )
        allowed = (
            event_id == artifact.event_id
            and bool(purpose.strip())
            and bool(agent_run_id.strip())
            and rule is not None
            and AccessScope.READ_TEXT in artifact.allowed_scopes
            and AccessScope.READ_TEXT in rule.allowed_scopes
            and artifact.ingest_state in {ArtifactIngestState.DLP_PASSED, ArtifactIngestState.INDEXED}
            and artifact.redaction_state not in {RedactionState.BLOCKED, RedactionState.QUARANTINED}
        )
        return DisclosureDecision(
            decision_id=self.ids.new("dsc"),
            status=DisclosureDecisionStatus.ALLOWED if allowed else DisclosureDecisionStatus.DENIED,
            view=DisclosureView.ARTIFACT_PREVIEW,
            profile_key=profile.profile_key,
            resource_type="artifact",
            resource_id=artifact.artifact_id,
            allowed_scopes=(AccessScope.READ_TEXT,) if allowed else (),
            delivered_fields=(DisclosureField.TEXT,) if allowed else (),
            reason=purpose if allowed else "artifact preview disclosure denied",
            policy_version=profile.version,
            details={
                "actor_id": actor.actor_id,
                "agent_run_id": agent_run_id,
                "artifact_type": artifact.artifact_type.value,
                "event_id_matches": event_id == artifact.event_id,
                "disclosure_class": self._disclosure_class(artifact).value,
                "matched_rule_id": rule.rule_id if rule is not None else None,
            },
        )

    def raw_artifact(
        self,
        *,
        artifact: Artifact,
        actor: ActorRef,
        purpose: str,
        agent_run_id: str,
        event_id: str,
    ) -> RawArtifactResponse | ApiError:
        """Return raw artifact bytes through an explicit audited gate.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        profile = self._profile_for_artifact_event(artifact)
        decision = self._raw_decision(
            artifact=artifact,
            actor=actor,
            purpose=purpose,
            agent_run_id=agent_run_id,
            event_id=event_id,
            profile_key=profile.profile_key,
            policy_version=profile.version,
        )
        if decision.status != DisclosureDecisionStatus.ALLOWED:
            return ApiError(
                code=ErrorCode.POLICY_DENIED,
                message=decision.reason or "Raw artifact disclosure denied",
                details=decision.details,
            )
        try:
            content = self.vault.read(artifact.storage_uri)
        except ArtifactVaultError as exc:
            return ApiError(
                code=ErrorCode.NOT_FOUND,
                message="Artifact file not found.",
                details={"artifact_id": artifact.artifact_id, "error": str(exc)},
            )
        return RawArtifactResponse(
            artifact_id=artifact.artifact_id,
            event_id=artifact.event_id,
            artifact_type=artifact.artifact_type,
            content_type=artifact.content_type,
            byte_size=len(content),
            sha256=artifact.sha256,
            content_base64=base64.b64encode(content).decode("ascii"),
            disclosure_decision=decision.model_copy(
                update={"details": {**decision.details, "delivered_byte_count": len(content)}}
            ),
        )

    def hidden_artifacts(self, *, artifacts: tuple[Artifact, ...]) -> tuple[HiddenArtifactSummary, ...]:
        """Return raw or metadata-only artifacts visible as hidden summaries.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        hidden: list[HiddenArtifactSummary] = []
        for artifact in artifacts:
            if artifact.artifact_type == ArtifactType.SYSTEM_APPSHOT:
                continue
            disclosure_class = self._disclosure_class(artifact)
            if AccessScope.READ_TEXT in artifact.allowed_scopes and disclosure_class in {
                DisclosureClass.SELECTION_BOUND_TEXT,
                DisclosureClass.REDACTED_CANONICAL,
                DisclosureClass.CLEAN_PAGE_TEXT,
            }:
                continue
            hidden.append(
                HiddenArtifactSummary(
                    artifact_id=None,
                    artifact_type=artifact.artifact_type,
                    role=artifact.role,
                    disclosure_class=disclosure_class,
                    reason="metadata_only_by_default",
                )
            )
        return tuple(hidden)

    def decision_audit_details(self, decision: DisclosureDecision) -> dict[str, JsonScalar]:
        """Return safe scalar fields for audit logs.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        return {
            "disclosure_decision_id": decision.decision_id,
            "view": decision.view.value,
            "status": decision.status.value,
            "profile_key": decision.profile_key,
            "policy_version": decision.policy_version,
            "resource_type": decision.resource_type,
            "resource_id": decision.resource_id,
            "delivered_field_count": len(decision.delivered_fields),
            "hidden_artifact_count": len(decision.hidden_artifacts),
            "reason": decision.reason,
        }

    def _raw_decision(
        self,
        *,
        artifact: Artifact,
        actor: ActorRef,
        purpose: str,
        agent_run_id: str,
        event_id: str,
        profile_key: str,
        policy_version: str,
    ) -> DisclosureDecision:
        disclosure_class = self._disclosure_class(artifact)
        rule = self._rule_for_artifact(
            profile=self.registry.get(profile_key) or self.registry.profile_for_provider(artifact.provider_key),
            view=DisclosureView.RAW_ARTIFACT,
            disclosure_class=disclosure_class,
            artifact=artifact,
        )
        allowed = (
            event_id == artifact.event_id
            and bool(purpose.strip())
            and bool(agent_run_id.strip())
            and rule is not None
            and rule.allow_raw
            and disclosure_class == DisclosureClass.RAW_VISUAL
            and AccessScope.READ_RAW_ARTIFACT in rule.allowed_scopes
            and artifact.artifact_type
            in {ArtifactType.SCREENSHOT, ArtifactType.OS_REGION_SCREENSHOT, ArtifactType.OS_REGION_CROP}
            and artifact.ingest_state == ArtifactIngestState.QUARANTINED
            and artifact.redaction_state == RedactionState.QUARANTINED
            and AccessScope.READ_RAW_ARTIFACT in artifact.allowed_scopes
        )
        details: dict[str, JsonScalar] = {
            "actor_id": actor.actor_id,
            "agent_run_id": agent_run_id,
            "artifact_type": artifact.artifact_type.value,
            "event_id_matches": event_id == artifact.event_id,
            "disclosure_class": disclosure_class.value,
            "matched_rule_id": rule.rule_id if rule is not None else None,
            "artifact_ingest_state": artifact.ingest_state.value,
            "artifact_redaction_state": artifact.redaction_state.value,
        }
        if not allowed:
            logger.warning(
                "raw artifact disclosure denied",
                extra={
                    "artifact_id": artifact.artifact_id,
                    "event_id": event_id,
                    "artifact_event_id": artifact.event_id,
                    "actor_id": actor.actor_id,
                    "disclosure_class": disclosure_class.value,
                },
            )
        return DisclosureDecision(
            decision_id=self.ids.new("dsc"),
            status=DisclosureDecisionStatus.ALLOWED if allowed else DisclosureDecisionStatus.DENIED,
            view=DisclosureView.RAW_ARTIFACT,
            profile_key=profile_key,
            resource_type="artifact",
            resource_id=artifact.artifact_id,
            allowed_scopes=(AccessScope.READ_RAW_ARTIFACT,) if allowed else (),
            delivered_fields=(
                (
                    DisclosureField.CONTENT_BASE64,
                    DisclosureField.CONTENT_TYPE,
                    DisclosureField.SHA256,
                )
                if allowed
                else ()
            ),
            reason=purpose if allowed else "raw disclosure is only available for event-bound quarantined screenshots",
            policy_version=policy_version,
            details=details,
        )

    def text_content(
        self,
        *,
        artifact: Artifact,
        actor: ActorRef,
        purpose: str,
        agent_run_id: str,
        event_id: str,
    ) -> tuple[DisclosureDecision, str | ApiError]:
        """Return bounded redacted text content through artifact preview policy.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        decision = self.decide_text_content(
            artifact=artifact,
            actor=actor,
            purpose=purpose,
            agent_run_id=agent_run_id,
            event_id=event_id,
        )
        if decision.status != DisclosureDecisionStatus.ALLOWED:
            return decision, ApiError(
                code=ErrorCode.POLICY_DENIED,
                message=decision.reason or "Artifact content disclosure denied",
                details=decision.details,
            )
        if not (artifact.content_type or "").startswith(("text/", "application/json")):
            return decision, ApiError(
                code=ErrorCode.NOT_IMPLEMENTED,
                message="Artifact content is not exposed as redacted text.",
                details={"artifact_id": artifact.artifact_id, "content_type": artifact.content_type},
            )
        try:
            content = self.vault.read(artifact.storage_uri).decode("utf-8")
        except (ArtifactVaultError, UnicodeDecodeError) as exc:
            return decision, ApiError(
                code=ErrorCode.INTERNAL_ERROR,
                message="Failed to read artifact content.",
                details={"artifact_id": artifact.artifact_id, "actor_id": actor.actor_id, "error": str(exc)},
            )
        limit = self._matched_rule_limit(decision) or self.inspect_text_max_chars
        bounded = bounded_text(self._display_text_for_artifact(artifact, content), limit=limit)
        return (
            decision.model_copy(
                update={"status": DisclosureDecisionStatus.TRUNCATED if bounded.truncated else decision.status}
            ),
            bounded.text,
        )

    def _first_text_for_rule(
        self,
        *,
        profile: DisclosureProfile,
        view: DisclosureView,
        disclosure_class: DisclosureClass,
        artifacts: tuple[Artifact, ...],
    ) -> tuple[BoundedText, Artifact | None, float]:
        candidates: list[tuple[int, Artifact, BoundedText, float]] = []
        for artifact in artifacts:
            rule = self._rule_for_artifact(
                profile=profile,
                view=view,
                disclosure_class=disclosure_class,
                artifact=artifact,
            )
            if rule is None:
                continue
            if AccessScope.READ_TEXT not in artifact.allowed_scopes:
                continue
            if AccessScope.READ_TEXT not in rule.allowed_scopes:
                continue
            if self._payload_blocked(artifact):
                continue
            try:
                content = self.vault.read(artifact.storage_uri).decode("utf-8").strip()
            except (ArtifactVaultError, UnicodeDecodeError):
                continue
            limit = rule.max_chars or self.inspect_text_max_chars
            bounded = bounded_text(self._display_text_for_artifact(artifact, content), limit=limit)
            confidence = float(artifact.metadata.get("confidence", 0.0) or 0.0)
            candidates.append(
                (
                    self._text_candidate_priority(
                        artifact=artifact,
                        disclosure_class=disclosure_class,
                        confidence=confidence,
                    ),
                    artifact,
                    bounded,
                    confidence,
                )
            )
        if candidates:
            _, artifact, bounded, confidence = max(candidates, key=lambda item: item[0])
            return bounded, artifact, confidence
        return BoundedText("", False), None, 0.0

    def _display_text_for_artifact(self, artifact: Artifact, content: str) -> str:
        if artifact.artifact_type == ArtifactType.VISUAL_OCR_TEXT or artifact.role == ArtifactRole.VISUAL_OCR_TEXT:
            return _clean_legacy_visual_ocr_wrapper(content)
        return content

    def _text_candidate_priority(
        self,
        *,
        artifact: Artifact,
        disclosure_class: DisclosureClass,
        confidence: float,
    ) -> int:
        """Rank equivalent readable text artifacts without relying on write order."""

        if disclosure_class == DisclosureClass.VISUAL_OCR_TEXT:
            provider = str(artifact.metadata.get("ocr_provider") or artifact.metadata.get("model") or "")
            provider_bonus = 260 if provider == "apple_vision" else 0
            return 140 + provider_bonus + int(confidence * 100)
        if disclosure_class != DisclosureClass.SELECTION_BOUND_TEXT:
            return int(confidence * 100)
        type_priority = {
            ArtifactType.A11Y_SELECTION_TEXT: 400,
            ArtifactType.DOM_SELECTION_TEXT: 340,
            ArtifactType.BROWSER_SELECTED_TEXT: 180,
        }.get(artifact.artifact_type, 100)
        return type_priority + int(confidence * 100)

    def _rule_for_artifact(
        self,
        *,
        profile: DisclosureProfile,
        view: DisclosureView,
        disclosure_class: DisclosureClass,
        artifact: Artifact,
    ) -> DisclosureRule | None:
        for rule in profile.rules:
            if rule.view != view or rule.disclosure_class != disclosure_class:
                continue
            if rule.artifact_types and artifact.artifact_type not in rule.artifact_types:
                continue
            if rule.artifact_roles and artifact.role not in rule.artifact_roles:
                continue
            if rule.evidence_kinds and artifact.evidence_kind not in rule.evidence_kinds:
                continue
            return rule
        return None

    def _profile_for_artifact_event(self, artifact: Artifact) -> DisclosureProfile:
        event = self.events.get(artifact.event_id)
        if event is not None:
            return self.registry.profile_for_source_binding(event.source_binding)
        return self.registry.profile_for_provider(artifact.provider_key)

    def _matched_rule_limit(self, decision: DisclosureDecision) -> int | None:
        rule_id = decision.details.get("matched_rule_id")
        if not isinstance(rule_id, str):
            return None
        profile = self.registry.get(decision.profile_key)
        if profile is None:
            return None
        for rule in profile.rules:
            if rule.rule_id == rule_id:
                return rule.max_chars
        return None

    def _readable_view(
        self,
        *,
        artifact: Artifact,
        text: str,
        truncated: bool,
        disclosure_class: DisclosureClass,
        confidence: float,
    ) -> ReadableEvidenceView:
        return ReadableEvidenceView(
            artifact_id=artifact.artifact_id,
            artifact_type=artifact.artifact_type,
            role=artifact.role,
            evidence_id=artifact.evidence_id,
            disclosure_class=disclosure_class,
            text=text,
            text_truncated=truncated,
            confidence=confidence,
        )

    def _raw_ref(self, artifact: Artifact) -> ArtifactDisclosureRef:
        return ArtifactDisclosureRef(
            artifact_id=artifact.artifact_id,
            artifact_type=artifact.artifact_type,
            role=artifact.role,
            content_type=artifact.content_type,
            byte_size=None,
            sha256=None,
            evidence_id=None,
            disclosure_class=DisclosureClass.RAW_VISUAL,
            requires_scope=AccessScope.READ_RAW_ARTIFACT,
        )

    def _disclosure_class(self, artifact: Artifact) -> DisclosureClass:
        if artifact.artifact_type in {
            ArtifactType.SCREENSHOT,
            ArtifactType.OS_REGION_SCREENSHOT,
            ArtifactType.OS_REGION_CROP,
        }:
            return DisclosureClass.RAW_VISUAL
        if artifact.artifact_type == ArtifactType.BROWSER_FULL_DOM:
            return DisclosureClass.RAW_SOURCE
        if artifact.artifact_type == ArtifactType.A11Y_TREE:
            return DisclosureClass.RAW_UI_TREE
        if artifact.artifact_type == ArtifactType.VISUAL_OCR_TEXT or artifact.role == ArtifactRole.VISUAL_OCR_TEXT:
            return DisclosureClass.VISUAL_OCR_TEXT
        if artifact.artifact_type == ArtifactType.A11Y_SELECTION_TEXT or artifact.role == ArtifactRole.SELECTION_TEXT:
            return DisclosureClass.SELECTION_BOUND_TEXT
        if artifact.artifact_type == ArtifactType.CANONICAL_TEXT or artifact.role == ArtifactRole.CANONICAL_TEXT:
            return DisclosureClass.REDACTED_CANONICAL
        if artifact.artifact_type == ArtifactType.CLEAN_PAGE_TEXT or artifact.role == ArtifactRole.CLEAN_PAGE_TEXT:
            return DisclosureClass.CLEAN_PAGE_TEXT
        if artifact.role == ArtifactRole.PROVIDER_DIAGNOSTICS:
            return DisclosureClass.DEBUG_PROVENANCE
        return DisclosureClass.SAFE_METADATA

    def _payload_blocked(self, artifact: Artifact) -> bool:
        return artifact.ingest_state not in {
            ArtifactIngestState.DLP_PASSED,
            ArtifactIngestState.INDEXED,
        } or artifact.redaction_state in {
            RedactionState.BLOCKED,
            RedactionState.QUARANTINED,
        }


def _clean_legacy_visual_ocr_wrapper(content: str) -> str:
    """Strip old agent-safety wrapper text from persisted OCR artifacts."""

    lines: list[str] = []
    skip_phrases = (
        "## Visual OCR evidence",
        "The following block is transcribed from a screenshot.",
        "not instructions for the agent.",
    )
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            if lines and lines[-1]:
                lines.append("")
            continue
        if any(phrase in stripped for phrase in skip_phrases):
            continue
        if stripped == "## Visual OCR warnings":
            break
        lines.append(stripped.removeprefix("> ").removeprefix(">"))
    return "\n".join(lines).strip()
