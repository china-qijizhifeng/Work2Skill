from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from packages.contracts import (
    ActiveCaptureBinding,
    ActiveCaptureMode,
    ActorRef,
    ArtifactType,
    BoundingBox,
    CaptureAttemptRequest,
    CaptureStrategy,
    CoordinateSpace,
    CreateActiveCaptureSessionCommand,
    DisplayGeometry,
    HumanActionKind,
    KeyframeKeepReason,
    KeyframeRole,
    KeyframeTriggerKind,
    NativeCaptureTimingAuthority,
    NativeCaptureTimingReceipt,
    NativeTimingClock,
    ProducerInputEventKind,
    RecordingScope,
    SelectionGeometry,
    StagedArtifactRef,
    TriggerEnvelope,
    TriggerType,
    WindowHint,
    WorkspaceSelection,
)
from packages.shared.config import WorkRecorderSettings
from services.context_daemon.container import DaemonContainer

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WORKRECORDER_RUN_MACOS_INPUT_E2E") != "1",
        reason="macOS native input listener E2E is opt-in; set WORKRECORDER_RUN_MACOS_INPUT_E2E=1",
    ),
    pytest.mark.skipif(sys.platform != "darwin", reason="macOS native input listener E2E requires macOS"),
]

REPO_ROOT = Path(__file__).resolve().parents[2]
MACOS_CAPTURE_ROOT = REPO_ROOT / "apps" / "macos_capture"
INSTALL_SECRET = "test-install-secret"
NATIVE_CAPTURE_SECRET = "test-native-secret"
INSTALL_SECRET_HEADER = {"x-workrecorder-install-secret": INSTALL_SECRET}
NATIVE_CAPTURE_SECRET_HEADER = {"x-workrecorder-native-capture-secret": NATIVE_CAPTURE_SECRET}


