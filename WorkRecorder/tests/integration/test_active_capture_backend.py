from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from packages.artifacts.vault import ArtifactVaultTransientError
from packages.contracts import (
    ActionCoordinates,
    ActionPoint,
    ActiveCaptureBinding,
    ActiveCaptureMode,
    ActorRef,
    ApiError,
    ArtifactType,
    AttachRecordingSegmentCommand,
    BoundingBox,
    CapturePostCommitDrainResult,
    CapturePostCommitTaskStatus,
    CaptureSaveRequest,
    CompleteActiveCaptureSessionCommand,
    CoordinateSpace,
    EventStatus,
    HotkeySemantic,
    HumanActionEvidenceRole,
    HumanActionKind,
    HumanActionOutcomeStatus,
    KeyboardEventKind,
    KeyboardInputClass,
    KeyCapturePolicy,
    KeyframeDropReason,
    KeyframeRole,
    KeyframeTriggerCandidateStatus,
    KeyframeTriggerKind,
    ModifierKey,
    NativeCaptureTimingAuthority,
    NativeCaptureTimingReceipt,
    NativeTimingClock,
    PointerButton,
    PointerInputPayload,
    ProducerDecisionReason,
    ProducerInputEventKind,
    RecordingControlKind,
    RecordingScope,
    RecordingScopeKind,
    RecordingSegmentState,
    RecordingTimingAnchor,
    RecordingVideoContentType,
    RecordingVideoMetadataKey,
    RecordProducerInputBatchCommand,
    RecordProducerInputEventCommand,
    StagedVideoArtifactRef,
    ScrollInputPayload,
    ScrollPhase,
    WindowHint,
)
from services.context_daemon.container import DaemonContainer

INSTALL_SECRET_HEADER = {"x-workrecorder-install-secret": "test-install-secret"}
NATIVE_CAPTURE_SECRET_HEADER = {"x-workrecorder-native-capture-secret": "test-native-secret"}


def test_capture_save_records_anchor_keyframe_without_changing_response(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    response = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}"},
        json=capture_save_request.model_dump(mode="json"),
    )
    payload = response.json()
    event_id = payload["data"]["event"]["event_id"]
    container = _container(client)

    keyframes = container.active_capture.keyframes_for_event(event_id)
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=verify_keyframes&inspect_views=keyframes,evidence_refs",
        headers={"authorization": f"Bearer {_token_with_scopes(client, ('read_metadata', 'read_text'))}"},
    ).json()

    assert response.status_code == 200
    assert payload["data"]["status"] == "accepted"
    assert len(keyframes) == 1
    assert keyframes[0].role == KeyframeRole.ANCHOR
    assert keyframes[0].trigger_kind == KeyframeTriggerKind.MANUAL_SCREENSHOT
    assert inspect["data"]["keyframes"][0]["keyframe_id"] == keyframes[0].keyframe_id
    assert inspect["data"]["keyframes"][0]["screenshot_artifact_id"]


def test_capture_save_default_response_does_not_expose_active_capture_sections(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    response = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}"},
        json=capture_save_request.model_dump(mode="json"),
    )
    data = response.json()["data"]

    assert response.status_code == 200
    assert data["status"] == "accepted"
    assert {"event", "artifacts", "workspace", "pending_enrichment", "route_plan"}.issubset(data)
    assert "keyframes" not in data
    assert "outbox" not in data
    assert "active_capture" not in data


def test_capture_save_enqueues_anchor_keyframe_without_running_hook_on_hot_path(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _container(client)
    real_drain = container.capture_post_commit_outbox.drain_due
    original_hook = container.active_capture.after_capture_committed
    hook_calls = 0

    def fail_if_called_on_hot_path(**_: object) -> None:
        nonlocal hook_calls
        hook_calls += 1
        raise RuntimeError("hot path must not call active capture hook")

    monkeypatch.setattr(container.active_capture, "after_capture_committed", fail_if_called_on_hot_path)
    monkeypatch.setattr(
        container.capture_post_commit_outbox,
        "drain_due_safe",
        lambda _event_id=None: CapturePostCommitDrainResult(),
    )

    response = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}"},
        json=capture_save_request.model_dump(mode="json"),
    )
    event_id = response.json()["data"]["event"]["event_id"]
    tasks = container.repositories.capture_post_commit_outbox.list_for_event(event_id)
    with container.repositories.database.transaction() as connection:
        task_row = connection.execute(
            "SELECT task_json FROM capture_post_commit_outbox WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    assert task_row is not None
    task_json = str(task_row["task_json"])

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "accepted"
    assert hook_calls == 0
    assert container.active_capture.keyframes_for_event(event_id) == ()
    assert len(tasks) == 1
    assert tasks[0].status == CapturePostCommitTaskStatus.PENDING
    assert tasks[0].ref.event_id == event_id
    assert '"active_capture":' not in task_json
    assert '"metadata":' not in task_json
    assert "evidence_records" not in task_json
    assert capture_save_request.staged_artifact.local_path not in task_json

    monkeypatch.setattr(container.active_capture, "after_capture_committed", original_hook)
    result = real_drain()
    completed = container.repositories.capture_post_commit_outbox.list_for_event(event_id)

    assert result.completed == 1
    assert container.active_capture.keyframes_for_event(event_id)
    assert completed[0].status == CapturePostCommitTaskStatus.COMPLETED


def test_capture_post_commit_outbox_retries_failed_hook_without_failing_capture(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _container(client)
    real_drain = container.capture_post_commit_outbox.drain_due
    monkeypatch.setattr(
        container.capture_post_commit_outbox,
        "drain_due_safe",
        lambda _event_id=None: CapturePostCommitDrainResult(),
    )
    container.capture_post_commit_outbox.config.retry_backoff_ms = 0

    response = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}"},
        json=capture_save_request.model_dump(mode="json"),
    )
    event_id = response.json()["data"]["event"]["event_id"]

    def fail_hook(**_: object) -> None:
        raise RuntimeError("synthetic hook failure")

    monkeypatch.setattr(container.active_capture, "after_capture_committed", fail_hook)
    failed_once = real_drain()
    task_after_failure = container.repositories.capture_post_commit_outbox.list_for_event(event_id)[0]

    assert response.status_code == 200
    assert failed_once.retryable == 1
    assert task_after_failure.status == CapturePostCommitTaskStatus.RETRYABLE
    assert task_after_failure.attempt_count == 1
    assert task_after_failure.last_error == "synthetic hook failure"
    assert container.active_capture.keyframes_for_event(event_id) == ()

    monkeypatch.undo()
    restored_container = _container(client)
    restored_container.capture_post_commit_outbox.config.retry_backoff_ms = 0
    recovered = real_drain()
    completed = restored_container.repositories.capture_post_commit_outbox.list_for_event(event_id)[0]

    assert recovered.completed == 1
    assert completed.status == CapturePostCommitTaskStatus.COMPLETED
    assert restored_container.active_capture.keyframes_for_event(event_id)


def test_capture_post_commit_outbox_survives_daemon_container_restart(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _container(client)
    monkeypatch.setattr(
        container.capture_post_commit_outbox,
        "drain_due_safe",
        lambda _event_id=None: CapturePostCommitDrainResult(),
    )

    response = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}"},
        json=capture_save_request.model_dump(mode="json"),
    )
    event_id = response.json()["data"]["event"]["event_id"]
    assert container.active_capture.keyframes_for_event(event_id) == ()

    restarted = DaemonContainer(container.settings)
    result = restarted.capture_post_commit_outbox.drain_due()

    assert response.status_code == 200
    assert result.completed == 1
    assert restarted.active_capture.keyframes_for_event(event_id)


def test_capture_route_still_accepts_when_post_commit_drain_fails_safely(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _container(client)

    def fail_drain() -> CapturePostCommitDrainResult:
        raise RuntimeError("synthetic outbox drain failure")

    monkeypatch.setattr(container.capture_post_commit_outbox, "drain_due", fail_drain)

    response = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}"},
        json=capture_save_request.model_dump(mode="json"),
    )
    event_id = response.json()["data"]["event"]["event_id"]
    tasks = container.repositories.capture_post_commit_outbox.list_for_event(event_id)

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "accepted"
    assert len(tasks) == 1
    assert tasks[0].status == CapturePostCommitTaskStatus.PENDING
    assert container.active_capture.keyframes_for_event(event_id) == ()


def test_default_event_inspect_trims_keyframes_and_raw_disclosure_audit(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    saved = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}"},
        json=capture_save_request.model_dump(mode="json"),
    ).json()
    event_id = saved["data"]["event"]["event_id"]

    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=verify_trim",
        headers={"authorization": f"Bearer {_token_with_scopes(client, ('read_metadata', 'read_text'))}"},
    ).json()
    decision = inspect["data"]["disclosure_decision"]

    assert inspect["data"]["keyframes"] == []
    assert inspect["data"]["raw_artifacts"] == []
    assert inspect["data"]["hidden_artifacts"] == []
    assert "keyframes" not in decision["delivered_fields"]
    assert "raw_artifact_refs" not in decision["delivered_fields"]
    assert "hidden_artifacts" not in decision["delivered_fields"]
    assert decision["details"]["raw_ref_count"] == 0
    assert decision["details"]["hidden_artifact_count"] == 0
    assert "keyframe_count" not in decision["details"]


def test_headless_recording_session_can_bind_start_final_keyframes_and_timeline(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]

    start_request = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_recording_start",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
        ),
    )
    final_request = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_recording_final",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.FINAL,
            trigger_kind=KeyframeTriggerKind.RECORDING_STOP,
        ),
    )
    start = client.post("/v1/captures", headers=headers, json=start_request.model_dump(mode="json")).json()
    final = client.post("/v1/captures", headers=headers, json=final_request.model_dump(mode="json")).json()
    completed = client.post(f"/v1/active-captures/{session_id}/complete", headers=native_headers, json={}).json()
    loaded = client.get(f"/v1/active-captures/{session_id}", headers=headers).json()
    inspect = client.get(
        f"/v1/events/{start['data']['event']['event_id']}"
        "?view=event_inspect&purpose=verify_active_capture"
        "&inspect_views=active_capture_summary,recording_timeline,video_ref",
        headers={"authorization": f"Bearer {_token_with_scopes(client, ('read_metadata', 'read_text'))}"},
    ).json()
    active_capture = inspect["data"]["active_capture"]
    container = _container(client)

    assert start["data"]["status"] == "accepted"
    assert final["data"]["status"] == "accepted"
    assert completed["data"]["session"]["status"] == "completed"
    assert len(loaded["data"]["keyframes"]) == 2
    assert {item["role"] for item in loaded["data"]["keyframes"]} == {"start", "final"}
    assert loaded["data"]["timeline"]["entries"][0]["media_time_ms"] is None
    assert loaded["data"]["timeline"]["entries"][0]["alignment_confidence"] == "unavailable"
    assert loaded["data"]["timeline"]["entries"][1]["media_time_ms"] is None
    assert loaded["data"]["timeline"]["entries"][1]["alignment_confidence"] == "unavailable"
    assert loaded["data"]["timeline"]["video"]["state"] == "not_recorded"
    assert active_capture["session_id"] == session_id
    assert active_capture["video_ref"]["state"] == "not_recorded"
    assert "sha256" not in active_capture["video_ref"]
    timeline_kinds = [step["kind"] for step in active_capture["timeline"]["steps"]]
    assert timeline_kinds.count("keyframe") == 2
    assert "control" in timeline_kinds
    assert inspect["data"]["disclosure_decision"]["details"]["active_capture_session_id"] == session_id
    assert container.repositories.index_policy_decisions.count_for_event(start["data"]["event"]["event_id"]) > 0


def test_recording_library_lists_all_recording_session_cards(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    first_session_id, first_event_id = _session_with_start_keyframe(
        client,
        token,
        capture_save_request,
        trigger_id="trg_library_first",
    )
    _second_session_id, second_event_id = _session_with_start_keyframe(
        client,
        token,
        capture_save_request,
        trigger_id="trg_library_second",
    )
    empty = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()["data"]["session"]["session_id"]

    response = client.get("/v1/active-captures/recordings?limit=10", headers=headers)
    payload = response.json()
    event_ids = [card["event_id"] for card in payload["data"]["results"]]

    assert response.status_code == 200, response.text
    assert event_ids[:2] == [second_event_id, first_event_id]
    assert empty not in event_ids
    assert payload["data"]["backend"] == "active_capture_sessions"
    assert payload["data"]["results"][0]["source_kind"] == "region_recording"
    assert "active_capture_recording" in payload["data"]["results"][0]["hidden_artifacts"]

    completed = client.post(
        f"/v1/active-captures/{first_session_id}/complete",
        headers=headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER,
        json={"user_note": "cua_only-f001"},
    )
    deleted = client.delete(f"/v1/events/{first_event_id}", headers=headers)
    default_after_delete = client.get("/v1/active-captures/recordings?limit=10", headers=headers).json()
    searched_after_delete = client.get(
        "/v1/active-captures/recordings?limit=10&query=cua",
        headers=headers,
    ).json()
    unrelated_search = client.get(
        "/v1/active-captures/recordings?limit=10&query=other",
        headers=headers,
    ).json()

    assert completed.status_code == 200, completed.text
    assert deleted.status_code == 200, deleted.text
    assert first_event_id not in {card["event_id"] for card in default_after_delete["data"]["results"]}
    assert first_event_id in {card["event_id"] for card in searched_after_delete["data"]["results"]}
    assert first_event_id not in {card["event_id"] for card in unrelated_search["data"]["results"]}

    native_token = _token_with_scopes(
        client,
        ("create_event", "read_metadata", "read_text", "delete_event"),
        actor_id="macos-capture",
    )
    native_session_id, native_event_id = _session_with_start_keyframe(
        client,
        native_token,
        capture_save_request,
        trigger_id="trg_library_native_cua",
    )
    native_headers = {
        "authorization": f"Bearer {native_token}",
        **INSTALL_SECRET_HEADER,
        **NATIVE_CAPTURE_SECRET_HEADER,
    }
    native_completed = client.post(
        f"/v1/active-captures/{native_session_id}/complete",
        headers=native_headers,
        json={"user_note": "cua_native_deleted"},
    )
    native_deleted = client.delete(
        f"/v1/events/{native_event_id}",
        headers={"authorization": f"Bearer {native_token}"},
    )
    workbench_token = _token_with_scopes(
        client,
        ("read_text",),
        actor_id="workrecorder-workbench",
    )
    workbench_search = client.get(
        "/v1/active-captures/recordings?limit=10&query=cua",
        headers={"authorization": f"Bearer {workbench_token}"},
    )

    assert native_completed.status_code == 200, native_completed.text
    assert native_deleted.status_code == 200, native_deleted.text
    assert workbench_search.status_code == 200, workbench_search.text
    assert native_event_id in {
        card["event_id"] for card in workbench_search.json()["data"]["results"]
    }


def test_active_capture_binding_metadata_rejects_raw_values_on_capture_save(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    request = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_reject_raw_binding_metadata",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
        ),
    ).model_dump(mode="json")
    request["active_capture"]["metadata"] = {
        "rawText": "SHOULD_NOT_LEAK_SECRET",
        "selector": "#password",
        "localPath": "/Users/example/private.png",
    }

    response = client.post("/v1/captures", headers=headers, json=request)

    assert response.status_code == 422
    assert "SHOULD_NOT_LEAK_SECRET" not in response.text
    assert "/Users/example" not in response.text

    allowed_key_request = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_reject_raw_binding_value",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
        ),
    ).model_dump(mode="json")
    allowed_key_request["active_capture"]["metadata"] = {
        "settle_stop_reason": "selector #password SHOULD_NOT_LEAK_SECRET",
        "settle_capture_claim_id": "/Users/example/private.png",
    }

    allowed_key_response = client.post("/v1/captures", headers=headers, json=allowed_key_request)

    assert allowed_key_response.status_code == 422
    assert "SHOULD_NOT_LEAK_SECRET" not in allowed_key_response.text
    assert "/Users/example" not in allowed_key_response.text


