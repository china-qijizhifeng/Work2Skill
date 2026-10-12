from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient

from packages.contracts import (
    ActionCoordinates,
    ActionPoint,
    ActiveCaptureMode,
    CoordinateSpace,
    KeyframeDropReason,
    KeyframeRole,
    KeyframeTriggerCandidateStatus,
    KeyframeTriggerKind,
    PointerButton,
    ProducerInputEventKind,
    RecordingControlKind,
    SettleSampleStatus,
    SettleStopReason,
    VisualDiffSummary,
    VisualProbeMode,
)
from packages.shared.config import WorkRecorderSettings
from services.context_daemon.app import DaemonAppFactory
from services.context_daemon.container import DaemonContainer

INSTALL_SECRET_HEADER = {"x-workrecorder-install-secret": "test-install-secret"}
NATIVE_CAPTURE_SECRET_HEADER = {"x-workrecorder-native-capture-secret": "test-native-secret"}


def test_producer_click_returns_result_without_fake_before_capture(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    )
    session_id = create.json()["data"]["session"]["session_id"]

    response = client.post(
        f"/v1/active-captures/{session_id}/producer-events",
        headers=native_headers,
        json={
            "event_kind": ProducerInputEventKind.POINTER_CLICK.value,
            "producer_kind": "macos_capture",
            "occurred_at_monotonic_ms": 3_000,
            "pointer": {
                "button": PointerButton.LEFT.value,
                "click_count": 1,
                "coordinates": _action_coordinates().model_dump(mode="json"),
            },
        },
    )

    assert response.status_code == 200
    result = response.json()["data"]["results"][0]
    trigger_kinds = {item["candidate"]["trigger_kind"] for item in result["triggers"]}
    assert KeyframeTriggerKind.ACTION_BEFORE.value not in trigger_kinds
    assert KeyframeTriggerKind.CLICK_SETTLE.value in trigger_kinds
    assert result["trigger"]["candidate"]["trigger_kind"] == KeyframeTriggerKind.CLICK_SETTLE.value
    assert result["trigger"]["capture_instruction"] is None
    candidate_id = result["trigger"]["candidate"]["candidate_id"]
    candidate = next(
        item
        for item in _container(client).repositories.active_capture.list_trigger_candidates_for_session(session_id)
        if item.candidate_id == candidate_id
    )
    assert candidate.metadata["settle_live_polling_state"] == "pending"

    early_poll = client.post(
        f"/v1/active-captures/{session_id}/capture-instructions/pending",
        headers=native_headers,
        json={"now_monotonic_ms": 3_100, "limit": 4},
    )
    assert early_poll.status_code == 200
    assert early_poll.json()["data"]["instructions"] == []
    assert early_poll.json()["data"]["probe_required_candidate_count"] == 0

    ready_poll = client.post(
        f"/v1/active-captures/{session_id}/capture-instructions/pending",
        headers=native_headers,
        json={"now_monotonic_ms": 3_250, "limit": 4},
    )
    assert ready_poll.status_code == 200
    ready_data = ready_poll.json()["data"]
    assert ready_data["observed_candidate_count"] == 1
    assert ready_data["ready_candidate_count"] == 1
    assert ready_data["probe_required_candidate_count"] == 1
    assert ready_data["instructions"][0]["candidate_id"] == candidate_id
    assert ready_data["instructions"][0]["execute_after_monotonic_ms"] == 3_250

    settled = _container(client).repositories.active_capture.get_trigger_candidate(candidate_id)
    assert settled is not None
    assert settled.metadata["settle_live_polling_state"] == "capturing"
    assert settled.metadata["settle_capture_claim_id"]
    assert settled.metadata["settle_needs_review"] is True
    assert ready_data["instructions"][0]["binding"]["metadata"]["settle_decision_status"] == "ready_to_capture"
    assert ready_data["instructions"][0]["binding"]["metadata"]["settle_stop_reason"] == "provider_unavailable"
    stale_ready = candidate.model_copy(update={"metadata": candidate.metadata | {"settle_live_polling_state": "ready"}})
    not_overwritten = _container(client).repositories.active_capture.save_settle_candidate_decision(
        candidate=stale_ready,
        now_monotonic_ms=3_255,
    )
    assert not_overwritten.metadata["settle_live_polling_state"] == "capturing"
    duplicate_poll = client.post(
        f"/v1/active-captures/{session_id}/capture-instructions/pending",
        headers=native_headers,
        json={"now_monotonic_ms": 3_260, "limit": 4},
    )
    assert duplicate_poll.status_code == 200
    assert duplicate_poll.json()["data"]["instructions"] == []
    expired_poll = client.post(
        f"/v1/active-captures/{session_id}/capture-instructions/pending",
        headers=native_headers,
        json={"now_monotonic_ms": 33_251, "limit": 4},
    )
    assert expired_poll.status_code == 200
    assert expired_poll.json()["data"]["instructions"] == []
    expired = _container(client).repositories.active_capture.get_trigger_candidate(candidate_id)
    assert expired is not None
    assert expired.status == KeyframeTriggerCandidateStatus.DROPPED
    assert expired.drop_reason == KeyframeDropReason.ADAPTIVE_TIMEOUT
    assert expired.metadata["settle_live_polling_state"] == "closed"
    audits = _container(client).repositories.active_capture.list_settle_audits_for_candidate(candidate_id)
    assert len(audits) >= 2
    assert audits[-1].sample is not None


