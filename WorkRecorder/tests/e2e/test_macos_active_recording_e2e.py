from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageChops, ImageStat

from packages.contracts import (
    ActionCoordinates,
    ActionPoint,
    ActiveCaptureBinding,
    ActiveCaptureMode,
    ActorRef,
    ArtifactType,
    BoundingBox,
    CaptureAttemptRequest,
    CaptureStrategy,
    CompleteActiveCaptureSessionCommand,
    CoordinateSpace,
    CreateActiveCaptureSessionCommand,
    DisplayGeometry,
    HotkeySemantic,
    HumanActionKind,
    KeyboardEventKind,
    KeyboardInputClass,
    KeyCapturePolicy,
    KeyframeKeepReason,
    KeyframeRole,
    KeyframeTriggerKind,
    ModifierKey,
    NativeCaptureTimingAuthority,
    NativeCaptureTimingReceipt,
    NativeTimingClock,
    PointerButton,
    ProducerInputEventKind,
    RecordingControlKind,
    RecordingScope,
    RecordingScopeKind,
    RecordingSegmentState,
    RecordingTimingAnchor,
    RecordingVideoContentType,
    ScrollPhase,
    SelectionGeometry,
    StagedArtifactRef,
    StagedVideoArtifactRef,
    TriggerEnvelope,
    TriggerType,
    WindowHint,
    WorkspaceSelection,
)
from packages.shared.config import WorkRecorderSettings
from services.context_daemon.container import DaemonContainer

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WORKRECORDER_RUN_MACOS_RECORDING_E2E") != "1",
        reason="macOS ScreenCaptureKit recording E2E is opt-in; set WORKRECORDER_RUN_MACOS_RECORDING_E2E=1",
    ),
    pytest.mark.skipif(sys.platform != "darwin", reason="macOS ScreenCaptureKit recording E2E requires macOS"),
]

REPO_ROOT = Path(__file__).resolve().parents[2]
MACOS_CAPTURE_ROOT = REPO_ROOT / "apps" / "macos_capture"
INSTALL_SECRET = "test-install-secret"
NATIVE_CAPTURE_SECRET = "test-native-secret"
INSTALL_SECRET_HEADER = {"x-workrecorder-install-secret": INSTALL_SECRET}
NATIVE_CAPTURE_SECRET_HEADER = {"x-workrecorder-native-capture-secret": NATIVE_CAPTURE_SECRET}


class FixtureStatus(StrEnum):
    OK = "ok"


class RecordingBackendValue(StrEnum):
    SCREEN_CAPTURE_KIT = "ScreenCaptureKit"


class RecordingContentFilterValue(StrEnum):
    DESKTOP_INDEPENDENT_WINDOW = "desktopIndependentWindow"


@dataclass(frozen=True)
class FixtureRect:
    x: int
    y: int
    width: int
    height: int
    coordinate_space: CoordinateSpace

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "FixtureRect":
        return cls(
            x=_required_int(payload, "x"),
            y=_required_int(payload, "y"),
            width=_required_int(payload, "width"),
            height=_required_int(payload, "height"),
            coordinate_space=CoordinateSpace(_required_str(payload, "coordinate_space")),
        )

    def to_bbox(self) -> BoundingBox:
        return BoundingBox(
            x=self.x,
            y=self.y,
            width=self.width,
            height=self.height,
            coordinate_space=self.coordinate_space,
        )


@dataclass(frozen=True)
class DisplayFixture:
    display_id: str
    frame: FixtureRect
    scale_factor: float

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "DisplayFixture":
        return cls(
            display_id=_required_str(payload, "display_id"),
            frame=FixtureRect.from_payload(_required_mapping(payload, "frame")),
            scale_factor=_required_float(payload, "scale_factor"),
        )


@dataclass(frozen=True)
class WindowFixture:
    title: str
    app_name: str
    bundle_id: str
    process_id: int
    window_id: str | None
    frame: FixtureRect
    expected_content_width: int
    expected_content_height: int

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "WindowFixture":
        window_id = payload.get("window_id")
        return cls(
            title=_required_str(payload, "title"),
            app_name=_required_str(payload, "app_name"),
            bundle_id=_required_str(payload, "bundle_id"),
            process_id=_required_int(payload, "process_id"),
            window_id=str(window_id) if window_id is not None else None,
            frame=FixtureRect.from_payload(_required_mapping(payload, "frame")),
            expected_content_width=_required_int(payload, "expected_content_width"),
            expected_content_height=_required_int(payload, "expected_content_height"),
        )


