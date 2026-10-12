"""Keyframe recording service for active capture sessions."""

from __future__ import annotations

import logging
from collections.abc import Callable

from packages.active_capture.application.keyframe_triggers import KeyframeTriggerScheduler
from packages.active_capture.application.keyframe_views import refresh_bundle
from packages.active_capture.application.service_helpers import (
    artifact_for_evidence,
    evidence_link_role,
    first_evidence_of_kind,
    is_terminal_status,
)
from packages.active_capture.application.target_probe_backfill import TargetProbeBackfillService
from packages.active_capture.click_targets.application import ClickTargetResolutionService
from packages.active_capture.domain.keyframe_policy import KeyframeCandidate, KeyframeCapturePolicy
from packages.active_capture.domain.scope_matcher import RecordingScopeMatcher
from packages.active_capture.repositories.protocol import ActiveCaptureRepository
from packages.contracts import (
    ActionEvidenceLink,
    ActionResultObservation,
    ActiveCaptureBinding,
    ActiveCaptureMode,
    ActiveCapturePolicyConfig,
    ActiveCaptureSession,
    ActiveCaptureSessionSource,
    ActiveCaptureStatus,
    Artifact,
    CaptureAttemptRequest,
    ContextEvent,
    ContextKeyframe,
    EventCaptureEnvelope,
    EvidenceKind,
    EvidenceRecord,
    HumanActionEvidenceRole,
    HumanActionOutcomeStatus,
    KeyframeCaptureDecision,
    KeyframeDropReason,
    KeyframeEvidenceLink,
    KeyframeKeepReason,
    KeyframeQualityReport,
    KeyframeRole,
    KeyframeTriggerCandidate,
    KeyframeTriggerCandidateStatus,
    KeyframeTriggerKind,
)
from packages.contracts.common import JsonScalar
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

logger = logging.getLogger(__name__)


