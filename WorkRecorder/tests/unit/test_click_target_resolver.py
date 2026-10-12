from __future__ import annotations

from datetime import UTC, datetime

import pytest

from packages.active_capture.click_targets.adapters.candidate_providers import (
    A11yTargetCandidateProvider,
    CoordinateFallbackProvider,
    EvidencePayloadReader,
)
from packages.active_capture.click_targets.application import ClickTargetResolutionService
from packages.active_capture.click_targets.domain.label_policy import ClickTargetLabelPolicy
from packages.contracts import (
    A11yCoverageReport,
    A11yNode,
    A11yPermissionState,
    A11ySnapshot,
    ActionCoordinates,
    ActionPoint,
    ActiveCaptureMode,
    ActiveCaptureSession,
    ActiveCaptureStatus,
    ArtifactIngestState,
    ArtifactRole,
    ArtifactType,
    BoundingBox,
    ClickTargetCandidate,
    ClickTargetConfidenceBand,
    ClickTargetPublicView,
    ClickTargetResolution,
    ClickTargetResolutionStatus,
    ClickTargetResolverConfig,
    ClickTargetSemanticKind,
    ClickTargetSourceKind,
    ContextKeyframe,
    CoordinateSpace,
    EvidenceKind,
    EvidenceLocator,
    EvidencePayloadRef,
    EvidencePhase,
    EvidenceProvenance,
    EvidenceRecord,
    EvidenceSensitivity,
    EvidenceTrustState,
    ExtractorRef,
    HumanActionEvent,
    HumanActionKind,
    HumanDemonstrationTrace,
    HumanDemonstrationTraceStatus,
    KeyframeKeepReason,
    KeyframeQualityReport,
    KeyframeRole,
    KeyframeTriggerKind,
    ProviderKind,
    RecordingCardSummary,
    RecordingStoryboardProjection,
    RedactionState,
    SourceType,
    StoryboardActionItem,
    VideoArtifactState,
)
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from packages.storage.container import RepositoryContainer
from packages.storage.database import SQLiteDatabase
from services.context_daemon.routers.active_capture_access import filter_storyboard_for_visible_keyframes

NOW = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


class FakeTargetRepository:
    def __init__(self, action: HumanActionEvent) -> None:
        self.action = action
        self.saved = []

    def get_human_action(self, action_id: str) -> HumanActionEvent | None:
        return self.action if action_id == self.action.action_id else None

    def save_click_target_resolution_graph(self, *, resolution, candidates):
        self.saved.append((resolution, candidates))
        return resolution

    def list_click_target_resolutions_for_actions(self, action_ids):
        return tuple(resolution for resolution, _ in self.saved if resolution.action_id in action_ids)


class _CrashingProvider:
    source_kind = ClickTargetSourceKind.A11Y_SNAPSHOT

    def candidates_for(
        self,
        *,
        action: HumanActionEvent,
        keyframe: ContextKeyframe,
        evidence_records: tuple[EvidenceRecord, ...],
        resolution_id: str,
        now_id_prefix: str,
        created_at: datetime,
    ) -> tuple[ClickTargetCandidate, ...]:
        del action, keyframe, evidence_records, resolution_id, now_id_prefix, created_at
        raise RuntimeError("provider crashed")


def test_click_target_public_view_rejects_sensitive_label() -> None:
    with pytest.raises(ValueError):
        ClickTargetPublicView(
            display_label="SHOULD_NOT_LEAK_TOKEN",
            semantic_kind=ClickTargetSemanticKind.BUTTON,
        )


def test_a11y_provider_resolves_button_without_raw_locator() -> None:
    label_policy = ClickTargetLabelPolicy(max_chars=80)
    provider = A11yTargetCandidateProvider(
        label_policy=label_policy,
        payload_reader=EvidencePayloadReader(),
        confidence_bands={"high": 0.78, "review": 0.55},
    )
    action = _click_action()
    keyframe = _keyframe()
    candidates = provider.candidates_for(
        action=action,
        keyframe=keyframe,
        evidence_records=(_a11y_evidence(label="保存"),),
        resolution_id="ctr_test",
        now_id_prefix="ctc_test",
        created_at=NOW,
    )

    assert candidates
    assert candidates[0].semantic_kind == ClickTargetSemanticKind.BUTTON
    assert candidates[0].safe_label is None
    assert candidates[0].locator_fingerprint
    dumped = candidates[0].model_dump_json()
    assert "AXButton" not in dumped
    assert "保存" not in dumped