def test_native_pre_action_click_returns_before_and_result_capture_instructions(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    )
    session_id = create.json()["data"]["session"]["session_id"]

    response = client.post(
        f"/v1/active-captures/{session_id}/producer-events",
        headers=native_headers,
        json={
            "event_kind": ProducerInputEventKind.POINTER_CLICK.value,
            "producer_kind": "macos_capture",
            "occurred_at_monotonic_ms": 3_000,
            "metadata": {"native_event_phase": "pre_action"},
            "pointer": {
                "button": PointerButton.LEFT.value,
                "click_count": 1,
                "coordinates": _action_coordinates().model_dump(mode="json"),
            },
        },
    )

    assert response.status_code == 200
    result = response.json()["data"]["results"][0]
    trigger_kinds = {item["candidate"]["trigger_kind"] for item in result["triggers"]}
    assert KeyframeTriggerKind.ACTION_BEFORE.value in trigger_kinds
    assert KeyframeTriggerKind.CLICK_SETTLE.value in trigger_kinds
    by_kind = {item["candidate"]["trigger_kind"]: item for item in result["triggers"]}
    assert by_kind[KeyframeTriggerKind.ACTION_BEFORE.value]["capture_instruction"] is not None
    assert by_kind[KeyframeTriggerKind.CLICK_SETTLE.value]["capture_instruction"] is None


def test_pending_capture_instruction_waits_for_native_visual_probe_stability(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    )
    session_id = create.json()["data"]["session"]["session_id"]
    response = client.post(
        f"/v1/active-captures/{session_id}/producer-events",
        headers=native_headers,
        json={
            "event_kind": ProducerInputEventKind.POINTER_CLICK.value,
            "producer_kind": "macos_capture",
            "occurred_at_monotonic_ms": 3_000,
            "pointer": {
                "button": PointerButton.LEFT.value,
                "click_count": 1,
                "coordinates": _action_coordinates().model_dump(mode="json"),
            },
        },
    )
    assert response.status_code == 200
    candidate_id = response.json()["data"]["results"][0]["trigger"]["candidate"]["candidate_id"]

    assert _poll_with_visual_probe(client, session_id, native_headers, fingerprint="phash-a", now=3_250) == []
    assert _poll_with_visual_probe(client, session_id, native_headers, fingerprint="phash-b", now=3_400) == []
    assert _poll_with_visual_probe(client, session_id, native_headers, fingerprint="phash-b", now=3_550) == []
    instructions = _poll_with_visual_probe(client, session_id, native_headers, fingerprint="phash-b", now=3_700)

    assert instructions[0]["candidate_id"] == candidate_id
    audits = _container(client).repositories.active_capture.list_settle_audits_for_candidate(candidate_id)
    statuses = [audit.sample.status for audit in audits if audit.sample is not None]
    assert statuses == [
        SettleSampleStatus.OBSERVED,
        SettleSampleStatus.CHANGED,
        SettleSampleStatus.STABLE,
        SettleSampleStatus.STABLE,
    ]