def test_pause_resume_completion_closes_live_segment_with_trusted_timing(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    container = _container(client)
    initial_segment = container.repositories.active_capture.list_recording_segments_for_session(session_id)[0]
    client.post(
        f"/v1/active-captures/{session_id}/segments",
        headers=native_headers,
        json={
            "segment_id": initial_segment.segment_id,
            "state": RecordingSegmentState.RECORDING.value,
            "started_at_monotonic_ms": 100,
        },
    )
    start_request = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_segment_start",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
        ),
    ).model_copy(
        update={
            "native_timing_receipt": NativeCaptureTimingReceipt(
                authority=NativeCaptureTimingAuthority.MACOS_CAPTURE,
                captured_at_monotonic_ms=150,
                source_clock=NativeTimingClock.SYSTEM_UPTIME_MS,
            )
        }
    )
    client.post("/v1/captures", headers=native_headers, json=start_request.model_dump(mode="json"))
    client.post(
        f"/v1/active-captures/{session_id}/controls",
        headers=native_headers,
        json={"kind": RecordingControlKind.PAUSE.value, "occurred_at_monotonic_ms": 1_000},
    )
    client.post(
        f"/v1/active-captures/{session_id}/controls",
        headers=native_headers,
        json={"kind": RecordingControlKind.RESUME.value, "occurred_at_monotonic_ms": 2_000},
    )
    final_request = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_segment_final",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.FINAL,
            trigger_kind=KeyframeTriggerKind.RECORDING_STOP,
        ),
    ).model_copy(
        update={
            "native_timing_receipt": NativeCaptureTimingReceipt(
                authority=NativeCaptureTimingAuthority.MACOS_CAPTURE,
                captured_at_monotonic_ms=2_500,
                source_clock=NativeTimingClock.SYSTEM_UPTIME_MS,
            )
        }
    )
    client.post("/v1/captures", headers=native_headers, json=final_request.model_dump(mode="json"))

    completed = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers=native_headers,
        json=CompleteActiveCaptureSessionCommand(
            recording_timing=RecordingTimingAnchor(
                authority=NativeCaptureTimingAuthority.MACOS_CAPTURE,
                session_id=session_id,
                source_clock=NativeTimingClock.SYSTEM_UPTIME_MS,
                started_at_monotonic_ms=100,
                ended_at_monotonic_ms=2_600,
            )
        ).model_dump(mode="json"),
    ).json()
    entries = completed["data"]["timeline"]["entries"]
    segments = container.repositories.active_capture.list_recording_segments_for_session(session_id)

    assert [entry["alignment_confidence"] for entry in entries] == ["exact", "exact"]
    assert entries[0]["media_time_ms"] == 50
    assert entries[1]["media_time_ms"] == 1_400
    assert entries[1]["nearest_video_segment_id"] == segments[1].segment_id
    assert segments[1].ended_at_monotonic_ms == 2_600


def test_complete_recording_session_persists_user_note(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    session_id, _event_id = _session_with_start_keyframe(
        client, token, capture_save_request, trigger_id="trg_recording_note"
    )
    headers = {"authorization": f"Bearer {token}"} | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER

    completed = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers=headers,
        json=CompleteActiveCaptureSessionCommand(user_note="  记录支付设置复现步骤  ").model_dump(mode="json"),
    ).json()

    assert completed["data"]["session"]["user_note"] == "记录支付设置复现步骤"
    session = _container(client).repositories.active_capture.get_session(session_id)
    assert session is not None
    assert session.user_note == "记录支付设置复现步骤"
    assert session.metadata["user_note"] == "记录支付设置复现步骤"


def test_recording_controls_triggers_actions_and_storyboard_are_backend_only(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]

    paused = client.post(
        f"/v1/active-captures/{session_id}/controls",
        headers=native_headers,
        json={"kind": RecordingControlKind.PAUSE.value, "occurred_at_monotonic_ms": 1_000},
    ).json()
    resumed = client.post(
        f"/v1/active-captures/{session_id}/controls",
        headers=native_headers,
        json={"kind": RecordingControlKind.RESUME.value, "occurred_at_monotonic_ms": 2_000},
    ).json()
    marked = client.post(
        f"/v1/active-captures/{session_id}/controls",
        headers=native_headers,
        json={"kind": RecordingControlKind.USER_MARK.value, "occurred_at_monotonic_ms": 2_500},
    ).json()
    trigger = client.post(
        f"/v1/active-captures/{session_id}/triggers",
        headers=native_headers,
        json={"trigger_kind": KeyframeTriggerKind.CLICK_SETTLE.value, "occurred_at_monotonic_ms": 3_000},
    ).json()
    action = client.post(
        f"/v1/active-captures/{session_id}/actions",
        headers=native_headers,
        json={
            "kind": HumanActionKind.CLICK.value,
            "occurred_at_monotonic_ms": 3_100,
            "coordinates": _action_coordinates().model_dump(mode="json"),
        },
    ).json()
    hotkey = client.post(
        f"/v1/active-captures/{session_id}/actions",
        headers=native_headers,
        json={
            "kind": HumanActionKind.HOTKEY.value,
            "occurred_at_monotonic_ms": 3_200,
            "hotkey_semantic": HotkeySemantic.OPEN_COMMAND.value,
        },
    ).json()
    segment_manifest = client.get(f"/v1/active-captures/{session_id}/segments", headers=headers).json()
    storyboard = client.get(f"/v1/active-captures/{session_id}/storyboard", headers=headers).json()

    assert paused["data"]["session"]["status"] == "paused"
    assert resumed["data"]["session"]["status"] == "recording"
    assert marked["data"]["session"]["status"] == "recording"
    assert trigger["data"]["candidate"]["status"] == "accepted"
    assert trigger["data"]["candidate"]["priority"] == "high"
    assert (
        trigger["data"]["capture_instruction"]["binding"]["candidate_id"]
        == trigger["data"]["candidate"]["candidate_id"]
    )
    assert action["data"]["kind"] == "click"
    assert "coordinates" not in action["data"]
    assert hotkey["data"]["kind"] == "hotkey"
    assert hotkey["data"]["hotkey_semantic"] == "open_command"
    assert len(segment_manifest["data"]["segments"]) == 2
    assert segment_manifest["data"]["segments"][1]["state"] == RecordingSegmentState.RECORDING.value
    assert "metadata" not in segment_manifest["data"]["control_events"][0]
    assert "note" not in segment_manifest["data"]["control_events"][0]
    assert {item["kind"] for item in storyboard["data"]["items"]} >= {"action", "control"}
    assert storyboard["data"]["card"]["action_count"] == 2
    assert storyboard["data"]["card"]["app_name"] is None
    assert storyboard["data"]["card"]["title"] is None
    assert "recording_video" in storyboard["data"]["card"]["hidden_materials"]


def test_trusted_active_capture_writers_require_install_secret(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]

    trigger = client.post(
        f"/v1/active-captures/{session_id}/triggers",
        headers=headers,
        json={"trigger_kind": KeyframeTriggerKind.CLICK_SETTLE.value},
    )
    action = client.post(
        f"/v1/active-captures/{session_id}/actions",
        headers=headers,
        json={"kind": HumanActionKind.CLICK.value, "coordinates": _action_coordinates().model_dump(mode="json")},
    )
    producer_event = client.post(
        f"/v1/active-captures/{session_id}/producer-events",
        headers=headers,
        json={
            "event_kind": ProducerInputEventKind.POINTER_CLICK.value,
            "producer_kind": "macos_capture",
            "pointer": {"coordinates": _action_coordinates().model_dump(mode="json")},
        },
    )
    control = client.post(
        f"/v1/active-captures/{session_id}/controls",
        headers=headers,
        json={"kind": RecordingControlKind.PAUSE.value, "occurred_at_monotonic_ms": 1_000},
    )
    complete = client.post(f"/v1/active-captures/{session_id}/complete", headers=headers, json={})
    cancel = client.post(
        f"/v1/active-captures/{session_id}/cancel",
        headers=headers,
        json={"reason": "missing-secret"},
    )
    owner_view = client.get(f"/v1/active-captures/{session_id}", headers=headers).json()

    assert trigger.status_code == 403
    assert action.status_code == 403
    assert producer_event.status_code == 403
    assert control.status_code == 403
    assert complete.status_code == 403
    assert cancel.status_code == 403
    assert owner_view["data"]["session"]["status"] == "recording"


def test_stopping_recording_session_can_be_discarded_before_final_save(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]

    stopped = client.post(
        f"/v1/active-captures/{session_id}/controls",
        headers=native_headers,
        json={"kind": RecordingControlKind.STOP.value, "occurred_at_monotonic_ms": 2_000},
    )
    discarded = client.post(
        f"/v1/active-captures/{session_id}/cancel",
        headers=native_headers,
        json={"reason": "discarded_before_save"},
    )

    assert stopped.status_code == 200
    assert stopped.json()["data"]["session"]["status"] == "stopping"
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["data"]["session"]["status"] == "cancelled"


def test_producer_events_atomically_create_action_trigger_and_skill_projection(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]

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
    hotkey = client.post(
        f"/v1/active-captures/{session_id}/producer-events",
        headers=native_headers,
        json={
            "event_kind": ProducerInputEventKind.HOTKEY.value,
            "producer_kind": "macos_capture",
            "occurred_at_monotonic_ms": 3_500,
            "keyboard": {
                "keyboard_event_kind": KeyboardEventKind.HOTKEY.value,
                "input_class": KeyboardInputClass.SHORTCUT.value,
                "capture_policy": KeyCapturePolicy.KEY_CHORD_ALLOWED.value,
                "key_chord": {
                    "physical_key_code": 40,
                    "normalized_key_label": "k",
                    "modifiers": [ModifierKey.COMMAND.value],
                    "semantic": HotkeySemantic.OPEN_COMMAND.value,
                },
                "hotkey_semantic": HotkeySemantic.OPEN_COMMAND.value,
            },
        },
    )
    typing = client.post(
        f"/v1/active-captures/{session_id}/producer-events",
        headers=native_headers,
        json={
            "event_kind": ProducerInputEventKind.TYPING_PAUSE.value,
            "producer_kind": "macos_capture",
            "occurred_at_monotonic_ms": 4_000,
            "keyboard": {
                "keyboard_event_kind": KeyboardEventKind.TYPING_PAUSE.value,
                "input_class": KeyboardInputClass.TEXT_INPUT.value,
                "capture_policy": KeyCapturePolicy.AGGREGATE_ONLY.value,
                "typing_summary": {
                    "event_count": 5,
                    "text_event_count": 5,
                    "character_count": 5,
                    "duration_ms": 700,
                },
            },
        },
    )
    rejected_text = client.post(
        f"/v1/active-captures/{session_id}/producer-events",
        headers=native_headers,
        json={
            "event_kind": ProducerInputEventKind.TYPING_PAUSE.value,
            "producer_kind": "macos_capture",
            "keyboard": {
                "keyboard_event_kind": KeyboardEventKind.TYPING_PAUSE.value,
                "input_class": KeyboardInputClass.TEXT_INPUT.value,
                "capture_policy": KeyCapturePolicy.AGGREGATE_ONLY.value,
                "typing_summary": {"event_count": 1},
            },
            "metadata": {"typed_text": "do not store me"},
        },
    )
    rejected_camel_text = client.post(
        f"/v1/active-captures/{session_id}/producer-events",
        headers=native_headers,
        json={
            "event_kind": ProducerInputEventKind.TYPING_PAUSE.value,
            "producer_kind": "macos_capture",
            "keyboard": {
                "keyboard_event_kind": KeyboardEventKind.TYPING_PAUSE.value,
                "input_class": KeyboardInputClass.TEXT_INPUT.value,
                "capture_policy": KeyCapturePolicy.AGGREGATE_ONLY.value,
                "typing_summary": {"event_count": 1},
            },
            "metadata": {"typedTextPreview": "do not store me"},
        },
    )
    rejected_key_down = client.post(
        f"/v1/active-captures/{session_id}/producer-events",
        headers=native_headers,
        json={
            "event_kind": ProducerInputEventKind.KEY_DOWN.value,
            "producer_kind": "macos_capture",
            "keyboard": {
                "keyboard_event_kind": KeyboardEventKind.KEY_DOWN.value,
                "input_class": KeyboardInputClass.SHORTCUT.value,
                "capture_policy": KeyCapturePolicy.KEY_CHORD_ALLOWED.value,
                "key_chord": {
                    "physical_key_code": 40,
                    "normalized_key_label": "k",
                    "modifiers": [ModifierKey.COMMAND.value],
                    "semantic": HotkeySemantic.OPEN_COMMAND.value,
                },
                "hotkey_semantic": HotkeySemantic.OPEN_COMMAND.value,
            },
        },
    )
    accepted_key_down = client.post(
        f"/v1/active-captures/{session_id}/producer-events",
        headers=native_headers,
        json={
            "event_kind": ProducerInputEventKind.KEY_DOWN.value,
            "producer_kind": "macos_capture",
            "occurred_at_monotonic_ms": 4_100,
            "keyboard": {
                "keyboard_event_kind": KeyboardEventKind.KEY_DOWN.value,
                "input_class": KeyboardInputClass.TEXT_INPUT.value,
                "capture_policy": KeyCapturePolicy.FULL_CONTENT.value,
                "key_chord": {
                    "physical_key_code": 4,
                    "normalized_key_label": "h",
                    "modifiers": [ModifierKey.SHIFT.value],
                    "semantic": HotkeySemantic.UNKNOWN.value,
                    "characters": "H",
                },
            },
        },
    )
    accepted_key_up = client.post(
        f"/v1/active-captures/{session_id}/producer-events",
        headers=native_headers,
        json={
            "event_kind": ProducerInputEventKind.KEY_UP.value,
            "producer_kind": "macos_capture",
            "occurred_at_monotonic_ms": 4_125,
            "keyboard": {
                "keyboard_event_kind": KeyboardEventKind.KEY_UP.value,
                "input_class": KeyboardInputClass.TEXT_INPUT.value,
                "capture_policy": KeyCapturePolicy.FULL_CONTENT.value,
                "key_chord": {
                    "physical_key_code": 4,
                    "normalized_key_label": "h",
                    "modifiers": [ModifierKey.SHIFT.value],
                    "semantic": HotkeySemantic.UNKNOWN.value,
                    "characters": "H",
                },
            },
        },
    )
    click_candidate_id = click.json()["data"]["results"][0]["trigger"]["candidate"]["candidate_id"]
    pending_instructions = client.post(
        f"/v1/active-captures/{session_id}/capture-instructions/pending",
        headers=native_headers,
        json={"now_monotonic_ms": 5_500, "limit": 8},
    )
    assert pending_instructions.status_code == 200, pending_instructions.text
    instructions_by_candidate = {
        item["candidate_id"]: item for item in pending_instructions.json()["data"]["instructions"]
    }
    binding = ActiveCaptureBinding.model_validate(instructions_by_candidate[click_candidate_id]["binding"])
    captured = client.post(
        "/v1/captures",
        headers=headers,
        json=_active_capture_attempt(
            client,
            capture_save_request,
            trigger_id="trg_producer_click_after",
            binding=binding,
        ).model_dump(mode="json"),
    )
    skill = client.get(f"/v1/active-captures/{session_id}/skill-distillation-input", headers=headers)
    container = _container(client)
    actions = container.repositories.active_capture.list_human_actions_for_session(session_id)
    events = container.repositories.active_capture.list_producer_events_for_session(session_id)
    decisions = container.repositories.active_capture.list_producer_decisions_for_session(session_id)
    keyframes = container.repositories.active_capture.list_keyframes_for_session(session_id)

    assert click.status_code == 200, click.text
    assert hotkey.status_code == 200, hotkey.text
    assert typing.status_code == 200, typing.text
    assert rejected_text.status_code == 422
    assert rejected_camel_text.status_code == 422
    assert rejected_key_down.status_code == 422
    assert accepted_key_down.status_code == 200, accepted_key_down.text
    assert accepted_key_down.json()["data"]["results"][0]["action"]["kind"] == "key_down"
    assert accepted_key_up.status_code == 200, accepted_key_up.text
    assert accepted_key_up.json()["data"]["results"][0]["action"]["kind"] == "key_up"
    assert "do not store me" not in rejected_text.text
    assert "do not store me" not in rejected_camel_text.text
    assert captured.status_code == 200, captured.text
    assert click.json()["data"]["results"][0]["trigger"]["candidate"]["trigger_kind"] == "click_settle"
    assert hotkey.json()["data"]["results"][0]["action"]["hotkey_semantic"] == "open_command"
    assert typing.json()["data"]["results"][0]["action"]["kind"] == "typing_pause"
    assert "coordinates" not in click.json()["data"]["results"][0]["action"]
    assert {action.kind for action in actions} >= {
        HumanActionKind.CLICK,
        HumanActionKind.HOTKEY,
        HumanActionKind.KEY_DOWN,
        HumanActionKind.KEY_UP,
        HumanActionKind.TYPING_PAUSE,
    }
    assert len(events) == 5
    assert len(decisions) == 5
    assert any(keyframe.quality.metrics.get("settle_stop_reason") == "provider_unavailable" for keyframe in keyframes)
    assert any(decision.reason == ProducerDecisionReason.TYPING_SETTLED for decision in decisions)
    assert skill.status_code == 200, skill.text
    skill_steps = skill.json()["data"]["steps"]
    assert any(step["key_chord"]["normalized_key_label"] == "k" for step in skill_steps if step["key_chord"])
    assert any(step["key_chord"]["characters"] == "H" for step in skill_steps if step["key_chord"])
    assert any(step["evidence_keyframe_ids"] for step in skill_steps if step["action_kind"] == "click")
    assert any(step["typing_summary"]["character_count"] == 5 for step in skill_steps if step["typing_summary"])
    assert "typed_text" not in skill.text
    assert "typedTextPreview" not in skill.text