def test_resolution_service_persists_safe_click_target() -> None:
    action = _click_action()
    repository = FakeTargetRepository(action)
    label_policy = ClickTargetLabelPolicy(max_chars=80)
    payload_reader = EvidencePayloadReader()
    config = ClickTargetResolverConfig()
    service = ClickTargetResolutionService(
        repository=repository,
        providers=(
            A11yTargetCandidateProvider(
                label_policy=label_policy,
                payload_reader=payload_reader,
                confidence_bands={"high": 0.78, "review": 0.55},
            ),
            CoordinateFallbackProvider(
                label_policy=label_policy,
                payload_reader=payload_reader,
                confidence_bands={"high": 0.78, "review": 0.55},
            ),
        ),
        ids=IdFactory(),
        clock=FixedClock(),
        config=config,
    )

    resolution = service.resolve_action_after_keyframe(
        action_id=action.action_id,
        keyframe=_keyframe(),
        evidence_records=(_a11y_evidence(label="保存"),),
    )

    assert resolution is not None
    assert resolution.display_label == "按钮"
    assert resolution.semantic_kind == ClickTargetSemanticKind.BUTTON
    assert resolution.source_kind == ClickTargetSourceKind.A11Y_SNAPSHOT
    assert resolution.needs_review is False
    assert repository.saved


def test_resolution_service_never_promotes_sensitive_label() -> None:
    action = _click_action()
    repository = FakeTargetRepository(action)
    label_policy = ClickTargetLabelPolicy(max_chars=80)
    payload_reader = EvidencePayloadReader()
    service = ClickTargetResolutionService(
        repository=repository,
        providers=(
            A11yTargetCandidateProvider(
                label_policy=label_policy,
                payload_reader=payload_reader,
                confidence_bands={"high": 0.78, "review": 0.55},
            ),
            CoordinateFallbackProvider(
                label_policy=label_policy,
                payload_reader=payload_reader,
                confidence_bands={"high": 0.78, "review": 0.55},
            ),
        ),
        ids=IdFactory(),
        clock=FixedClock(),
        config=ClickTargetResolverConfig(),
    )

    resolution = service.resolve_action_after_keyframe(
        action_id=action.action_id,
        keyframe=_keyframe(),
        evidence_records=(_a11y_evidence(label="SHOULD_NOT_LEAK_PASSWORD"),),
    )

    assert resolution is not None
    assert resolution.display_label == "按钮"
    assert "SHOULD_NOT_LEAK" not in resolution.model_dump_json()


def test_resolution_service_ignores_hidden_evidence_and_falls_back_to_coordinates() -> None:
    action = _click_action()
    repository = FakeTargetRepository(action)
    label_policy = ClickTargetLabelPolicy(max_chars=80)
    payload_reader = EvidencePayloadReader()
    service = ClickTargetResolutionService(
        repository=repository,
        providers=(
            A11yTargetCandidateProvider(
                label_policy=label_policy,
                payload_reader=payload_reader,
                confidence_bands={"high": 0.78, "review": 0.55},
            ),
            CoordinateFallbackProvider(
                label_policy=label_policy,
                payload_reader=payload_reader,
                confidence_bands={"high": 0.78, "review": 0.55},
            ),
        ),
        ids=IdFactory(),
        clock=FixedClock(),
        config=ClickTargetResolverConfig(),
    )
    hidden_evidence = _a11y_evidence(label="保存").model_copy(
        update={"trust_state": EvidenceTrustState.BLOCKED, "redaction_state": RedactionState.QUARANTINED}
    )

    resolution = service.resolve_action_after_keyframe(
        action_id=action.action_id,
        keyframe=_keyframe(),
        evidence_records=(hidden_evidence,),
    )

    assert resolution is not None
    assert resolution.source_kind == ClickTargetSourceKind.COORDINATE_FALLBACK
    assert resolution.display_label == "目标待确认"
    assert resolution.needs_review is True
    assert "保存" not in resolution.model_dump_json()