def test_pending_capture_instruction_requires_native_capture_secret(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    )
    session_id = create.json()["data"]["session"]["session_id"]

    response = client.post(
        f"/v1/active-captures/{session_id}/capture-instructions/pending",
        headers=headers | INSTALL_SECRET_HEADER,
        json={"now_monotonic_ms": 3_250, "limit": 4},
    )

    assert response.status_code == 403
    assert "test-native-secret" not in response.text


def test_pending_capture_instruction_rejects_unsafe_probe_without_audit_write(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    )
    session_id = create.json()["data"]["session"]["session_id"]
    click = client.post(
        f"/v1/active-captures/{session_id}/producer-events",
        headers=native_headers,
        json={
            "event_kind": ProducerInputEventKind.POINTER_CLICK.value,
            "producer_kind": "macos_capture",
            "occurred_at_monotonic_ms": 3_000,
            "pointer": {
                "button": PointerButton.LEFT.value,
                "click_count": 1,
                "coordinates": _action_coordinates().model_dump(mode="json"),
            },
        },
    )
    candidate_id = click.json()["data"]["results"][0]["trigger"]["candidate"]["candidate_id"]

    response = client.post(
        f"/v1/active-captures/{session_id}/capture-instructions/pending",
        headers=native_headers,
        json={
            "now_monotonic_ms": 3_250,
            "limit": 4,
            "probe_snapshot": {
                "sample_id": "kfs_unsafe",
                "sampled_at_monotonic_ms": 3_250,
                "visual": {
                    "mode": VisualProbeMode.HYBRID.value,
                    "status": SettleSampleStatus.OBSERVED.value,
                    "sample_fingerprint": "https://example.com/token=SHOULD_NOT_LEAK_SECRET",
                },
                "diagnostics": ("selector #password SHOULD_NOT_LEAK_SECRET",),
            },
        },
    )

    assert response.status_code == 422
    assert "SHOULD_NOT_LEAK_SECRET" not in response.text
    assert _container(client).repositories.active_capture.list_settle_audits_for_candidate(candidate_id) == ()