def test_producer_batch_graph_write_failure_is_all_or_nothing(
    client: TestClient,
    token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    container = _container(client)
    session = container.active_capture.view_session(session_id).session

    def fail_append(**_kwargs: object) -> None:
        raise RuntimeError("simulated producer batch commit failure")

    monkeypatch.setattr(container.repositories.active_capture, "append_producer_event_batch_graph", fail_append)

    with pytest.raises(RuntimeError, match="simulated producer batch commit failure"):
        container.active_capture.record_producer_events(
            session_id=session.session_id,
            command=RecordProducerInputBatchCommand(
                events=(
                    RecordProducerInputEventCommand(
                        event_kind=ProducerInputEventKind.POINTER_CLICK,
                        producer_kind="macos_capture",
                        pointer=PointerInputPayload(coordinates=_action_coordinates()),
                    ),
                )
            ),
        )

    assert container.repositories.active_capture.list_producer_events_for_session(session_id) == ()
    assert container.repositories.active_capture.list_producer_decisions_for_session(session_id) == ()
    assert container.repositories.active_capture.list_human_actions_for_session(session_id) == ()
    assert container.repositories.active_capture.list_trigger_candidates_for_session(session_id) == ()


def test_coalesced_plain_typing_chunks_emit_one_result_keyframe_candidate(
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
    container = _container(client)
    old_scroll_events = tuple(
        RecordProducerInputEventCommand(
            event_kind=ProducerInputEventKind.SCROLL,
            producer_kind="macos_capture",
            occurred_at_monotonic_ms=index,
            scroll=ScrollInputPayload(delta_y=1, phase=ScrollPhase.CHANGED),
        )
        for index in range(130)
    )
    container.active_capture.record_producer_events(
        session_id=session_id,
        command=RecordProducerInputBatchCommand(events=old_scroll_events[:100]),
    )
    container.active_capture.record_producer_events(
        session_id=session_id,
        command=RecordProducerInputBatchCommand(events=old_scroll_events[100:]),
    )

    chunks = (
        (1, 1, 1_000),
        (6, 6, 2_000),
        (4, 4, 3_000),
        (5, 5, 4_000),
    )
    responses = []
    for index, (events, chars, monotonic_ms) in enumerate(chunks):
        responses.append(
            client.post(
                f"/v1/active-captures/{session_id}/producer-events",
                headers=native_headers,
                json={
                    "event_kind": ProducerInputEventKind.TYPING_PAUSE.value,
                    "producer_kind": "macos_capture",
                    "occurred_at_monotonic_ms": monotonic_ms,
                    "keyboard": {
                        "keyboard_event_kind": KeyboardEventKind.TYPING_PAUSE.value,
                        "input_class": KeyboardInputClass.TEXT_INPUT.value,
                        "capture_policy": KeyCapturePolicy.AGGREGATE_ONLY.value,
                        "typing_summary": {
                            "event_count": events,
                            "text_event_count": events,
                            "character_count": chars,
                            "submitted_by_enter": False,
                        },
                    },
                    "metadata": {"chunk_index": index},
                },
            )
        )

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert responses[0].json()["data"]["results"][0]["trigger"] is None
    assert responses[1].json()["data"]["results"][0]["trigger"] is None
    third = responses[2].json()["data"]["results"][0]
    fourth = responses[3].json()["data"]["results"][0]
    assert third["trigger"]["candidate"]["trigger_kind"] == KeyframeTriggerKind.TYPING_SETTLE.value
    assert "coalesced_typing_chars=11" in third["decision"]["diagnostics"]
    assert "coalesced_typing_events=11" in third["decision"]["diagnostics"]
    assert fourth["trigger"] is None

    candidates = container.repositories.active_capture.list_trigger_candidates_for_session(session_id)
    typing_candidates = [
        candidate for candidate in candidates if candidate.trigger_kind == KeyframeTriggerKind.TYPING_SETTLE
    ]
    assert len(typing_candidates) == 1
    assert typing_candidates[0].metadata["typing_capture_reason"] == "coalesced_typing_milestone"


def test_accepted_trigger_returns_typed_capture_instruction_and_links_keyframe(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    submission = client.post(
        f"/v1/active-captures/{session_id}/triggers",
        headers=native_headers,
        json={"trigger_kind": KeyframeTriggerKind.CLICK_SETTLE.value, "occurred_at_monotonic_ms": 3_000},
    ).json()["data"]
    binding = ActiveCaptureBinding.model_validate(submission["capture_instruction"]["binding"])
    attempt = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_instruction_capture",
        binding=binding,
    )

    saved = client.post("/v1/captures", headers=headers, json=attempt.model_dump(mode="json")).json()
    candidate = _container(client).repositories.active_capture.get_trigger_candidate(
        submission["candidate"]["candidate_id"]
    )
    event = _container(client).repositories.events.get(saved["data"]["event"]["event_id"])

    assert saved["data"]["status"] == "accepted"
    assert binding.candidate_id == submission["candidate"]["candidate_id"]
    assert event is not None
    assert event.trigger.metadata["active_capture_candidate_id"] == binding.candidate_id
    assert candidate is not None
    assert candidate.status.value == "captured"
    assert candidate.keyframe_id is not None
    assert candidate.event_id == saved["data"]["event"]["event_id"]


def test_complete_drains_pending_keyframe_outbox_before_terminal_session(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    submission = client.post(
        f"/v1/active-captures/{session_id}/triggers",
        headers=native_headers,
        json={"trigger_kind": KeyframeTriggerKind.CLICK_SETTLE.value, "occurred_at_monotonic_ms": 3_000},
    ).json()["data"]
    binding = ActiveCaptureBinding.model_validate(submission["capture_instruction"]["binding"])
    assert binding.candidate_id is not None
    container = _container(client)
    container.capture_post_commit_outbox.config.claim_limit = 1
    monkeypatch.setattr(
        container.capture_post_commit_outbox,
        "drain_due_safe",
        lambda event_id=None: CapturePostCommitDrainResult(),
    )
    backlog = client.post(
        "/v1/captures",
        headers=headers,
        json=capture_save_request.model_dump(mode="json"),
    )
    backlog_event_id = backlog.json()["data"]["event"]["event_id"]
    attempt = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_instruction_capture_before_complete",
        binding=binding,
    )

    saved = client.post("/v1/captures", headers=headers, json=attempt.model_dump(mode="json"))
    before_complete = container.repositories.active_capture.get_trigger_candidate(binding.candidate_id)
    completed = client.post(f"/v1/active-captures/{session_id}/complete", headers=native_headers, json={})
    after_complete = container.repositories.active_capture.get_trigger_candidate(binding.candidate_id)

    assert backlog.status_code == 200, backlog.text
    assert container.repositories.capture_post_commit_outbox.list_for_event(backlog_event_id)[0].status == (
        CapturePostCommitTaskStatus.PENDING
    )
    assert saved.status_code == 200, saved.text
    assert before_complete is not None
    assert before_complete.status == KeyframeTriggerCandidateStatus.ACCEPTED
    assert completed.status_code == 200, completed.text
    assert after_complete is not None
    assert after_complete.status == KeyframeTriggerCandidateStatus.CAPTURED
    assert after_complete.event_id == saved.json()["data"]["event"]["event_id"]


def test_complete_waits_when_keyframe_outbox_is_retryable(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    submission = client.post(
        f"/v1/active-captures/{session_id}/triggers",
        headers=native_headers,
        json={"trigger_kind": KeyframeTriggerKind.CLICK_SETTLE.value, "occurred_at_monotonic_ms": 3_000},
    ).json()["data"]
    binding = ActiveCaptureBinding.model_validate(submission["capture_instruction"]["binding"])
    assert binding.candidate_id is not None
    container = _container(client)
    monkeypatch.setattr(
        container.capture_post_commit_outbox,
        "drain_due_safe",
        lambda event_id=None: CapturePostCommitDrainResult(),
    )
    monkeypatch.setattr(
        container.active_capture,
        "after_capture_committed",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic keyframe outbox retry")),
    )
    attempt = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_instruction_capture_retryable_before_complete",
        binding=binding,
    )

    saved = client.post("/v1/captures", headers=headers, json=attempt.model_dump(mode="json"))
    completed = client.post(f"/v1/active-captures/{session_id}/complete", headers=native_headers, json={})
    event_id = saved.json()["data"]["event"]["event_id"]
    candidate = container.repositories.active_capture.get_trigger_candidate(binding.candidate_id)

    assert saved.status_code == 200, saved.text
    assert completed.status_code == 503, completed.text
    assert completed.json()["error"]["details"]["retryable"] is True
    assert candidate is not None
    assert candidate.status == KeyframeTriggerCandidateStatus.ACCEPTED
    assert container.repositories.capture_post_commit_outbox.list_for_event(event_id)[0].status == (
        CapturePostCommitTaskStatus.RETRYABLE
    )


def test_complete_drops_candidate_when_keyframe_outbox_permanently_failed(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    submission = client.post(
        f"/v1/active-captures/{session_id}/triggers",
        headers=native_headers,
        json={"trigger_kind": KeyframeTriggerKind.CLICK_SETTLE.value, "occurred_at_monotonic_ms": 3_000},
    ).json()["data"]
    binding = ActiveCaptureBinding.model_validate(submission["capture_instruction"]["binding"])
    assert binding.candidate_id is not None
    container = _container(client)
    container.capture_post_commit_outbox.config.max_attempts = 1
    monkeypatch.setattr(
        container.capture_post_commit_outbox,
        "drain_due_safe",
        lambda event_id=None: CapturePostCommitDrainResult(),
    )
    monkeypatch.setattr(
        container.active_capture,
        "after_capture_committed",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic keyframe outbox permanent failure")),
    )
    attempt = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_instruction_capture_failed_before_complete",
        binding=binding,
    )

    saved = client.post("/v1/captures", headers=headers, json=attempt.model_dump(mode="json"))
    completed = client.post(f"/v1/active-captures/{session_id}/complete", headers=native_headers, json={})
    event_id = saved.json()["data"]["event"]["event_id"]
    candidate = container.repositories.active_capture.get_trigger_candidate(binding.candidate_id)

    assert saved.status_code == 200, saved.text
    assert completed.status_code == 200, completed.text
    assert candidate is not None
    assert candidate.status == KeyframeTriggerCandidateStatus.DROPPED
    assert candidate.drop_reason == KeyframeDropReason.INVALID_EVIDENCE
    assert candidate.event_id == event_id
    assert "post_commit_outbox_failed_before_terminal" in candidate.diagnostics
    assert container.repositories.capture_post_commit_outbox.list_for_event(event_id)[0].status == (
        CapturePostCommitTaskStatus.FAILED
    )


def test_trusted_capture_instruction_failure_marks_candidate_dropped(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    submission = client.post(
        f"/v1/active-captures/{session_id}/triggers",
        headers=native_headers,
        json={"trigger_kind": KeyframeTriggerKind.CLICK_SETTLE.value, "occurred_at_monotonic_ms": 3_000},
    ).json()["data"]
    candidate_id = submission["candidate"]["candidate_id"]

    denied = client.post(
        f"/v1/active-captures/{session_id}/capture-instructions/failure",
        headers=headers,
        json={"candidate_id": candidate_id, "reason": KeyframeDropReason.INVALID_EVIDENCE.value},
    )
    accepted = client.post(
        f"/v1/active-captures/{session_id}/capture-instructions/failure",
        headers=native_headers,
        json={
            "candidate_id": candidate_id,
            "reason": KeyframeDropReason.INVALID_EVIDENCE.value,
            "diagnostic": "native_capture_instruction_failed",
        },
    )
    candidate = _container(client).repositories.active_capture.get_trigger_candidate(candidate_id)

    assert denied.status_code == 403
    assert accepted.status_code == 200
    assert candidate is not None
    assert candidate.status == KeyframeTriggerCandidateStatus.DROPPED
    assert candidate.drop_reason == KeyframeDropReason.INVALID_EVIDENCE


def test_capture_instruction_failure_lets_committed_capture_win_pending_outbox(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    submission = client.post(
        f"/v1/active-captures/{session_id}/triggers",
        headers=native_headers,
        json={"trigger_kind": KeyframeTriggerKind.CLICK_SETTLE.value, "occurred_at_monotonic_ms": 3_000},
    ).json()["data"]
    binding = ActiveCaptureBinding.model_validate(submission["capture_instruction"]["binding"])
    assert binding.candidate_id is not None
    container = _container(client)
    monkeypatch.setattr(
        container.capture_post_commit_outbox,
        "drain_due_safe",
        lambda event_id=None: CapturePostCommitDrainResult(),
    )
    attempt = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_instruction_capture_before_failure",
        binding=binding,
    )

    saved = client.post("/v1/captures", headers=headers, json=attempt.model_dump(mode="json"))
    failure = client.post(
        f"/v1/active-captures/{session_id}/capture-instructions/failure",
        headers=native_headers,
        json={
            "candidate_id": binding.candidate_id,
            "reason": KeyframeDropReason.INVALID_EVIDENCE.value,
            "diagnostic": "native_capture_instruction_failed",
        },
    )
    candidate = container.repositories.active_capture.get_trigger_candidate(binding.candidate_id)

    assert saved.status_code == 200, saved.text
    assert failure.status_code == 200, failure.text
    assert candidate is not None
    assert candidate.status == KeyframeTriggerCandidateStatus.CAPTURED
    assert candidate.event_id == saved.json()["data"]["event"]["event_id"]


def test_capture_instruction_failure_is_not_blocked_by_unrelated_retryable_candidate(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    failed_submission = client.post(
        f"/v1/active-captures/{session_id}/triggers",
        headers=native_headers,
        json={"trigger_kind": KeyframeTriggerKind.CLICK_SETTLE.value, "occurred_at_monotonic_ms": 3_000},
    ).json()["data"]
    unrelated_submission = client.post(
        f"/v1/active-captures/{session_id}/triggers",
        headers=native_headers,
        json={"trigger_kind": KeyframeTriggerKind.HOTKEY_SETTLE.value, "occurred_at_monotonic_ms": 4_000},
    ).json()["data"]
    failed_candidate_id = failed_submission["candidate"]["candidate_id"]
    unrelated_binding = ActiveCaptureBinding.model_validate(unrelated_submission["capture_instruction"]["binding"])
    assert unrelated_binding.candidate_id is not None
    container = _container(client)
    monkeypatch.setattr(
        container.capture_post_commit_outbox,
        "drain_due_safe",
        lambda event_id=None: CapturePostCommitDrainResult(),
    )
    monkeypatch.setattr(
        container.active_capture,
        "after_capture_committed",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic unrelated keyframe retry")),
    )
    attempt = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_unrelated_retryable_candidate",
        binding=unrelated_binding,
    )

    saved = client.post("/v1/captures", headers=headers, json=attempt.model_dump(mode="json"))
    unrelated_event_id = saved.json()["data"]["event"]["event_id"]
    container.capture_post_commit_outbox.drain_due_before_terminal_safe(event_id=unrelated_event_id)
    failure = client.post(
        f"/v1/active-captures/{session_id}/capture-instructions/failure",
        headers=native_headers,
        json={
            "candidate_id": failed_candidate_id,
            "reason": KeyframeDropReason.INVALID_EVIDENCE.value,
            "diagnostic": "native_capture_instruction_failed",
        },
    )
    failed_candidate = container.repositories.active_capture.get_trigger_candidate(failed_candidate_id)
    unrelated_candidate = container.repositories.active_capture.get_trigger_candidate(unrelated_binding.candidate_id)

    assert saved.status_code == 200, saved.text
    assert failure.status_code == 200, failure.text
    assert failed_candidate is not None
    assert failed_candidate.status == KeyframeTriggerCandidateStatus.DROPPED
    assert unrelated_candidate is not None
    assert unrelated_candidate.status == KeyframeTriggerCandidateStatus.ACCEPTED
    assert container.repositories.capture_post_commit_outbox.list_for_event(unrelated_event_id)[0].status == (
        CapturePostCommitTaskStatus.RETRYABLE
    )


def test_region_recording_keyframe_accepts_title_drift_and_stays_out_of_default_search(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    selected = capture_save_request.selection_geometry.selected_region
    window_frame = BoundingBox(x=100, y=100, width=820, height=620)
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={
            "mode": ActiveCaptureMode.RECORDING_SESSION.value,
            "start_recording": True,
            "scope": RecordingScope(
                kind=RecordingScopeKind.REGION,
                display_id=capture_save_request.selection_geometry.display.display_id,
                scale_factor=capture_save_request.selection_geometry.display.scale_factor,
                window_id="win_google",
                process_id=1234,
                bundle_id="com.example.Browser",
                app_name="Browser",
                title="openrouter - Google 搜索",
                bounds=window_frame,
                selection_region=selected,
            ).model_dump(mode="json"),
        },
    ).json()
    session_id = create["data"]["session"]["session_id"]
    submission = client.post(
        f"/v1/active-captures/{session_id}/triggers",
        headers=native_headers,
        json={"trigger_kind": KeyframeTriggerKind.CLICK_SETTLE.value, "occurred_at_monotonic_ms": 3_000},
    ).json()["data"]
    attempt = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_region_title_drift",
        binding=ActiveCaptureBinding.model_validate(submission["capture_instruction"]["binding"]),
    ).model_copy(
        update={
            "window_hints": (
                WindowHint(
                    app_name="Browser",
                    title="openrouter。新的查询 - Google 搜索",
                    process_id=1234,
                    window_id="win_google",
                    bundle_id="com.example.Browser",
                    display_id=capture_save_request.selection_geometry.display.display_id,
                    frame=window_frame,
                    overlap_ratio=0.99,
                    confidence=0.95,
                ),
            )
        }
    )

    saved = client.post("/v1/captures", headers=headers, json=attempt.model_dump(mode="json"))
    event_id = saved.json()["data"]["event"]["event_id"]
    candidate = _container(client).repositories.active_capture.get_trigger_candidate(
        submission["candidate"]["candidate_id"]
    )
    keyframes = _container(client).repositories.active_capture.list_keyframes_for_event(event_id)
    search = client.get(
        "/v1/search?query=&limit=20&sort=captured_at",
        headers={"authorization": f"Bearer {_token_with_scopes(client, ('read_text', 'read_metadata'))}"},
    ).json()

    assert saved.status_code == 200
    assert candidate is not None
    assert candidate.status.value == "captured"
    assert candidate.event_id == event_id
    assert len(keyframes) == 1
    assert event_id not in {item["event_id"] for item in search["data"]["results"]}


def test_native_timing_keyframe_capture_requires_secret_and_captures_with_secret(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    submission = client.post(
        f"/v1/active-captures/{session_id}/triggers",
        headers=native_headers,
        json={"trigger_kind": KeyframeTriggerKind.CLICK_SETTLE.value, "occurred_at_monotonic_ms": 3_000},
    ).json()["data"]
    attempt = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_native_timing_instruction_capture",
        binding=ActiveCaptureBinding.model_validate(submission["capture_instruction"]["binding"]),
    ).model_copy(
        update={
            "native_timing_receipt": NativeCaptureTimingReceipt(
                authority=NativeCaptureTimingAuthority.MACOS_CAPTURE,
                captured_at_monotonic_ms=3_100,
                source_clock=NativeTimingClock.SYSTEM_UPTIME_MS,
            )
        }
    )

    rejected = client.post(
        "/v1/captures", headers=headers | INSTALL_SECRET_HEADER, json=attempt.model_dump(mode="json")
    )
    accepted = client.post("/v1/captures", headers=native_headers, json=attempt.model_dump(mode="json"))
    candidate = _container(client).repositories.active_capture.get_trigger_candidate(
        submission["candidate"]["candidate_id"]
    )

    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "policy.denied"
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["status"] == "accepted"
    assert candidate is not None
    assert candidate.status.value == "captured"
    assert candidate.keyframe_id is not None


def test_validation_errors_do_not_echo_sensitive_inputs(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    local_path = "/Users/example/private/SHOULD_NOT_LEAK_capture.png"

    response = client.post(
        "/v1/captures",
        headers=headers,
        json={
            "schema_version": 1,
            "trigger": {"trigger_id": "trg_bad"},
            "staged_artifact": {"local_path": local_path, "typedTextPreview": "SHOULD_NOT_LEAK_TEXT"},
        },
    )

    assert response.status_code == 422
    assert "SHOULD_NOT_LEAK" not in response.text
    assert local_path not in response.text


def test_scoped_keyboard_producer_requires_frontmost_observed_scope(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={
            "mode": ActiveCaptureMode.RECORDING_SESSION.value,
            "start_recording": True,
            "scope": {
                "kind": RecordingScopeKind.WINDOW.value,
                "window_id": "target-window",
                "process_id": 4242,
                "bundle_id": "com.example.target",
                "bounds": {"x": 0, "y": 0, "width": 800, "height": 600, "coordinate_space": "macos_global"},
            },
        },
    ).json()
    session_id = create["data"]["session"]["session_id"]

    response = client.post(
        f"/v1/active-captures/{session_id}/producer-events",
        headers=native_headers,
        json={
            "event_kind": ProducerInputEventKind.HOTKEY.value,
            "producer_kind": "macos_capture",
            "occurred_at_monotonic_ms": 3_500,
            "keyboard": {
                "keyboard_event_kind": KeyboardEventKind.HOTKEY.value,
                "input_class": KeyboardInputClass.SHORTCUT.value,
                "capture_policy": KeyCapturePolicy.KEY_CHORD_ALLOWED.value,
                "key_chord": {
                    "physical_key_code": 40,
                    "normalized_key_label": "k",
                    "modifiers": [ModifierKey.COMMAND.value],
                    "semantic": HotkeySemantic.OPEN_COMMAND.value,
                },
                "hotkey_semantic": HotkeySemantic.OPEN_COMMAND.value,
            },
            "scope": {
                "kind": RecordingScopeKind.WINDOW.value,
                "window_id": "target-window",
                "bounds": {"x": 0, "y": 0, "width": 800, "height": 600, "coordinate_space": "macos_global"},
            },
        },
    )
    container = _container(client)

    assert response.status_code == 200, response.text
    result = response.json()["data"]["results"][0]
    assert result["decision"]["status"] == "dropped"
    assert result["decision"]["reason"] == "scope_lost"
    assert result["action"] is None
    assert result["trigger"] is None
    assert container.repositories.active_capture.list_human_actions_for_session(session_id) == ()
    assert container.repositories.active_capture.list_trigger_candidates_for_session(session_id) == ()


def test_human_action_evidence_result_and_derived_media_time_round_trip(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    session_id, event_id = _session_with_start_keyframe(
        client,
        token,
        capture_save_request,
        trigger_id="trg_action_evidence",
    )
    container = _container(client)
    segment = container.repositories.active_capture.list_recording_segments_for_session(session_id)[0]
    client.post(
        f"/v1/active-captures/{session_id}/segments",
        headers=native_headers,
        json={
            "segment_id": segment.segment_id,
            "state": RecordingSegmentState.RECORDING.value,
            "started_at_monotonic_ms": 100,
            "media_start_monotonic_ms": 175,
            "media_start_wall_time_epoch_ms": 1_782_300_000_175,
        },
    )
    saved_segment = container.repositories.active_capture.get_recording_segment(segment.segment_id)
    assert saved_segment is not None
    assert saved_segment.media_start_wall_time_epoch_ms == 1_782_300_000_175
    keyframe = container.active_capture.view_session(session_id).keyframes[0]
    link = container.repositories.active_capture.list_evidence_links_for_keyframe(keyframe.keyframe_id)[0]

    action = client.post(
        f"/v1/active-captures/{session_id}/actions",
        headers=native_headers,
        json={
            "kind": HumanActionKind.CLICK.value,
            "occurred_at_monotonic_ms": 350,
            "media_time_ms": 999_999,
            "coordinates": _action_coordinates().model_dump(mode="json"),
            "evidence_refs": [
                {
                    "role": HumanActionEvidenceRole.BEFORE_KEYFRAME.value,
                    "keyframe_id": keyframe.keyframe_id,
                    "event_id": event_id,
                    "evidence_id": link.evidence_id,
                    "artifact_id": link.artifact_id,
                }
            ],
            "result": {
                "status": HumanActionOutcomeStatus.OBSERVED.value,
                "result_keyframe_id": keyframe.keyframe_id,
            },
        },
    ).json()["data"]
    completed = client.post(f"/v1/active-captures/{session_id}/complete", headers=native_headers, json={}).json()
    trace = container.repositories.active_capture.get_demonstration_trace_for_session(session_id)
    saved_actions = container.repositories.active_capture.list_human_actions_for_session(session_id)

    assert action["media_time_ms"] == 175
    assert action["result_status"] == "observed"
    assert saved_actions[0].media_time_ms == 175
    assert container.repositories.active_capture.list_action_evidence_links(saved_actions[0].action_id)
    assert container.repositories.active_capture.get_action_observation(saved_actions[0].action_id) is not None
    assert completed["data"]["session"]["status"] == "completed_with_warnings"
    assert trace is not None
    assert trace.status.value == "completed_with_warnings"


def test_human_action_rejects_cross_session_evidence_and_sensitive_metadata(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]

    bad_ref = client.post(
        f"/v1/active-captures/{session_id}/actions",
        headers=native_headers,
        json={
            "kind": HumanActionKind.CLICK.value,
            "coordinates": _action_coordinates().model_dump(mode="json"),
            "evidence_refs": [
                {
                    "role": HumanActionEvidenceRole.BEFORE_KEYFRAME.value,
                    "keyframe_id": "kf_other",
                }
            ],
        },
    )
    sensitive_metadata = client.post(
        f"/v1/active-captures/{session_id}/actions",
        headers=native_headers,
        json={
            "kind": HumanActionKind.CLICK.value,
            "coordinates": _action_coordinates().model_dump(mode="json"),
            "metadata": {"raw_text": "do not store this"},
        },
    )

    assert bad_ref.status_code == 422
    assert sensitive_metadata.status_code == 422
    assert "do not store this" not in sensitive_metadata.text


def test_human_action_rejects_same_session_event_evidence_mismatch(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    native_headers = headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER
    session_id, start_event_id = _session_with_start_keyframe(
        client,
        token,
        capture_save_request,
        trigger_id="trg_action_start_mismatch",
    )
    final_request = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_action_final_mismatch",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.FINAL,
            trigger_kind=KeyframeTriggerKind.RECORDING_STOP,
        ),
    )
    final = client.post("/v1/captures", headers=headers, json=final_request.model_dump(mode="json")).json()
    container = _container(client)
    start_keyframe = next(
        keyframe
        for keyframe in container.active_capture.view_session(session_id).keyframes
        if keyframe.event_id == start_event_id
    )
    start_link = container.repositories.active_capture.list_evidence_links_for_keyframe(start_keyframe.keyframe_id)[0]

    response = client.post(
        f"/v1/active-captures/{session_id}/actions",
        headers=native_headers,
        json={
            "kind": HumanActionKind.CLICK.value,
            "coordinates": _action_coordinates().model_dump(mode="json"),
            "evidence_refs": [
                {
                    "role": HumanActionEvidenceRole.BEFORE_KEYFRAME.value,
                    "event_id": final["data"]["event"]["event_id"],
                    "evidence_id": start_link.evidence_id,
                }
            ],
        },
    )

    assert response.status_code == 422


def test_active_session_view_filters_deleted_secondary_keyframe_and_timeline_entry(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    start_request = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_visible_start",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
        ),
    )
    final_request = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_hidden_final",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.FINAL,
            trigger_kind=KeyframeTriggerKind.RECORDING_STOP,
        ),
    )
    start = client.post("/v1/captures", headers=headers, json=start_request.model_dump(mode="json")).json()
    final = client.post("/v1/captures", headers=headers, json=final_request.model_dump(mode="json")).json()
    container = _container(client)
    final_keyframe = next(
        keyframe
        for keyframe in container.repositories.active_capture.list_keyframes_for_session(session_id)
        if keyframe.event_id == final["data"]["event"]["event_id"]
    )
    start_keyframe = next(
        keyframe
        for keyframe in container.repositories.active_capture.list_keyframes_for_session(session_id)
        if keyframe.event_id == start["data"]["event"]["event_id"]
    )
    assert final_keyframe.screenshot_evidence_id is not None
    assert final_keyframe.screenshot_artifact_id is not None
    assert start_keyframe.screenshot_evidence_id is not None
    assert start_keyframe.screenshot_artifact_id is not None
    hidden_action_response = client.post(
        f"/v1/active-captures/{session_id}/actions",
        headers=headers | {"x-workrecorder-install-secret": "test-install-secret"},
        json={
            "kind": HumanActionKind.CLICK.value,
            "occurred_at_monotonic_ms": 3_000,
            "coordinates": _action_coordinates().model_dump(mode="json"),
            "evidence_refs": [
                {
                    "role": HumanActionEvidenceRole.AFTER_KEYFRAME.value,
                    "keyframe_id": final_keyframe.keyframe_id,
                }
            ],
        },
    )
    hidden_action = hidden_action_response.json()
    hidden_target_hotkey_response = client.post(
        f"/v1/active-captures/{session_id}/actions",
        headers=headers | {"x-workrecorder-install-secret": "test-install-secret"},
        json={
            "kind": HumanActionKind.HOTKEY.value,
            "occurred_at_monotonic_ms": 3_100,
            "hotkey_semantic": HotkeySemantic.OPEN_COMMAND.value,
            "target": {
                "target_kind": "keyframe",
                "keyframe_id": final_keyframe.keyframe_id,
                "evidence_id": final_keyframe.screenshot_evidence_id,
                "artifact_id": final_keyframe.screenshot_artifact_id,
                "confidence": 1.0,
            },
        },
    )
    hidden_target_hotkey = hidden_target_hotkey_response.json()
    hidden_unkeyed_target_response = client.post(
        f"/v1/active-captures/{session_id}/actions",
        headers=headers | {"x-workrecorder-install-secret": "test-install-secret"},
        json={
            "kind": HumanActionKind.HOTKEY.value,
            "occurred_at_monotonic_ms": 3_200,
            "hotkey_semantic": HotkeySemantic.OPEN_COMMAND.value,
            "target": {
                "target_kind": "unknown",
                "evidence_id": final_keyframe.screenshot_evidence_id,
                "artifact_id": final_keyframe.screenshot_artifact_id,
                "confidence": 1.0,
            },
        },
    )
    hidden_unkeyed_target = hidden_unkeyed_target_response.json()
    client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers=headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER,
        json={},
    ).json()
    final_event = container.repositories.events.get(final["data"]["event"]["event_id"])
    assert final_event is not None
    container.events.mark_deleted(final_event)

    loaded = client.get(f"/v1/active-captures/{session_id}", headers=headers).json()
    storyboard = client.get(f"/v1/active-captures/{session_id}/storyboard", headers=headers).json()
    skill = client.get(f"/v1/active-captures/{session_id}/skill-distillation-input", headers=headers).json()
    storyboard_text = repr(storyboard["data"])
    skill_text = repr(skill["data"])

    assert hidden_action_response.status_code == 200, hidden_action_response.text
    assert hidden_target_hotkey_response.status_code == 200, hidden_target_hotkey_response.text
    assert hidden_unkeyed_target_response.status_code == 200, hidden_unkeyed_target_response.text
    assert hidden_action["data"]["kind"] == "click"
    assert hidden_target_hotkey["data"]["kind"] == "hotkey"
    assert hidden_unkeyed_target["data"]["kind"] == "hotkey"
    assert start["data"]["status"] == "accepted"
    assert len(loaded["data"]["keyframes"]) == 1
    assert loaded["data"]["keyframes"][0]["role"] == "start"
    assert len(loaded["data"]["timeline"]["entries"]) == 1
    assert loaded["data"]["timeline"]["entries"][0]["keyframe_id"] == loaded["data"]["keyframes"][0]["keyframe_id"]
    assert loaded["data"]["bundle"]["keyframe_count"] == 1
    assert final_keyframe.keyframe_id not in storyboard_text
    assert hidden_action["data"]["action_id"] not in storyboard_text
    assert hidden_target_hotkey["data"]["action_id"] not in storyboard_text
    assert hidden_unkeyed_target["data"]["action_id"] not in storyboard_text
    assert final_keyframe.keyframe_id not in skill_text
    assert hidden_action["data"]["action_id"] not in skill_text
    hotkey_step = next(
        step for step in skill["data"]["steps"] if step["step_id"] == hidden_target_hotkey["data"]["action_id"]
    )
    assert hotkey_step["needs_review"] is True
    assert hotkey_step["target"]["target_kind"] == "unknown"
    assert hotkey_step["target"]["keyframe_id"] is None
    assert hotkey_step["target"]["evidence_id"] is None
    assert hotkey_step["target"]["artifact_id"] is None
    scrubbed_target_step = next(
        step for step in skill["data"]["steps"] if step["step_id"] == hidden_unkeyed_target["data"]["action_id"]
    )
    assert scrubbed_target_step["target"]["keyframe_id"] is None
    assert scrubbed_target_step["target"]["evidence_id"] is None
    assert scrubbed_target_step["target"]["artifact_id"] is None