def test_resolution_service_persists_failed_state_when_provider_crashes() -> None:
    action = _click_action()
    repository = FakeTargetRepository(action)
    label_policy = ClickTargetLabelPolicy(max_chars=80)
    payload_reader = EvidencePayloadReader()
    service = ClickTargetResolutionService(
        repository=repository,
        providers=(
            _CrashingProvider(),
            CoordinateFallbackProvider(
                label_policy=label_policy,
                payload_reader=payload_reader,
                confidence_bands={"high": 0.78, "review": 0.55},
            ),
        ),
        ids=IdFactory(),
        clock=FixedClock(),
        config=ClickTargetResolverConfig(),
    )

    resolution = service.resolve_action_after_keyframe(
        action_id=action.action_id,
        keyframe=_keyframe(),
        evidence_records=(_a11y_evidence(label="保存"),),
    )

    assert resolution is not None
    assert resolution.status == ClickTargetResolutionStatus.FAILED
    assert repository.saved


def test_sqlite_repository_round_trips_target_resolution_graph() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    session = ActiveCaptureSession(
        session_id="acs_test",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=NOW,
        updated_at=NOW,
    )
    repositories.active_capture.save_session(session)
    trace = HumanDemonstrationTrace(
        trace_id="trace_test",
        session_id=session.session_id,
        status=HumanDemonstrationTraceStatus.ACTIVE,
        started_at=NOW,
    )
    action = repositories.active_capture.append_human_action_graph(
        action=_click_action(),
        links=(),
        observation=None,
        trace=trace,
    )
    resolution = ClickTargetResolution(
        resolution_id="ctr_test",
        action_id=action.action_id,
        session_id=session.session_id,
        status=ClickTargetResolutionStatus.RESOLVED,
        semantic_kind=ClickTargetSemanticKind.BUTTON,
        source_kind=ClickTargetSourceKind.A11Y_SNAPSHOT,
        display_label="保存",
        confidence=0.92,
        confidence_band=ClickTargetConfidenceBand.HIGH,
        candidate_ids=(),
        needs_review=False,
        input_fingerprint="fp_test",
        resolver_version="resolver_v1",
        policy_version="policy_v1",
        created_at=NOW,
        updated_at=NOW,
    )

    repositories.active_capture.save_click_target_resolution_graph(resolution=resolution, candidates=())
    loaded = repositories.active_capture.list_click_target_resolutions_for_actions((action.action_id,))

    assert len(loaded) == 1
    assert loaded[0].display_label == "保存"
    assert loaded[0].semantic_kind == ClickTargetSemanticKind.BUTTON


def test_storyboard_visibility_sanitizes_nested_click_target_refs() -> None:
    projection = RecordingStoryboardProjection(
        session_id="acs_test",
        card=RecordingCardSummary(
            session_id="acs_test",
            status=ActiveCaptureStatus.COMPLETED,
            action_count=1,
            video_state=VideoArtifactState.AVAILABLE,
        ),
        items=(
            StoryboardActionItem(
                item_id="sb_act_test",
                action_id="act_test",
                action_kind=HumanActionKind.CLICK,
                sequence_index=0,
                occurred_at=NOW,
                caption="点击「按钮」",
                evidence_keyframe_ids=("visible_kf",),
                target=ClickTargetPublicView(
                    resolution_id="ctr_test",
                    status=ClickTargetResolutionStatus.RESOLVED,
                    display_label="按钮",
                    semantic_kind=ClickTargetSemanticKind.BUTTON,
                    confidence=0.92,
                    confidence_band=ClickTargetConfidenceBand.HIGH,
                    source_badges=(ClickTargetSourceKind.A11Y_SNAPSHOT,),
                    needs_review=False,
                    evidence_keyframe_ids=("hidden_kf",),
                    has_coordinates=True,
                ),
                target_label="按钮",
            ),
        ),
        generated_at=NOW,
    )

    sanitized = filter_storyboard_for_visible_keyframes(
        projection,
        session_has_keyframes=True,
        visible_keyframe_ids={"visible_kf"},
    )

    assert len(sanitized.items) == 1
    item = sanitized.items[0]
    assert isinstance(item, StoryboardActionItem)
    assert item.target is None
    assert item.target_label is None
    assert item.caption == "点击（目标待确认）"
    assert "按钮" not in item.model_dump_json()
    assert sanitized.card.action_count == 1