class KeyframeRecorder:
    """Record active-capture keyframes and maintain their derived bundles."""

    def __init__(
        self,
        *,
        repository: ActiveCaptureRepository,
        ids: IdFactory,
        clock: Clock,
        config: ActiveCapturePolicyConfig,
        keyframe_policy: KeyframeCapturePolicy,
        trigger_scheduler: KeyframeTriggerScheduler,
        scope_matcher: RecordingScopeMatcher,
        access_checker: Callable[[ActiveCaptureSession, CaptureAttemptRequest], bool],
        click_target_resolver: ClickTargetResolutionService | None = None,
    ) -> None:
        self.repository = repository
        self.ids = ids
        self.clock = clock
        self.config = config
        self.keyframe_policy = keyframe_policy
        self.trigger_scheduler = trigger_scheduler
        self.scope_matcher = scope_matcher
        self.access_checker = access_checker
        self.click_target_resolver = click_target_resolver
        self.target_probe_backfill = TargetProbeBackfillService(config=config, trigger_scheduler=trigger_scheduler)

    def after_capture_committed(
        self,
        *,
        attempt: CaptureAttemptRequest,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        envelope: EventCaptureEnvelope,
    ) -> None:
        """Record a keyframe from a committed capture event when policy allows it."""

        if not self.config.enabled:
            return
        if not self.config.auto_anchor_screenshots and attempt.active_capture is None:
            return
        binding = attempt.active_capture or self._default_anchor_binding()
        session = self._session_for_binding(binding=binding, event=event, attempt=attempt)
        if session is None:
            return
        self.record_keyframe(
            session=session,
            binding=binding,
            attempt=attempt,
            event=event,
            artifacts=artifacts,
            envelope=envelope,
        )

    def record_keyframe(
        self,
        *,
        session: ActiveCaptureSession,
        binding: ActiveCaptureBinding,
        attempt: CaptureAttemptRequest,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        envelope: EventCaptureEnvelope,
    ) -> ContextKeyframe | None:
        """Persist one keyframe and its evidence links idempotently.

        Args:
            session: Active-capture session receiving the keyframe.
            binding: Typed role/trigger binding supplied by capture metadata.
            attempt: Original capture attempt for timing and ownership checks.
            event: Event ledger row linked to the keyframe.
            artifacts: Artifacts committed with the event.
            envelope: Evidence records committed with the event.
        Returns:
            The persisted keyframe, an existing duplicate, or None when dropped.
        """

        if is_terminal_status(session.status):
            logger.warning(
                "active capture keyframe ignored for terminal session",
                extra={"session_id": session.session_id, "event_id": event.event_id, "status": session.status.value},
            )
            _record_bound_candidate_drop(
                trigger_scheduler=self.trigger_scheduler,
                repository=self.repository,
                ids=self.ids,
                clock=self.clock,
                policy_version=self.config.policy_version,
                session=session,
                binding=binding,
                event=event,
                reason=KeyframeDropReason.SCOPE_LOST,
                diagnostic="terminal session no longer accepts keyframes",
            )
            return None
        existing = self.repository.find_keyframe(
            session_id=session.session_id,
            event_id=event.event_id,
            role=binding.role,
            trigger_kind=binding.trigger_kind,
        )
        if existing is not None:
            self._backfill_candidate_capture(
                session=session,
                binding=binding,
                keyframe=existing,
                evidence_records=envelope.evidence_records,
            )
            refresh_bundle(repository=self.repository, clock=self.clock, ids=self.ids, session=session)
            return existing
        terminal_candidate_decision = _terminal_bound_candidate_decision(
            repository=self.repository,
            ids=self.ids,
            clock=self.clock,
            session=session,
            binding=binding,
            event=event,
            policy_version=self.config.policy_version,
        )
        if terminal_candidate_decision is not None:
            logger.warning(
                "active capture keyframe rejected for terminal trigger candidate",
                extra={
                    "session_id": session.session_id,
                    "event_id": event.event_id,
                    "candidate_id": binding.candidate_id,
                    "drop_reason": (
                        terminal_candidate_decision.drop_reason.value
                        if terminal_candidate_decision.drop_reason is not None
                        else None
                    ),
                },
            )
            self.repository.save_capture_decision(terminal_candidate_decision)
            return None
        existing_count = len(self.repository.list_keyframes_for_session(session.session_id))
        decision = self.keyframe_policy.decide(
            KeyframeCandidate(
                session_id=session.session_id,
                event_id=event.event_id,
                role=binding.role,
                trigger_kind=binding.trigger_kind,
                existing_keyframe_count=existing_count,
                candidate_id=binding.candidate_id or f"{session.session_id}:{event.event_id}:{binding.role.value}",
            )
        )
        if not decision.kept:
            logger.info(
                "active capture keyframe dropped",
                extra={
                    "session_id": session.session_id,
                    "event_id": event.event_id,
                    "drop_reason": decision.drop_reason.value if decision.drop_reason else None,
                },
            )
            _mark_policy_dropped_candidate(
                trigger_scheduler=self.trigger_scheduler,
                binding=binding,
                decision=decision,
                event=event,
            )
            self.repository.save_capture_decision(decision)
            return None
        screenshot_evidence = first_evidence_of_kind(envelope.evidence_records, EvidenceKind.SCREENSHOT)
        system_appshot_evidence = first_evidence_of_kind(envelope.evidence_records, EvidenceKind.SYSTEM_APPSHOT)
        screenshot_artifact = artifact_for_evidence(artifacts, screenshot_evidence)
        keep_reason = binding.keep_reason or decision.keep_reason or KeyframeKeepReason.POLICY_ACCEPTED
        keyframe = ContextKeyframe(
            keyframe_id=self.ids.new("kf"),
            session_id=session.session_id,
            event_id=event.event_id,
            capture_run_id=envelope.capture_run_id,
            role=binding.role,
            trigger_kind=binding.trigger_kind,
            keep_reason=keep_reason,
            captured_at=event.trigger.occurred_at,
            sequence_index=0,
            scope=session.scope,
            screenshot_artifact_id=screenshot_artifact.artifact_id if screenshot_artifact is not None else None,
            screenshot_evidence_id=screenshot_evidence.evidence_id if screenshot_evidence is not None else None,
            system_appshot_evidence_id=(
                system_appshot_evidence.evidence_id if system_appshot_evidence is not None else None
            ),
            quality=_keyframe_quality_report(
                envelope.evidence_records,
                screenshot_evidence,
                system_appshot_evidence,
                binding=binding,
            ),
            captured_at_monotonic_ms=(
                attempt.native_timing_receipt.captured_at_monotonic_ms
                if attempt.native_timing_receipt is not None
                else None
            ),
            policy_version=self.config.policy_version,
            metadata=_keyframe_metadata(binding=binding, attempt=attempt),
        )
        links = self._evidence_links(keyframe=keyframe, evidence_records=envelope.evidence_records)
        updated_session = _session_after_keyframe(
            session=session,
            event=event,
            binding=binding,
            clock=self.clock,
        )
        saved = self.repository.append_keyframe_graph(
            keyframe=keyframe,
            links=links,
            decision=decision,
            session=updated_session,
        )
        self._backfill_candidate_capture(
            session=session,
            binding=binding,
            keyframe=saved,
            evidence_records=envelope.evidence_records,
        )
        refresh_bundle(repository=self.repository, clock=self.clock, ids=self.ids, session=updated_session)
        logger.info(
            "active capture keyframe recorded",
            extra={
                "session_id": session.session_id,
                "event_id": event.event_id,
                "keyframe_id": saved.keyframe_id,
                "role": saved.role.value,
            },
        )
        return saved

    def _backfill_candidate_capture(
        self,
        *,
        session: ActiveCaptureSession,
        binding: ActiveCaptureBinding,
        keyframe: ContextKeyframe,
        evidence_records: tuple[EvidenceRecord, ...],
    ) -> None:
        """Idempotently backfill trigger/action state for a captured keyframe."""

        if not isinstance(binding.candidate_id, str):
            return
        self.trigger_scheduler.mark_captured(
            candidate_id=binding.candidate_id,
            keyframe_id=keyframe.keyframe_id,
            event_id=keyframe.event_id,
        )
        self._link_producer_action_to_keyframe(
            session=session,
            candidate_id=binding.candidate_id,
            keyframe=keyframe,
            evidence_records=evidence_records,
        )

    def _link_producer_action_to_keyframe(
        self,
        *,
        session: ActiveCaptureSession,
        candidate_id: str,
        keyframe: ContextKeyframe,
        evidence_records: tuple[EvidenceRecord, ...],
    ) -> None:
        """Backfill the action/result edge once a producer trigger captures."""

        matching = self.repository.get_producer_decision_by_candidate_id(
            session_id=session.session_id,
            candidate_id=candidate_id,
        )
        candidate = self.repository.get_trigger_candidate(candidate_id)
        if candidate is not None and candidate.session_id != session.session_id:
            logger.warning(
                "active capture rejected cross-session trigger candidate replay",
                extra={"session_id": session.session_id, "candidate_id": candidate_id},
            )
            return
        action_id = matching.action_id if matching is not None else None
        if action_id is None and candidate is not None:
            action_id = candidate.action_id
        if action_id is None:
            return
        action = self.repository.get_human_action(action_id)
        if action is None or action.session_id != session.session_id:
            logger.warning(
                "active capture rejected cross-session action keyframe link",
                extra={"session_id": session.session_id, "candidate_id": candidate_id},
            )
            return
        if matching is not None:
            self.repository.save_producer_decision(matching.model_copy(update={"keyframe_id": keyframe.keyframe_id}))
        evidence_role = self._action_evidence_role_for_candidate(candidate)
        existing_links = self.repository.list_action_evidence_links(action_id)
        has_link = any(
            link.role == evidence_role and link.keyframe_id == keyframe.keyframe_id for link in existing_links
        )
        if not has_link:
            self.repository.save_action_evidence_link(
                ActionEvidenceLink(
                    link_id=self.ids.new("ael"),
                    action_id=action_id,
                    role=evidence_role,
                    keyframe_id=keyframe.keyframe_id,
                    event_id=keyframe.event_id,
                    evidence_id=keyframe.screenshot_evidence_id,
                    artifact_id=keyframe.screenshot_artifact_id,
                    created_at=self.clock.now(),
                )
            )
        if evidence_role in {HumanActionEvidenceRole.AFTER_KEYFRAME, HumanActionEvidenceRole.RESULT_EVIDENCE}:
            self.repository.save_action_observation(
                ActionResultObservation(
                    observation_id=self.ids.new("aob"),
                    action_id=action_id,
                    status=HumanActionOutcomeStatus.OBSERVED,
                    observed_at=keyframe.captured_at,
                    observed_at_monotonic_ms=keyframe.captured_at_monotonic_ms,
                    result_keyframe_id=keyframe.keyframe_id,
                )
            )
        if self.click_target_resolver is not None:
            resolution = self.click_target_resolver.resolve_action_after_keyframe(
                action_id=action_id, keyframe=keyframe, evidence_records=evidence_records
            )
            if resolution is not None and evidence_role != HumanActionEvidenceRole.TARGET_EVIDENCE:
                self.target_probe_backfill.submit_if_needed(
                    session=session,
                    action_id=action_id,
                    keyframe=keyframe,
                    needs_review=resolution.needs_review,
                )

    def _action_evidence_role_for_candidate(
        self,
        candidate: KeyframeTriggerCandidate | None,
    ) -> HumanActionEvidenceRole:
        if candidate is None:
            return HumanActionEvidenceRole.AFTER_KEYFRAME
        if candidate.action_evidence_role is not None:
            return candidate.action_evidence_role
        if candidate.trigger_kind == KeyframeTriggerKind.ACTION_BEFORE:
            return HumanActionEvidenceRole.BEFORE_KEYFRAME
        if candidate.trigger_kind == KeyframeTriggerKind.TARGET_RESOLUTION_PROBE:
            return HumanActionEvidenceRole.TARGET_EVIDENCE
        return HumanActionEvidenceRole.AFTER_KEYFRAME

    def keyframes_for_event(self, event_id: str) -> tuple[ContextKeyframe, ...]:
        """Return keyframes linked to an event.

        Args:
            event_id: Context event id to inspect.

        Returns:
            Keyframes linked to that event.
        """

        return self.repository.list_keyframes_for_event(event_id)

    def _default_anchor_binding(self) -> ActiveCaptureBinding:
        return ActiveCaptureBinding(
            session_id=ActiveCaptureBinding.AUTO_SESSION_ID,
            role=KeyframeRole.ANCHOR,
            trigger_kind=KeyframeTriggerKind.MANUAL_SCREENSHOT,
            keep_reason=KeyframeKeepReason.USER_ANCHOR,
        )

    def _session_for_binding(
        self,
        *,
        binding: ActiveCaptureBinding,
        event: ContextEvent,
        attempt: CaptureAttemptRequest,
    ) -> ActiveCaptureSession | None:
        if not binding.is_auto_session:
            session = self._require_session(binding.session_id)
            if not self._binding_matches_attempt(session=session, attempt=attempt):
                logger.warning(
                    "active capture binding rejected for session ownership mismatch",
                    extra={
                        "session_id": session.session_id,
                        "event_id": event.event_id,
                        "session_actor_id": session.actor.actor_id if session.actor is not None else None,
                        "attempt_actor_id": attempt.actor.actor_id,
                        "session_workspace_id": session.workspace_id,
                        "attempt_workspace_id": attempt.workspace.workspace_id,
                    },
                )
                _record_bound_candidate_drop(
                    trigger_scheduler=self.trigger_scheduler,
                    repository=self.repository,
                    ids=self.ids,
                    clock=self.clock,
                    policy_version=self.config.policy_version,
                    session=session,
                    binding=binding,
                    event=event,
                    reason=KeyframeDropReason.SCOPE_LOST,
                    diagnostic="capture attempt did not match active capture scope or ownership",
                )
                return None
            return session
        existing = self.repository.get_bundle_for_event(event.event_id)
        if existing is not None:
            return self._require_session(existing.session_id)
        now = self.clock.now()
        session = ActiveCaptureSession(
            session_id=self.ids.new("acs"),
            mode=ActiveCaptureMode.SCREENSHOT_KEYFRAMES,
            status=ActiveCaptureStatus.CREATED,
            actor=attempt.actor,
            workspace_id=attempt.workspace.workspace_id,
            primary_event_id=event.event_id,
            scope=None,
            started_at=event.trigger.occurred_at,
            ended_at=now,
            created_at=now,
            updated_at=now,
            policy_version=self.config.policy_version,
            metadata={"source": ActiveCaptureSessionSource.ORDINARY_SCREENSHOT_ANCHOR.value},
        )
        return self.repository.save_session(session)

    def _binding_matches_attempt(
        self,
        *,
        session: ActiveCaptureSession,
        attempt: CaptureAttemptRequest,
    ) -> bool:
        return self.access_checker(session, attempt) and self.scope_matcher.matches(session.scope, attempt)

    def _require_session(self, session_id: str) -> ActiveCaptureSession:
        session = self.repository.get_session(session_id)
        if session is None:
            raise ValueError(f"active capture session not found: {session_id}")
        return session

    def _evidence_links(
        self,
        *,
        keyframe: ContextKeyframe,
        evidence_records: tuple[EvidenceRecord, ...],
    ) -> tuple[KeyframeEvidenceLink, ...]:
        now = self.clock.now()
        links: list[KeyframeEvidenceLink] = []
        for record in evidence_records:
            links.append(
                KeyframeEvidenceLink(
                    link_id=self.ids.new("kfl"),
                    keyframe_id=keyframe.keyframe_id,
                    event_id=keyframe.event_id,
                    evidence_id=record.evidence_id,
                    artifact_id=record.artifact_id,
                    role=evidence_link_role(record),
                    provider_key=record.provenance.provider_key,
                    created_at=now,
                )
            )
        return tuple(links)


