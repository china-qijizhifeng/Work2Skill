from __future__ import annotations

from datetime import UTC, datetime

from packages.contracts import (
    AccessScope,
    ActorRef,
    ArtifactIngestState,
    ArtifactRole,
    ArtifactType,
    BoundingBox,
    CaptureStrategy,
    ContextEvent,
    CoordinateSpace,
    DisclosureClass,
    DisclosureDecision,
    DisclosureDecisionStatus,
    DisclosureField,
    DisclosureProfile,
    DisclosureRule,
    DisclosureView,
    DisplayGeometry,
    EventCaptureEnvelope,
    EventInspectView,
    EventStatus,
    EventType,
    EvidenceKind,
    EvidenceLocator,
    EvidencePayloadRef,
    EvidencePhase,
    EvidenceProvenance,
    EvidenceRecord,
    EvidenceSensitivity,
    EvidenceTrustState,
    ExtractorRef,
    IndexManifest,
    PolicySnapshot,
    ProviderCapability,
    ProviderDecision,
    ProviderDecisionStatus,
    ProviderKind,
    ProviderManifest,
    ProviderMode,
    ProviderRoutePlan,
    RedactionState,
    SearchMatchReason,
    SearchResultCard,
    SearchResultSource,
    SelectionGeometry,
    SelectionTextBlock,
    SelectionTextProjection,
    SelectionTextSourceMethod,
    SourceBinding,
    SourceRef,
    SourceType,
    TriggerEnvelope,
    TriggerType,
)


def test_event_capture_envelope_round_trip_is_auditable():
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    actor = ActorRef(actor_id="test")
    selection = BoundingBox(x=-10, y=20, width=300, height=180, coordinate_space=CoordinateSpace.MACOS_GLOBAL)
    trigger = TriggerEnvelope(
        trigger_id="trg_protocol",
        trigger_type=TriggerType.MANUAL_OS_REGION_HOTKEY,
        capture_strategy=CaptureStrategy.OS_REGION,
        actor=actor,
        occurred_at=now,
        selection=selection,
    )
    source_binding = SourceBinding(
        binding_id="src_protocol",
        source_ref=SourceRef(
            source_type=SourceType.WEB,
            title="ACME",
            url="https://example.test/acme",
            origin="https://example.test",
        ),
        confidence=0.91,
        resolved_at=now,
        provider_key="web.browser_extension",
        provider_context_id="ctx_protocol",
    )
    event = ContextEvent(
        event_id="evt_protocol",
        event_type=EventType.WEBPAGE_SELECTION_CAPTURED,
        trigger=trigger,
        source_binding=source_binding,
        status=EventStatus.AGENT_READY,
        intent_text=None,
        created_at=now,
        updated_at=now,
    )
    evidence = EvidenceRecord(
        evidence_id="evd_protocol",
        event_id=event.event_id,
        capture_run_id="run_protocol",
        phase=EvidencePhase.CAPTURED,
        kind=EvidenceKind.VISIBLE_TEXT,
        artifact_id="art_protocol",
        artifact_type=ArtifactType.BROWSER_VISIBLE_TEXT,
        role=ArtifactRole.SOURCE_TEXT,
        payload=EvidencePayloadRef(
            content_type="text/plain; charset=utf-8",
            storage_uri="local-artifact://blobs/aa/example.txt",
            byte_size=12,
            sha256="a" * 64,
            payload_schema="visible_text",
        ),
        locator=EvidenceLocator(source_uri="https://example.test/acme", source_type=SourceType.WEB),
        observed_at=now,
        captured_at=now,
        ingested_at=now,
        provenance=EvidenceProvenance(
            provider_key="web.browser_extension",
            provider_kind=ProviderKind.SOURCE,
            provider_session_id="ctx_protocol",
            command_id="cmd_protocol",
            source_binding_id=source_binding.binding_id,
            extractor=ExtractorRef(name="web.browser_extension", version="p3_test"),
        ),
        sensitivity=EvidenceSensitivity.INTERNAL,
        trust_state=EvidenceTrustState.DLP_PASSED,
        ingest_state=ArtifactIngestState.DLP_PASSED,
        redaction_state=RedactionState.REDACTED,
        allowed_scopes=(AccessScope.READ_METADATA, AccessScope.READ_TEXT),
        indexable=False,
    )
    envelope = EventCaptureEnvelope(
        capture_run_id="run_protocol",
        event_id=event.event_id,
        event_type=EventType.WEBPAGE_SELECTION_CAPTURED,
        trigger=trigger,
        selection_geometry=SelectionGeometry(
            selected_region=selection,
            display=DisplayGeometry(display_id="display", frame=selection, scale_factor=2.0),
        ),
        route_plan=ProviderRoutePlan(
            trigger_id=trigger.trigger_id,
            selected_provider_key="web.browser_extension",
            selected_surface_id="surface_0",
            decisions=(
                ProviderDecision(
                    provider_key="web.browser_extension",
                    status=ProviderDecisionStatus.SELECTED,
                    confidence=0.9,
                    surface_id="surface_0",
                ),
            ),
        ),
        evidence_records=(evidence,),
        artifact_ids=("art_protocol",),
        index_manifest=IndexManifest(event_id=event.event_id),
        policy_snapshot=PolicySnapshot(create_event_decision_id="pol_protocol"),
        context_event=event,
        created_at=now,
        updated_at=now,
    )

    round_tripped = EventCaptureEnvelope.model_validate_json(envelope.model_dump_json())

    assert round_tripped.evidence_records[0].provenance.provider_key == "web.browser_extension"
    assert round_tripped.evidence_records[0].locator.source_uri == "https://example.test/acme"
    assert round_tripped.policy_snapshot.create_event_decision_id == "pol_protocol"