def test_active_session_view_filters_restricted_secondary_keyframe(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    start_request = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_restricted_start",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
        ),
    )
    final_request = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_restricted_final",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.FINAL,
            trigger_kind=KeyframeTriggerKind.RECORDING_STOP,
        ),
    )
    start = client.post("/v1/captures", headers=headers, json=start_request.model_dump(mode="json")).json()
    final = client.post("/v1/captures", headers=headers, json=final_request.model_dump(mode="json")).json()
    client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers=headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER,
        json={},
    ).json()
    container = _container(client)
    final_event = container.repositories.events.get(final["data"]["event"]["event_id"])
    assert final_event is not None
    container.repositories.events.save(
        final_event.model_copy(update={"status": EventStatus.RESTRICTED, "updated_at": container.clock.now()})
    )

    loaded = client.get(f"/v1/active-captures/{session_id}", headers=headers).json()

    assert len(loaded["data"]["keyframes"]) == 1
    assert start["data"]["event"]["event_id"] != final["data"]["event"]["event_id"]
    assert len(loaded["data"]["timeline"]["entries"]) == 1


def test_active_session_view_sanitizes_stale_timeline_after_keyframe_delete(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    for trigger_id, role in (
        ("trg_stale_start", KeyframeRole.START),
        ("trg_stale_final", KeyframeRole.FINAL),
    ):
        request = _active_capture_attempt(
            client,
            capture_save_request,
            trigger_id=trigger_id,
            binding=ActiveCaptureBinding(
                session_id=session_id,
                role=role,
                trigger_kind=(
                    KeyframeTriggerKind.RECORDING_START
                    if role == KeyframeRole.START
                    else KeyframeTriggerKind.RECORDING_STOP
                ),
            ),
        )
        client.post("/v1/captures", headers=headers, json=request.model_dump(mode="json")).json()
    client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers=headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER,
        json={},
    ).json()
    with _container(client).repositories.database.transaction() as connection:
        connection.execute(
            "DELETE FROM context_keyframes WHERE session_id = ? AND role = ?",
            (session_id, KeyframeRole.FINAL.value),
        )

    loaded = client.get(f"/v1/active-captures/{session_id}", headers=headers).json()

    assert len(loaded["data"]["keyframes"]) == 1
    assert loaded["data"]["keyframes"][0]["role"] == "start"
    assert loaded["data"]["bundle"]["keyframe_count"] == 1
    assert len(loaded["data"]["timeline"]["entries"]) == 1
    assert loaded["data"]["timeline"]["entries"][0]["keyframe_id"] == loaded["data"]["keyframes"][0]["keyframe_id"]