def _record_bound_candidate_drop(
    *,
    trigger_scheduler: KeyframeTriggerScheduler,
    repository: ActiveCaptureRepository,
    ids: IdFactory,
    clock: Clock,
    policy_version: str,
    session: ActiveCaptureSession,
    binding: ActiveCaptureBinding,
    event: ContextEvent,
    reason: KeyframeDropReason,
    diagnostic: str,
) -> None:
    if not isinstance(binding.candidate_id, str):
        return
    trigger_scheduler.mark_dropped(
        candidate_id=binding.candidate_id,
        reason=reason,
        event_id=event.event_id,
        diagnostic=diagnostic,
    )
    repository.save_capture_decision(
        KeyframeCaptureDecision(
            decision_id=ids.new("kfd"),
            session_id=session.session_id,
            event_id=event.event_id,
            candidate_id=binding.candidate_id,
            role=binding.role,
            trigger_kind=binding.trigger_kind,
            kept=False,
            drop_reason=reason,
            policy_version=policy_version,
            metrics={"diagnostic": diagnostic},
            decided_at=clock.now(),
        )
    )


def _terminal_bound_candidate_decision(
    *,
    repository: ActiveCaptureRepository,
    ids: IdFactory,
    clock: Clock,
    session: ActiveCaptureSession,
    binding: ActiveCaptureBinding,
    event: ContextEvent,
    policy_version: str,
) -> KeyframeCaptureDecision | None:
    if not isinstance(binding.candidate_id, str):
        return None
    candidate = repository.get_trigger_candidate(binding.candidate_id)
    reason: KeyframeDropReason | None = None
    diagnostic: str | None = None
    if candidate is None:
        reason = KeyframeDropReason.INVALID_EVIDENCE
        diagnostic = "bound trigger candidate was not found"
    elif candidate.session_id != session.session_id:
        reason = KeyframeDropReason.INVALID_EVIDENCE
        diagnostic = "bound trigger candidate belongs to another session"
    elif candidate.status != KeyframeTriggerCandidateStatus.ACCEPTED:
        reason = candidate.drop_reason or KeyframeDropReason.INVALID_EVIDENCE
        diagnostic = f"bound trigger candidate is terminal: {candidate.status.value}"
    if reason is None:
        return None
    return KeyframeCaptureDecision(
        decision_id=ids.new("kfd"),
        session_id=session.session_id,
        event_id=event.event_id,
        candidate_id=binding.candidate_id,
        role=binding.role,
        trigger_kind=binding.trigger_kind,
        kept=False,
        drop_reason=reason,
        policy_version=policy_version,
        metrics={"diagnostic": diagnostic or "bound trigger candidate rejected"},
        decided_at=clock.now(),
    )