def test_provider_manifest_declares_provider_contract():
    manifest = ProviderManifest(
        provider_key="web.browser_extension",
        display_name="Browser Extension",
        provider_kind=ProviderKind.SOURCE,
        modes=(ProviderMode.CAPTURE,),
        source_types=(SourceType.WEB,),
        capabilities=(ProviderCapability.COLLECT_FULL_DOM,),
        evidence_kinds=(EvidenceKind.FULL_DOM,),
    )

    assert manifest.provider_key == "web.browser_extension"
    assert manifest.evidence_kinds == (EvidenceKind.FULL_DOM,)


def test_selection_text_and_search_card_contracts_round_trip():
    now = datetime(2026, 5, 16, 12, 30, tzinfo=UTC)
    selection = BoundingBox(x=120, y=140, width=520, height=280, coordinate_space=CoordinateSpace.MACOS_GLOBAL)
    projection = SelectionTextProjection(
        text="Account\nStatus\nACME\nProcurement delayed",
        source_method=SelectionTextSourceMethod.A11Y_BLOCKS,
        selection=selection,
        blocks=(
            SelectionTextBlock(
                text="Procurement delayed",
                source_block_id="a11y_block_4",
                role="AXCell",
                frame=BoundingBox(x=250, y=180, width=170, height=20, coordinate_space=CoordinateSpace.MACOS_GLOBAL),
                selection_overlap_ratio=0.01,
                element_overlap_ratio=1.0,
                confidence=0.91,
            ),
        ),
        confidence=0.91,
        block_count=4,
        source_block_count=7,
    )
    card = SearchResultCard(
        event_id="evt_selection_text",
        event_type=EventType.WEBPAGE_SELECTION_CAPTURED,
        captured_at=now,
        source=SearchResultSource(
            app_name="Google Chrome",
            title="ACME Pricing Dashboard",
            origin="https://example.test",
            sanitized_url="https://example.test/acme",
        ),
        selection_bbox=selection,
        user_note="用于 ACME 续约 brief",
        selection_text_snippet="Procurement delayed",
        preview_evidence_id="evd_selection_text",
        preview_confidence=0.91,
        match_reason=SearchMatchReason.SELECTION_TEXT,
        hidden_artifacts=("screenshot", "browser_full_dom", "a11y_tree"),
    )

    assert (
        SelectionTextProjection.model_validate_json(projection.model_dump_json()).source_method
        == SelectionTextSourceMethod.A11Y_BLOCKS
    )
    assert SearchResultCard.model_validate_json(card.model_dump_json()).preview_evidence_id == "evd_selection_text"
    assert SearchResultCard.model_validate_json(card.model_dump_json()).user_note == "用于 ACME 续约 brief"


def test_disclosure_profile_and_event_inspect_contracts_round_trip():
    now = datetime(2026, 5, 16, 13, 0, tzinfo=UTC)
    profile = DisclosureProfile(
        profile_key="app.chrome.web_capture",
        display_name="Chrome Web Capture Disclosure",
        provider_keys=("web.browser_extension",),
        app_names=("Google Chrome",),
        source_types=(SourceType.WEB,),
        rules=(
            DisclosureRule(
                rule_id="chrome.summary.selection",
                view=DisclosureView.SUMMARY_CARD,
                disclosure_class=DisclosureClass.SELECTION_BOUND_TEXT,
                artifact_types=(ArtifactType.A11Y_SELECTION_TEXT,),
                artifact_roles=(ArtifactRole.SELECTION_TEXT,),
                evidence_kinds=(EvidenceKind.SELECTION_TEXT,),
                allowed_scopes=(AccessScope.READ_TEXT,),
                max_chars=4000,
            ),
        ),
    )
    decision = DisclosureDecision(
        decision_id="dsc_contract",
        status=DisclosureDecisionStatus.ALLOWED,
        view=DisclosureView.EVENT_INSPECT,
        profile_key=profile.profile_key,
        resource_type="event",
        resource_id="evt_contract",
        delivered_fields=(
            DisclosureField.CANONICAL_TEXT,
            DisclosureField.CLEAN_PAGE_TEXT,
            DisclosureField.RAW_ARTIFACT_REFS,
        ),
    )
    inspect = EventInspectView(
        event_id="evt_contract",
        captured_at=now,
        source=SearchResultSource(
            app_name="Google Chrome",
            title="ACME Pricing Dashboard",
            origin="https://example.test",
            sanitized_url="https://example.test/acme",
        ),
        canonical_text="## Selection\n\nBudget variance",
        clean_page_text="# ACME Pricing Dashboard\n\nBudget variance",
        disclosure_decision=decision,
    )

    assert DisclosureProfile.model_validate_json(profile.model_dump_json()).rules[0].view == DisclosureView.SUMMARY_CARD
    assert (
        EventInspectView.model_validate_json(inspect.model_dump_json()).disclosure_decision.profile_key
        == profile.profile_key
    )