@dataclass(frozen=True)
class SentinelOcclusionFixture:
    overlaps_target: bool
    overlap_area: int
    overlap_frame: FixtureRect | None

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "SentinelOcclusionFixture":
        overlap_frame = payload.get("overlap_frame")
        return cls(
            overlaps_target=_required_bool(payload, "overlaps_target"),
            overlap_area=_required_int(payload, "overlap_area"),
            overlap_frame=(FixtureRect.from_payload(overlap_frame) if isinstance(overlap_frame, Mapping) else None),
        )


@dataclass(frozen=True)
class RecordingTimingFixture:
    started_monotonic_ms: int
    first_frame_monotonic_ms: int
    final_frame_monotonic_ms: int
    ended_monotonic_ms: int

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "RecordingTimingFixture":
        return cls(
            started_monotonic_ms=_required_int(payload, "started_monotonic_ms"),
            first_frame_monotonic_ms=_required_int(payload, "first_frame_monotonic_ms"),
            final_frame_monotonic_ms=_required_int(payload, "final_frame_monotonic_ms"),
            ended_monotonic_ms=_required_int(payload, "ended_monotonic_ms"),
        )


@dataclass(frozen=True)
class ProducerEventFixture:
    kind: ProducerInputEventKind
    occurred_at_monotonic_ms: int
    x: float | None
    y: float | None
    delta_x: float | None
    delta_y: float | None
    key_code: int | None
    key_label: str | None
    modifiers: tuple[ModifierKey, ...]
    semantic: HotkeySemantic | None
    typing_event_count: int | None
    typing_character_count: int | None

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "ProducerEventFixture":
        raw_modifiers = payload.get("modifiers", ())
        assert isinstance(raw_modifiers, list)
        semantic = payload.get("semantic")
        return cls(
            kind=ProducerInputEventKind(_required_str(payload, "kind")),
            occurred_at_monotonic_ms=_required_int(payload, "occurred_at_monotonic_ms"),
            x=_optional_float(payload, "x"),
            y=_optional_float(payload, "y"),
            delta_x=_optional_float(payload, "delta_x"),
            delta_y=_optional_float(payload, "delta_y"),
            key_code=_optional_int(payload, "key_code"),
            key_label=_optional_str(payload, "key_label"),
            modifiers=tuple(ModifierKey(str(item)) for item in raw_modifiers),
            semantic=HotkeySemantic(str(semantic)) if semantic is not None else None,
            typing_event_count=_optional_int(payload, "typing_event_count"),
            typing_character_count=_optional_int(payload, "typing_character_count"),
        )


@dataclass(frozen=True)
class RecordingFixture:
    status: FixtureStatus
    recording_backend: RecordingBackendValue
    content_filter: RecordingContentFilterValue
    video_path: Path
    start_keyframe_path: Path
    final_keyframe_path: Path
    requested_duration_ms: int
    duration_ms: int
    container_duration_ms: int
    frame_count: int
    video_width: int
    video_height: int
    display: DisplayFixture
    target_window: WindowFixture
    sentinel_window: WindowFixture
    sentinel_occlusion: SentinelOcclusionFixture
    timing: RecordingTimingFixture
    producer_events: tuple[ProducerEventFixture, ...]

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "RecordingFixture":
        return cls(
            status=FixtureStatus(_required_str(payload, "status")),
            recording_backend=RecordingBackendValue(_required_str(payload, "recording_backend")),
            content_filter=RecordingContentFilterValue(_required_str(payload, "content_filter")),
            video_path=Path(_required_str(payload, "video_path")),
            start_keyframe_path=Path(_required_str(payload, "start_keyframe_path")),
            final_keyframe_path=Path(_required_str(payload, "final_keyframe_path")),
            requested_duration_ms=_required_int(payload, "requested_duration_ms"),
            duration_ms=_required_int(payload, "duration_ms"),
            container_duration_ms=_required_int(payload, "container_duration_ms"),
            frame_count=_required_int(payload, "frame_count"),
            video_width=_required_int(payload, "video_width"),
            video_height=_required_int(payload, "video_height"),
            display=DisplayFixture.from_payload(_required_mapping(payload, "display")),
            target_window=WindowFixture.from_payload(_required_mapping(payload, "target_window")),
            sentinel_window=WindowFixture.from_payload(_required_mapping(payload, "sentinel_window")),
            sentinel_occlusion=SentinelOcclusionFixture.from_payload(_required_mapping(payload, "sentinel_occlusion")),
            timing=RecordingTimingFixture.from_payload(_required_mapping(payload, "timing")),
            producer_events=tuple(
                ProducerEventFixture.from_payload(item)
                for item in _required_sequence(payload, "producer_events")
                if isinstance(item, Mapping)
            ),
        )