def _keyframe_metadata(
    *,
    binding: ActiveCaptureBinding,
    attempt: CaptureAttemptRequest,
) -> dict[str, JsonScalar]:
    metadata = dict(binding.metadata)
    if attempt.native_timing_receipt is not None:
        metadata["native_timing_authority"] = attempt.native_timing_receipt.authority.value
        metadata["native_timing_source_clock"] = attempt.native_timing_receipt.source_clock.value
    return metadata


def _mark_policy_dropped_candidate(
    *,
    trigger_scheduler: KeyframeTriggerScheduler,
    binding: ActiveCaptureBinding,
    decision: KeyframeCaptureDecision,
    event: ContextEvent,
) -> None:
    if not isinstance(binding.candidate_id, str) or decision.drop_reason is None:
        return
    trigger_scheduler.mark_dropped(
        candidate_id=binding.candidate_id,
        reason=decision.drop_reason,
        event_id=event.event_id,
        diagnostic="keyframe policy dropped committed capture",
    )


def _session_after_keyframe(
    *,
    session: ActiveCaptureSession,
    event: ContextEvent,
    binding: ActiveCaptureBinding,
    clock: Clock,
) -> ActiveCaptureSession:
    now = clock.now()
    update: dict[str, object] = {"updated_at": now}
    if session.primary_event_id is None and (
        session.mode == ActiveCaptureMode.SCREENSHOT_KEYFRAMES
        or (
            session.mode == ActiveCaptureMode.RECORDING_SESSION
            and binding.role == KeyframeRole.START
            and binding.trigger_kind == KeyframeTriggerKind.RECORDING_START
        )
    ):
        update["primary_event_id"] = event.event_id
    if session.mode == ActiveCaptureMode.SCREENSHOT_KEYFRAMES:
        update["status"] = ActiveCaptureStatus.COMPLETED
        update["ended_at"] = now
    return session.model_copy(update=update)