def test_storyboard_visibility_drops_actions_without_visible_supporting_keyframe() -> None:
    projection = RecordingStoryboardProjection(
        session_id="acs_test",
        card=RecordingCardSummary(
            session_id="acs_test",
            status=ActiveCaptureStatus.COMPLETED,
            action_count=1,
            video_state=VideoArtifactState.AVAILABLE,
        ),
        items=(
            StoryboardActionItem(
                item_id="sb_act_hidden",
                action_id="act_hidden",
                action_kind=HumanActionKind.CLICK,
                sequence_index=0,
                occurred_at=NOW,
                caption="点击（目标待确认）",
                evidence_keyframe_ids=("hidden_kf",),
            ),
        ),
        generated_at=NOW,
    )

    sanitized = filter_storyboard_for_visible_keyframes(
        projection,
        session_has_keyframes=True,
        visible_keyframe_ids=set(),
    )

    assert sanitized.items == ()
    assert sanitized.card.action_count == 0


def _click_action() -> HumanActionEvent:
    return HumanActionEvent(
        action_id="act_test",
        trace_id="trace_test",
        session_id="acs_test",
        sequence_index=0,
        kind=HumanActionKind.CLICK,
        occurred_at=NOW,
        coordinates=ActionCoordinates(screen_abs=ActionPoint(x=50, y=50, coordinate_space=CoordinateSpace.SCREEN_PX)),
    )


def _keyframe() -> ContextKeyframe:
    return ContextKeyframe(
        keyframe_id="kf_test",
        session_id="acs_test",
        event_id="evt_test",
        capture_run_id="cap_test",
        role=KeyframeRole.SETTLE,
        trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
        keep_reason=KeyframeKeepReason.POLICY_ACCEPTED,
        captured_at=NOW,
        sequence_index=1,
        quality=KeyframeQualityReport(confidence=1.0, screenshot_available=True),
        policy_version="active_capture_policy_v1",
    )


def _a11y_evidence(*, label: str) -> EvidenceRecord:
    snapshot = A11ySnapshot(
        permission_state=A11yPermissionState.GRANTED,
        selection=BoundingBox(x=0, y=0, width=200, height=200),
        root_nodes=(
            A11yNode(
                element_id="node_save",
                role="AXButton",
                name=label,
                frame=BoundingBox(x=20, y=20, width=90, height=44),
                confidence=0.9,
            ),
        ),
        coverage=A11yCoverageReport(
            selection=BoundingBox(x=0, y=0, width=200, height=200),
            permission_state=A11yPermissionState.GRANTED,
            node_count=1,
            text_block_count=1,
            covered_area_ratio=1.0,
            confidence=0.9,
        ),
    )
    return EvidenceRecord(
        evidence_id="ev_a11y",
        event_id="evt_test",
        capture_run_id="cap_test",
        phase=EvidencePhase.CAPTURED,
        kind=EvidenceKind.A11Y,
        artifact_id="art_a11y",
        artifact_type=ArtifactType.A11Y_TREE,
        role=ArtifactRole.UI_STRUCTURE,
        payload=EvidencePayloadRef(content_type="application/json", inline_content=snapshot.model_dump_json()),
        locator=EvidenceLocator(source_uri="local://a11y", source_type=SourceType.DESKTOP_WINDOW),
        observed_at=NOW,
        captured_at=NOW,
        ingested_at=NOW,
        provenance=EvidenceProvenance(
            provider_key="system.macos_a11y",
            provider_kind=ProviderKind.SYSTEM_EVIDENCE,
            extractor=ExtractorRef(name="test", version="1"),
        ),
        sensitivity=EvidenceSensitivity.INTERNAL,
        trust_state=EvidenceTrustState.DLP_PASSED,
        ingest_state=ArtifactIngestState.DLP_PASSED,
        redaction_state=RedactionState.NONE,
    )