def test_active_session_route_hides_deleted_primary_event(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    session_id, event_id = _session_with_start_keyframe(client, token, capture_save_request, trigger_id="trg_primary")
    headers = {"authorization": f"Bearer {token}"}
    container = _container(client)
    event = container.repositories.events.get(event_id)
    assert event is not None
    container.events.mark_deleted(event)

    response = client.get(f"/v1/active-captures/{session_id}", headers=headers)

    assert response.status_code == 404


def test_recording_video_artifact_is_promoted_as_locked_metadata(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    start_request = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_video_start",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
        ),
    )
    capture = client.post("/v1/captures", headers=headers, json=start_request.model_dump(mode="json")).json()
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording.mp4"
    _write_mp4(video_path, duration_ms=1200)

    completed = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers=headers | {"x-workrecorder-install-secret": "test-install-secret"},
        json={
            "video": {
                "local_path": str(video_path),
                "content_type": "video/mp4",
                "filename": "recording.mp4",
                "duration_ms": 1200,
                "metadata": {
                    "producer_note": "SHOULD_NOT_LEAK_VIDEO_METADATA",
                    "localPath": "/Users/example/SHOULD_NOT_LEAK_VIDEO_PATH.mp4",
                    "typedTextPreview": "SHOULD_NOT_LEAK_VIDEO_TEXT",
                },
            }
        },
    ).json()
    video = completed["data"]["timeline"]["video"]
    metadata = client.get(f"/v1/artifacts/{video['artifact_id']}", headers=headers).json()
    verify = client.get(f"/v1/artifacts/{video['artifact_id']}/verify", headers=headers).json()
    event_artifacts = client.get(
        f"/v1/events/{capture['data']['event']['event_id']}?include=artifacts",
        headers=headers,
    ).json()
    raw = client.get(
        f"/v1/artifacts/{video['artifact_id']}/raw"
        f"?event_id={capture['data']['event']['event_id']}&purpose=verify_video_gate",
        headers={"authorization": f"Bearer {_token_with_scopes(client, ('read_metadata', 'read_raw_artifact'))}"},
    ).json()

    assert video["state"] == "available"
    assert video["content_type"] == "video/mp4"
    assert video["duration_ms"] == 1200
    assert "sha256" not in video
    assert "metadata" not in video
    assert "scope" not in completed["data"]["session"]
    assert "actor" not in completed["data"]["session"]
    assert metadata["data"]["artifact_type"] == "recording_video"
    assert "storage_uri" not in metadata["data"]
    assert "sha256" not in metadata["data"]
    assert metadata["data"]["metadata"] == {}
    assert metadata["data"]["allowed_scopes"] == ["read_metadata"]
    assert verify["data"]["ok"] is True
    assert "expected_sha256" not in verify["data"]
    assert "actual_sha256" not in verify["data"]
    recording_video_items = [
        item for item in event_artifacts["data"]["artifacts"] if item["artifact_type"] == "recording_video"
    ]
    assert recording_video_items
    assert "sha256" not in recording_video_items[0]
    assert recording_video_items[0]["metadata"] == {}
    artifact = _container(client).repositories.artifacts.get(video["artifact_id"])
    assert artifact is not None
    assert artifact.metadata["duration_ms"] == 1200
    assert artifact.metadata["session_id"] == session_id
    assert "SHOULD_NOT_LEAK" not in repr(artifact.metadata)
    assert raw["ok"] is False
    assert raw["error"]["code"] == "policy.denied"


def test_recording_segment_video_artifact_is_promoted_without_public_raw_metadata(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    session_id, event_id = _session_with_start_keyframe(
        client,
        token,
        capture_save_request,
        trigger_id="trg_segment_video",
    )
    container = _container(client)
    segment = container.repositories.active_capture.list_recording_segments_for_session(session_id)[0]
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_segment.mp4"
    _write_mp4(video_path, duration_ms=700)
    headers = {"authorization": f"Bearer {token}", "x-workrecorder-install-secret": "test-install-secret"}

    response = client.post(
        f"/v1/active-captures/{session_id}/segments",
        headers=headers,
        json={
            "segment_id": segment.segment_id,
            "state": RecordingSegmentState.AVAILABLE.value,
            "started_at_monotonic_ms": 100,
            "ended_at_monotonic_ms": 800,
            "duration_ms": 700,
            "staged_video": {
                "local_path": str(video_path),
                "content_type": "video/mp4",
                "duration_ms": 700,
            },
        },
    )
    payload = response.json()
    data = payload["data"]
    artifact_id = data["video"]["artifact_id"]
    manifest = client.get(
        f"/v1/active-captures/{session_id}/segments",
        headers={"authorization": f"Bearer {token}"},
    ).json()["data"]
    completed = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers=headers,
        json={"user_note": "segment-backed recording"},
    )
    completed_payload = completed.json()["data"]
    raw = client.get(
        f"/v1/artifacts/{artifact_id}/raw?event_id={event_id}&purpose=verify_segment_video_gate",
        headers={"authorization": f"Bearer {_token_with_scopes(client, ('read_metadata', 'read_raw_artifact'))}"},
    ).json()
    artifact = container.repositories.artifacts.get(artifact_id)
    internal_segment = container.repositories.active_capture.get_recording_segment(segment.segment_id)

    assert response.status_code == 200
    assert data["state"] == RecordingSegmentState.AVAILABLE.value
    assert data["video"]["state"] == "available"
    assert data["video"]["content_type"] == "video/mp4"
    assert data["video"]["duration_ms"] == 700
    assert "sha256" not in data["video"]
    assert "metadata" not in data["video"]
    assert "staged_video" not in data
    assert manifest["segments"][0]["video"]["artifact_id"] == artifact_id
    assert "sha256" not in manifest["segments"][0]["video"]
    assert completed.status_code == 200, completed.text
    assert completed_payload["timeline"]["video"]["artifact_id"] == artifact_id
    assert completed_payload["timeline"]["video"]["state"] == "available"
    assert artifact is not None
    assert artifact.metadata[RecordingVideoMetadataKey.SESSION_ID.value] == session_id
    assert artifact.metadata[RecordingVideoMetadataKey.SEGMENT_ID.value] == segment.segment_id
    assert artifact.metadata[RecordingVideoMetadataKey.SEGMENT_SEQUENCE_INDEX.value] == 0
    assert artifact.metadata[RecordingVideoMetadataKey.DURATION_MS.value] == 700
    assert internal_segment is not None
    assert internal_segment.staged_video is None
    assert internal_segment.video is not None
    assert internal_segment.video.artifact_id == artifact_id
    assert raw["ok"] is False
    assert raw["error"]["code"] == "policy.denied"
    assert not video_path.exists()

    with container.repositories.database.transaction() as connection:
        connection.execute("DELETE FROM artifacts WHERE artifact_id = ?", (artifact_id,))
    manifest_after_delete = client.get(
        f"/v1/active-captures/{session_id}/segments",
        headers={"authorization": f"Bearer {token}"},
    ).json()["data"]
    internal_after_delete = container.repositories.active_capture.get_recording_segment(segment.segment_id)

    assert manifest_after_delete["segments"][0]["video"] is None
    assert internal_after_delete is not None
    assert internal_after_delete.video is None