def _keyframe_quality_report(
    records: tuple[EvidenceRecord, ...],
    screenshot_evidence: EvidenceRecord | None,
    system_appshot_evidence: EvidenceRecord | None,
    *,
    binding: ActiveCaptureBinding,
) -> KeyframeQualityReport:
    text_chars = 0
    for record in records:
        if record.kind in {
            EvidenceKind.SELECTION_TEXT,
            EvidenceKind.CANONICAL_TEXT,
            EvidenceKind.CLEAN_PAGE_TEXT,
            EvidenceKind.VISUAL_OCR_TEXT,
        }:
            text_chars += _safe_text_length(record)
    metrics = {
        key: value
        for key, value in binding.metadata.items()
        if key.startswith("settle_")
        and key
        in {
            "settle_live_polling_state",
            "settle_decision_status",
            "settle_stop_reason",
            "settle_sample_count",
            "settle_stable_sample_count",
            "settle_needs_review",
        }
    }
    diagnostics: tuple[str, ...] = ()
    if metrics.get("settle_stop_reason") is not None:
        diagnostics = (f"settle:{metrics['settle_stop_reason']}",)
    if text_chars <= 0:
        diagnostics = (*diagnostics, "no_text_evidence_at_keyframe_commit")
    confidence = 1.0
    if screenshot_evidence is None:
        confidence = 0.35
    elif text_chars <= 0:
        confidence = 0.65
    return KeyframeQualityReport(
        confidence=confidence,
        text_chars=text_chars,
        screenshot_available=screenshot_evidence is not None,
        system_appshot_available=system_appshot_evidence is not None,
        diagnostics=diagnostics,
        metrics=metrics,
    )


def _safe_text_length(record: EvidenceRecord) -> int:
    for key in ("text_chars", "text_length", "char_count"):
        value = record.metadata.get(key)
        if isinstance(value, int | float) and value > 0:
            return int(value)
    return 0