def test_macos_screencapturekit_window_recording_flows_into_active_capture_backend(
    client: TestClient,
    token: str,
    settings: WorkRecorderSettings,
) -> None:
    fixture = _run_native_recording_fixture(settings.artifact_staging_dir / "native-recording-e2e")
    _assert_window_only_keyframes(fixture)
    video_path = fixture.video_path
    video_bytes = fixture.video_path.read_bytes()
    final_keyframe_bytes = fixture.final_keyframe_path.read_bytes()
    video_sha256 = hashlib.sha256(video_bytes).hexdigest()
    assert len(video_bytes) > 20_000
    assert video_bytes[4:8] == b"ftyp"
    assert fixture.recording_backend == RecordingBackendValue.SCREEN_CAPTURE_KIT
    assert fixture.content_filter == RecordingContentFilterValue.DESKTOP_INDEPENDENT_WINDOW
    assert fixture.container_duration_ms > 0
    assert fixture.frame_count >= 20
    assert 2_500 <= fixture.container_duration_ms <= 5_000

    workspace_id = "macos-recording-e2e"
    headers = {
        "authorization": f"Bearer {token}",
        "x-workrecorder-workspace-id": workspace_id,
    }
    create = client.post(
        "/v1/active-captures/sessions",
        headers=headers,
        json=CreateActiveCaptureSessionCommand(
            mode=ActiveCaptureMode.RECORDING_SESSION,
            start_recording=True,
            scope=_recording_scope(fixture),
        ).model_dump(mode="json"),
    )
    assert create.status_code == 200, create.text
    session_id = str(create.json()["data"]["session"]["session_id"])
    initial_segments = client.get(f"/v1/active-captures/{session_id}/segments", headers=headers)
    assert initial_segments.status_code == 200, initial_segments.text
    initial_segment_id = str(initial_segments.json()["data"]["segments"][0]["segment_id"])
    attached_segment = client.post(
        f"/v1/active-captures/{session_id}/segments",
        headers=headers | INSTALL_SECRET_HEADER,
        json={
            "segment_id": initial_segment_id,
            "state": RecordingSegmentState.RECORDING.value,
            "started_at_monotonic_ms": fixture.timing.first_frame_monotonic_ms,
        },
    )
    assert attached_segment.status_code == 200, attached_segment.text

    start = client.post(
        "/v1/captures",
        headers=headers | NATIVE_CAPTURE_SECRET_HEADER,
        json=_capture_attempt_payload(
            fixture=fixture,
            session_id=session_id,
            role=KeyframeRole.START,
            trigger_kind=KeyframeTriggerKind.RECORDING_START,
            trigger_id="trg_macos_recording_e2e_start",
            staged_path=fixture.start_keyframe_path,
            captured_at_monotonic_ms=fixture.timing.first_frame_monotonic_ms,
            workspace_id=workspace_id,
        ),
    )
    assert start.status_code == 200, start.text
    start_payload = start.json()
    assert start_payload["data"]["status"] == "accepted"

    final = client.post(
        "/v1/captures",
        headers=headers | NATIVE_CAPTURE_SECRET_HEADER,
        json=_capture_attempt_payload(
            fixture=fixture,
            session_id=session_id,
            role=KeyframeRole.FINAL,
            trigger_kind=KeyframeTriggerKind.RECORDING_STOP,
            trigger_id="trg_macos_recording_e2e_final",
            staged_path=fixture.final_keyframe_path,
            captured_at_monotonic_ms=fixture.timing.final_frame_monotonic_ms,
            workspace_id=workspace_id,
        ),
    )
    assert final.status_code == 200, final.text
    final_payload = final.json()
    assert final_payload["data"]["status"] == "accepted"
    native_delta_ms = fixture.timing.final_frame_monotonic_ms - fixture.timing.first_frame_monotonic_ms

    action = client.post(
        f"/v1/active-captures/{session_id}/actions",
        headers=headers | INSTALL_SECRET_HEADER,
        json={
            "kind": HumanActionKind.CLICK.value,
            "occurred_at_monotonic_ms": fixture.timing.final_frame_monotonic_ms,
            "media_time_ms": fixture.timing.final_frame_monotonic_ms - fixture.timing.first_frame_monotonic_ms,
            "coordinates": _action_coordinates(fixture).model_dump(mode="json"),
            "metadata": {"producer": "ScreenCaptureKit", "fixture": "macos_recording_e2e"},
        },
    )
    assert action.status_code == 200, action.text
    assert action.json()["data"]["kind"] == "click"
    assert abs(action.json()["data"]["media_time_ms"] - native_delta_ms) <= 5
    assert "coordinates" not in action.json()["data"]

    producer_responses = [
        client.post(
            f"/v1/active-captures/{session_id}/producer-events",
            headers=headers | INSTALL_SECRET_HEADER,
            json=_producer_event_payload(fixture, event),
        )
        for event in fixture.producer_events
    ]
    assert producer_responses, "native fixture must emit input producer event fixtures"
    assert all(response.status_code == 200 for response in producer_responses), [
        response.text for response in producer_responses
    ]
    producer_payloads = [response.json()["data"]["results"][0] for response in producer_responses]
    assert {item["event"]["event_kind"] for item in producer_payloads} >= {
        "pointer_click",
        "scroll",
        "hotkey",
        "typing_pause",
    }
    hotkey_payloads = [item for item in producer_payloads if item["event"]["event_kind"] == "hotkey"]
    assert any(item["action"]["hotkey_semantic"] == "open_command" for item in hotkey_payloads)
    assert any(item["trigger"]["candidate"]["trigger_kind"] == "command_submitted" for item in hotkey_payloads)
    pending_response = client.post(
        f"/v1/active-captures/{session_id}/capture-instructions/pending",
        headers=headers | INSTALL_SECRET_HEADER | NATIVE_CAPTURE_SECRET_HEADER,
        json={"now_monotonic_ms": fixture.timing.final_frame_monotonic_ms + 5_000, "limit": 32},
    )
    assert pending_response.status_code == 200, pending_response.text
    pending_instructions = [
        item for item in pending_response.json()["data"]["instructions"] if isinstance(item, Mapping)
    ]
    all_instructions: list[Mapping[str, object]] = []
    seen_instruction_ids: set[str] = set()
    for item in producer_payloads:
        instruction = item.get("trigger", {}).get("capture_instruction") if item.get("trigger") else None
        if not isinstance(instruction, Mapping):
            continue
        candidate_id = str(instruction.get("candidate_id"))
        if candidate_id in seen_instruction_ids:
            continue
        seen_instruction_ids.add(candidate_id)
        all_instructions.append(instruction)
    for instruction in pending_instructions:
        candidate_id = str(instruction.get("candidate_id"))
        if candidate_id in seen_instruction_ids:
            continue
        seen_instruction_ids.add(candidate_id)
        all_instructions.append(instruction)

    producer_capture_count = 0
    for index, instruction in enumerate(all_instructions):
        binding = _required_mapping(instruction, "binding")
        execute_after = instruction.get("execute_after_monotonic_ms")
        captured_at_monotonic_ms = execute_after if isinstance(execute_after, int) else 0
        producer_frame = fixture.final_keyframe_path.parent / f"producer-keyframe-{index}.png"
        producer_frame.write_bytes(final_keyframe_bytes)
        captured = client.post(
            "/v1/captures",
            headers=headers | NATIVE_CAPTURE_SECRET_HEADER,
            json=_capture_attempt_payload(
                fixture=fixture,
                session_id=session_id,
                role=KeyframeRole(_required_str(binding, "role")),
                trigger_kind=KeyframeTriggerKind(_required_str(binding, "trigger_kind")),
                trigger_id=f"trg_macos_recording_e2e_producer_{index}",
                staged_path=producer_frame,
                captured_at_monotonic_ms=captured_at_monotonic_ms,
                workspace_id=workspace_id,
                candidate_id=_optional_str(binding, "candidate_id"),
                keep_reason=None,
            ),
        )
        assert captured.status_code == 200, captured.text
        producer_capture_count += 1
    assert producer_capture_count >= 2, producer_payloads

    mark = client.post(
        f"/v1/active-captures/{session_id}/controls",
        headers=headers | INSTALL_SECRET_HEADER,
        json={
            "kind": RecordingControlKind.USER_MARK.value,
            "occurred_at_monotonic_ms": fixture.timing.final_frame_monotonic_ms,
            "note": "native e2e mark",
        },
    )
    assert mark.status_code == 200, mark.text

    trigger = client.post(
        f"/v1/active-captures/{session_id}/triggers",
        headers=headers | INSTALL_SECRET_HEADER,
        json={
            "trigger_kind": KeyframeTriggerKind.CLICK_SETTLE.value,
            "occurred_at_monotonic_ms": fixture.timing.final_frame_monotonic_ms + 1_000,
            "metadata": {"producer": "ScreenCaptureKit", "fixture": "macos_recording_e2e"},
        },
    )
    assert trigger.status_code == 200, trigger.text
    assert trigger.json()["data"]["candidate"]["status"] == "accepted"
    assert trigger.json()["data"]["capture_instruction"]["binding"]["candidate_id"]

    complete = client.post(
        f"/v1/active-captures/{session_id}/complete",
        headers=headers | INSTALL_SECRET_HEADER,
        json=CompleteActiveCaptureSessionCommand(
            recording_timing=RecordingTimingAnchor(
                authority=NativeCaptureTimingAuthority.MACOS_CAPTURE,
                session_id=session_id,
                source_clock=NativeTimingClock.SYSTEM_UPTIME_MS,
                started_at_monotonic_ms=fixture.timing.first_frame_monotonic_ms,
                ended_at_monotonic_ms=fixture.timing.final_frame_monotonic_ms,
                started_at_wall_time=datetime.now(UTC),
                ended_at_wall_time=datetime.now(UTC),
                metadata={"producer": "ScreenCaptureKit", "fixture": "macos_recording_e2e"},
            ),
            video=StagedVideoArtifactRef(
                local_path=str(video_path),
                content_type=RecordingVideoContentType.MP4,
                filename=video_path.name,
                duration_ms=fixture.container_duration_ms,
                metadata={
                    "producer": "ScreenCaptureKit",
                    "recording_backend": fixture.recording_backend.value,
                    "content_filter": fixture.content_filter.value,
                    "frame_count": fixture.frame_count,
                    "e2e_fixture": True,
                },
            ),
        ).model_dump(mode="json"),
    )
    assert complete.status_code == 200, complete.text
    loaded = client.get(f"/v1/active-captures/{session_id}", headers=headers)
    assert loaded.status_code == 200, loaded.text
    view = loaded.json()["data"]

    assert view["session"]["status"] == "completed"
    assert len(view["keyframes"]) >= 4
    assert {"start", "final"}.issubset({item["role"] for item in view["keyframes"]})
    assert all(item["screenshot_artifact_id"] for item in view["keyframes"])
    assert all(item["screenshot_evidence_id"] for item in view["keyframes"])
    assert all(item["system_appshot_evidence_id"] for item in view["keyframes"])
    assert all(item["quality"]["screenshot_available"] for item in view["keyframes"])
    assert all(item["quality"]["system_appshot_available"] for item in view["keyframes"])

    video = view["timeline"]["video"]
    assert video["state"] == "available"
    assert video["content_type"] == "video/mp4"
    assert video["byte_size"] == len(video_bytes)
    assert video["duration_ms"] == fixture.container_duration_ms
    assert not video_path.exists()

    entries = view["timeline"]["entries"]
    assert {"start", "final", "settle"}.issubset({entry["role"] for entry in entries})
    start_entry = next(entry for entry in entries if entry["role"] == "start")
    final_entry = next(entry for entry in entries if entry["role"] == "final")
    assert start_entry["media_time_ms"] == 0
    assert abs(final_entry["media_time_ms"] - native_delta_ms) <= 5
    assert 0 < final_entry["media_time_ms"] <= fixture.container_duration_ms + 800
    assert all(
        entry["media_time_ms"] is None or entry["media_time_ms"] <= fixture.container_duration_ms + 800
        for entry in entries
    )
    assert {entry["alignment_confidence"] for entry in entries} == {"exact"}
    assert {entry["alignment_status"] for entry in entries} == {"aligned"}

    segments = client.get(f"/v1/active-captures/{session_id}/segments", headers=headers)
    assert segments.status_code == 200, segments.text
    assert segments.json()["data"]["segments"][0]["state"] == "finalizing"
    assert segments.json()["data"]["control_events"][0]["kind"] == "start_segment"

    storyboard = client.get(f"/v1/active-captures/{session_id}/storyboard", headers=headers)
    assert storyboard.status_code == 200, storyboard.text
    storyboard_data = storyboard.json()["data"]
    assert storyboard_data["card"]["action_count"] >= 6
    assert {item["kind"] for item in storyboard_data["items"]} >= {"keyframe", "action", "control"}
    action_items = [item for item in storyboard_data["items"] if item["kind"] == "action"]
    assert action_items
    assert any(abs(item["media_time_ms"] - native_delta_ms) <= 5 for item in action_items)

    skill = client.get(f"/v1/active-captures/{session_id}/skill-distillation-input", headers=headers)
    assert skill.status_code == 200, skill.text
    skill_steps = skill.json()["data"]["steps"]
    assert any(step["key_chord"] and step["key_chord"]["normalized_key_label"] == "k" for step in skill_steps)
    assert any(step["action_kind"] == "typing_pause" for step in skill_steps)
    assert any(step["evidence_keyframe_ids"] for step in skill_steps if step["action_kind"] in {"click", "hotkey"})
    assert "typed_text" not in skill.text

    container = _container(client)
    primary_event_id = str(view["session"]["primary_event_id"])
    recording_videos = [
        artifact
        for artifact in container.repositories.artifacts.list_for_event(primary_event_id)
        if artifact.artifact_type == ArtifactType.RECORDING_VIDEO
    ]
    assert len(recording_videos) == 1
    assert recording_videos[0].sha256 == video_sha256
    persisted_bytes = container.vault.read(recording_videos[0].storage_uri)
    assert hashlib.sha256(persisted_bytes).hexdigest() == video_sha256
    assert persisted_bytes[4:8] == b"ftyp"

    inspect = client.get(
        f"/v1/events/{start_payload['data']['event']['event_id']}"
        "?view=event_inspect&purpose=macos_recording_e2e&inspect_views=keyframes,evidence_refs",
        headers={"authorization": f"Bearer {_token_with_scopes(client, ('read_metadata', 'read_text'))}"},
    )
    assert inspect.status_code == 200, inspect.text
    assert inspect.json()["data"]["keyframes"][0]["system_appshot_evidence_id"]

    raw_token = _token_with_scopes(client, ("read_metadata", "read_raw_artifact"))
    denied = client.get(
        f"/v1/artifacts/{video['artifact_id']}/raw?event_id={primary_event_id}&purpose=macos_recording_e2e",
        headers={"authorization": f"Bearer {raw_token}"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "policy.denied"


def _run_native_recording_fixture(output_dir: Path) -> RecordingFixture:
    if shutil.which("swift") is None:
        pytest.skip("swift is not available for macOS recording E2E")
    output_dir.mkdir(parents=True, exist_ok=True)
    build = subprocess.run(
        ["swift", "build", "--target", "WorkRecorderRecordingE2E"],
        cwd=MACOS_CAPTURE_ROOT,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert build.returncode == 0, build.stderr or build.stdout
    executable = MACOS_CAPTURE_ROOT / ".build" / "debug" / "WorkRecorderRecordingE2E"
    run = subprocess.run(
        [str(executable), "--output-dir", str(output_dir), "--duration-ms", "3_200".replace("_", "")],
        cwd=MACOS_CAPTURE_ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    if run.returncode != 0 and _looks_like_screen_recording_permission_failure(run.stderr + run.stdout):
        pytest.skip("ScreenCaptureKit recording permission is not available in this macOS session")
    assert run.returncode == 0, run.stderr or run.stdout
    parsed: object = json.loads(run.stdout)
    assert isinstance(parsed, Mapping)
    fixture = RecordingFixture.from_payload(parsed)
    assert fixture.status == FixtureStatus.OK
    return fixture


def _action_coordinates(fixture: RecordingFixture) -> ActionCoordinates:
    target = fixture.target_window.frame
    return ActionCoordinates(
        screen_abs=ActionPoint(
            x=target.x + target.width / 2,
            y=target.y + target.height / 2,
            coordinate_space=CoordinateSpace.MACOS_GLOBAL,
            display_id=fixture.display.display_id,
            scale_factor=fixture.display.scale_factor,
        ),
        screenshot_rel=ActionPoint(
            x=fixture.video_width / 2,
            y=fixture.video_height / 2,
            coordinate_space=CoordinateSpace.ARTIFACT_PX,
            display_id=fixture.display.display_id,
            scale_factor=fixture.display.scale_factor,
        ),
        scope_rel=ActionPoint(
            x=target.width / 2,
            y=target.height / 2,
            coordinate_space=CoordinateSpace.WINDOW_PX,
            display_id=fixture.display.display_id,
            scale_factor=fixture.display.scale_factor,
        ),
    )


def _producer_event_payload(fixture: RecordingFixture, event: ProducerEventFixture) -> dict[str, object]:
    payload: dict[str, object] = {
        "event_kind": event.kind.value,
        "producer_kind": "macos_capture_e2e_fixture",
        "occurred_at_monotonic_ms": event.occurred_at_monotonic_ms,
        "scope": _recording_scope(fixture).model_dump(mode="json"),
    }
    if event.kind == ProducerInputEventKind.POINTER_CLICK:
        payload["pointer"] = {
            "button": PointerButton.LEFT.value,
            "click_count": 1,
            "coordinates": _action_coordinates_from_point(fixture, event).model_dump(mode="json"),
        }
    elif event.kind == ProducerInputEventKind.SCROLL:
        payload["scroll"] = {
            "delta_x": event.delta_x or 0,
            "delta_y": event.delta_y or -1,
            "phase": ScrollPhase.ENDED.value,
            "duration_ms": 250,
            "velocity_bucket": 3,
        }
    elif event.kind == ProducerInputEventKind.HOTKEY:
        payload["keyboard"] = {
            "keyboard_event_kind": KeyboardEventKind.HOTKEY.value,
            "input_class": KeyboardInputClass.SHORTCUT.value,
            "capture_policy": KeyCapturePolicy.KEY_CHORD_ALLOWED.value,
            "key_chord": {
                "physical_key_code": event.key_code or 0,
                "normalized_key_label": event.key_label or "unknown",
                "modifiers": [modifier.value for modifier in event.modifiers],
                "semantic": (event.semantic or HotkeySemantic.UNKNOWN).value,
            },
            "hotkey_semantic": (event.semantic or HotkeySemantic.UNKNOWN).value,
        }
    elif event.kind == ProducerInputEventKind.TYPING_PAUSE:
        payload["keyboard"] = {
            "keyboard_event_kind": KeyboardEventKind.TYPING_PAUSE.value,
            "input_class": KeyboardInputClass.TEXT_INPUT.value,
            "capture_policy": KeyCapturePolicy.AGGREGATE_ONLY.value,
            "typing_summary": {
                "event_count": event.typing_event_count or 0,
                "text_event_count": event.typing_event_count or 0,
                "character_count": event.typing_character_count or 0,
                "duration_ms": 500,
            },
        }
    else:
        raise AssertionError(f"unsupported producer event fixture: {event.kind}")
    return payload


def _action_coordinates_from_point(fixture: RecordingFixture, event: ProducerEventFixture) -> ActionCoordinates:
    target = fixture.target_window.frame
    x = event.x if event.x is not None else target.x + target.width / 2
    y = event.y if event.y is not None else target.y + target.height / 2
    return ActionCoordinates(
        screen_abs=ActionPoint(
            x=x,
            y=y,
            coordinate_space=CoordinateSpace.MACOS_GLOBAL,
            display_id=fixture.display.display_id,
            scale_factor=fixture.display.scale_factor,
        ),
        scope_rel=ActionPoint(
            x=max(0, x - target.x),
            y=max(0, y - target.y),
            coordinate_space=CoordinateSpace.WINDOW_PX,
            display_id=fixture.display.display_id,
            scale_factor=fixture.display.scale_factor,
        ),
    )


def _assert_window_only_keyframes(fixture: RecordingFixture) -> None:
    start = Image.open(fixture.start_keyframe_path).convert("RGB")
    final = Image.open(fixture.final_keyframe_path).convert("RGB")
    assert start.size == final.size == (fixture.video_width, fixture.video_height)

    scale = fixture.display.scale_factor
    assert fixture.sentinel_occlusion.overlaps_target
    assert fixture.sentinel_occlusion.overlap_area > 4_000
    assert start.width < int(fixture.display.frame.width * scale)
    assert start.height < int(fixture.display.frame.height * scale)

    target_frame = fixture.target_window.frame
    assert abs(start.width - int(target_frame.width * scale)) <= 4
    assert abs(start.height - int(target_frame.height * scale)) <= 4
    assert _count_pixels(start, lambda red, green, blue: red > 180 and blue > 180 and green < 90) == 0
    assert _count_pixels(final, lambda red, green, blue: red > 180 and blue > 180 and green < 90) == 0
    assert _count_pixels(start, lambda red, green, blue: red < 130 and green > 140 and blue > 150) > 100
    assert _count_pixels(start, lambda red, green, blue: red > 170 and green > 130 and blue < 130) > 80

    diff = ImageChops.difference(start, final)
    assert sum(ImageStat.Stat(diff).sum) > 500_000


def _count_pixels(image: Image.Image, predicate: Callable[[int, int, int], bool]) -> int:
    pixels = image.load()
    count = 0
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue = cast(tuple[int, int, int], pixels[x, y])
            if predicate(red, green, blue):
                count += 1
    return count


def _recording_scope(fixture: RecordingFixture) -> RecordingScope:
    target = fixture.target_window
    return RecordingScope(
        kind=RecordingScopeKind.WINDOW,
        display_id=fixture.display.display_id,
        scale_factor=fixture.display.scale_factor,
        window_id=target.window_id,
        process_id=target.process_id,
        bundle_id=target.bundle_id,
        app_name=target.app_name,
        title=target.title,
        bounds=target.frame.to_bbox(),
        selection_region=target.frame.to_bbox(),
        scope_confidence=1.0,
        occlusion_estimate=0.0,
        metadata={
            "recording_backend": fixture.recording_backend.value,
            "content_filter": fixture.content_filter.value,
            "sentinel_overlap_area": fixture.sentinel_occlusion.overlap_area,
        },
    )


def _capture_attempt_payload(
    *,
    fixture: RecordingFixture,
    session_id: str,
    role: KeyframeRole,
    trigger_kind: KeyframeTriggerKind,
    trigger_id: str,
    staged_path: Path,
    captured_at_monotonic_ms: int,
    workspace_id: str,
    candidate_id: str | None = None,
    keep_reason: KeyframeKeepReason | None = KeyframeKeepReason.REQUIRED_BOUNDARY,
) -> dict[str, object]:
    target = fixture.target_window
    actor = ActorRef(actor_id="test-cli", display_name="macOS Recording E2E")
    target_bbox = target.frame.to_bbox()
    attempt = CaptureAttemptRequest(
        schema_version=1,
        trigger=TriggerEnvelope(
            trigger_id=trigger_id,
            trigger_type=TriggerType.MANUAL_OS_REGION_HOTKEY,
            capture_strategy=CaptureStrategy.OS_REGION,
            actor=actor,
            occurred_at=datetime.now(UTC),
            selection=target_bbox,
            intent_text="macOS ScreenCaptureKit recording E2E",
        ),
        selection_geometry=SelectionGeometry(
            selected_region=target_bbox,
            display=DisplayGeometry(
                display_id=fixture.display.display_id,
                frame=fixture.display.frame.to_bbox(),
                scale_factor=fixture.display.scale_factor,
            ),
        ),
        window_hints=(
            WindowHint(
                app_name=target.app_name,
                title=target.title,
                process_id=target.process_id,
                window_id=target.window_id,
                frame=target_bbox,
                overlap_ratio=1.0,
                confidence=0.99,
                bundle_id=target.bundle_id,
                display_id=fixture.display.display_id,
                visible_area_ratio=1.0,
                is_frontmost=True,
            ),
        ),
        workspace=WorkspaceSelection(workspace_id=workspace_id, label="macOS Recording E2E", auto=False),
        actor=actor,
        staged_artifact=StagedArtifactRef(
            local_path=str(staged_path),
            artifact_type=ArtifactType.SCREENSHOT,
            content_type="image/png",
            filename=staged_path.name,
        ),
        intent_text="macOS ScreenCaptureKit recording E2E",
        active_capture=ActiveCaptureBinding(
            session_id=session_id,
            role=role,
            trigger_kind=trigger_kind,
            keep_reason=keep_reason,
            candidate_id=candidate_id,
            metadata={
                "producer": "ScreenCaptureKit",
                "keyframe_source": "first_or_final_recorded_frame",
            },
        ),
        native_timing_receipt=NativeCaptureTimingReceipt(
            authority=NativeCaptureTimingAuthority.MACOS_CAPTURE,
            captured_at_monotonic_ms=captured_at_monotonic_ms,
            source_clock=NativeTimingClock.SYSTEM_UPTIME_MS,
            recorded_at_wall_time=datetime.now(UTC),
            metadata={"producer": "ScreenCaptureKit", "fixture": "macos_recording_e2e"},
        ),
    )
    return attempt.model_dump(mode="json")


def _looks_like_screen_recording_permission_failure(output: str) -> bool:
    lowered = output.lower()
    return "permission" in lowered or "not authorized" in lowered or "screen recording" in lowered


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


def _required_float(payload: Mapping[str, object], key: str) -> float:
    value = payload[key]
    assert isinstance(value, int | float) and not isinstance(value, bool), f"{key} must be a number"
    return float(value)


def _required_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload[key]
    assert isinstance(value, bool), f"{key} must be a boolean"
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


def _optional_float(payload: Mapping[str, object], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    assert isinstance(value, int | float) and not isinstance(value, bool), f"{key} must be a number"
    return float(value)


def _token_with_scopes(client: TestClient, scopes: tuple[str, ...]) -> str:
    response = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": INSTALL_SECRET},
        json={"actor_id": "test-cli", "display_name": "macOS Recording E2E", "scopes": list(scopes)},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["data"]["access_token"])


def _container(client: TestClient) -> DaemonContainer:
    app = cast(FastAPI, client.app)
    return cast(DaemonContainer, getattr(app.state, "container"))