def test_complete_session_uses_longest_segment_video_when_stitched_video_is_absent(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    session_id, _event_id = _session_with_start_keyframe(
        client,
        token,
        capture_save_request,
        trigger_id="trg_multi_segment_video_fallback",
    )
    container = _container(client)
    headers = {"authorization": f"Bearer {token}", "x-workrecorder-install-secret": "test-install-secret"}
    first_segment = container.repositories.active_capture.list_recording_segments_for_session(session_id)[0]
    client.post(
        f"/v1/active-captures/{session_id}/controls",
        headers=headers,
        json={
            "kind": RecordingControlKind.PAUSE.value,
            "source": "native_client",
            "occurred_at_monotonic_ms": 900,
        },
    )
    client.post(
        f"/v1/active-captures/{session_id}/controls",
        headers=headers,
        json={
            "kind": RecordingControlKind.RESUME.value,
            "source": "native_client",
            "occurred_at_monotonic_ms": 1_200,
        },
    )
    second_segment = container.repositories.active_capture.list_recording_segments_for_session(session_id)[1]
    base_dir = Path(capture_save_request.staged_artifact.local_path).parent
    short_video = base_dir / "recording_segment_short.mp4"
    long_video = base_dir / "recording_segment_long.mp4"
    _write_mp4(short_video, duration_ms=300)
    _write_mp4(long_video, duration_ms=1_600)

    first = client.post(
        f"/v1/active-captures/{session_id}/segments",
        headers=headers,
        json={
            "segment_id": first_segment.segment_id,
            "state": RecordingSegmentState.AVAILABLE.value,
            "started_at_monotonic_ms": 100,
            "ended_at_monotonic_ms": 400,
            "duration_ms": 300,
            "staged_video": {
                "local_path": str(short_video),
                "content_type": "video/mp4",
                "duration_ms": 300,
            },
        },
    ).json()["data"]
    second = client.post(
        f"/v1/active-captures/{session_id}/segments",
        headers=headers,
        json={
            "segment_id": second_segment.segment_id,
            "state": RecordingSegmentState.AVAILABLE.value,
            "started_at_monotonic_ms": 1_200,
            "ended_at_monotonic_ms": 2_800,
            "duration_ms": 1_600,
            "staged_video": {
                "local_path": str(long_video),
                "content_type": "video/mp4",
                "duration_ms": 1_600,
            },
        },
    ).json()["data"]
    completed = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers=headers,
        json={
            "warnings": [
                {
                    "code": "video_unavailable",
                    "message": "stitched video unavailable; using segment video fallback",
                    "created_at": "2026-06-05T11:40:00Z",
                }
            ],
            "user_note": "multi segment fallback",
        },
    )
    payload = completed.json()["data"]

    assert completed.status_code == 200, completed.text
    assert payload["timeline"]["video"]["artifact_id"] == second["video"]["artifact_id"]
    assert payload["timeline"]["video"]["artifact_id"] != first["video"]["artifact_id"]
    assert payload["timeline"]["video"]["state"] == "available"
    assert payload["timeline"]["video"]["duration_ms"] == 1_600
    assert payload["session"]["status"] == "completed_with_warnings"


def test_recording_segment_video_validation_failure_does_not_persist_staged_path(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    session_id, event_id = _session_with_start_keyframe(
        client,
        token,
        capture_save_request,
        trigger_id="trg_segment_video_validation",
    )
    container = _container(client)
    segment = container.repositories.active_capture.list_recording_segments_for_session(session_id)[0]
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_segment_spoof.mp4"
    _write_mp4(video_path, duration_ms=700)

    response = client.post(
        f"/v1/active-captures/{session_id}/segments",
        headers={"authorization": f"Bearer {token}", "x-workrecorder-install-secret": "test-install-secret"},
        json={
            "segment_id": segment.segment_id,
            "state": RecordingSegmentState.AVAILABLE.value,
            "started_at_monotonic_ms": 100,
            "ended_at_monotonic_ms": 800,
            "duration_ms": 700,
            "staged_video": {
                "local_path": str(video_path),
                "content_type": "video/mp4",
                "duration_ms": 10_000,
            },
        },
    )
    internal_segment = container.repositories.active_capture.get_recording_segment(segment.segment_id)
    recording_videos = [
        artifact
        for artifact in container.repositories.artifacts.list_for_event(event_id)
        if artifact.artifact_type == ArtifactType.RECORDING_VIDEO
    ]

    assert response.status_code == 200
    assert response.json()["data"]["state"] == "failed"
    assert response.json()["data"]["video"]["failure_reason"] == "validation_failed"
    assert internal_segment is not None
    assert internal_segment.staged_video is None
    assert internal_segment.video is not None
    assert internal_segment.video.state.value == "failed"
    assert recording_videos == []
    assert video_path.exists()


def test_recording_segment_video_transient_failure_is_retryable_without_mutating_segment(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id, _event_id = _session_with_start_keyframe(
        client,
        token,
        capture_save_request,
        trigger_id="trg_segment_video_transient",
    )
    container = _container(client)
    segment = container.repositories.active_capture.list_recording_segments_for_session(session_id)[0]
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_segment_transient.mp4"
    _write_mp4(video_path, duration_ms=700)

    def fail_copy_video(**_kwargs):  # type: ignore[no-untyped-def]
        raise ArtifactVaultTransientError("simulated transient segment copy failure")

    monkeypatch.setattr(container.vault, "copy_video", fail_copy_video)
    response = client.post(
        f"/v1/active-captures/{session_id}/segments",
        headers={"authorization": f"Bearer {token}", "x-workrecorder-install-secret": "test-install-secret"},
        json={
            "segment_id": segment.segment_id,
            "state": RecordingSegmentState.AVAILABLE.value,
            "started_at_monotonic_ms": 100,
            "ended_at_monotonic_ms": 800,
            "duration_ms": 700,
            "staged_video": {"local_path": str(video_path), "content_type": "video/mp4", "duration_ms": 700},
        },
    )
    internal_segment = container.repositories.active_capture.get_recording_segment(segment.segment_id)

    assert response.status_code == 503
    assert response.json()["error"]["details"]["retryable"] is True
    assert internal_segment == segment
    assert video_path.exists()


def test_recording_segment_video_graph_write_failure_cleans_prepared_vault_file(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id, event_id = _session_with_start_keyframe(
        client,
        token,
        capture_save_request,
        trigger_id="trg_segment_video_graph_failure",
    )
    container = _container(client)
    segment = container.repositories.active_capture.list_recording_segments_for_session(session_id)[0]
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_segment_graph_fail.mp4"
    _write_mp4(video_path, duration_ms=700)
    vault_mp4_count = len(tuple(container.settings.artifact_vault_dir.rglob("*.mp4")))

    def fail_segment_graph(*, segment, artifacts=()):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated segment graph write failure")

    monkeypatch.setattr(container.repositories.active_capture, "save_recording_segment_graph", fail_segment_graph)
    command = AttachRecordingSegmentCommand(
        segment_id=segment.segment_id,
        state=RecordingSegmentState.AVAILABLE,
        started_at_monotonic_ms=100,
        ended_at_monotonic_ms=800,
        duration_ms=700,
        staged_video=StagedVideoArtifactRef(
            local_path=str(video_path),
            content_type=RecordingVideoContentType.MP4,
            duration_ms=700,
        ),
    )

    with pytest.raises(RuntimeError, match="simulated segment graph write failure"):
        container.active_capture.attach_recording_segment(session_id=session_id, command=command)
    recording_videos = [
        artifact
        for artifact in container.repositories.artifacts.list_for_event(event_id)
        if artifact.artifact_type == ArtifactType.RECORDING_VIDEO
    ]

    assert recording_videos == []
    assert len(tuple(container.settings.artifact_vault_dir.rglob("*.mp4"))) == vault_mp4_count
    assert video_path.exists()


def test_recording_segment_video_attach_is_idempotent_and_preserves_replacement_staging(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    session_id, event_id = _session_with_start_keyframe(
        client,
        token,
        capture_save_request,
        trigger_id="trg_segment_video_idempotent",
    )
    container = _container(client)
    segment = container.repositories.active_capture.list_recording_segments_for_session(session_id)[0]
    first_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_segment_idem.mp4"
    replacement_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_segment_replace.mp4"
    _write_mp4(first_path, duration_ms=700)
    _write_mp4(replacement_path, duration_ms=900)
    headers = {"authorization": f"Bearer {token}", "x-workrecorder-install-secret": "test-install-secret"}

    first = client.post(
        f"/v1/active-captures/{session_id}/segments",
        headers=headers,
        json={
            "segment_id": segment.segment_id,
            "state": RecordingSegmentState.AVAILABLE.value,
            "started_at_monotonic_ms": 100,
            "ended_at_monotonic_ms": 800,
            "duration_ms": 700,
            "staged_video": {"local_path": str(first_path), "content_type": "video/mp4", "duration_ms": 700},
        },
    ).json()
    second = client.post(
        f"/v1/active-captures/{session_id}/segments",
        headers=headers,
        json={
            "segment_id": segment.segment_id,
            "state": RecordingSegmentState.AVAILABLE.value,
            "started_at_monotonic_ms": 100,
            "ended_at_monotonic_ms": 800,
            "duration_ms": 700,
            "staged_video": {"local_path": str(replacement_path), "content_type": "video/mp4", "duration_ms": 900},
        },
    ).json()
    recording_videos = [
        artifact
        for artifact in container.repositories.artifacts.list_for_event(event_id)
        if artifact.artifact_type == ArtifactType.RECORDING_VIDEO
    ]

    assert first["data"]["video"]["artifact_id"] == second["data"]["video"]["artifact_id"]
    assert len(recording_videos) == 1
    assert not first_path.exists()
    assert replacement_path.exists()


def test_recording_video_completion_requires_install_secret(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    session_id, _event_id = _session_with_start_keyframe(
        client, token, capture_save_request, trigger_id="trg_video_secret"
    )
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_requires_secret.mp4"
    _write_mp4(video_path, duration_ms=1000)

    response = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers={"authorization": f"Bearer {token}"},
        json={"video": {"local_path": str(video_path), "content_type": "video/mp4", "duration_ms": 1000}},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "policy.denied"
    assert _container(client).active_capture.view_session(session_id).session.status.value == "recording"


def test_recording_video_duration_hint_mismatch_fails_video_without_promoting_artifact(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    session_id, event_id = _session_with_start_keyframe(
        client, token, capture_save_request, trigger_id="trg_video_duration_spoof"
    )
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_duration_spoof.mp4"
    _write_mp4(video_path, duration_ms=900)

    completed = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers={"authorization": f"Bearer {token}", "x-workrecorder-install-secret": "test-install-secret"},
        json={"video": {"local_path": str(video_path), "content_type": "video/mp4", "duration_ms": 10_000}},
    ).json()
    recording_videos = [
        artifact
        for artifact in _container(client).repositories.artifacts.list_for_event(event_id)
        if artifact.artifact_type == ArtifactType.RECORDING_VIDEO
    ]

    assert completed["data"]["session"]["status"] == "completed_with_warnings"
    assert completed["data"]["timeline"]["video"]["state"] == "failed"
    assert completed["data"]["timeline"]["video"]["failure_reason"] == "validation_failed"
    assert recording_videos == []


def test_recording_video_reserved_metadata_keys_are_not_accepted(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    session_id, event_id = _session_with_start_keyframe(
        client, token, capture_save_request, trigger_id="trg_video_reserved_metadata"
    )
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_reserved_metadata.mp4"
    _write_mp4(video_path, duration_ms=900)

    completed = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers={"authorization": f"Bearer {token}", "x-workrecorder-install-secret": "test-install-secret"},
        json={
            "video": {
                "local_path": str(video_path),
                "content_type": "video/mp4",
                "duration_ms": 900,
                "metadata": {"session_id": "spoofed-session"},
            }
        },
    ).json()
    recording_videos = [
        artifact
        for artifact in _container(client).repositories.artifacts.list_for_event(event_id)
        if artifact.artifact_type == ArtifactType.RECORDING_VIDEO
    ]

    assert completed["data"]["timeline"]["video"]["state"] == "failed"
    assert completed["data"]["timeline"]["video"]["failure_reason"] == "validation_failed"
    assert recording_videos == []


def test_complete_session_without_keyframes_or_video_fails_terminal_quality_policy(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]

    completed = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers=headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER,
        json={},
    ).json()

    assert completed["data"]["session"]["status"] == "failed"
    assert completed["data"]["bundle"]["status"] == "failed"
    assert completed["data"]["keyframes"] == []


def test_capture_retry_does_not_rebind_existing_event_to_new_session(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    first = client.post("/v1/captures", headers=headers, json=capture_save_request.model_dump(mode="json")).json()
    event_id = first["data"]["event"]["event_id"]
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    recording_session_id = create["data"]["session"]["session_id"]
    retry = (
        _container(client)
        .capture_attempts.from_legacy_save_request(capture_save_request)
        .model_copy(
            update={
                "active_capture": ActiveCaptureBinding(
                    session_id=recording_session_id,
                    role=KeyframeRole.START,
                    trigger_kind=KeyframeTriggerKind.RECORDING_START,
                )
            }
        )
    )

    second = client.post("/v1/captures", headers=headers, json=retry.model_dump(mode="json")).json()
    recording_view = client.get(f"/v1/active-captures/{recording_session_id}", headers=headers).json()
    event_keyframes = _container(client).active_capture.keyframes_for_event(event_id)

    assert second["data"]["event"]["event_id"] == event_id
    assert len(event_keyframes) == 1
    assert event_keyframes[0].role == KeyframeRole.ANCHOR
    assert recording_view["data"]["keyframes"] == []


def test_active_session_routes_hide_session_from_different_actor(
    client: TestClient,
    token: str,
) -> None:
    owner_headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=owner_headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    other_headers = {
        "authorization": f"Bearer {_token_with_scopes(client, ('read_metadata', 'create_event'), actor_id='other-cli')}"
    }

    read = client.get(f"/v1/active-captures/{session_id}", headers=other_headers)
    complete = client.post(f"/v1/active-captures/{session_id}/complete", headers=other_headers, json={})
    cancel = client.post(f"/v1/active-captures/{session_id}/cancel", headers=other_headers, json={"reason": "nope"})
    owner_view = client.get(f"/v1/active-captures/{session_id}", headers=owner_headers).json()

    assert read.status_code == 404
    assert complete.status_code == 404
    assert cancel.status_code == 404
    assert owner_view["data"]["session"]["status"] == "recording"


def test_active_session_routes_require_matching_workspace_header_for_workspace_session(
    client: TestClient,
    token: str,
) -> None:
    owner_headers = {"authorization": f"Bearer {token}", "x-workrecorder-workspace-id": "workspace_a"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=owner_headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    wrong_workspace_headers = {"authorization": f"Bearer {token}", "x-workrecorder-workspace-id": "workspace_b"}
    no_workspace_headers = {"authorization": f"Bearer {token}"}

    read_without_workspace = client.get(f"/v1/active-captures/{session_id}", headers=no_workspace_headers)
    read_wrong_workspace = client.get(f"/v1/active-captures/{session_id}", headers=wrong_workspace_headers)
    complete_wrong_workspace = client.post(
        f"/v1/active-captures/{session_id}/complete", headers=wrong_workspace_headers, json={}
    )
    owner_view = client.get(f"/v1/active-captures/{session_id}", headers=owner_headers)

    assert read_without_workspace.status_code == 404
    assert read_wrong_workspace.status_code == 404
    assert complete_wrong_workspace.status_code == 404
    assert owner_view.status_code == 200


def test_active_session_create_rejects_body_workspace_without_matching_header(
    client: TestClient,
    token: str,
) -> None:
    response = client.post(
        "/v1/active-captures/sessions",
        headers={"authorization": f"Bearer {token}"},
        json={
            "mode": ActiveCaptureMode.RECORDING_SESSION.value,
            "workspace_id": "workspace_a",
            "start_recording": True,
        },
    )

    assert response.status_code == 422


def test_scoped_session_rejects_keyframe_binding_from_wrong_display(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={
            "mode": ActiveCaptureMode.RECORDING_SESSION.value,
            "start_recording": True,
            "scope": RecordingScope(
                kind=RecordingScopeKind.REGION,
                display_id="display_other",
                selection_region=BoundingBox(x=120, y=140, width=520, height=280),
            ).model_dump(mode="json"),
        },
    ).json()
    session_id = create["data"]["session"]["session_id"]
    attempt = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_wrong_display",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
        ),
    )

    saved = client.post("/v1/captures", headers=headers, json=attempt.model_dump(mode="json")).json()
    loaded = client.get(f"/v1/active-captures/{session_id}", headers=headers).json()

    assert saved["data"]["status"] == "accepted"
    assert loaded["data"]["keyframes"] == []


def test_scoped_session_rejects_keyframe_binding_from_wrong_region(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={
            "mode": ActiveCaptureMode.RECORDING_SESSION.value,
            "start_recording": True,
            "scope": RecordingScope(
                kind=RecordingScopeKind.REGION,
                display_id="display_main",
                selection_region=BoundingBox(x=900, y=700, width=120, height=100),
            ).model_dump(mode="json"),
        },
    ).json()
    session_id = create["data"]["session"]["session_id"]
    attempt = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_wrong_region",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
        ),
    )

    saved = client.post("/v1/captures", headers=headers, json=attempt.model_dump(mode="json")).json()
    loaded = client.get(f"/v1/active-captures/{session_id}", headers=headers).json()

    assert saved["data"]["status"] == "accepted"
    assert loaded["data"]["keyframes"] == []


def test_scoped_session_rejects_tiny_selection_inside_large_region(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={
            "mode": ActiveCaptureMode.RECORDING_SESSION.value,
            "start_recording": True,
            "scope": RecordingScope(
                kind=RecordingScopeKind.REGION,
                display_id="display_main",
                selection_region=BoundingBox(x=0, y=0, width=1200, height=800),
            ).model_dump(mode="json"),
        },
    ).json()
    session_id = create["data"]["session"]["session_id"]
    attempt = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_tiny_region",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
        ),
    )

    saved = client.post("/v1/captures", headers=headers, json=attempt.model_dump(mode="json")).json()
    loaded = client.get(f"/v1/active-captures/{session_id}", headers=headers).json()

    assert saved["data"]["status"] == "accepted"
    assert loaded["data"]["keyframes"] == []


