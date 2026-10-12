"""Application orchestration for click target resolution."""

from __future__ import annotations

import logging
from datetime import datetime
from hashlib import sha256

from packages.active_capture.click_targets.domain.label_policy import ClickTargetLabelPolicy
from packages.active_capture.click_targets.domain.scoring import ClickTargetScoringPolicy
from packages.active_capture.click_targets.ports.protocol import (
    ClickTargetRepository,
    TargetCandidateProvider,
)
from packages.contracts import (
    ArtifactIngestState,
    ClickTargetCandidate,
    ClickTargetConfidenceBand,
    ClickTargetEvidenceAnchor,
    ClickTargetResolution,
    ClickTargetResolutionStatus,
    ClickTargetResolverConfig,
    ClickTargetSemanticKind,
    ClickTargetSourceKind,
    ClickTargetSuppressionReason,
    ContextKeyframe,
    EvidenceRecord,
    EvidenceTrustState,
    HumanActionEvent,
    HumanActionKind,
    RedactionState,
)
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

logger = logging.getLogger(__name__)


class ClickTargetResolutionService:
    """Resolve semantic click targets after result evidence is available."""

    def __init__(
        self,
        *,
        repository: ClickTargetRepository,
        providers: tuple[TargetCandidateProvider, ...],
        ids: IdFactory,
        clock: Clock,
        config: ClickTargetResolverConfig,
    ) -> None:
        self.repository = repository
        self.providers = providers
        self.ids = ids
        self.clock = clock
        self.config = config
        self.scoring = ClickTargetScoringPolicy(config=config)
        self.label_policy = ClickTargetLabelPolicy(max_chars=config.max_safe_label_chars)

    def resolve_action_after_keyframe(
        self,
        *,
        action_id: str,
        keyframe: ContextKeyframe,
        evidence_records: tuple[EvidenceRecord, ...],
    ) -> ClickTargetResolution | None:
        """Resolve a click target after a click-settle keyframe has committed."""

        if not self.config.enabled:
            return None
        action = self.repository.get_human_action(action_id)
        if action is None or action.kind != HumanActionKind.CLICK:
            return None
        now = self.clock.now()
        visible_evidence = self._safe_evidence_records(evidence_records)
        input_fingerprint = self._input_fingerprint(
            action=action,
            keyframe=keyframe,
            evidence_records=visible_evidence,
        )
        resolution_id = self.ids.new("ctr")
        try:
            candidates = self._collect_candidates(
                action=action,
                keyframe=keyframe,
                evidence_records=visible_evidence,
                resolution_id=resolution_id,
                created_at=now,
            )
        except Exception:
            logger.warning(
                "click target candidate collection failed",
                extra={"session_id": action.session_id, "action_id": action.action_id},
                exc_info=True,
            )
            failed = self._failed_resolution(
                action=action,
                keyframe=keyframe,
                resolution_id=resolution_id,
                input_fingerprint=input_fingerprint,
            )
            return self.repository.save_click_target_resolution_graph(resolution=failed, candidates=())
        winner = self.scoring.choose_winner(candidates)
        resolution = self._resolution(
            action=action,
            keyframe=keyframe,
            resolution_id=resolution_id,
            input_fingerprint=input_fingerprint,
            candidates=candidates,
            winner=winner,
        )
        saved = self.repository.save_click_target_resolution_graph(
            resolution=resolution,
            candidates=candidates,
        )
        logger.info(
            "click target resolved",
            extra={
                "session_id": action.session_id,
                "action_id": action.action_id,
                "status": saved.status.value,
                "confidence": saved.confidence,
                "semantic_kind": saved.semantic_kind.value,
            },
        )
        return saved

    def _collect_candidates(
        self,
        *,
        action: HumanActionEvent,
        keyframe: ContextKeyframe,
        evidence_records: tuple[EvidenceRecord, ...],
        resolution_id: str,
        created_at: datetime,
    ) -> tuple[ClickTargetCandidate, ...]:
        candidates: list[ClickTargetCandidate] = []
        for provider in self.providers:
            if provider.source_kind not in self.config.enabled_source_kinds:
                continue
            provider_candidates = provider.candidates_for(
                action=action,
                keyframe=keyframe,
                evidence_records=evidence_records,
                resolution_id=resolution_id,
                now_id_prefix=self.ids.new("ctc"),
                created_at=created_at,
            )
            candidates.extend(provider_candidates)
        return tuple(sorted(candidates, key=lambda item: item.confidence, reverse=True)[: self.config.max_candidates])

    def _safe_evidence_records(self, records: tuple[EvidenceRecord, ...]) -> tuple[EvidenceRecord, ...]:
        allowed_trust = {EvidenceTrustState.DLP_PASSED, EvidenceTrustState.PROVIDER_REDACTED}
        allowed_ingest = {ArtifactIngestState.DLP_PASSED, ArtifactIngestState.INDEXED}
        blocked_redaction = {RedactionState.BLOCKED, RedactionState.QUARANTINED}
        return tuple(
            record
            for record in records
            if record.trust_state in allowed_trust
            and record.ingest_state in allowed_ingest
            and record.redaction_state not in blocked_redaction
        )

    def _resolution(
        self,
        *,
        action: HumanActionEvent,
        keyframe: ContextKeyframe,
        resolution_id: str,
        input_fingerprint: str,
        candidates: tuple[ClickTargetCandidate, ...],
        winner: ClickTargetCandidate | None,
    ) -> ClickTargetResolution:
        now = self.clock.now()
        if winner is None:
            return ClickTargetResolution(
                resolution_id=resolution_id,
                action_id=action.action_id,
                session_id=action.session_id,
                status=ClickTargetResolutionStatus.LOW_CONFIDENCE,
                semantic_kind=ClickTargetSemanticKind.UNKNOWN,
                source_kind=ClickTargetSourceKind.COORDINATE_FALLBACK,
                display_label="目标待确认",
                confidence=0.0,
                confidence_band=ClickTargetConfidenceBand.UNAVAILABLE,
                evidence_anchor=ClickTargetEvidenceAnchor(keyframe_id=keyframe.keyframe_id),
                candidate_ids=(),
                needs_review=True,
                suppression_reason=ClickTargetSuppressionReason.NO_CANDIDATE,
                input_fingerprint=input_fingerprint,
                resolver_version=self.config.resolver_version,
                policy_version=self.config.policy_version,
                created_at=now,
                updated_at=now,
            )
        display_label = winner.safe_label or self.label_policy.fallback_label(winner.semantic_kind)
        status = self.scoring.status_for(
            confidence=winner.confidence,
            candidate_count=len(candidates),
        )
        confidence_band = self.scoring.confidence_band(winner.confidence)
        return ClickTargetResolution(
            resolution_id=resolution_id,
            action_id=action.action_id,
            session_id=action.session_id,
            status=status,
            semantic_kind=winner.semantic_kind,
            source_kind=winner.source_kind,
            display_label=display_label,
            confidence=winner.confidence,
            confidence_band=confidence_band,
            evidence_anchor=winner.evidence_anchor,
            bbox=winner.bbox,
            candidate_ids=tuple(candidate.candidate_id for candidate in candidates),
            needs_review=status != ClickTargetResolutionStatus.RESOLVED,
            suppression_reason=(
                ClickTargetSuppressionReason.LOW_CONFIDENCE
                if status == ClickTargetResolutionStatus.LOW_CONFIDENCE
                else None
            ),
            input_fingerprint=input_fingerprint,
            resolver_version=self.config.resolver_version,
            policy_version=self.config.policy_version,
            created_at=now,
            updated_at=now,
        )

    def _failed_resolution(
        self,
        *,
        action: HumanActionEvent,
        keyframe: ContextKeyframe,
        resolution_id: str,
        input_fingerprint: str,
    ) -> ClickTargetResolution:
        now = self.clock.now()
        return ClickTargetResolution(
            resolution_id=resolution_id,
            action_id=action.action_id,
            session_id=action.session_id,
            status=ClickTargetResolutionStatus.FAILED,
            semantic_kind=ClickTargetSemanticKind.UNKNOWN,
            source_kind=ClickTargetSourceKind.COORDINATE_FALLBACK,
            display_label="目标待确认",
            confidence=0.0,
            confidence_band=ClickTargetConfidenceBand.UNAVAILABLE,
            evidence_anchor=ClickTargetEvidenceAnchor(keyframe_id=keyframe.keyframe_id),
            candidate_ids=(),
            needs_review=True,
            suppression_reason=ClickTargetSuppressionReason.POLICY_DENIED,
            input_fingerprint=input_fingerprint,
            resolver_version=self.config.resolver_version,
            policy_version=self.config.policy_version,
            created_at=now,
            updated_at=now,
        )

    def _input_fingerprint(
        self,
        *,
        action: HumanActionEvent,
        keyframe: ContextKeyframe,
        evidence_records: tuple[EvidenceRecord, ...],
    ) -> str:
        evidence_ids = ",".join(sorted(record.evidence_id for record in evidence_records))
        coordinate = action.coordinates.model_dump_json() if action.coordinates is not None else "none"
        material = "|".join(
            (action.action_id, keyframe.keyframe_id, coordinate, evidence_ids, self.config.resolver_version)
        )
        return sha256(material.encode("utf-8")).hexdigest()