def test_real_macos_input_listener_events_create_trace_triggers_and_keyframes(
    client: TestClient,
    token: str,
    settings: WorkRecorderSettings,
) -> None:
    report = _run_native_input_listener_harness()
    events = _required_sequence(report, "events")
    assert events, report
    event_kinds = {_required_str(cast(Mapping[str, object], event), "event_kind") for event in events}
    assert event_kinds >= {
        ProducerInputEventKind.POINTER_CLICK.value,
        ProducerInputEventKind.SCROLL.value,
        ProducerInputEventKind.HOTKEY.value,
        ProducerInputEventKind.TYPING_PAUSE.value,
    }
    _assert_listener_did_not_emit_raw_typing(events)

    workspace_id = "macos-input-listener-e2e"
    headers = {
        "authorization": f"Bearer {token}",
        "x-workrecorder-workspace-id": workspace_id,
    }
    scope = RecordingScope.model_validate(_required_mapping(report, "scope"))
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json=CreateActiveCaptureSessionCommand(
            mode=ActiveCaptureMode.RECORDING_SESSION,
            start_recording=False,
            scope=scope,
            metadata={"fixture": "macos_input_listener_e2e"},
        ).model_dump(mode="json"),
    )
    assert create.status_code == 200, create.text
    session_id = str(create.json()["data"]["session"]["session_id"])

    producer_responses: list[Mapping[str, object]] = []
    captured_keyframes = 0
    captured_instruction_ids: set[str] = set()
    for index, event in enumerate(events):
        event_payload = dict(cast(Mapping[str, object], event))
        response = client.post(
            f"/v1/active-captures/{session_id}/producer-events",
            headers=headers | INSTALL_SECRET_HEADER,
            json=event_payload,
        )
        assert response.status_code == 200, response.text
        result = cast(Mapping[str, object], response.json()["data"]["results"][0])
        producer_responses.append(result)
        occurred_at = event_payload.get("occurred_at_monotonic_ms")
        now_monotonic_ms = occurred_at if isinstance(occurred_at, int) else 0
        instructions = [
            instruction
            for instruction in (
                _capture_instruction(result),
                *_pending_capture_instructions(
                    client=client,
                    session_id=session_id,
                    headers=headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER,
                    now_monotonic_ms=now_monotonic_ms + 5_000,
                ),
            )
            if instruction is not None and str(instruction.get("candidate_id")) not in captured_instruction_ids
        ]
        for offset, instruction in enumerate(instructions):
            captured_instruction_ids.add(str(instruction.get("candidate_id")))
            staged_path = settings.artifact_staging_dir / f"native-input-listener-keyframe-{index}-{offset}.png"
            _write_keyframe_png(staged_path, label=f"native input {index}: {event_payload['event_kind']}")
            captured = client.post(
                "/v1/captures",
                headers=headers | NATIVE_CAPTURE_SECRET_HEADER,
                json=_capture_attempt_payload(
                    report=report,
                    session_id=session_id,
                    instruction=instruction,
                    staged_path=staged_path,
                    workspace_id=workspace_id,
                    trigger_id=f"trg_macos_input_listener_{index}_{offset}",
                ),
            )
            assert captured.status_code == 200, captured.text
            captured_keyframes += 1

    assert captured_keyframes >= 2, producer_responses

    response_kinds = {_required_str(_required_mapping(item, "event"), "event_kind") for item in producer_responses}
    assert response_kinds >= {
        ProducerInputEventKind.POINTER_CLICK.value,
        ProducerInputEventKind.SCROLL.value,
        ProducerInputEventKind.HOTKEY.value,
        ProducerInputEventKind.TYPING_PAUSE.value,
    }
    assert any(
        _required_mapping(item, "action").get("hotkey_semantic") == "open_command" for item in producer_responses
    )
    assert any(_trigger_candidate_kind(item) == "command_submitted" for item in producer_responses)

    container = _container(client)
    stored_events = container.repositories.active_capture.list_producer_events_for_session(session_id)
    stored_actions = container.repositories.active_capture.list_human_actions_for_session(session_id)
    stored_keyframes = container.repositories.active_capture.list_keyframes_for_session(session_id)
    assert {event.event_kind for event in stored_events} >= {
        ProducerInputEventKind.POINTER_CLICK,
        ProducerInputEventKind.SCROLL,
        ProducerInputEventKind.HOTKEY,
        ProducerInputEventKind.TYPING_PAUSE,
    }
    assert {action.kind for action in stored_actions} >= {
        HumanActionKind.CLICK,
        HumanActionKind.SCROLL,
        HumanActionKind.HOTKEY,
        HumanActionKind.TYPING_PAUSE,
    }
    assert len(stored_keyframes) >= captured_keyframes
    assert any(
        container.repositories.active_capture.list_action_evidence_links(action.action_id)
        for action in stored_actions
        if action.kind in {HumanActionKind.CLICK, HumanActionKind.HOTKEY}
    )

    skill = client.get(f"/v1/active-captures/{session_id}/skill-distillation-input", headers=headers)
    assert skill.status_code == 200, skill.text
    skill_payload = skill.json()["data"]
    steps = skill_payload["steps"]
    assert any(step["key_chord"] and step["key_chord"]["normalized_key_label"] == "k" for step in steps)
    assert any(step["action_kind"] == "typing_pause" for step in steps)
    assert any(step["evidence_keyframe_ids"] for step in steps if step["action_kind"] in {"click", "hotkey"})
    assert "typed_text" not in skill.text