def test_complete_session_is_idempotent_and_preserves_promoted_video(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    session_id, event_id = _session_with_start_keyframe(client, token, capture_save_request, trigger_id="trg_idem")
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_idempotent.mp4"
    _write_mp4(video_path, duration_ms=1400)
    headers = {"authorization": f"Bearer {token}"}

    first = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers=headers | {"x-workrecorder-install-secret": "test-install-secret"},
        json={"video": {"local_path": str(video_path), "content_type": "video/mp4", "duration_ms": 1400}},
    ).json()
    replacement_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_replacement.mp4"
    _write_mp4(replacement_path, duration_ms=1800)
    second = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers=headers | {"x-workrecorder-install-secret": "test-install-secret"},
        json={"video": {"local_path": str(replacement_path), "content_type": "video/mp4", "duration_ms": 1800}},
    ).json()
    artifacts = _container(client).repositories.artifacts.list_for_event(event_id)
    recording_videos = [artifact for artifact in artifacts if artifact.artifact_type.value == "recording_video"]

    assert first["data"]["timeline"]["video"]["state"] == "available"
    assert second["data"]["timeline"]["video"]["artifact_id"] == first["data"]["timeline"]["video"]["artifact_id"]
    assert second["data"]["session"]["status"] == "completed_with_warnings"
    assert len(recording_videos) == 1
    assert replacement_path.exists()


def test_complete_retry_reuses_promoted_video_after_graph_write_failure(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id, event_id = _session_with_start_keyframe(client, token, capture_save_request, trigger_id="trg_retry")
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_retry.mp4"
    _write_mp4(video_path, duration_ms=1400)
    container = _container(client)
    original_complete_graph = container.repositories.active_capture.complete_session_graph
    calls = {"count": 0}

    def flaky_complete_graph(*, session, timeline, bundle, artifacts=()):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated graph write failure")
        return original_complete_graph(session=session, timeline=timeline, bundle=bundle, artifacts=artifacts)

    monkeypatch.setattr(container.repositories.active_capture, "complete_session_graph", flaky_complete_graph)
    command = CompleteActiveCaptureSessionCommand(
        video=StagedVideoArtifactRef(
            local_path=str(video_path),
            content_type=RecordingVideoContentType.MP4,
            duration_ms=1400,
        )
    )

    with pytest.raises(RuntimeError, match="simulated graph write failure"):
        container.active_capture.complete_session(session_id=session_id, command=command)

    artifacts_after_failure = container.repositories.artifacts.list_for_event(event_id)
    recording_videos_after_failure = [
        artifact for artifact in artifacts_after_failure if artifact.artifact_type == ArtifactType.RECORDING_VIDEO
    ]
    assert len(recording_videos_after_failure) == 0
    assert video_path.exists() is True

    retried = container.active_capture.complete_session(session_id=session_id, command=command)
    recording_videos_after_retry = [
        artifact
        for artifact in container.repositories.artifacts.list_for_event(event_id)
        if artifact.artifact_type == ArtifactType.RECORDING_VIDEO
    ]

    assert retried.timeline is not None
    assert retried.timeline.video.artifact_id == recording_videos_after_retry[0].artifact_id
    assert retried.timeline.video.state.value == "available"
    assert retried.session.status.value == "completed_with_warnings"
    assert len(recording_videos_after_retry) == 1
    assert video_path.exists() is False


def test_transient_video_copy_failure_keeps_session_retryable(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id, event_id = _session_with_start_keyframe(
        client, token, capture_save_request, trigger_id="trg_copy_retry"
    )
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_copy_retry.mp4"
    _write_mp4(video_path, duration_ms=1400)
    container = _container(client)

    def fail_copy_video(**_kwargs):  # type: ignore[no-untyped-def]
        raise ArtifactVaultTransientError("simulated transient copy failure")

    monkeypatch.setattr(container.vault, "copy_video", fail_copy_video)
    command = CompleteActiveCaptureSessionCommand(
        video=StagedVideoArtifactRef(
            local_path=str(video_path),
            content_type=RecordingVideoContentType.MP4,
            duration_ms=1400,
        )
    )

    with pytest.raises(ArtifactVaultTransientError):
        container.active_capture.complete_session(session_id=session_id, command=command)
    session = container.active_capture.view_session(session_id).session
    recording_videos = [
        artifact
        for artifact in container.repositories.artifacts.list_for_event(event_id)
        if artifact.artifact_type == ArtifactType.RECORDING_VIDEO
    ]

    assert session.status.value == "recording"
    assert video_path.exists() is True
    assert recording_videos == []


def test_transient_video_copy_failure_returns_retryable_503(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id, _event_id = _session_with_start_keyframe(
        client, token, capture_save_request, trigger_id="trg_copy_retry_route"
    )
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_copy_retry_route.mp4"
    _write_mp4(video_path, duration_ms=1400)
    container = _container(client)

    def fail_copy_video(**_kwargs):  # type: ignore[no-untyped-def]
        raise ArtifactVaultTransientError("simulated transient copy failure")

    monkeypatch.setattr(container.vault, "copy_video", fail_copy_video)

    response = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers={"authorization": f"Bearer {token}", "x-workrecorder-install-secret": "test-install-secret"},
        json={
            "video": {
                "local_path": str(video_path),
                "content_type": "video/mp4",
                "duration_ms": 1400,
            }
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["details"]["retryable"] is True
    assert container.active_capture.view_session(session_id).session.status.value == "recording"


def test_complete_rejects_client_supplied_timeline_manifest(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]

    response = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers=headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER,
        json={"timeline": {"session_id": session_id, "manifest_id": "tlm_spoof"}},
    )

    assert response.status_code == 422
    assert response.json()["ok"] is False


def test_complete_rejects_client_supplied_monotonic_clock(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]

    response = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers=headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER,
        json={"started_at_monotonic_ms": 1, "ended_at_monotonic_ms": 999_999},
    )

    assert response.status_code == 422
    assert response.json()["ok"] is False


def test_complete_rejects_recording_timing_for_different_session(
    client: TestClient,
    token: str,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]

    response = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers=headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER,
        json=CompleteActiveCaptureSessionCommand(
            recording_timing=RecordingTimingAnchor(
                authority=NativeCaptureTimingAuthority.MACOS_CAPTURE,
                session_id="acs_other",
                source_clock=NativeTimingClock.SYSTEM_UPTIME_MS,
                started_at_monotonic_ms=100,
                ended_at_monotonic_ms=200,
            )
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_capture_binding_rejects_client_supplied_timeline_fields(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    attempt = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_media_spoof",
        binding=ActiveCaptureBinding(
            session_id=create["data"]["session"]["session_id"],
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
        ),
    ).model_dump(mode="json")
    attempt["active_capture"]["media_time_ms"] = 999_999
    attempt["active_capture"]["captured_at_monotonic_ms"] = 999_999
    attempt["active_capture"]["sequence_index"] = 999_999

    response = client.post("/v1/captures", headers=headers | INSTALL_SECRET_HEADER, json=attempt)

    assert response.status_code == 422
    assert response.json()["ok"] is False


def test_native_timing_receipt_requires_local_native_authority(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    attempt = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_untrusted_native_timing",
        binding=ActiveCaptureBinding(
            session_id=create["data"]["session"]["session_id"],
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
        ),
    ).model_dump(mode="json")
    attempt["native_timing_receipt"] = {
        "authority": NativeCaptureTimingAuthority.MACOS_CAPTURE.value,
        "captured_at_monotonic_ms": 123_456,
        "source_clock": "system_uptime_ms",
    }

    response = client.post("/v1/captures", headers=headers | INSTALL_SECRET_HEADER, json=attempt)

    assert response.status_code == 403
    payload = response.json()
    assert payload["error"]["code"] == "policy.denied"
    assert payload["audit_id"]
    assert _container(client).repositories.ledger.get_envelope_by_trigger_id("trg_untrusted_native_timing") is None
    audits = tuple(
        audit
        for audit in _container(client).repositories.audits.list(limit=20)
        if audit.audit_id == payload["audit_id"]
    )
    assert audits[0].details["reason"] == "native_timing_receipt_secret_missing"


def test_active_capture_binding_requires_trusted_workspace_header_for_scoped_session(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    scoped_workspace_id = "workspace-scoped-active-capture"
    scoped_headers = {
        "authorization": f"Bearer {token}",
        "x-workrecorder-workspace-id": scoped_workspace_id,
    }
    create = client.post(
        "/v1/active-captures/sessions",
        headers=scoped_headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]

    spoofed_without_header = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_workspace_spoof_no_header",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
        ),
    ).model_dump(mode="json")
    spoofed_without_header["workspace"] = {
        "workspace_id": scoped_workspace_id,
        "label": "Scoped Active Capture",
        "auto": False,
    }
    saved = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}"},
        json=spoofed_without_header,
    )
    loaded_after_spoof = client.get(f"/v1/active-captures/{session_id}", headers=scoped_headers).json()

    assert saved.status_code == 200
    assert saved.json()["data"]["status"] == "accepted"
    assert loaded_after_spoof["data"]["keyframes"] == []

    wrong_header_attempt = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_workspace_spoof_wrong_header",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
        ),
    ).model_dump(mode="json")
    wrong_header_attempt["workspace"] = {
        "workspace_id": scoped_workspace_id,
        "label": "Scoped Active Capture",
        "auto": False,
    }
    wrong_header = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}", "x-workrecorder-workspace-id": "other-workspace"},
        json=wrong_header_attempt,
    )

    assert wrong_header.status_code == 422
    assert wrong_header.json()["error"]["code"] == "validation_error"

    trusted_attempt = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_workspace_trusted_header",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
        ),
    ).model_dump(mode="json")
    trusted_attempt["workspace"] = {"workspace_id": "auto", "label": "Auto", "auto": True}
    trusted = client.post("/v1/captures", headers=scoped_headers, json=trusted_attempt)
    loaded_after_trusted = client.get(f"/v1/active-captures/{session_id}", headers=scoped_headers).json()

    assert trusted.status_code == 200
    assert len(loaded_after_trusted["data"]["keyframes"]) == 1
    assert _container(client).active_capture.keyframes_for_event(trusted.json()["data"]["event"]["event_id"])


def test_terminal_session_ignores_later_keyframe_binding(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    session_id, _event_id = _session_with_start_keyframe(client, token, capture_save_request, trigger_id="trg_terminal")
    headers = {"authorization": f"Bearer {token}"}
    completed = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers=headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER,
        json={},
    ).json()
    late_request = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_terminal_late",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.FINAL,
            trigger_kind=KeyframeTriggerKind.RECORDING_STOP,
        ),
    )
    late = client.post("/v1/captures", headers=headers, json=late_request.model_dump(mode="json")).json()
    loaded = client.get(f"/v1/active-captures/{session_id}", headers=headers).json()

    assert completed["data"]["session"]["status"] == "completed_with_warnings"
    assert late["data"]["status"] == "accepted"
    assert len(loaded["data"]["keyframes"]) == 1
    assert loaded["data"]["keyframes"][0]["role"] == "start"


