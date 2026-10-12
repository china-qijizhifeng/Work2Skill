"""Unit tests for the active-capture recording filesystem exporter."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from packages.active_capture.application.export import RecordingExporter, RecordingExportError
from packages.active_capture.application.read_model import RecordingSessionGraph
from packages.active_capture.application.vm_coordinate_mapping import VMDisplayGeometry
from packages.contracts import (
    AccessScope,
    ActionCoordinates,
    ActionEvidenceLink,
    ActionPoint,
    ActionResultObservation,
    ActiveCaptureMode,
    ActiveCaptureSession,
    ActiveCaptureStatus,
    Artifact,
    ArtifactIngestState,
    ArtifactRole,
    ArtifactType,
    BoundingBox,
    ContextKeyframe,
    CoordinateSpace,
    HumanActionEvent,
    HumanActionEvidenceRole,
    HumanActionKind,
    HumanActionOutcomeStatus,
    KeyframeEvidenceLink,
    KeyframeEvidenceRole,
    KeyframeKeepReason,
    KeyframeRole,
    KeyframeTriggerKind,
    RecordingControlEvent,
    RecordingControlKind,
    RecordingControlSource,
    RecordingExportFallbackMode,
    RecordingScope,
    RecordingScopeKind,
    RecordingSegmentState,
    RecordingTimelineManifest,
    RecordingVideoSegmentRef,
    RedactionState,
    TimelineAlignmentConfidence,
    TimelineAlignmentStatus,
    TimelineKeyframeEntry,
    VideoArtifactRef,
    VideoArtifactState,
)


def _now() -> datetime:
    return datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)


class _FakeGraphReader:
    def __init__(self, graph: RecordingSessionGraph) -> None:
        self._graph = graph

    def load_for_session(self, session_id: str) -> RecordingSessionGraph | None:
        return self._graph if session_id == self._graph.session.session_id else None


class _FakeArtifacts:
    def __init__(self, artifacts: dict[str, Artifact], by_event: dict[str, tuple[Artifact, ...]]) -> None:
        self._artifacts = artifacts
        self._by_event = by_event

    def get(self, artifact_id: str) -> Artifact | None:
        return self._artifacts.get(artifact_id)

    def list_for_event(self, event_id: str) -> tuple[Artifact, ...]:
        return self._by_event.get(event_id, ())


class _FakeContentSource:
    def __init__(self, contents: dict[str, bytes], tmp_path: Path) -> None:
        self._paths: dict[str, Path] = {}
        for uri, payload in contents.items():
            blob = tmp_path / "blobs" / uri.replace("/", "_")
            blob.parent.mkdir(parents=True, exist_ok=True)
            blob.write_bytes(payload)
            self._paths[uri] = blob

    def resolve_local_path(self, storage_uri: str) -> Path:
        path = self._paths.get(storage_uri)
        if path is None:
            raise FileNotFoundError(storage_uri)
        return path


class _FakeVideoFrameExtractor:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, int, Path]] = []

    def extract_png(self, *, video_path: Path, media_time_ms: int, output_path: Path) -> bool:
        self.calls.append((video_path, media_time_ms, output_path))
        output_path.write_bytes(f"video frame at {media_time_ms}".encode())
        return True


class _FakeVMA11yProbe:
    def __init__(self, records: tuple[dict[str, object], ...]) -> None:
        self._records = records

    def export_records_for_session(self, session_id: str) -> tuple[dict[str, object], ...]:
        return self._records if session_id == "acs_demo" else ()


class _FakeVMEventLogProbe(_FakeVMA11yProbe):
    def __init__(
        self,
        records: tuple[dict[str, object], ...] = (),
        event_log: tuple[dict[str, object], ...] = (),
        click_log: tuple[dict[str, object], ...] = (),
    ) -> None:
        super().__init__(records)
        self._event_log = event_log
        self._click_log = click_log

    def export_event_log_for_session(self, session_id: str) -> tuple[dict[str, object], ...]:
        return self._event_log if session_id == "acs_demo" else ()

    def export_click_log_for_session(self, session_id: str) -> tuple[dict[str, object], ...]:
        return self._click_log if session_id == "acs_demo" else ()


class _FakeLiveVMDomProbe(_FakeVMA11yProbe):
    def __init__(self) -> None:
        super().__init__(())
        self.points: list[tuple[float, float, str]] = []

    def sample_point_for_export(
        self,
        *,
        session_id: str,
        occurred_at_monotonic_ms: int | None,
        point_x: float,
        point_y: float,
        coordinate_space: str,
    ) -> dict[str, object] | None:
        self.points.append((point_x, point_y, coordinate_space))
        return {
            "source": "export_live_dom_probe",
            "trigger": {
                "session_id": session_id,
                "event_kind": "pointer_click",
                "occurred_at_monotonic_ms": occurred_at_monotonic_ms,
                "point": {"x": point_x, "y": point_y, "coordinate_space": coordinate_space},
            },
            "sample": {"hit": {"tag": "button", "text": "Live Save", "role": "button"}},
            "hit_dom": {"tag": "button", "text": "Live Save", "role": "button"},
            "error": None,
        }


def _artifact(artifact_id: str, event_id: str, artifact_type: ArtifactType, content_type: str, uri: str) -> Artifact:
    return Artifact(
        artifact_id=artifact_id,
        event_id=event_id,
        artifact_type=artifact_type,
        role=ArtifactRole.VISUAL_EVIDENCE,
        storage_uri=uri,
        redaction_state=RedactionState.NONE,
        allowed_scopes=(AccessScope.READ_RAW_ARTIFACT,),
        content_type=content_type,
        ingest_state=ArtifactIngestState.INDEXED,
        metadata={},
        created_at=_now(),
    )


def _build_graph() -> RecordingSessionGraph:
    session = ActiveCaptureSession(
        session_id="acs_demo",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.COMPLETED,
        primary_event_id="evt_primary",
        started_at=_now(),
        ended_at=_now(),
        created_at=_now(),
        updated_at=_now(),
    )
    keyframe_before = ContextKeyframe(
        keyframe_id="kf_before",
        session_id=session.session_id,
        event_id="evt_primary",
        capture_run_id="cap_1",
        role=KeyframeRole.BEFORE_ACTION,
        trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
        keep_reason=KeyframeKeepReason.BEFORE_ACTION_CONTEXT,
        captured_at=_now(),
        sequence_index=0,
        screenshot_artifact_id="art_shot_before",
        media_time_ms=0,
    )
    keyframe_result = ContextKeyframe(
        keyframe_id="kf_result",
        session_id=session.session_id,
        event_id="evt_primary",
        capture_run_id="cap_1",
        role=KeyframeRole.RESULT,
        trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
        keep_reason=KeyframeKeepReason.RESULT_OBSERVED,
        captured_at=_now(),
        sequence_index=1,
        screenshot_artifact_id="art_shot_result",
        media_time_ms=1200,
    )
    action = HumanActionEvent(
        action_id="act_click",
        trace_id="trace_demo",
        session_id=session.session_id,
        sequence_index=0,
        kind=HumanActionKind.CLICK,
        occurred_at=_now(),
        occurred_at_monotonic_ms=600,
        media_time_ms=600,
        coordinates=ActionCoordinates(
            screen_abs=ActionPoint(x=321.5, y=654.25, coordinate_space=CoordinateSpace.MACOS_GLOBAL)
        ),
    )
    keyframe_links = (
        KeyframeEvidenceLink(
            link_id="kfl_ocr",
            keyframe_id="kf_result",
            event_id="evt_primary",
            evidence_id="ev_ocr",
            artifact_id="art_ocr",
            role=KeyframeEvidenceRole.OCR,
            created_at=_now(),
        ),
        KeyframeEvidenceLink(
            link_id="kfl_a11y",
            keyframe_id="kf_result",
            event_id="evt_primary",
            evidence_id="ev_a11y",
            artifact_id="art_a11y",
            role=KeyframeEvidenceRole.A11Y,
            created_at=_now(),
        ),
    )
    action_links = (
        ActionEvidenceLink(
            link_id="ael_before",
            action_id="act_click",
            role=HumanActionEvidenceRole.BEFORE_KEYFRAME,
            keyframe_id="kf_before",
            created_at=_now(),
        ),
    )
    observation = ActionResultObservation(
        observation_id="obs_click",
        action_id="act_click",
        status=HumanActionOutcomeStatus.OBSERVED,
        result_keyframe_id="kf_result",
        observed_at=_now(),
    )
    return RecordingSessionGraph(
        session=session,
        keyframes=(keyframe_before, keyframe_result),
        actions=(action,),
        controls=(),
        timeline=None,
        keyframe_links=keyframe_links,
        action_links=action_links,
        action_observations=(observation,),
        target_resolutions=(),
        producer_events=(),
        producer_decisions=(),
        total_keyframe_count=2,
        total_action_count=1,
    )


def _build_exporter(tmp_path: Path, graph: RecordingSessionGraph | None = None) -> RecordingExporter:
    artifacts = {
        "art_shot_before": _artifact(
            "art_shot_before", "evt_primary", ArtifactType.SCREENSHOT, "image/png", "local-artifact://shot_before.png"
        ),
        "art_shot_result": _artifact(
            "art_shot_result", "evt_primary", ArtifactType.SCREENSHOT, "image/png", "local-artifact://shot_result.png"
        ),
        "art_ocr": _artifact(
            "art_ocr", "evt_primary", ArtifactType.VISUAL_OCR_TEXT, "text/plain", "local-artifact://ocr.txt"
        ),
        "art_a11y": _artifact(
            "art_a11y", "evt_primary", ArtifactType.A11Y_TREE, "application/json", "local-artifact://a11y.json"
        ),
        "art_video": _artifact(
            "art_video", "evt_primary", ArtifactType.RECORDING_VIDEO, "video/mp4", "local-artifact://video.mp4"
        ),
    }
    by_event = {"evt_primary": (artifacts["art_video"],)}
    contents = {
        "local-artifact://shot_before.png": b"\x89PNG before",
        "local-artifact://shot_result.png": b"\x89PNG result",
        "local-artifact://ocr.txt": b"hello ocr",
        "local-artifact://a11y.json": b'{"role": "button"}',
        "local-artifact://video.mp4": b"mp4 bytes",
    }
    return RecordingExporter(
        graph_reader=_FakeGraphReader(graph or _build_graph()),
        artifacts=_FakeArtifacts(artifacts, by_event),
        content_source=_FakeContentSource(contents, tmp_path),
    )


def test_export_materializes_per_keyframe_folders(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = _build_exporter(tmp_path).export_session(session_id="acs_demo", output_root=out)

    assert result.keyframe_dir_count == 2
    assert result.action_count == 1
    assert result.video_file_count == 1

    recording_dir = result.output_dir
    assert recording_dir.parent == out
    assert (recording_dir / "trajectory.json").is_file()
    assert (recording_dir / "summary.md").is_file()
    assert (recording_dir / "recording.json").is_file()
    assert (recording_dir / "video.mp4").read_bytes() == b"mp4 bytes"

    before_dir = recording_dir / "0000_20260624T120000_000"
    result_dir = recording_dir / "0001_20260624T120000_000"
    assert (before_dir / "screenshot.png").read_bytes() == b"\x89PNG before"
    assert (result_dir / "screenshot.png").read_bytes() == b"\x89PNG result"
    assert (result_dir / "ocr.txt").read_text() == "hello ocr"
    assert not (result_dir / "a11y.json").exists()


def test_export_uses_note_and_mode_as_direct_recording_folder(tmp_path: Path) -> None:
    base = _build_graph()
    graph = replace(
        base,
        session=base.session.model_copy(update={"user_note": "cua/demo: 01"}),
    )
    out = tmp_path / "out"
    exporter = _build_exporter(tmp_path, graph=graph)

    results = {
        mode: exporter.export_session(
            session_id="acs_demo",
            output_root=out,
            fallback_mode=mode,
        )
        for mode in RecordingExportFallbackMode
    }

    assert results[RecordingExportFallbackMode.NORMAL].output_dir == out / "cua_demo_ 01+normal"
    assert results[RecordingExportFallbackMode.EVENT_ONLY].output_dir == out / "cua_demo_ 01+event_only"
    assert results[RecordingExportFallbackMode.CLICK_ONLY].output_dir == out / "cua_demo_ 01+click_only"
    assert all((result.output_dir / "summary.md").is_file() for result in results.values())


def test_export_summary_uses_english_labels(tmp_path: Path) -> None:
    result = _build_exporter(tmp_path).export_session(session_id="acs_demo", output_root=tmp_path / "out")

    summary = (result.output_dir / "summary.md").read_text(encoding="utf-8")

    assert "# Recording Summary - acs_demo" in summary
    assert "- Mode: recording_session" in summary
    assert "- Started: 2026-06-24T12:00:00+00:00" in summary
    assert "- Ended: 2026-06-24T12:00:00+00:00" in summary
    assert "- Duration: unknown" in summary
    assert "- Counts: 2 keyframes, 1 action, 0 controls" in summary
    assert "- Input log: keylog.jsonl" in summary
    assert "## Timeline" in summary
    assert "[keyframe] Before action" in summary
    assert "[action] Click (target needs review)" in summary
    assert "[keyframe] Action result" in summary
    assert not any("\u4e00" <= char <= "\u9fff" for char in summary)


def test_export_key_caption_uses_normalized_label_for_control_characters() -> None:
    from packages.contracts import KeyChord, ModifierKey

    control_p = KeyChord(
        physical_key_code=35,
        normalized_key_label="p",
        modifiers=(ModifierKey.CONTROL,),
        characters="\x10",
    )
    backspace = KeyChord(
        physical_key_code=51,
        normalized_key_label="backspace",
        characters="\b",
    )
    right_arrow = KeyChord(
        physical_key_code=124,
        normalized_key_label="right_arrow",
        modifiers=(ModifierKey.FUNCTION,),
        characters="\x1d",
    )

    assert RecordingExporter._export_key_chord_caption(control_p) == "Control+P"
    assert RecordingExporter._export_key_chord_caption(backspace) == "Backspace"
    assert RecordingExporter._export_key_chord_caption(right_arrow) == "Function+Right Arrow"


def test_export_trajectory_uses_english_safe_captions(tmp_path: Path) -> None:
    base = _build_graph()
    control = RecordingControlEvent(
        control_id="rctl_start",
        session_id=base.session.session_id,
        kind=RecordingControlKind.START_SEGMENT,
        source=RecordingControlSource.TEST,
        occurred_at=_now(),
        occurred_at_monotonic_ms=0,
    )
    graph = replace(base, controls=(control,))

    result = _build_exporter(tmp_path, graph=graph).export_session(session_id="acs_demo", output_root=tmp_path / "out")

    trajectory = json.loads((result.output_dir / "trajectory.json").read_text(encoding="utf-8"))
    captions = [step["safe_caption"] for step in trajectory["steps"]]
    assert "Segment started" in captions
    assert "Before action" in captions
    assert "Click (target needs review)" in captions
    assert "Action result" in captions
    assert not any("\u4e00" <= char <= "\u9fff" for caption in captions for char in caption)


def test_export_derives_missing_keyframe_screenshot_from_video(tmp_path: Path) -> None:
    base = _build_graph()
    keyframes = tuple(keyframe.model_copy(update={"screenshot_artifact_id": None}) for keyframe in base.keyframes)
    graph = RecordingSessionGraph(
        session=base.session,
        keyframes=keyframes,
        actions=base.actions,
        controls=base.controls,
        timeline=base.timeline,
        keyframe_links=base.keyframe_links,
        action_links=base.action_links,
        action_observations=base.action_observations,
        target_resolutions=base.target_resolutions,
        producer_events=base.producer_events,
        producer_decisions=base.producer_decisions,
        total_keyframe_count=base.total_keyframe_count,
        total_action_count=base.total_action_count,
    )
    video = _artifact("art_video", "evt_primary", ArtifactType.RECORDING_VIDEO, "video/mp4", "local-artifact://video.mp4")
    extractor = _FakeVideoFrameExtractor()
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(graph),
        artifacts=_FakeArtifacts({"art_video": video}, {"evt_primary": (video,)}),
        content_source=_FakeContentSource({"local-artifact://video.mp4": b"mp4 bytes"}, tmp_path),
        video_frame_extractor=extractor,
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")

    before_dir = result.output_dir / "0000_20260624T120000_000"
    result_dir = result.output_dir / "0001_20260624T120000_000"
    assert (before_dir / "screenshot.png").read_bytes() == b"video frame at 0"
    assert (result_dir / "screenshot.png").read_bytes() == b"video frame at 1200"
    assert [call[1] for call in extractor.calls] == [0, 1200]
    recording = json.loads((result.output_dir / "recording.json").read_text(encoding="utf-8"))
    assert recording["keyframes"][0]["evidence_files"] == ["screenshot.png"]
    assert "screenshot.png" in recording["keyframes"][1]["evidence_files"]


def test_export_omits_host_a11y_and_browser_text(tmp_path: Path) -> None:
    base = _build_graph()
    extra_links = (
        KeyframeEvidenceLink(
            link_id="kfl_appshot",
            keyframe_id="kf_result",
            event_id="evt_primary",
            evidence_id="ev_appshot",
            artifact_id="art_appshot",
            role=KeyframeEvidenceRole.SYSTEM_APPSHOT,
            created_at=_now(),
        ),
        KeyframeEvidenceLink(
            link_id="kfl_web",
            keyframe_id="kf_result",
            event_id="evt_primary",
            evidence_id="ev_web",
            artifact_id="art_web",
            role=KeyframeEvidenceRole.WEB,
            created_at=_now(),
        ),
        KeyframeEvidenceLink(
            link_id="kfl_selection_text",
            keyframe_id="kf_result",
            event_id="evt_primary",
            evidence_id="ev_selection_text",
            artifact_id="art_selection_text",
            role=KeyframeEvidenceRole.SELECTION_TEXT,
            created_at=_now(),
        ),
        KeyframeEvidenceLink(
            link_id="kfl_canonical",
            keyframe_id="kf_result",
            event_id="evt_primary",
            evidence_id="ev_canonical",
            artifact_id="art_canonical",
            role=KeyframeEvidenceRole.CANONICAL_TEXT,
            created_at=_now(),
        ),
        KeyframeEvidenceLink(
            link_id="kfl_clean",
            keyframe_id="kf_result",
            event_id="evt_primary",
            evidence_id="ev_clean",
            artifact_id="art_clean",
            role=KeyframeEvidenceRole.CLEAN_TEXT,
            created_at=_now(),
        ),
    )
    graph = RecordingSessionGraph(
        session=base.session,
        keyframes=base.keyframes,
        actions=base.actions,
        controls=base.controls,
        timeline=base.timeline,
        keyframe_links=(*base.keyframe_links, *extra_links),
        action_links=base.action_links,
        action_observations=base.action_observations,
        target_resolutions=base.target_resolutions,
        producer_events=base.producer_events,
        producer_decisions=base.producer_decisions,
        total_keyframe_count=base.total_keyframe_count,
        total_action_count=base.total_action_count,
    )
    artifacts = {
        "art_shot_before": _artifact(
            "art_shot_before", "evt_primary", ArtifactType.SCREENSHOT, "image/png", "local-artifact://shot_before.png"
        ),
        "art_shot_result": _artifact(
            "art_shot_result", "evt_primary", ArtifactType.SCREENSHOT, "image/png", "local-artifact://shot_result.png"
        ),
        "art_appshot": _artifact(
            "art_appshot", "evt_primary", ArtifactType.SYSTEM_APPSHOT, "application/json", "local-artifact://appshot.json"
        ),
        "art_web": _artifact(
            "art_web", "evt_primary", ArtifactType.PAGE_METADATA, "application/json", "local-artifact://web.json"
        ),
        "art_selection_text": _artifact(
            "art_selection_text",
            "evt_primary",
            ArtifactType.DOM_SELECTION_TEXT,
            "text/plain",
            "local-artifact://selection.txt",
        ),
        "art_canonical": _artifact(
            "art_canonical",
            "evt_primary",
            ArtifactType.CANONICAL_TEXT,
            "text/plain",
            "local-artifact://canonical.txt",
        ),
        "art_clean": _artifact(
            "art_clean",
            "evt_primary",
            ArtifactType.CLEAN_PAGE_TEXT,
            "text/markdown",
            "local-artifact://clean.md",
        ),
    }
    contents = {
        "local-artifact://shot_before.png": b"\x89PNG before",
        "local-artifact://shot_result.png": b"\x89PNG result",
        "local-artifact://appshot.json": json.dumps(
            {
                "a11y_evidence_ids": ["ev_a11y_one", "ev_a11y_two"],
                "quality": {
                    "a11y_supported": True,
                    "a11y_permission_state": "granted",
                    "text_block_count": 3,
                    "diagnostics": ["ok"],
                },
                "permissions": {"accessibility": "granted"},
            }
        ).encode(),
        "local-artifact://web.json": b'{"url": "https://example.test/private"}',
        "local-artifact://selection.txt": b"selected browser text",
        "local-artifact://canonical.txt": b"canonical browser text",
        "local-artifact://clean.md": b"# clean browser text",
    }
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(graph),
        artifacts=_FakeArtifacts(artifacts, {}),
        content_source=_FakeContentSource(contents, tmp_path),
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")

    result_dir = result.output_dir / "0001_20260624T120000_000"
    assert (result_dir / "system_appshot.json").is_file()
    assert not (result_dir / "web.json").exists()
    assert not (result_dir / "selection_text.txt").exists()
    assert not (result_dir / "canonical_text.txt").exists()
    assert not (result_dir / "clean_text.md").exists()
    assert not (result_dir / "a11y_summary.json").exists()
    assert not (result_dir / "vm_a11y.json").exists()


def test_export_attaches_vm_periodic_a11y_to_keyframes(tmp_path: Path) -> None:
    sample_ts = _now().timestamp()
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(_build_graph()),
        artifacts=_FakeArtifacts({}, {}),
        content_source=_FakeContentSource({}, tmp_path),
        vm_a11y_probe=_FakeVMA11yProbe(
            (
                {
                    "source": "periodic_watch",
                    "sample": {
                        "active_window": "LibreOffice Calc",
                        "host_ts": sample_ts,
                        "focused": {"role": "entry", "name": "A1"},
                    },
                    "sample_host_ts": sample_ts,
                    "received_at_host_ts": sample_ts,
                },
            )
        ),
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")

    result_dir = result.output_dir / "0001_20260624T120000_000"
    jsonl_lines = (result_dir / "vm_a11y.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(jsonl_lines) == 1
    record = json.loads(jsonl_lines[0])
    assert record["source"] == "periodic_watch"
    assert record["sample"]["active_window"] == "LibreOffice Calc"
    assert record["sample"]["focused"] == {"role": "entry", "name": "A1"}
    assert record["keyframe_id"] == "kf_result"
    vm_a11y = json.loads((result_dir / "vm_a11y.json").read_text(encoding="utf-8"))
    assert vm_a11y["record_count"] == 1
    assert vm_a11y["latest"]["source"] == "periodic_watch"


def test_export_does_not_attach_stale_vm_periodic_a11y_to_keyframe(tmp_path: Path) -> None:
    sample_ts = _now().timestamp() + 0.6
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(_build_graph()),
        artifacts=_FakeArtifacts({}, {}),
        content_source=_FakeContentSource({}, tmp_path),
        vm_a11y_probe=_FakeVMA11yProbe(
            (
                {
                    "source": "periodic_watch",
                    "sample": {"active_window": "stale-window", "host_ts": sample_ts},
                    "sample_host_ts": sample_ts,
                    "received_at_host_ts": sample_ts,
                },
            )
        ),
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")

    result_dir = result.output_dir / "0001_20260624T120000_000"
    assert not (result_dir / "vm_a11y.json").exists()
    assert not (result_dir / "vm_a11y.jsonl").exists()


def test_export_includes_vm_a11y_probe_records_when_available(tmp_path: Path) -> None:
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(_build_graph()),
        artifacts=_FakeArtifacts({}, {}),
        content_source=_FakeContentSource({}, tmp_path),
        vm_a11y_probe=_FakeVMA11yProbe(
            (
                {
                    "trigger": {
                        "session_id": "acs_demo",
                        "event_kind": "pointer_click",
                        "occurred_at_monotonic_ms": 600,
                        "host_ts": 1.0,
                    },
                    "sample": {
                        "active_window": "LibreOffice Calc",
                        "host_ts": 1.25,
                        "hit": {"tag": "button", "text": "Save", "role": "button", "href": None},
                    },
                    "hit_dom": {"tag": "button", "text": "Save", "role": "button", "href": None},
                    "error": None,
                    "started_at_host_ts": 1.1,
                    "completed_at_host_ts": 1.3,
                    "command": ["python3", "a11y_point_probe_chinatime.py", "--jsonl"],
                },
            )
        ),
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")

    result_dir = result.output_dir / "0001_20260624T120000_000"
    jsonl_lines = (result_dir / "vm_a11y.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(jsonl_lines) == 1
    assert json.loads(jsonl_lines[0])["sample"]["active_window"] == "LibreOffice Calc"
    assert json.loads(jsonl_lines[0])["action_id"] == "act_click"
    assert json.loads(jsonl_lines[0])["hit_dom"]["text"] == "Save"
    result_actions = json.loads((result_dir / "actions.json").read_text(encoding="utf-8"))
    assert result_actions[0]["dom_hit"] == {"tag": "button", "text": "Save", "role": "button", "href": None}
    trajectory = json.loads((result.output_dir / "trajectory.json").read_text(encoding="utf-8"))
    action_steps = [step for step in trajectory["steps"] if step.get("action_id") == "act_click"]
    assert action_steps[0]["dom_hit"] == {"tag": "button", "text": "Save", "role": "button", "href": None}
    root_jsonl_lines = (result.output_dir / "vm_a11y.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(root_jsonl_lines) == 1
    assert json.loads(root_jsonl_lines[0])["hit_dom"]["text"] == "Save"
    root_vm_a11y = json.loads((result.output_dir / "vm_a11y.json").read_text(encoding="utf-8"))
    assert root_vm_a11y["record_count"] == 1
    dom_hits = [json.loads(line) for line in (result.output_dir / "dom_hits.jsonl").read_text(encoding="utf-8").splitlines()]
    assert dom_hits == [
        {
            "action_id": "act_click",
            "action_kind": "click",
            "status": "hit",
            "sequence_index": 0,
            "occurred_at": "2026-06-24T12:00:00+00:00",
            "media_time_ms": 600,
            "dom_hit": {"tag": "button", "text": "Save", "role": "button", "href": None},
            "dom_hit_label": "button · Save",
        }
    ]
    vm_a11y = json.loads((result_dir / "vm_a11y.json").read_text(encoding="utf-8"))
    assert vm_a11y["record_count"] == 1
    assert vm_a11y["latest"]["trigger"]["event_kind"] == "pointer_click"
    recording = json.loads((result.output_dir / "recording.json").read_text(encoding="utf-8"))
    assert recording["vm_a11y_files"] == [
        "vm_a11y.json",
        "vm_a11y.jsonl",
        "0001_20260624T120000_000/vm_a11y.json",
        "0001_20260624T120000_000/vm_a11y.jsonl",
    ]
    assert recording["dom_hits_file"] == "dom_hits.jsonl"
    assert recording["dom_hits_count"] == 1
    assert recording["dom_hits_hit_count"] == 1


def test_export_summary_does_not_truncate_long_dom_hit_text(tmp_path: Path) -> None:
    long_text = (
        "Reservation Confirmed: Coney Island Texas Weiners on 2026-07-25 "
        "Party size 4 Confirmation number ABC123456789 Notes please arrive early"
    )
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(_build_graph()),
        artifacts=_FakeArtifacts({}, {}),
        content_source=_FakeContentSource({}, tmp_path),
        vm_a11y_probe=_FakeVMA11yProbe(
            (
                {
                    "trigger": {
                        "session_id": "acs_demo",
                        "event_kind": "pointer_click",
                        "occurred_at_monotonic_ms": 600,
                        "host_ts": 1.0,
                    },
                    "sample": {"host_ts": 1.25, "hit": {"tag": "SPAN", "text": long_text}},
                    "hit_dom": {"tag": "SPAN", "text": long_text},
                    "error": None,
                    "started_at_host_ts": 1.1,
                    "completed_at_host_ts": 1.3,
                },
            )
        ),
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")

    summary = (result.output_dir / "summary.md").read_text(encoding="utf-8")
    assert long_text in summary
    assert "Reservation Confirmed: Coney Island Texas Weiners on 2026-07-25 Party size..." not in summary
    dom_hits = [json.loads(line) for line in (result.output_dir / "dom_hits.jsonl").read_text(encoding="utf-8").splitlines()]
    assert dom_hits[0]["dom_hit_label"] == f"span · {long_text}"


def test_export_does_not_backfill_dom_hit_with_live_probe_by_default(tmp_path: Path) -> None:
    base = _build_graph()
    graph = replace(
        base,
        session=base.session.model_copy(
            update={
                "scope": RecordingScope(
                    kind=RecordingScopeKind.WINDOW,
                    window_id="win_tiger",
                    process_id=4242,
                    app_name="TigerVNC",
                    title="QEMU (mypcbench-persist) - TigerVNC",
                    bounds={
                        "x": 0,
                        "y": 0,
                        "width": 1380,
                        "height": 894,
                        "coordinate_space": "macos_global",
                    },
                )
            }
        ),
    )
    probe = _FakeLiveVMDomProbe()
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(graph),
        artifacts=_FakeArtifacts({}, {}),
        content_source=_FakeContentSource({}, tmp_path),
        vm_a11y_probe=probe,
        vm_display=VMDisplayGeometry(vm_width=1380, vm_height=866, title_bar_pt=28),
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")

    result_dir = result.output_dir / "0001_20260624T120000_000"
    actions = json.loads((result_dir / "actions.json").read_text(encoding="utf-8"))
    assert "dom_hit" not in actions[0]
    assert not (result_dir / "vm_a11y.json").exists()
    assert (result.output_dir / "vm_a11y.jsonl").read_text(encoding="utf-8") == ""
    dom_hits = [json.loads(line) for line in (result.output_dir / "dom_hits.jsonl").read_text(encoding="utf-8").splitlines()]
    assert dom_hits[0]["status"] == "miss"
    assert dom_hits[0]["errors"] == ["no_vm_a11y_record"]
    assert probe.points == []


def test_export_writes_dom_hits_from_event_log_backfill_within_three_seconds(tmp_path: Path) -> None:
    event_ts = _now().timestamp() + 1.2
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(_build_graph()),
        artifacts=_FakeArtifacts({}, {}),
        content_source=_FakeContentSource({}, tmp_path),
        vm_a11y_probe=_FakeVMEventLogProbe(
            event_log=(
                {"seq": 11, "ts": event_ts, "role": "menu item", "name": "Recent item", "bbox": [8, 9, 120, 24]},
            )
        ),
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")

    result_dir = result.output_dir / "0001_20260624T120000_000"
    actions = json.loads((result_dir / "actions.json").read_text(encoding="utf-8"))
    assert actions[0]["dom_hit"] == {"role": "menu item", "name": "Recent item", "bbox": [8, 9, 120, 24]}
    trajectory = json.loads((result.output_dir / "trajectory.json").read_text(encoding="utf-8"))
    action_steps = [step for step in trajectory["steps"] if step.get("action_id") == "act_click"]
    assert action_steps[0]["needs_review"] is False
    assert action_steps[0]["readiness"]["state"] == "ready"
    assert action_steps[0]["action_summary"]["target"]["status"] == "resolved"
    assert action_steps[0]["action_summary"]["target"]["display_label"] == "menu item - Recent item"
    assert action_steps[0]["action_summary"]["target"]["needs_review"] is False
    dom_hits = [json.loads(line) for line in (result.output_dir / "dom_hits.jsonl").read_text(encoding="utf-8").splitlines()]
    assert dom_hits == [
        {
            "action_id": "act_click",
            "action_kind": "click",
            "status": "hit",
            "sequence_index": 0,
            "occurred_at": "2026-06-24T12:00:00+00:00",
            "media_time_ms": 600,
            "dom_hit": {"role": "menu item", "name": "Recent item", "bbox": [8, 9, 120, 24]},
            "dom_hit_label": "menu item · Recent item",
            "source": "event_log_backfill",
            "backfill_delta_ms": 1200.0,
            "event_seq": 11,
        }
    ]
    recording = json.loads((result.output_dir / "recording.json").read_text(encoding="utf-8"))
    assert recording["dom_hits_file"] == "dom_hits.jsonl"
    assert recording["dom_hits_count"] == 1
    assert recording["dom_hits_hit_count"] == 1


def test_export_backfills_generic_a11y_hit_from_dom_click_log(tmp_path: Path) -> None:
    click_ts = _now().timestamp() + 0.2
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(_build_graph()),
        artifacts=_FakeArtifacts({}, {}),
        content_source=_FakeContentSource({}, tmp_path),
        vm_a11y_probe=_FakeVMEventLogProbe(
            records=(
                {
                    "action_id": "act_click",
                    "action_kind": "click",
                    "source": "event_watch",
                    "hit_dom": {"role": "document web", "name": "HooliMail", "bbox": [66, 183, 1215, 617]},
                    "sample": {"source": "event_watch"},
                    "error": None,
                },
            ),
            click_log=(
                {
                    "ts": click_ts,
                    "iso": "12:00:00",
                    "x": 664,
                    "y": 364,
                    "button": "left",
                    "dom": {"tag": "SPAN", "text": "Reservation Confirmed", "rect": [578, 169, 202, 21]},
                    "dom_url": "http://localhost:3016/inbox?_autologin=1",
                    "a11y": {"role": "document web", "name": "HooliMail", "bbox": [66, 183, 1215, 617]},
                },
            ),
        ),
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")

    result_dir = result.output_dir / "0001_20260624T120000_000"
    actions = json.loads((result_dir / "actions.json").read_text(encoding="utf-8"))
    assert actions[0]["dom_hit"] == {"tag": "SPAN", "text": "Reservation Confirmed", "rect": [578, 169, 202, 21]}
    dom_hits = [json.loads(line) for line in (result.output_dir / "dom_hits.jsonl").read_text(encoding="utf-8").splitlines()]
    assert dom_hits[0]["dom_hit"] == {"tag": "SPAN", "text": "Reservation Confirmed", "rect": [578, 169, 202, 21]}
    assert dom_hits[0]["source"] == "click_log_backfill"
    vm_clicks = [json.loads(line) for line in (result.output_dir / "vm_clicks.jsonl").read_text(encoding="utf-8").splitlines()]
    assert vm_clicks[0]["dom"]["text"] == "Reservation Confirmed"
    recording = json.loads((result.output_dir / "recording.json").read_text(encoding="utf-8"))
    assert recording["vm_clicks_file"] == "vm_clicks.jsonl"
    assert recording["vm_clicks_count"] == 1


def test_export_fallback_mode_selects_event_or_click_backfill(tmp_path: Path) -> None:
    event_ts = _now().timestamp() + 0.2
    click_ts = _now().timestamp() + 0.1
    probe = _FakeVMEventLogProbe(
        event_log=(
            {
                "seq": 10,
                "source_seq": 41,
                "ts": event_ts,
                "event": "pointer:left",
                "role": "window",
                "name": "Application",
                "bbox": [0, 0, 1280, 720],
            },
            {
                "seq": 11,
                "ts": _now().timestamp() + 1.2,
                "event": "pointer-resolution",
                "pointer_seq": 41,
                "resolution": "resolved",
                "source": "atspi-event",
                "role": "menu item",
                "name": "Event target",
                "bbox": [8, 9, 120, 24],
            },
        ),
        click_log=(
            {
                "ts": click_ts,
                "x": 664,
                "y": 364,
                "button": "left",
                "dom": {"tag": "BUTTON", "text": "Click target", "rect": [578, 169, 202, 21]},
            },
        ),
    )

    expected = {
        RecordingExportFallbackMode.NORMAL: ("event_log_backfill", "Event target"),
        RecordingExportFallbackMode.EVENT_ONLY: ("pointer_resolution_backfill", "Event target"),
        RecordingExportFallbackMode.CLICK_ONLY: ("click_log_backfill", "Click target"),
    }
    for mode, (expected_source, expected_label) in expected.items():
        exporter = RecordingExporter(
            graph_reader=_FakeGraphReader(_build_graph()),
            artifacts=_FakeArtifacts({}, {}),
            content_source=_FakeContentSource({}, tmp_path),
            vm_a11y_probe=probe,
        )
        result = exporter.export_session(
            session_id="acs_demo",
            output_root=tmp_path / mode.value,
            fallback_mode=mode,
        )
        dom_hit = json.loads((result.output_dir / "dom_hits.jsonl").read_text(encoding="utf-8").splitlines()[0])
        recording = json.loads((result.output_dir / "recording.json").read_text(encoding="utf-8"))

        assert dom_hit["source"] == expected_source
        assert expected_label in dom_hit["dom_hit_label"]
        assert recording["fallback_mode"] == mode.value
        assert recording["vm_events_count"] == 2
        assert recording["vm_clicks_count"] == 1


def test_click_only_discards_existing_event_watch_target(tmp_path: Path) -> None:
    probe = _FakeVMEventLogProbe(
        records=(
            {
                "action_id": "act_click",
                "action_kind": "click",
                "source": "event_watch",
                "hit_dom": {"role": "push button", "name": "Event target", "bbox": [8, 9, 120, 24]},
                "sample": {"source": "event_watch"},
                "error": None,
            },
        ),
        click_log=(
            {
                "ts": _now().timestamp() + 0.1,
                "x": 664,
                "y": 364,
                "button": "left",
                "dom": {"tag": "BUTTON", "text": "Click target", "rect": [578, 169, 202, 21]},
            },
        ),
    )
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(_build_graph()),
        artifacts=_FakeArtifacts({}, {}),
        content_source=_FakeContentSource({}, tmp_path),
        vm_a11y_probe=probe,
    )

    result = exporter.export_session(
        session_id="acs_demo",
        output_root=tmp_path / "click_only",
        fallback_mode=RecordingExportFallbackMode.CLICK_ONLY,
    )

    dom_hit = json.loads((result.output_dir / "dom_hits.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert dom_hit["source"] == "click_log_backfill"
    assert dom_hit["dom_hit"]["text"] == "Click target"
    trajectory = json.loads((result.output_dir / "trajectory.json").read_text(encoding="utf-8"))
    step = next(item for item in trajectory["steps"] if item.get("action_id") == "act_click")
    assert step["action_summary"]["target"]["display_label"] == "button - Click target"


def test_event_only_discards_existing_event_watch_target(tmp_path: Path) -> None:
    probe = _FakeVMEventLogProbe(
        records=(
            {
                "action_id": "act_click",
                "action_kind": "click",
                "source": "event_watch",
                "hit_dom": {"role": "push button", "name": "Recorded target", "bbox": [8, 9, 120, 24]},
                "sample": {"source": "event_watch"},
                "error": None,
            },
        ),
        event_log=(
            {
                "seq": 10,
                "source_seq": 90,
                "ts": _now().timestamp() + 0.1,
                "event": "pointer:left",
                "role": "window",
                "name": "Application",
                "bbox": [0, 0, 1280, 720],
            },
            {
                "seq": 11,
                "ts": _now().timestamp() + 0.05,
                "event": "object:selection-changed",
                "role": "menu item",
                "name": "Distractor target",
                "bbox": [8, 9, 120, 24],
            },
            {
                "seq": 12,
                "ts": _now().timestamp() + 1.5,
                "event": "pointer-resolution",
                "pointer_seq": 90,
                "resolution": "resolved",
                "source": "atspi-event",
                "role": "menu item",
                "name": "Resolution target",
                "bbox": [9, 10, 121, 25],
            },
        ),
        click_log=(
            {
                "ts": _now().timestamp() + 0.1,
                "dom": {"tag": "BUTTON", "text": "Click target", "rect": [578, 169, 202, 21]},
            },
        ),
    )
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(_build_graph()),
        artifacts=_FakeArtifacts({}, {}),
        content_source=_FakeContentSource({}, tmp_path),
        vm_a11y_probe=probe,
    )

    result = exporter.export_session(
        session_id="acs_demo",
        output_root=tmp_path / "event_only",
        fallback_mode=RecordingExportFallbackMode.EVENT_ONLY,
    )

    dom_hit = json.loads((result.output_dir / "dom_hits.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert dom_hit["source"] == "pointer_resolution_backfill"
    assert dom_hit["dom_hit"]["name"] == "Resolution target"
    assert dom_hit["backfill_delta_ms"] == 100.0
    trajectory = json.loads((result.output_dir / "trajectory.json").read_text(encoding="utf-8"))
    step = next(item for item in trajectory["steps"] if item.get("action_id") == "act_click")
    assert step["action_summary"]["target"]["display_label"] == "menu item - Resolution target"


def test_event_only_does_not_use_semantic_events_without_pointer_resolution(tmp_path: Path) -> None:
    probe = _FakeVMEventLogProbe(
        event_log=(
            {
                "seq": 11,
                "ts": _now().timestamp() + 0.05,
                "event": "object:state-changed:selected",
                "role": "menu item",
                "name": "Must not become the target",
                "bbox": [8, 9, 120, 24],
            },
        ),
    )
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(_build_graph()),
        artifacts=_FakeArtifacts({}, {}),
        content_source=_FakeContentSource({}, tmp_path),
        vm_a11y_probe=probe,
    )

    result = exporter.export_session(
        session_id="acs_demo",
        output_root=tmp_path / "event_only",
        fallback_mode=RecordingExportFallbackMode.EVENT_ONLY,
    )

    dom_hit = json.loads((result.output_dir / "dom_hits.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert dom_hit["status"] == "miss"
    assert "dom_hit" not in dom_hit
    trajectory = json.loads((result.output_dir / "trajectory.json").read_text(encoding="utf-8"))
    assert "Must not become the target" not in json.dumps(trajectory)


def test_batch_export_recovers_probe_sidecars_from_prior_parent_export(tmp_path: Path) -> None:
    graph = _build_graph()
    exporter = _build_exporter(tmp_path, graph=graph)
    output_root = tmp_path / "exports"
    recording_slug = exporter._recording_slug(graph)
    prior_export = output_root / recording_slug
    prior_export.mkdir(parents=True)
    (prior_export / "recording.json").write_text(
        json.dumps({"session_id": graph.session.session_id}),
        encoding="utf-8",
    )
    (prior_export / "vm_clicks.jsonl").write_text(
        json.dumps(
            {
                "ts": _now().timestamp() + 0.2,
                "dom": {"tag": "BUTTON", "text": "Recovered historical target", "rect": [1, 2, 30, 40]},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = exporter.export_session(
        session_id="acs_demo",
        output_root=output_root / "click_only",
        fallback_mode=RecordingExportFallbackMode.CLICK_ONLY,
    )

    dom_hit = json.loads((result.output_dir / "dom_hits.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert dom_hit["status"] == "hit"
    assert dom_hit["source"] == "click_log_backfill"
    assert dom_hit["dom_hit"]["text"] == "Recovered historical target"
    assert result.vm_click_log_count == 1
    assert result.fallback_warning is None


def test_export_backfills_dom_hit_with_live_probe_when_explicitly_enabled(tmp_path: Path) -> None:
    base = _build_graph()
    graph = replace(
        base,
        session=base.session.model_copy(
            update={
                "scope": RecordingScope(
                    kind=RecordingScopeKind.WINDOW,
                    window_id="win_tiger",
                    process_id=4242,
                    app_name="TigerVNC",
                    title="QEMU (mypcbench-persist) - TigerVNC",
                    bounds={
                        "x": 0,
                        "y": 0,
                        "width": 1380,
                        "height": 894,
                        "coordinate_space": "macos_global",
                    },
                )
            }
        ),
    )
    probe = _FakeLiveVMDomProbe()
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(graph),
        artifacts=_FakeArtifacts({}, {}),
        content_source=_FakeContentSource({}, tmp_path),
        vm_a11y_probe=probe,
        vm_display=VMDisplayGeometry(vm_width=1380, vm_height=866, title_bar_pt=28),
        allow_live_vm_a11y_export_fallback=True,
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")

    result_dir = result.output_dir / "0001_20260624T120000_000"
    actions = json.loads((result_dir / "actions.json").read_text(encoding="utf-8"))
    assert actions[0]["dom_hit"] == {"tag": "button", "text": "Live Save", "role": "button"}
    vm_record = json.loads((result_dir / "vm_a11y.json").read_text(encoding="utf-8"))["latest"]
    assert vm_record["source"] == "export_live_dom_probe"
    assert vm_record["action_id"] == "act_click"
    assert probe.points and probe.points[0][2] == "vm_screen"


def test_export_anchors_actions_to_referenced_keyframes(tmp_path: Path) -> None:
    result = _build_exporter(tmp_path).export_session(session_id="acs_demo", output_root=tmp_path / "out")
    recording_dir = result.output_dir

    before_actions = json.loads((recording_dir / "0000_20260624T120000_000" / "actions.json").read_text())
    result_actions = json.loads((recording_dir / "0001_20260624T120000_000" / "actions.json").read_text())

    assert [item["action_id"] for item in before_actions] == ["act_click"]
    assert before_actions[0]["relations"] == ["before_keyframe"]
    assert before_actions[0]["coordinates"]["screen_abs"] == {
        "x": 321.5,
        "y": 654.25,
        "coordinate_space": "macos_global",
    }
    assert [item["action_id"] for item in result_actions] == ["act_click"]
    assert result_actions[0]["relations"] == ["result"]
    assert result_actions[0]["coordinates"]["screen_abs"]["x"] == 321.5


def test_export_records_keyframe_metadata_and_index(tmp_path: Path) -> None:
    result = _build_exporter(tmp_path).export_session(session_id="acs_demo", output_root=tmp_path / "out")
    recording_dir = result.output_dir

    meta = json.loads((recording_dir / "0001_20260624T120000_000" / "meta.json").read_text())
    assert meta["keyframe_id"] == "kf_result"
    assert meta["role"] == "result"
    assert set(meta["evidence_files"]) == {"screenshot.png", "ocr.txt"}

    recording_meta = json.loads((recording_dir / "recording.json").read_text())
    assert recording_meta["session_id"] == "acs_demo"
    assert recording_meta["keyframe_count"] == 2
    assert len(recording_meta["keyframes"]) == 2


def test_export_sidecars_use_projected_media_time(tmp_path: Path) -> None:
    base = _build_graph()
    keyframes = tuple(keyframe.model_copy(update={"media_time_ms": None}) for keyframe in base.keyframes)
    actions = tuple(action.model_copy(update={"media_time_ms": None}) for action in base.actions)
    timeline = RecordingTimelineManifest(
        manifest_id="tlm_demo",
        session_id=base.session.session_id,
        primary_event_id=base.session.primary_event_id,
        clock_origin_wall_time=_now(),
        clock_origin_monotonic_ms=0,
        duration_ms=1_200,
        entries=(
            TimelineKeyframeEntry(
                keyframe_id="kf_before",
                role=keyframes[0].role,
                trigger_kind=keyframes[0].trigger_kind,
                sequence_index=keyframes[0].sequence_index,
                captured_at_wall_time=keyframes[0].captured_at,
                captured_at_monotonic_ms=keyframes[0].captured_at_monotonic_ms,
                media_time_ms=0,
                alignment_confidence=TimelineAlignmentConfidence.EXACT,
                alignment_status=TimelineAlignmentStatus.ALIGNED,
            ),
            TimelineKeyframeEntry(
                keyframe_id="kf_result",
                role=keyframes[1].role,
                trigger_kind=keyframes[1].trigger_kind,
                sequence_index=keyframes[1].sequence_index,
                captured_at_wall_time=keyframes[1].captured_at,
                captured_at_monotonic_ms=keyframes[1].captured_at_monotonic_ms,
                media_time_ms=1_200,
                alignment_confidence=TimelineAlignmentConfidence.EXACT,
                alignment_status=TimelineAlignmentStatus.ALIGNED,
            ),
        ),
        created_at=_now(),
        updated_at=_now(),
    )
    graph = RecordingSessionGraph(
        session=base.session,
        keyframes=keyframes,
        actions=actions,
        controls=base.controls,
        timeline=timeline,
        keyframe_links=base.keyframe_links,
        action_links=base.action_links,
        action_observations=base.action_observations,
        target_resolutions=base.target_resolutions,
        producer_events=base.producer_events,
        producer_decisions=base.producer_decisions,
        total_keyframe_count=base.total_keyframe_count,
        total_action_count=base.total_action_count,
    )
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(graph),
        artifacts=_FakeArtifacts({}, {}),
        content_source=_FakeContentSource({}, tmp_path),
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")

    before_meta = json.loads((result.output_dir / "0000_20260624T120000_000" / "meta.json").read_text())
    result_meta = json.loads((result.output_dir / "0001_20260624T120000_000" / "meta.json").read_text())
    result_actions = json.loads((result.output_dir / "0001_20260624T120000_000" / "actions.json").read_text())
    recording_meta = json.loads((result.output_dir / "recording.json").read_text())
    assert before_meta["media_time_ms"] == 0
    assert result_meta["media_time_ms"] == 1_200
    assert result_actions[0]["media_time_ms"] == 1_200
    assert [item["media_time_ms"] for item in recording_meta["keyframes"]] == [0, 1_200]


def test_export_reprojects_action_media_time_from_segment_media_start(tmp_path: Path) -> None:
    base = _build_graph()
    action = base.actions[0].model_copy(update={"occurred_at_monotonic_ms": 700, "media_time_ms": 900})
    segment = RecordingVideoSegmentRef(
        segment_id="rseg_1",
        session_id=base.session.session_id,
        sequence_index=0,
        state=RecordingSegmentState.AVAILABLE,
        started_at=_now(),
        started_at_monotonic_ms=0,
        media_start_monotonic_ms=100,
        ended_at_monotonic_ms=1_300,
        duration_ms=1_200,
        video=VideoArtifactRef(state=VideoArtifactState.AVAILABLE, artifact_id="art_video", duration_ms=1_200),
    )
    graph = replace(base, actions=(action,), segments=(segment,))
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(graph),
        artifacts=_FakeArtifacts({}, {}),
        content_source=_FakeContentSource({}, tmp_path),
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")

    result_actions = json.loads((result.output_dir / "0001_20260624T120000_000" / "actions.json").read_text())
    key_log = (result.output_dir / "keylog.jsonl").read_text(encoding="utf-8").splitlines()
    assert result_actions[0]["media_time_ms"] == 600
    assert "# Started: 2026-06-24 12:00:00.100" in key_log
    assert any('"timestamp": "00:00:00.600"' in line and "LClick" in line for line in key_log)


def test_summary_omits_keyframes_without_media_time(tmp_path: Path) -> None:
    base = _build_graph()
    trailing_result = base.keyframes[-1].model_copy(
        update={
            "keyframe_id": "kf_result_without_media",
            "role": KeyframeRole.FINAL,
            "trigger_kind": KeyframeTriggerKind.RECORDING_STOP,
            "sequence_index": 2,
            "screenshot_artifact_id": None,
            "media_time_ms": None,
        }
    )
    timeline = RecordingTimelineManifest(
        manifest_id="tlm_demo",
        session_id=base.session.session_id,
        primary_event_id=base.session.primary_event_id,
        clock_origin_wall_time=_now(),
        clock_origin_monotonic_ms=0,
        duration_ms=1_200,
        entries=(),
        created_at=_now(),
        updated_at=_now(),
    )
    graph = RecordingSessionGraph(
        session=base.session,
        keyframes=(*base.keyframes, trailing_result),
        actions=base.actions,
        controls=base.controls,
        timeline=timeline,
        keyframe_links=base.keyframe_links,
        action_links=base.action_links,
        action_observations=base.action_observations,
        target_resolutions=base.target_resolutions,
        producer_events=base.producer_events,
        producer_decisions=base.producer_decisions,
        total_keyframe_count=3,
        total_action_count=base.total_action_count,
    )
    artifacts = {
        "art_shot_before": _artifact(
            "art_shot_before", "evt_primary", ArtifactType.SCREENSHOT, "image/png", "local-artifact://shot_before.png"
        ),
        "art_shot_result": _artifact(
            "art_shot_result", "evt_primary", ArtifactType.SCREENSHOT, "image/png", "local-artifact://shot_result.png"
        ),
    }
    contents = {
        "local-artifact://shot_before.png": b"\x89PNG before",
        "local-artifact://shot_result.png": b"\x89PNG result",
    }
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(graph),
        artifacts=_FakeArtifacts(artifacts, {}),
        content_source=_FakeContentSource(contents, tmp_path),
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")

    summary = (result.output_dir / "summary.md").read_text()
    assert "--:--.---" not in summary
    trajectory = json.loads((result.output_dir / "trajectory.json").read_text())
    assert not any(step["keyframe_id"] == "kf_result_without_media" for step in trajectory["steps"])
    assert not (result.output_dir / "0002_20260624T120000_000").exists()
    recording_meta = json.loads((result.output_dir / "recording.json").read_text())
    assert recording_meta["keyframe_count"] == 2
    assert recording_meta["total_keyframe_count"] == 3
    assert recording_meta["omitted_keyframe_count"] == 1


def test_export_includes_typed_characters_when_full_capture_enabled(tmp_path: Path) -> None:
    from packages.contracts import (
        KeyboardEventKind,
        KeyboardInputClass,
        KeyboardInputPayload,
        KeyCapturePolicy,
        KeyChord,
        ProducerDecision,
        ProducerDecisionReason,
        ProducerDecisionStatus,
        ProducerEventEnvelope,
        ProducerInputEventKind,
    )

    graph = _build_graph()
    key_action = HumanActionEvent(
        action_id="act_key",
        trace_id="trace_demo",
        session_id="acs_demo",
        sequence_index=2,
        kind=HumanActionKind.KEY_DOWN,
        occurred_at=_now(),
        media_time_ms=700,
        scope=RecordingScope(
            kind=RecordingScopeKind.WINDOW,
            window_id="win_tiger",
            process_id=4242,
            app_name="TigerVNC",
            title="QEMU (mypcbench-persist) - TigerVNC",
            bounds={"x": 0, "y": 0, "width": 100, "height": 100, "coordinate_space": "macos_global"},
        ),
    )
    scroll_action = HumanActionEvent(
        action_id="act_scroll",
        trace_id="trace_demo",
        session_id="acs_demo",
        sequence_index=3,
        kind=HumanActionKind.SCROLL,
        occurred_at=_now(),
        media_time_ms=800,
        coordinates=ActionCoordinates(
            screen_abs=ActionPoint(x=10.4, y=20.6, coordinate_space=CoordinateSpace.MACOS_GLOBAL)
        ),
        scroll_delta_y=2.0,
        scope=key_action.scope,
    )
    producer_event = ProducerEventEnvelope(
        producer_event_id="pe_key",
        session_id="acs_demo",
        event_kind=ProducerInputEventKind.KEY_DOWN,
        producer_kind="macos_input",
        occurred_at=_now(),
        keyboard=KeyboardInputPayload(
            keyboard_event_kind=KeyboardEventKind.KEY_DOWN,
            input_class=KeyboardInputClass.TEXT_INPUT,
            capture_policy=KeyCapturePolicy.FULL_CONTENT,
            key_chord=KeyChord(physical_key_code=0, normalized_key_label="a", characters="a"),
        ),
    )
    decision = ProducerDecision(
        decision_id="pd_key",
        producer_event_id="pe_key",
        session_id="acs_demo",
        status=ProducerDecisionStatus.ACCEPTED,
        reason=ProducerDecisionReason.ACCEPTED,
        action_kind=HumanActionKind.KEY_DOWN,
        action_id="act_key",
        created_at=_now(),
    )
    key_link = ActionEvidenceLink(
        link_id="ael_key",
        action_id="act_key",
        role=HumanActionEvidenceRole.AFTER_KEYFRAME,
        keyframe_id="kf_result",
        created_at=_now(),
    )
    graph = RecordingSessionGraph(
        session=graph.session,
        keyframes=graph.keyframes,
        actions=(*graph.actions, key_action, scroll_action),
        controls=graph.controls,
        timeline=graph.timeline,
        keyframe_links=graph.keyframe_links,
        action_links=(*graph.action_links, key_link),
        action_observations=graph.action_observations,
        target_resolutions=graph.target_resolutions,
        producer_events=(producer_event,),
        producer_decisions=(decision,),
    )

    artifacts = {
        artifact_id: _artifact(
            artifact_id, "evt_primary", ArtifactType.SCREENSHOT, "image/png", f"local-artifact://{artifact_id}.png"
        )
        for artifact_id in ("art_shot_before", "art_shot_result")
    }
    artifacts["art_ocr"] = _artifact(
        "art_ocr", "evt_primary", ArtifactType.VISUAL_OCR_TEXT, "text/plain", "local-artifact://ocr.txt"
    )
    artifacts["art_a11y"] = _artifact(
        "art_a11y", "evt_primary", ArtifactType.A11Y_TREE, "application/json", "local-artifact://a11y.json"
    )
    contents = {a.storage_uri: b"x" for a in artifacts.values()}
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(graph),
        artifacts=_FakeArtifacts(artifacts, {}),
        content_source=_FakeContentSource(contents, tmp_path),
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")
    result_actions = json.loads((result.output_dir / "0001_20260624T120000_000" / "actions.json").read_text())
    key_entry = next(item for item in result_actions if item["action_id"] == "act_key")
    assert key_entry["kind"] == "key_down"
    assert key_entry["keyboard"]["characters"] == "a"
    assert key_entry["keyboard"]["key_label"] == "a"
    key_log = (result.output_dir / "keylog.jsonl").read_text(encoding="utf-8").splitlines()
    assert key_log[:5] == [
        "# Input Recording Log",
        "# Started: 2026-06-24 12:00:00.000",
        '# Metadata: {"video_start_time": "2026-06-24 12:00:00.000", "start_message": "Mouse and keyboard monitoring service started", "recording_timestamp": "20260624_120000", "session_id": "acs_demo", "screen_info": {}}',
        "# Format: JSON per line",
        "# Fields: timestamp, message, window",
    ]
    payloads = [json.loads(line) for line in key_log if line and not line.startswith("#")]
    assert payloads == [
        {"timestamp": "00:00:00.600", "message": "LClick at (322, 654)", "window": "unknown"},
        {"timestamp": "00:00:00.601", "message": "LRelease at (322, 654)", "window": "unknown"},
        {
            "timestamp": "00:00:00.700",
            "message": "Key Press: a",
            "window": "TigerVNC - QEMU (mypcbench-persist) - TigerVNC",
        },
        {
            "timestamp": "00:00:00.800",
            "message": "ScrollUp at (10, 21)",
            "window": "TigerVNC - QEMU (mypcbench-persist) - TigerVNC",
        },
    ]


def test_export_input_log_uses_region_screenshot_relative_pixels(tmp_path: Path) -> None:
    base = _build_graph()
    scope = RecordingScope(
        kind=RecordingScopeKind.REGION,
        display_id="1",
        scale_factor=2.0,
        selection_region=BoundingBox(
            x=100,
            y=50,
            width=320,
            height=240,
            coordinate_space=CoordinateSpace.MACOS_GLOBAL,
        ),
    )
    action = base.actions[0].model_copy(
        update={
            "coordinates": ActionCoordinates(
                screen_abs=ActionPoint(
                    x=150,
                    y=80,
                    coordinate_space=CoordinateSpace.MACOS_GLOBAL,
                )
            )
        }
    )
    graph = replace(
        base,
        session=base.session.model_copy(update={"scope": scope}),
        actions=(action,),
    )

    result = _build_exporter(tmp_path, graph=graph).export_session(session_id="acs_demo", output_root=tmp_path / "out")

    key_log = (result.output_dir / "keylog.jsonl").read_text(encoding="utf-8").splitlines()
    assert key_log[2] == (
        '# Metadata: {"video_start_time": "2026-06-24 12:00:00.000", '
        '"start_message": "Mouse and keyboard monitoring service started", '
        '"recording_timestamp": "20260624_120000", "session_id": "acs_demo", '
        '"screen_info": {"1": {"x0": 0, "y0": 0, "width": 640, "height": 480, "scale_factor": 1.0}}}'
    )
    payloads = [json.loads(line) for line in key_log if line and not line.startswith("#")]
    assert payloads[0] == {
        "timestamp": "00:00:00.000",
        "message": '{"1": {"x0": 0, "y0": 0, "width": 640, "height": 480, "scale_factor": 1.0}}',
        "window": "System Info",
    }
    assert payloads[1]["message"] == "LClick at (100, 60)"
    assert payloads[2]["message"] == "LRelease at (100, 60)"
    actions = json.loads((result.output_dir / "0001_20260624T120000_000" / "actions.json").read_text())
    assert actions[0]["coordinates"] == {
        "screenshot_rel": {"x": 100, "y": 60, "coordinate_space": "artifact_px"}
    }
    trajectory = json.loads((result.output_dir / "trajectory.json").read_text())
    action_step = next(step for step in trajectory["steps"] if step.get("action_id") == "act_click")
    assert action_step["coordinates"] == {
        "screenshot_rel": {"x": 100, "y": 60, "coordinate_space": "artifact_px"}
    }


def test_export_input_log_uses_recorded_pointer_button(tmp_path: Path) -> None:
    base = _build_graph()
    action = base.actions[0].model_copy(update={"metadata": {"button": "right", "click_count": 1}})
    graph = replace(base, actions=(action,))

    result = _build_exporter(tmp_path, graph=graph).export_session(session_id="acs_demo", output_root=tmp_path / "out")

    key_log = (result.output_dir / "keylog.jsonl").read_text(encoding="utf-8").splitlines()
    payloads = [json.loads(line) for line in key_log if line and not line.startswith("#")]
    assert payloads[0]["message"] == "RClick at (322, 654)"
    assert payloads[1]["message"] == "RRelease at (322, 654)"
    trajectory = json.loads((result.output_dir / "trajectory.json").read_text(encoding="utf-8"))
    action_step = next(step for step in trajectory["steps"] if step.get("action_id") == "act_click")
    assert action_step["safe_caption"] == "Right Click (target needs review)"
    anchored_actions = json.loads(
        (result.output_dir / "0001_20260624T120000_000" / "actions.json").read_text(encoding="utf-8")
    )
    assert anchored_actions[0]["caption"] == "Right Click (target needs review)"
    summary = (result.output_dir / "summary.md").read_text(encoding="utf-8")
    assert "[action] Right Click (target needs review)" in summary


def test_export_writes_drag_input_log_in_aloha_format(tmp_path: Path) -> None:
    base = _build_graph()
    drag = HumanActionEvent(
        action_id="act_drag",
        trace_id="trace_demo",
        session_id=base.session.session_id,
        sequence_index=0,
        kind=HumanActionKind.DRAG,
        occurred_at=_now(),
        occurred_at_monotonic_ms=1_000,
        media_time_ms=1_000,
        coordinates=ActionCoordinates(
            screen_abs=ActionPoint(x=797, y=784, coordinate_space=CoordinateSpace.MACOS_GLOBAL)
        ),
        metadata={
            "button": "left",
            "drag_start_x": 1179,
            "drag_start_y": 707,
            "drag_duration_ms": 1000,
            "drag_path": "1179,707;1140,719;1082,746;797,784",
        },
    )
    graph = replace(
        base,
        actions=(drag,),
        action_links=(),
        action_observations=(),
        producer_events=(),
        producer_decisions=(),
    )
    artifacts = {
        artifact_id: _artifact(
            artifact_id, "evt_primary", ArtifactType.SCREENSHOT, "image/png", f"local-artifact://{artifact_id}.png"
        )
        for artifact_id in ("art_shot_before", "art_shot_result")
    }
    contents = {artifact.storage_uri: b"x" for artifact in artifacts.values()}
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(graph),
        artifacts=_FakeArtifacts(artifacts, {}),
        content_source=_FakeContentSource(contents, tmp_path),
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")

    key_log = (result.output_dir / "keylog.jsonl").read_text(encoding="utf-8").splitlines()
    payloads = [json.loads(line) for line in key_log if line and not line.startswith("#")]
    assert [item["message"] for item in payloads] == [
        "LClick at (1179, 707)",
        "DragStart at (1179, 707)",
        "DragMove to (1140, 719)",
        "DragMove to (1082, 746)",
        "LDragEnd: from (1179, 707) to (797, 784), distance (-382, 77)",
    ]


def test_export_input_log_converts_drag_path_to_region_screenshot_relative_pixels(tmp_path: Path) -> None:
    base = _build_graph()
    scope = RecordingScope(
        kind=RecordingScopeKind.REGION,
        display_id="1",
        scale_factor=2.0,
        selection_region=BoundingBox(
            x=100,
            y=50,
            width=320,
            height=240,
            coordinate_space=CoordinateSpace.MACOS_GLOBAL,
        ),
    )
    drag = HumanActionEvent(
        action_id="act_drag",
        trace_id="trace_demo",
        session_id=base.session.session_id,
        sequence_index=0,
        kind=HumanActionKind.DRAG,
        occurred_at=_now(),
        occurred_at_monotonic_ms=1_000,
        media_time_ms=1_000,
        coordinates=ActionCoordinates(
            screen_abs=ActionPoint(x=150, y=80, coordinate_space=CoordinateSpace.MACOS_GLOBAL)
        ),
        metadata={
            "button": "left",
            "drag_start_x": 110,
            "drag_start_y": 60,
            "drag_duration_ms": 1000,
            "drag_path": "110,60;130,70;150,80",
        },
    )
    graph = replace(
        base,
        session=base.session.model_copy(update={"scope": scope}),
        actions=(drag,),
        action_links=(),
        action_observations=(),
        producer_events=(),
        producer_decisions=(),
    )

    result = _build_exporter(tmp_path, graph=graph).export_session(session_id="acs_demo", output_root=tmp_path / "out")

    key_log = (result.output_dir / "keylog.jsonl").read_text(encoding="utf-8").splitlines()
    payloads = [json.loads(line) for line in key_log if line and not line.startswith("#")]
    assert [item["message"] for item in payloads[1:]] == [
        "LClick at (20, 20)",
        "DragStart at (20, 20)",
        "DragMove to (60, 40)",
        "LDragEnd: from (20, 20) to (100, 60), distance (80, 40)",
    ]


def test_export_reconstructs_typed_text_for_typing_burst(tmp_path: Path) -> None:
    from packages.contracts import (
        KeyboardEventKind,
        KeyboardInputClass,
        KeyboardInputPayload,
        KeyCapturePolicy,
        KeyChord,
        ProducerDecision,
        ProducerDecisionReason,
        ProducerDecisionStatus,
        ProducerEventEnvelope,
        ProducerInputEventKind,
    )

    base = _build_graph()
    actions: list[HumanActionEvent] = list(base.actions)
    producer_events = []
    producer_decisions = []
    action_links = list(base.action_links)
    for index, char in enumerate(("h", "i")):
        action_id = f"act_key_{char}"
        actions.append(
            HumanActionEvent(
                action_id=action_id,
                trace_id="trace_demo",
                session_id="acs_demo",
                sequence_index=10 + index,
                kind=HumanActionKind.KEY_DOWN,
                occurred_at=_now(),
            )
        )
        producer_events.append(
            ProducerEventEnvelope(
                producer_event_id=f"pe_{char}",
                session_id="acs_demo",
                event_kind=ProducerInputEventKind.KEY_DOWN,
                producer_kind="macos_input",
                occurred_at=_now(),
                keyboard=KeyboardInputPayload(
                    keyboard_event_kind=KeyboardEventKind.KEY_DOWN,
                    input_class=KeyboardInputClass.TEXT_INPUT,
                    capture_policy=KeyCapturePolicy.FULL_CONTENT,
                    key_chord=KeyChord(physical_key_code=index, normalized_key_label=char, characters=char),
                ),
            )
        )
        producer_decisions.append(
            ProducerDecision(
                decision_id=f"pd_{char}",
                producer_event_id=f"pe_{char}",
                session_id="acs_demo",
                status=ProducerDecisionStatus.ACCEPTED,
                reason=ProducerDecisionReason.ACCEPTED,
                action_kind=HumanActionKind.KEY_DOWN,
                action_id=action_id,
                created_at=_now(),
            )
        )
    typing_action = HumanActionEvent(
        action_id="act_typing_burst",
        trace_id="trace_demo",
        session_id="acs_demo",
        sequence_index=12,
        kind=HumanActionKind.TYPING_PAUSE,
        occurred_at=_now(),
    )
    actions.append(typing_action)
    action_links.append(
        ActionEvidenceLink(
            link_id="ael_typing",
            action_id="act_typing_burst",
            role=HumanActionEvidenceRole.AFTER_KEYFRAME,
            keyframe_id="kf_result",
            created_at=_now(),
        )
    )
    graph = RecordingSessionGraph(
        session=base.session,
        keyframes=base.keyframes,
        actions=tuple(actions),
        controls=base.controls,
        timeline=base.timeline,
        keyframe_links=base.keyframe_links,
        action_links=tuple(action_links),
        action_observations=base.action_observations,
        target_resolutions=base.target_resolutions,
        producer_events=tuple(producer_events),
        producer_decisions=tuple(producer_decisions),
    )
    artifacts = {
        "art_shot_result": _artifact(
            "art_shot_result", "evt_primary", ArtifactType.SCREENSHOT, "image/png", "local-artifact://shot_result.png"
        ),
    }
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(graph),
        artifacts=_FakeArtifacts(artifacts, {}),
        content_source=_FakeContentSource({"local-artifact://shot_result.png": b"x"}, tmp_path),
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")
    result_actions = json.loads((result.output_dir / "0001_20260624T120000_000" / "actions.json").read_text())
    typing_entry = next(item for item in result_actions if item["action_id"] == "act_typing_burst")
    assert typing_entry["keyboard"]["typed_text"] == "hi"


def test_export_typed_text_recovers_dropped_key_down_from_key_up(tmp_path: Path) -> None:
    from packages.contracts import (
        KeyboardEventKind,
        KeyboardInputClass,
        KeyboardInputPayload,
        KeyCapturePolicy,
        KeyChord,
        ProducerDecision,
        ProducerDecisionReason,
        ProducerDecisionStatus,
        ProducerEventEnvelope,
        ProducerInputEventKind,
    )

    base = _build_graph()
    actions: list[HumanActionEvent] = list(base.actions)
    producer_events = []
    producer_decisions = []
    # "h" captured as down+up (paired), "i" captured only as key_up (its key_down was
    # dropped at capture time). Reconstruction should still yield "hi".
    key_events = [
        (KeyboardEventKind.KEY_DOWN, ProducerInputEventKind.KEY_DOWN, HumanActionKind.KEY_DOWN, "h", 10),
        (KeyboardEventKind.KEY_UP, ProducerInputEventKind.KEY_UP, HumanActionKind.KEY_UP, "h", 11),
        (KeyboardEventKind.KEY_UP, ProducerInputEventKind.KEY_UP, HumanActionKind.KEY_UP, "i", 12),
    ]
    for index, (kb_kind, pe_kind, action_kind, char, seq) in enumerate(key_events):
        action_id = f"act_key_{seq}"
        actions.append(
            HumanActionEvent(
                action_id=action_id,
                trace_id="trace_demo",
                session_id="acs_demo",
                sequence_index=seq,
                kind=action_kind,
                occurred_at=_now(),
            )
        )
        producer_events.append(
            ProducerEventEnvelope(
                producer_event_id=f"pe_{index}",
                session_id="acs_demo",
                event_kind=pe_kind,
                producer_kind="macos_input",
                occurred_at=_now(),
                keyboard=KeyboardInputPayload(
                    keyboard_event_kind=kb_kind,
                    input_class=KeyboardInputClass.TEXT_INPUT,
                    capture_policy=KeyCapturePolicy.FULL_CONTENT,
                    key_chord=KeyChord(physical_key_code=index, normalized_key_label=char, characters=char),
                ),
            )
        )
        producer_decisions.append(
            ProducerDecision(
                decision_id=f"pd_{index}",
                producer_event_id=f"pe_{index}",
                session_id="acs_demo",
                status=ProducerDecisionStatus.ACCEPTED,
                reason=ProducerDecisionReason.ACCEPTED,
                action_kind=action_kind,
                action_id=action_id,
                created_at=_now(),
            )
        )
    actions.append(
        HumanActionEvent(
            action_id="act_typing_burst",
            trace_id="trace_demo",
            session_id="acs_demo",
            sequence_index=13,
            kind=HumanActionKind.TYPING_PAUSE,
            occurred_at=_now(),
        )
    )
    action_links = (
        *base.action_links,
        ActionEvidenceLink(
            link_id="ael_typing",
            action_id="act_typing_burst",
            role=HumanActionEvidenceRole.AFTER_KEYFRAME,
            keyframe_id="kf_result",
            created_at=_now(),
        ),
    )
    graph = RecordingSessionGraph(
        session=base.session,
        keyframes=base.keyframes,
        actions=tuple(actions),
        controls=base.controls,
        timeline=base.timeline,
        keyframe_links=base.keyframe_links,
        action_links=action_links,
        action_observations=base.action_observations,
        target_resolutions=base.target_resolutions,
        producer_events=tuple(producer_events),
        producer_decisions=tuple(producer_decisions),
    )
    artifacts = {
        "art_shot_result": _artifact(
            "art_shot_result", "evt_primary", ArtifactType.SCREENSHOT, "image/png", "local-artifact://shot_result.png"
        ),
    }
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(graph),
        artifacts=_FakeArtifacts(artifacts, {}),
        content_source=_FakeContentSource({"local-artifact://shot_result.png": b"x"}, tmp_path),
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")
    result_actions = json.loads((result.output_dir / "0001_20260624T120000_000" / "actions.json").read_text())
    typing_entry = next(item for item in result_actions if item["action_id"] == "act_typing_burst")
    assert typing_entry["keyboard"]["typed_text"] == "hi"


def test_export_typed_text_orders_recovered_key_up_before_pending_overlap(tmp_path: Path) -> None:
    from packages.contracts import (
        KeyboardEventKind,
        KeyboardInputClass,
        KeyboardInputPayload,
        KeyCapturePolicy,
        KeyChord,
        ProducerDecision,
        ProducerDecisionReason,
        ProducerDecisionStatus,
        ProducerEventEnvelope,
        ProducerInputEventKind,
    )

    base = _build_graph()
    actions: list[HumanActionEvent] = list(base.actions)
    producer_events = []
    producer_decisions = []
    # Physical order was press 1, press 2, release 1, release 2, but press 1
    # was dropped. The recovered text should still read "12", not "21".
    key_events = [
        (KeyboardEventKind.KEY_DOWN, ProducerInputEventKind.KEY_DOWN, HumanActionKind.KEY_DOWN, "2", 10),
        (KeyboardEventKind.KEY_UP, ProducerInputEventKind.KEY_UP, HumanActionKind.KEY_UP, "1", 11),
        (KeyboardEventKind.KEY_UP, ProducerInputEventKind.KEY_UP, HumanActionKind.KEY_UP, "2", 12),
    ]
    for index, (kb_kind, pe_kind, action_kind, char, seq) in enumerate(key_events):
        action_id = f"act_overlap_{seq}"
        actions.append(
            HumanActionEvent(
                action_id=action_id,
                trace_id="trace_demo",
                session_id="acs_demo",
                sequence_index=seq,
                kind=action_kind,
                occurred_at=_now(),
            )
        )
        producer_events.append(
            ProducerEventEnvelope(
                producer_event_id=f"pe_overlap_{index}",
                session_id="acs_demo",
                event_kind=pe_kind,
                producer_kind="macos_input",
                occurred_at=_now(),
                keyboard=KeyboardInputPayload(
                    keyboard_event_kind=kb_kind,
                    input_class=KeyboardInputClass.TEXT_INPUT,
                    capture_policy=KeyCapturePolicy.FULL_CONTENT,
                    key_chord=KeyChord(physical_key_code=index, normalized_key_label=char, characters=char),
                ),
            )
        )
        producer_decisions.append(
            ProducerDecision(
                decision_id=f"pd_overlap_{index}",
                producer_event_id=f"pe_overlap_{index}",
                session_id="acs_demo",
                status=ProducerDecisionStatus.ACCEPTED,
                reason=ProducerDecisionReason.ACCEPTED,
                action_kind=action_kind,
                action_id=action_id,
                created_at=_now(),
            )
        )
    actions.append(
        HumanActionEvent(
            action_id="act_typing_burst",
            trace_id="trace_demo",
            session_id="acs_demo",
            sequence_index=13,
            kind=HumanActionKind.TYPING_PAUSE,
            occurred_at=_now(),
        )
    )
    action_links = (
        *base.action_links,
        ActionEvidenceLink(
            link_id="ael_typing",
            action_id="act_typing_burst",
            role=HumanActionEvidenceRole.AFTER_KEYFRAME,
            keyframe_id="kf_result",
            created_at=_now(),
        ),
    )
    graph = RecordingSessionGraph(
        session=base.session,
        keyframes=base.keyframes,
        actions=tuple(actions),
        controls=base.controls,
        timeline=base.timeline,
        keyframe_links=base.keyframe_links,
        action_links=action_links,
        action_observations=base.action_observations,
        target_resolutions=base.target_resolutions,
        producer_events=tuple(producer_events),
        producer_decisions=tuple(producer_decisions),
    )
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(graph),
        artifacts=_FakeArtifacts(
            {
                "art_shot_result": _artifact(
                    "art_shot_result",
                    "evt_primary",
                    ArtifactType.SCREENSHOT,
                    "image/png",
                    "local-artifact://shot_result.png",
                ),
            },
            {},
        ),
        content_source=_FakeContentSource({"local-artifact://shot_result.png": b"x"}, tmp_path),
    )

    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")
    result_actions = json.loads((result.output_dir / "0001_20260624T120000_000" / "actions.json").read_text())
    typing_entry = next(item for item in result_actions if item["action_id"] == "act_typing_burst")
    assert typing_entry["keyboard"]["typed_text"] == "12"


def test_export_failure_does_not_leave_empty_folder(tmp_path: Path) -> None:
    class _BoomProjector:
        def build(self, graph: object) -> object:
            raise RuntimeError("boom")

    exporter = _build_exporter(tmp_path)
    exporter.timeline_projector = _BoomProjector()  # type: ignore[assignment]
    out = tmp_path / "out"
    try:
        exporter.export_session(session_id="acs_demo", output_root=out)
    except RuntimeError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("expected RuntimeError")
    leftover = list(out.iterdir()) if out.exists() else []
    assert leftover == [], f"expected no orphan recording folder, found {leftover}"


def test_export_unknown_session_raises(tmp_path: Path) -> None:
    exporter = _build_exporter(tmp_path)
    try:
        exporter.export_session(session_id="missing", output_root=tmp_path / "out")
    except RecordingExportError as error:
        assert "missing" in str(error)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected RecordingExportError")


def test_backfill_dom_hits_from_event_log_recovers_missed_targets() -> None:
    exporter = RecordingExporter(graph_reader=object(), artifacts=object(), content_source=object())
    base = 1_000_000.0

    def at(delta: float) -> datetime:
        return datetime.fromtimestamp(base + delta, tz=UTC)

    graph = SimpleNamespace(
        actions=[
            SimpleNamespace(action_id="a1", kind=HumanActionKind.CLICK, occurred_at=at(0.0), metadata={}),
            SimpleNamespace(action_id="a2", kind=HumanActionKind.CLICK, occurred_at=at(0.15), metadata={}),
            SimpleNamespace(action_id="a3", kind=HumanActionKind.DRAG, occurred_at=at(5.0), metadata={}),
            SimpleNamespace(action_id="a4", kind=HumanActionKind.CLICK, occurred_at=at(60.0), metadata={}),
        ]
    )
    event_log = [
        {"seq": 1, "ts": base - 0.05, "role": "document web", "name": "Page", "bbox": [0, 0, 100, 100]},
        {"seq": 2, "ts": base + 0.10, "role": "menu item", "name": "LockedIn", "bbox": [10, 10, 50, 20]},
        {"seq": 3, "ts": base + 5.20, "role": "link", "name": "TMIQ-3", "bbox": [5, 5, 40, 40]},
        {"seq": 4, "ts": base + 5.30, "role": "window", "name": "", "bbox": [-99, -99, 1, 1]},
    ]

    out = exporter._backfill_dom_hits_from_event_log(graph=graph, existing={}, event_log=event_log)

    # The nearest specific event wins; the generic page/window focuses are ignored.
    assert out["a1"][0]["hit_dom"] == {"role": "menu item", "name": "LockedIn", "bbox": [10, 10, 50, 20]}
    assert out["a1"][0]["source"] == "event_log_backfill"
    assert out["a3"][0]["hit_dom"]["name"] == "TMIQ-3"
    # The single LockedIn event is consumed once, so the second nearby click does not reuse it.
    assert "a2" not in out
    # No specific event within the window for the far click.
    assert "a4" not in out


def test_backfill_dom_hits_from_event_log_uses_dom_when_a11y_is_generic() -> None:
    exporter = RecordingExporter(graph_reader=object(), artifacts=object(), content_source=object())
    base = 1_000_000.0
    graph = SimpleNamespace(
        actions=[
            SimpleNamespace(
                action_id="a1",
                kind=HumanActionKind.CLICK,
                occurred_at=datetime.fromtimestamp(base, tz=UTC),
                metadata={},
            )
        ]
    )
    event_log = [
        {
            "seq": 1,
            "ts": base + 0.2,
            "dom": {
                "tag": "SPAN",
                "text": "reservations@pizzabyalfredo.com",
                "rect": [324, 217, 211, 21],
            },
            "a11y": {"role": "document web", "name": "HooliChat Web", "bbox": [66, 183, 1215, 617]},
        }
    ]

    out = exporter._backfill_dom_hits_from_event_log(graph=graph, existing={}, event_log=event_log)

    assert out["a1"][0]["hit_dom"] == {
        "tag": "SPAN",
        "text": "reservations@pizzabyalfredo.com",
        "rect": [324, 217, 211, 21],
    }


def test_backfill_skips_actions_that_already_have_a_hit() -> None:
    exporter = RecordingExporter(graph_reader=object(), artifacts=object(), content_source=object())
    base = 1_000_000.0
    graph = SimpleNamespace(
        actions=[
            SimpleNamespace(action_id="a1", kind=HumanActionKind.CLICK, occurred_at=datetime.fromtimestamp(base, tz=UTC), metadata={})
        ]
    )
    existing = {"a1": [{"hit_dom": {"role": "button", "name": "Live"}}]}
    event_log = [{"seq": 1, "ts": base, "role": "menu item", "name": "Backfill", "bbox": [1, 1, 9, 9]}]

    out = exporter._backfill_dom_hits_from_event_log(graph=graph, existing=existing, event_log=event_log)

    assert out == {}


def test_backfill_anchors_drag_at_grab_start_not_release() -> None:
    exporter = RecordingExporter(graph_reader=object(), artifacts=object(), content_source=object())
    base = 1_000_000.0
    # Drag released 8s after grab; its target's event fires at the grab, not release.
    drag = SimpleNamespace(
        action_id="d1",
        kind=HumanActionKind.DRAG,
        occurred_at=datetime.fromtimestamp(base + 8.0, tz=UTC),
        metadata={"drag_duration_ms": 8000},
    )
    graph = SimpleNamespace(actions=[drag])
    event_log = [
        {"seq": 1, "ts": base - 0.3, "role": "link", "name": "Grabbed Card", "bbox": [10, 10, 80, 30]},
        {"seq": 2, "ts": base + 8.0, "role": "document web", "name": "Board", "bbox": [0, 0, 500, 500]},
    ]

    out = exporter._backfill_dom_hits_from_event_log(graph=graph, existing={}, event_log=event_log)

    # Anchored at grab (base): the dragged card, not the generic page focus at release.
    assert out["d1"][0]["hit_dom"]["name"] == "Grabbed Card"


def test_vm_event_log_stamps_media_time_and_drops_stale(tmp_path: Path) -> None:
    exporter = RecordingExporter(graph_reader=object(), artifacts=object(), content_source=object())
    start = datetime(2026, 6, 29, 12, 0, 0, tzinfo=UTC)
    start_epoch = start.timestamp()
    session = SimpleNamespace(
        started_at=start,
        created_at=start,
        ended_at=datetime.fromtimestamp(start_epoch + 30, tz=UTC),
    )
    graph = SimpleNamespace(session=session)
    events = [
        {"seq": 1, "ts": start_epoch - 100.0, "role": "frame", "name": "old session"},  # stale backlog
        {"seq": 2, "ts": start_epoch - 1.0, "role": "page tab", "name": "Pre"},          # just before start
        {"seq": 3, "ts": start_epoch + 5.936, "role": "menu item", "name": "LockedIn"},
        {"seq": 4, "ts": start_epoch + 100.0, "role": "link", "name": "after end"},       # past end+margin
    ]

    count = exporter._write_vm_event_log(events=events, recording_dir=tmp_path, graph=graph)

    lines = [json.loads(line) for line in (tmp_path / "vm_events.jsonl").read_text().splitlines()]
    kept_seqs = {line["seq"] for line in lines}
    assert kept_seqs == {2, 3}  # stale-before and past-end dropped
    assert count == 2
    by_seq = {line["seq"]: line for line in lines}
    assert by_seq[3]["media_time"] == "00:05.936"
    assert by_seq[3]["media_time_ms"] == 5936
    assert by_seq[2]["media_time"] == "-00:01.000"  # pre-start offset renders negative


def test_vm_sidecars_use_first_video_frame_wall_clock_anchor(tmp_path: Path) -> None:
    exporter = RecordingExporter(graph_reader=object(), artifacts=object(), content_source=object())
    session_start = datetime(2026, 7, 19, 14, 35, 16, 834_000, tzinfo=UTC)
    session_start_epoch = session_start.timestamp()
    media_start_epoch_ms = round((session_start_epoch + 1.989) * 1000)
    session = SimpleNamespace(
        started_at=session_start,
        created_at=session_start,
        ended_at=datetime.fromtimestamp(session_start_epoch + 30, tz=UTC),
    )
    segment = SimpleNamespace(
        sequence_index=0,
        started_at=session_start,
        media_start_wall_time_epoch_ms=media_start_epoch_ms,
        media_start_monotonic_ms=10_000,
        ended_at_monotonic_ms=20_000,
        duration_ms=10_000,
        video=None,
    )
    graph = SimpleNamespace(session=session, segments=(segment,))

    count = exporter._write_vm_event_log(
        events=[{"seq": 1, "ts": session_start_epoch + 7.035, "event": "focus:"}],
        recording_dir=tmp_path,
        graph=graph,
    )
    clicks = exporter._session_window_clicks(
        graph=graph,
        clicks=[{"ts": session_start_epoch + 7.027, "button": "left"}],
    )

    event = json.loads((tmp_path / "vm_events.jsonl").read_text().strip())
    assert count == 1
    assert event["media_time_ms"] == 5046
    assert event["media_time"] == "00:05.046"
    assert clicks[0]["media_time_ms"] == 5038
    assert clicks[0]["media_time"] == "00:05.038"


def test_vm_sidecar_wall_clock_projection_skips_pause_gap() -> None:
    exporter = RecordingExporter(graph_reader=object(), artifacts=object(), content_source=object())
    session_start = datetime(2026, 7, 19, 14, 35, 16, tzinfo=UTC)
    start_ms = round(session_start.timestamp() * 1_000)
    session = SimpleNamespace(
        started_at=session_start,
        created_at=session_start,
        ended_at=datetime.fromtimestamp(session_start.timestamp() + 30, tz=UTC),
    )
    segments = (
        SimpleNamespace(
            sequence_index=0,
            started_at=session_start,
            media_start_wall_time_epoch_ms=start_ms + 2_000,
            media_start_monotonic_ms=10_000,
            ended_at_monotonic_ms=15_000,
            duration_ms=5_000,
            video=None,
        ),
        SimpleNamespace(
            sequence_index=1,
            started_at=datetime.fromtimestamp(session_start.timestamp() + 10, tz=UTC),
            media_start_wall_time_epoch_ms=start_ms + 10_000,
            media_start_monotonic_ms=20_000,
            ended_at_monotonic_ms=24_000,
            duration_ms=4_000,
            video=None,
        ),
    )
    graph = SimpleNamespace(session=session, segments=segments)

    clicks = exporter._session_window_clicks(
        graph=graph,
        clicks=[
            {"ts": session_start.timestamp() + 8, "button": "left"},
            {"ts": session_start.timestamp() + 11, "button": "left"},
        ],
    )

    assert "media_time_ms" not in clicks[0]
    assert clicks[1]["media_time_ms"] == 6_000


def test_export_preserves_linux_atspi_tree_in_event_archive(tmp_path: Path) -> None:
    snapshot = {
        "started_at": _now().timestamp() - 0.2,
        "completed_at": _now().timestamp() - 0.1,
        "tree": {"children": [{"role": "push button", "name": "Save"}]},
    }
    exporter = RecordingExporter(
        graph_reader=_FakeGraphReader(_build_graph()),
        artifacts=_FakeArtifacts({}, {}),
        content_source=_FakeContentSource({}, tmp_path),
        vm_a11y_probe=_FakeVMEventLogProbe(
            event_log=(
                {
                    "seq": 1,
                    "ts": _now().timestamp() + 0.1,
                    "source_profile": "linux_atspi_v1",
                    "role": "push button",
                    "name": "Save",
                    "a11y_snapshot": snapshot,
                },
            )
        ),
    )
    result = exporter.export_session(session_id="acs_demo", output_root=tmp_path / "out")
    events = [json.loads(line) for line in (result.output_dir / "vm_events.jsonl").read_text().splitlines()]
    assert events[0]["a11y_snapshot"] == snapshot
    assert events[0]["source_profile"] == "linux_atspi_v1"