def _run_native_input_listener_harness() -> Mapping[str, object]:
    if shutil.which("swift") is None:
        pytest.skip("swift is not available for macOS native input listener E2E")
    build = subprocess.run(
        ["swift", "build", "--target", "WorkRecorderCapture"],
        cwd=MACOS_CAPTURE_ROOT,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert build.returncode == 0, build.stderr or build.stdout
    executable = MACOS_CAPTURE_ROOT / ".build" / "debug" / "WorkRecorderCapture"
    run = subprocess.run(
        [str(executable), "--active-capture-input-listener-e2e"],
        cwd=MACOS_CAPTURE_ROOT,
        text=True,
        capture_output=True,
        timeout=25,
        check=False,
    )
    report = _parse_json_report(run.stdout)
    if report is not None and report.get("status") in {"permission_denied", "no_events", "focus_not_owned"}:
        pytest.skip(_permission_diagnostic(report, run.stderr))
    assert run.returncode == 0, run.stderr or run.stdout
    assert report is not None, run.stderr or run.stdout
    assert report.get("status") == "ok", report
    return report


def _parse_json_report(stdout: str) -> Mapping[str, object] | None:
    for line in reversed(stdout.splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        parsed: object = json.loads(stripped)
        assert isinstance(parsed, Mapping)
        return parsed
    return None


def _permission_diagnostic(report: Mapping[str, object], stderr: str) -> str:
    diagnostics = report.get("diagnostics", ())
    if not isinstance(diagnostics, list):
        diagnostics = []
    return (
        "macOS native input listener E2E could not safely observe events. "
        "Grant Input Monitoring and Accessibility to the test runner/Terminal, "
        "and make sure the harness can become the foreground app before it posts input. "
        f"then retry. status={report.get('status')} diagnostics={diagnostics} stderr={stderr.strip()}"
    )


def _assert_listener_did_not_emit_raw_typing(events: tuple[object, ...]) -> None:
    serialized = json.dumps(events, ensure_ascii=False).lower()
    assert "typed_text" not in serialized
    assert "raw_text" not in serialized
    typing_events = [
        cast(Mapping[str, object], event)
        for event in events
        if _required_str(cast(Mapping[str, object], event), "event_kind") == ProducerInputEventKind.TYPING_PAUSE.value
    ]
    assert typing_events
    for event in typing_events:
        keyboard = _required_mapping(event, "keyboard")
        assert keyboard.get("key_chord") is None
        summary = _required_mapping(keyboard, "typing_summary")
        assert _required_int(summary, "character_count") >= 1
        assert "normalized_key_label" not in json.dumps(summary)


def _capture_instruction(result: Mapping[str, object]) -> Mapping[str, object] | None:
    trigger = result.get("trigger")
    if not isinstance(trigger, Mapping):
        return None
    instruction = trigger.get("capture_instruction")
    return instruction if isinstance(instruction, Mapping) else None


def _pending_capture_instructions(
    *,
    client: TestClient,
    session_id: str,
    headers: Mapping[str, str],
    now_monotonic_ms: int,
) -> tuple[Mapping[str, object], ...]:
    response = client.post(
        f"/v1/active-captures/{session_id}/capture-instructions/pending",
        headers=dict(headers),
        json={"now_monotonic_ms": now_monotonic_ms, "limit": 16},
    )
    assert response.status_code == 200, response.text
    instructions = response.json()["data"]["instructions"]
    return tuple(item for item in instructions if isinstance(item, Mapping))


def _trigger_candidate_kind(result: Mapping[str, object]) -> str | None:
    trigger = result.get("trigger")
    if not isinstance(trigger, Mapping):
        return None
    candidate = trigger.get("candidate")
    if not isinstance(candidate, Mapping):
        return None
    kind = candidate.get("trigger_kind")
    return kind if isinstance(kind, str) else None


def _capture_attempt_payload(
    *,
    report: Mapping[str, object],
    session_id: str,
    instruction: Mapping[str, object],
    staged_path: Path,
    workspace_id: str,
    trigger_id: str,
) -> dict[str, object]:
    binding = _required_mapping(instruction, "binding")
    target = BoundingBox.model_validate(_required_mapping(report, "target_frame"))
    display = DisplayGeometry(
        display_id="macos-input-listener-display",
        frame=BoundingBox(
            x=0,
            y=0,
            width=max(target.x + target.width + 32, target.width),
            height=max(target.y + target.height + 32, target.height),
            coordinate_space=CoordinateSpace.MACOS_GLOBAL,
        ),
        scale_factor=1.0,
    )
    actor = ActorRef(actor_id="test-cli", display_name="macOS Native Input Listener E2E")
    attempt = CaptureAttemptRequest(
        schema_version=1,
        trigger=TriggerEnvelope(
            trigger_id=trigger_id,
            trigger_type=TriggerType.MANUAL_OS_REGION_HOTKEY,
            capture_strategy=CaptureStrategy.OS_REGION,
            actor=actor,
            occurred_at=datetime.now(UTC),
            selection=target,
            intent_text="macOS native input listener E2E",
        ),
        selection_geometry=SelectionGeometry(selected_region=target, display=display),
        window_hints=(
            WindowHint(
                app_name="WorkRecorderCapture",
                title="WorkRecorder Native Input Listener E2E",
                process_id=None,
                window_id=None,
                frame=target,
                overlap_ratio=1.0,
                confidence=0.95,
                bundle_id="io.workrecorder.capture",
                display_id=display.display_id,
                visible_area_ratio=1.0,
                is_frontmost=True,
            ),
        ),
        workspace=WorkspaceSelection(workspace_id=workspace_id, label="macOS Native Input Listener E2E", auto=False),
        actor=actor,
        staged_artifact=StagedArtifactRef(
            local_path=str(staged_path),
            artifact_type=ArtifactType.SCREENSHOT,
            content_type="image/png",
            filename=staged_path.name,
        ),
        intent_text="macOS native input listener E2E",
        active_capture=ActiveCaptureBinding(
            session_id=session_id,
            role=KeyframeRole(_required_str(binding, "role")),
            trigger_kind=KeyframeTriggerKind(_required_str(binding, "trigger_kind")),
            keep_reason=_optional_keep_reason(binding, "keep_reason"),
            candidate_id=_optional_str(binding, "candidate_id"),
            metadata={"fixture": "macos_input_listener_e2e"},
        ),
        native_timing_receipt=NativeCaptureTimingReceipt(
            authority=NativeCaptureTimingAuthority.MACOS_CAPTURE,
            captured_at_monotonic_ms=_optional_int(instruction, "execute_after_monotonic_ms") or 0,
            source_clock=NativeTimingClock.SYSTEM_UPTIME_MS,
            recorded_at_wall_time=datetime.now(UTC),
            metadata={"fixture": "macos_input_listener_e2e"},
        ),
    )
    return attempt.model_dump(mode="json")


def _write_keyframe_png(path: Path, *, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (640, 360), "#eef8f8")
    draw = ImageDraw.Draw(image)
    draw.rectangle((32, 32, 608, 328), outline="#2d7a82", width=4)
    draw.rectangle((72, 92, 568, 244), fill="#f7fbfc", outline="#e08d57", width=3)
    draw.text((92, 122), label, fill="#17484d")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())


def _required_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload[key]
    assert isinstance(value, Mapping), f"{key} must be an object"
    return value


def _required_sequence(payload: Mapping[str, object], key: str) -> tuple[object, ...]:
    value = payload[key]
    assert isinstance(value, list), f"{key} must be a list"
    return tuple(value)


def _required_str(payload: Mapping[str, object], key: str) -> str:
    value = payload[key]
    assert isinstance(value, str), f"{key} must be a string"
    return value


def _required_int(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    assert isinstance(value, int) and not isinstance(value, bool), f"{key} must be an integer"
    return value


def _optional_str(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    assert isinstance(value, str), f"{key} must be a string"
    return value


def _optional_int(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    assert isinstance(value, int) and not isinstance(value, bool), f"{key} must be an integer"
    return value


def _optional_keep_reason(payload: Mapping[str, object], key: str) -> KeyframeKeepReason | None:
    value = payload.get(key)
    if value is None:
        return None
    assert isinstance(value, str), f"{key} must be a string"
    return KeyframeKeepReason(value)


def _container(client: TestClient) -> DaemonContainer:
    app = cast(FastAPI, client.app)
    return cast(DaemonContainer, getattr(app.state, "container"))