def test_cancelled_session_ignores_later_keyframe_binding(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    session_id, _event_id = _session_with_start_keyframe(client, token, capture_save_request, trigger_id="trg_cancel")
    headers = {"authorization": f"Bearer {token}"}
    cancelled = client.post(
        f"/v1/active-captures/{session_id}/cancel",
        headers=headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER,
        json={"reason": "test"},
    ).json()
    late_request = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id="trg_cancel_late",
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.FINAL,
            trigger_kind=KeyframeTriggerKind.RECORDING_STOP,
        ),
    )
    client.post("/v1/captures", headers=headers, json=late_request.model_dump(mode="json")).json()
    loaded = client.get(f"/v1/active-captures/{session_id}", headers=headers).json()

    assert cancelled["data"]["session"]["status"] == "cancelled"
    assert len(loaded["data"]["keyframes"]) == 1
    assert loaded["data"]["keyframes"][0]["role"] == "start"


def test_active_capture_disabled_does_not_create_anchor_side_effect(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    container = _container(client)
    container.active_capture.config.enabled = False

    saved = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}"},
        json=capture_save_request.model_dump(mode="json"),
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    with container.repositories.database.transaction() as connection:
        session_count = connection.execute("SELECT COUNT(*) AS count FROM active_capture_sessions").fetchone()["count"]

    assert saved["data"]["status"] == "accepted"
    assert container.active_capture.keyframes_for_event(event_id) == ()
    assert session_count == 0


def test_active_capture_disabled_rejects_headless_session_create(
    client: TestClient,
    token: str,
) -> None:
    container = _container(client)
    container.active_capture.config.enabled = False

    response = client.post(
        "/v1/active-captures/sessions",
        headers={"authorization": f"Bearer {token}"},
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    )
    with container.repositories.database.transaction() as connection:
        session_count = connection.execute("SELECT COUNT(*) AS count FROM active_capture_sessions").fetchone()["count"]

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert session_count == 0


def test_video_raw_policy_denies_recording_video_even_with_agent_run(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    session_id, event_id = _session_with_start_keyframe(client, token, capture_save_request, trigger_id="trg_raw_video")
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_raw_policy.mp4"
    _write_mp4(video_path, duration_ms=900)
    completed = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers={"authorization": f"Bearer {token}", "x-workrecorder-install-secret": "test-install-secret"},
        json={"video": {"local_path": str(video_path), "content_type": "video/mp4", "duration_ms": 900}},
    ).json()
    artifact = _container(client).repositories.artifacts.get(completed["data"]["timeline"]["video"]["artifact_id"])
    assert artifact is not None

    result = _container(client).disclosure.raw_artifact(
        artifact=artifact,
        actor=ActorRef(actor_id="test-cli"),
        purpose="verify video raw gate",
        agent_run_id="run_video_policy",
        event_id=event_id,
    )

    assert isinstance(result, ApiError)
    assert result.code.value == "policy.denied"
    assert result.details["artifact_type"] == "recording_video"


def test_recording_video_raw_route_denies_even_after_prior_ref_gate(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id, event_id = _session_with_start_keyframe(
        client, token, capture_save_request, trigger_id="trg_raw_video_route"
    )
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_raw_route.mp4"
    _write_mp4(video_path, duration_ms=900)
    completed = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers={"authorization": f"Bearer {token}", "x-workrecorder-install-secret": "test-install-secret"},
        json={"video": {"local_path": str(video_path), "content_type": "video/mp4", "duration_ms": 900}},
    ).json()
    artifact_id = completed["data"]["timeline"]["video"]["artifact_id"]
    assert artifact_id is not None, completed
    container = _container(client)

    monkeypatch.setattr(
        container.repositories.agent_run_traces,
        "has_successful_screenshot_ref_delivery",
        lambda *, agent_run_id, artifact_id, event_id: True,
    )
    begin = client.post(
        "/v1/agent-runs",
        headers={"authorization": f"Bearer {token}"},
        json={"agent": "codex", "purpose": "verify_video_raw_route", "user_question": "Need recording video"},
    )
    assert begin.status_code == 200, begin.text
    run_id = begin.json()["data"]["agent_run_id"]
    raw_token = _token_with_scopes(client, ("read_metadata", "read_raw_artifact"))

    response = client.get(
        f"/v1/artifacts/{artifact_id}/raw?event_id={event_id}&purpose=verify_video_raw_route&agent_run_id={run_id}",
        headers={"authorization": f"Bearer {raw_token}"},
    )

    assert response.status_code == 403, response.text
    payload = response.json()
    assert payload["error"]["code"] == "policy.denied"
    assert payload["error"]["details"]["artifact_type"] == "recording_video"
    assert payload["retrieval_call_id"]


def test_recording_video_playback_route_returns_video_after_explicit_user_request(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    session_id, event_id = _session_with_start_keyframe(
        client, token, capture_save_request, trigger_id="trg_play_recording_video"
    )
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_playback.mp4"
    _write_mp4(video_path, duration_ms=1100)
    expected_video = video_path.read_bytes()
    completed = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers={"authorization": f"Bearer {token}", "x-workrecorder-install-secret": "test-install-secret"},
        json={"video": {"local_path": str(video_path), "content_type": "video/mp4", "duration_ms": 1100}},
    ).json()
    artifact_id = completed["data"]["timeline"]["video"]["artifact_id"]
    raw_token = _token_with_scopes(client, ("read_metadata", "read_raw_artifact"), actor_id="workrecorder-workbench")

    response_without_local_secret = client.post(
        f"/v1/active-captures/{session_id}/video/playback",
        headers={"authorization": f"Bearer {raw_token}"},
        json={"event_id": event_id, "artifact_id": artifact_id, "purpose": "workbench_user_play_recording"},
    )
    response = client.post(
        f"/v1/active-captures/{session_id}/video/playback",
        headers={"authorization": f"Bearer {raw_token}", "x-workrecorder-install-secret": "test-install-secret"},
        json={"event_id": event_id, "artifact_id": artifact_id, "purpose": "workbench_user_play_recording"},
    )

    assert response_without_local_secret.status_code == 403, response_without_local_secret.text
    assert response_without_local_secret.json()["error"]["code"] == "policy.denied"
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["ok"] is True
    playback = payload["data"]
    assert playback["session_id"] == session_id
    assert playback["event_id"] == event_id
    assert playback["artifact_id"] == artifact_id
    assert playback["content_type"] == "video/mp4"
    assert "content_base64" not in playback
    assert Path(playback["playback_file_path"]).read_bytes() == expected_video
    assert playback["byte_size"] == len(expected_video)


def test_recording_export_route_materializes_directory_after_explicit_user_request(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    tmp_path: Path,
) -> None:
    session_id, event_id = _session_with_start_keyframe(
        client, token, capture_save_request, trigger_id="trg_export_recording"
    )
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_export.mp4"
    _write_mp4(video_path, duration_ms=1100)
    client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers={"authorization": f"Bearer {token}", "x-workrecorder-install-secret": "test-install-secret"},
        json={"video": {"local_path": str(video_path), "content_type": "video/mp4", "duration_ms": 1100}},
    )
    raw_token = _token_with_scopes(client, ("read_metadata", "read_raw_artifact"), actor_id="workrecorder-workbench")
    output_root = tmp_path / "exported"

    response_without_local_secret = client.post(
        f"/v1/active-captures/{session_id}/export",
        headers={"authorization": f"Bearer {raw_token}"},
        json={"output_root": str(output_root)},
    )
    response = client.post(
        f"/v1/active-captures/{session_id}/export",
        headers={"authorization": f"Bearer {raw_token}", "x-workrecorder-install-secret": "test-install-secret"},
        json={
            "output_root": str(output_root),
            "purpose": "workbench_user_export_recording",
            "fallback_mode": "click_only",
        },
    )

    assert response_without_local_secret.status_code == 403, response_without_local_secret.text
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()["data"]
    assert payload["session_id"] == session_id
    assert payload["keyframe_dir_count"] >= 1
    assert payload["video_file_count"] == 1
    recording_dir = Path(payload["output_dir"])
    assert recording_dir.parent == output_root
    assert (recording_dir / "recording.json").is_file()
    assert json.loads((recording_dir / "recording.json").read_text(encoding="utf-8"))["fallback_mode"] == "click_only"
    assert (recording_dir / "trajectory.json").is_file()
    assert (recording_dir / "summary.md").is_file()
    assert (recording_dir / "video.mp4").is_file()
    keyframe_dirs = sorted(path for path in recording_dir.iterdir() if path.is_dir())
    assert keyframe_dirs, "expected at least one keyframe folder"
    assert (keyframe_dirs[0] / "meta.json").is_file()
    assert (keyframe_dirs[0] / "actions.json").is_file()


def test_workbench_inspect_can_open_native_created_recording_detail(
    client: TestClient,
    capture_save_request: CaptureSaveRequest,
) -> None:
    native_token = _token_with_scopes(
        client,
        ("read_metadata", "read_text", "create_event"),
        actor_id="macos-capture",
    )
    session_id, event_id = _session_with_start_keyframe(
        client,
        native_token,
        capture_save_request,
        trigger_id="trg_workbench_native_recording",
    )
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_workbench_open.mp4"
    _write_mp4(video_path, duration_ms=1250)
    completed = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers={"authorization": f"Bearer {native_token}", "x-workrecorder-install-secret": "test-install-secret"},
        json={"video": {"local_path": str(video_path), "content_type": "video/mp4", "duration_ms": 1250}},
    ).json()
    workbench_token = _token_with_scopes(
        client,
        ("read_metadata", "read_text"),
        actor_id="workrecorder-workbench",
    )

    inspect = client.get(
        f"/v1/events/{event_id}"
        "?view=event_inspect&purpose=workbench_inspect"
        "&inspect_views=active_capture_summary,recording_timeline,video_ref,human_demo_summary",
        headers={"authorization": f"Bearer {workbench_token}"},
    )

    assert inspect.status_code == 200, inspect.text
    active_capture = inspect.json()["data"]["active_capture"]
    assert active_capture["session_id"] == session_id
    assert active_capture["video_ref"]["artifact_id"] == completed["data"]["timeline"]["video"]["artifact_id"]
    assert active_capture["video_ref"]["state"] == "available"
    assert active_capture["timeline"]["steps"]


def test_recording_video_playback_route_rejects_wrong_event_or_artifact(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
) -> None:
    session_id, event_id = _session_with_start_keyframe(
        client, token, capture_save_request, trigger_id="trg_play_reject_video"
    )
    video_path = Path(capture_save_request.staged_artifact.local_path).parent / "recording_playback_reject.mp4"
    _write_mp4(video_path, duration_ms=1100)
    completed = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers={"authorization": f"Bearer {token}", "x-workrecorder-install-secret": "test-install-secret"},
        json={"video": {"local_path": str(video_path), "content_type": "video/mp4", "duration_ms": 1100}},
    ).json()
    artifact_id = completed["data"]["timeline"]["video"]["artifact_id"]
    raw_token = _token_with_scopes(client, ("read_metadata", "read_raw_artifact"), actor_id="workrecorder-workbench")

    playback_headers = {"authorization": f"Bearer {raw_token}", "x-workrecorder-install-secret": "test-install-secret"}
    wrong_event = client.post(
        f"/v1/active-captures/{session_id}/video/playback",
        headers=playback_headers,
        json={"event_id": "evt_wrong", "artifact_id": artifact_id, "purpose": "workbench_user_play_recording"},
    )
    wrong_artifact = client.post(
        f"/v1/active-captures/{session_id}/video/playback",
        headers=playback_headers,
        json={"event_id": event_id, "artifact_id": "art_wrong", "purpose": "workbench_user_play_recording"},
    )
    missing_artifact = client.post(
        f"/v1/active-captures/{session_id}/video/playback",
        headers=playback_headers,
        json={"event_id": event_id, "purpose": "workbench_user_play_recording"},
    )

    assert wrong_event.status_code == 404, wrong_event.text
    assert wrong_event.json()["error"]["code"] == "not_found"
    assert wrong_artifact.status_code == 403, wrong_artifact.text
    assert wrong_artifact.json()["error"]["code"] == "policy.denied"
    assert missing_artifact.status_code == 422, missing_artifact.text


def _container(client: TestClient) -> DaemonContainer:
    return cast(DaemonContainer, cast(FastAPI, client.app).state.container)


def _action_coordinates() -> ActionCoordinates:
    return ActionCoordinates(
        screen_abs=ActionPoint(x=120.0, y=240.0, coordinate_space=CoordinateSpace.MACOS_GLOBAL, display_id="main"),
        screenshot_rel=ActionPoint(x=20.0, y=40.0, coordinate_space=CoordinateSpace.ARTIFACT_PX),
        scope_rel=ActionPoint(x=10.0, y=30.0, coordinate_space=CoordinateSpace.WINDOW_PX),
    )


def _token_with_scopes(client: TestClient, scopes: tuple[str, ...], *, actor_id: str = "test-cli") -> str:
    response = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": actor_id, "display_name": "Test CLI", "scopes": list(scopes)},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    return str(payload["data"]["access_token"])


def _active_capture_attempt(
    client: TestClient,
    capture_save_request: CaptureSaveRequest,
    *,
    trigger_id: str,
    binding: ActiveCaptureBinding,
) -> Any:
    container = _container(client)
    staged_file = Path(capture_save_request.staged_artifact.local_path).parent / f"{trigger_id}.png"
    _write_png(staged_file)
    attempt = container.capture_attempts.from_legacy_save_request(capture_save_request)
    trigger = attempt.trigger.model_copy(
        update={
            "trigger_id": trigger_id,
            "occurred_at": datetime.now(UTC),
        }
    )
    return attempt.model_copy(
        update={
            "trigger": trigger,
            "active_capture": binding,
            "staged_artifact": attempt.staged_artifact.model_copy(update={"local_path": str(staged_file)}),
        }
    )


def _session_with_start_keyframe(
    client: TestClient,
    token: str,
    capture_save_request: CaptureSaveRequest,
    *,
    trigger_id: str,
) -> tuple[str, str]:
    headers = {"authorization": f"Bearer {token}"}
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    start_request = _active_capture_attempt(
        client,
        capture_save_request,
        trigger_id=trigger_id,
        binding=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
        ),
    )
    capture = client.post("/v1/captures", headers=headers, json=start_request.model_dump(mode="json")).json()
    return session_id, str(capture["data"]["event"]["event_id"])


def _write_png(path: Path) -> None:
    image = Image.new("RGB", (120, 80), "#f7fbfc")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())


def _write_mp4(path: Path, *, duration_ms: int) -> None:
    def box(kind: bytes, payload: bytes) -> bytes:
        return (len(payload) + 8).to_bytes(4, byteorder="big") + kind + payload

    ftyp = box(b"ftyp", b"mp42\x00\x00\x00\x00mp42isom")
    mvhd_payload = (
        b"\x00\x00\x00\x00"
        + (0).to_bytes(4, byteorder="big")
        + (0).to_bytes(4, byteorder="big")
        + (1000).to_bytes(4, byteorder="big")
        + duration_ms.to_bytes(4, byteorder="big")
    )
    moov = box(b"moov", box(b"mvhd", mvhd_payload))
    mdat = box(b"mdat", b"workrecorder-test-video")
    path.write_bytes(ftyp + moov + mdat)