def test_pending_capture_instruction_respects_visual_probe_feature_flag(settings: WorkRecorderSettings) -> None:
    local_settings = settings.model_copy(update={"active_capture_settle_visual_diff_enabled": False})
    local_client = TestClient(DaemonAppFactory(local_settings).create())
    token_response = local_client.post(
        "/v1/auth/tokens",
        headers=INSTALL_SECRET_HEADER,
        json={"actor_id": "test-cli", "display_name": "Test CLI"},
    )
    headers = {"authorization": f"Bearer {token_response.json()['data']['access_token']}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = local_client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    )
    session_id = create.json()["data"]["session"]["session_id"]
    click = local_client.post(
        f"/v1/active-captures/{session_id}/producer-events",
        headers=native_headers,
        json={
            "event_kind": ProducerInputEventKind.POINTER_CLICK.value,
            "producer_kind": "macos_capture",
            "occurred_at_monotonic_ms": 3_000,
            "pointer": {
                "button": PointerButton.LEFT.value,
                "click_count": 1,
                "coordinates": _action_coordinates().model_dump(mode="json"),
            },
        },
    )
    candidate_id = click.json()["data"]["results"][0]["trigger"]["candidate"]["candidate_id"]

    instructions = _poll_with_visual_probe(
        local_client,
        session_id,
        native_headers,
        fingerprint="phash-feature-flag",
        now=3_250,
    )

    assert instructions[0]["candidate_id"] == candidate_id
    audits = _container(local_client).repositories.active_capture.list_settle_audits_for_candidate(candidate_id)
    assert audits[-1].sample is not None
    assert audits[-1].sample.visual is None
    assert audits[-1].stop_reason == SettleStopReason.PROVIDER_UNAVAILABLE


def test_pause_resume_controls_create_required_boundary_triggers(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    )
    session_id = create.json()["data"]["session"]["session_id"]

    pause = client.post(
        f"/v1/active-captures/{session_id}/controls",
        headers=native_headers,
        json={
            "kind": RecordingControlKind.PAUSE.value,
            "source": "native_client",
            "occurred_at_monotonic_ms": 5_000,
        },
    )
    resume = client.post(
        f"/v1/active-captures/{session_id}/controls",
        headers=native_headers,
        json={
            "kind": RecordingControlKind.RESUME.value,
            "source": "native_client",
            "occurred_at_monotonic_ms": 6_000,
        },
    )
    triggers = _container(client).repositories.active_capture.list_trigger_candidates_for_session(session_id)

    assert pause.status_code == 200
    assert resume.status_code == 200
    assert pause.json()["data"]["control_trigger"]["capture_instruction"]["trigger_kind"] == (
        KeyframeTriggerKind.PAUSE_BOUNDARY.value
    )
    assert resume.json()["data"]["control_trigger"]["capture_instruction"]["trigger_kind"] == (
        KeyframeTriggerKind.RESUME_BOUNDARY.value
    )
    boundary = {
        (item.trigger_kind, item.role, item.priority.value)
        for item in triggers
        if item.trigger_kind in {KeyframeTriggerKind.PAUSE_BOUNDARY, KeyframeTriggerKind.RESUME_BOUNDARY}
    }
    assert (
        KeyframeTriggerKind.PAUSE_BOUNDARY,
        KeyframeRole.PAUSE_BOUNDARY,
        "required",
    ) in boundary
    assert (
        KeyframeTriggerKind.RESUME_BOUNDARY,
        KeyframeRole.RESUME_BOUNDARY,
        "required",
    ) in boundary


def test_stop_control_does_not_emit_unconsumed_final_trigger(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    )
    session_id = create.json()["data"]["session"]["session_id"]

    stop = client.post(
        f"/v1/active-captures/{session_id}/controls",
        headers=native_headers,
        json={
            "kind": RecordingControlKind.STOP.value,
            "source": "native_client",
            "occurred_at_monotonic_ms": 7_000,
        },
    )

    triggers = _container(client).repositories.active_capture.list_trigger_candidates_for_session(session_id)
    assert stop.status_code == 200
    assert stop.json()["data"].get("control_trigger") is None
    assert all(item.trigger_kind != KeyframeTriggerKind.RECORDING_STOP for item in triggers)


def _action_coordinates() -> ActionCoordinates:
    return ActionCoordinates(
        screen_abs=ActionPoint(x=120, y=80, coordinate_space=CoordinateSpace.MACOS_GLOBAL),
        scope_rel=ActionPoint(x=20, y=30, coordinate_space=CoordinateSpace.WINDOW_PX),
    )


def _poll_with_visual_probe(
    client: TestClient,
    session_id: str,
    headers: dict[str, str],
    *,
    fingerprint: str,
    now: int,
) -> list[dict[str, object]]:
    response = client.post(
        f"/v1/active-captures/{session_id}/capture-instructions/pending",
        headers=headers,
        json={
            "now_monotonic_ms": now,
            "limit": 4,
            "probe_snapshot": {
                "sample_id": f"kfs_{fingerprint}_{now}",
                "sampled_at_monotonic_ms": now,
                "visual": VisualDiffSummary(
                    mode=VisualProbeMode.HYBRID,
                    status=SettleSampleStatus.OBSERVED,
                    sample_fingerprint=fingerprint,
                ).model_dump(mode="json"),
            },
        },
    )
    assert response.status_code == 200
    return list(response.json()["data"]["instructions"])


def _container(client: TestClient) -> DaemonContainer:
    app = cast(Any, client.app)
    return cast(DaemonContainer, app.state.container)
