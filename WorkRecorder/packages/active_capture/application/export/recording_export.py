"""Materialize an active-capture recording into a human-browsable directory.

The daemon stores artifacts content-addressed inside an opaque vault
(``blobs/<sha>/...``); every relation between a recording, its keyframes, and
the screenshot/OCR/a11y/action evidence lives only in SQLite. This exporter
reads the loaded recording graph and lays the same data out on disk as::

    <output_root>/<recording_slug>/
        recording.json                 # session metadata + folder index
        trajectory.json                # full ordered timeline (keyframes+actions)
        summary.md                     # human-readable operation trajectory
        dom_hits.jsonl                 # normalized action-aligned DOM hits
        video.mp4 | video/<n>.mp4      # recording video, when available
        0000_<timestamp>/              # one folder per keyframe
            screenshot.png
            ocr.txt | ocr.json
            vm_a11y.json | vm_a11y.jsonl
            ...                        # other non-browser linked evidence
            actions.json               # actions anchored to this keyframe
            meta.json                  # keyframe trigger/role/timing metadata

The vault layout is left untouched; this is an additive, read-only projection.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from packages.active_capture.application.vm_coordinate_mapping import VMDisplayGeometry, build_vm_display_mapping
from packages.active_capture.application.inspect.timeline import RecordingTimelineProjector
from packages.active_capture.application.read_model import (
    RecordingSessionGraph,
    RecordingSessionGraphReader,
)
from packages.contracts import (
    Artifact,
    ArtifactType,
    BoundingBox,
    ContextKeyframe,
    HotkeySemantic,
    HumanActionEvent,
    HumanActionKind,
    KeyframeEvidenceLink,
    KeyframeEvidenceRole,
    KeyframeRole,
    RecordingControlKind,
    RecordingExportFallbackMode,
    RecordingScope,
    RecordingTimelineInspectView,
    RecordingTimelineStepView,
    RecordingStoryboardItemKind,
)


class RecordingExportError(Exception):
    """Raised when a recording cannot be exported."""


class ArtifactLookup(Protocol):
    """Minimal artifact repository surface needed for export."""

    def get(self, artifact_id: str) -> Artifact | None: ...

    def list_for_event(self, event_id: str) -> tuple[Artifact, ...]: ...


class ArtifactContentSource(Protocol):
    """Resolves a stored artifact URI to a readable local file path."""

    def resolve_local_path(self, storage_uri: str) -> Path: ...


class VMAccessibilityExportSource(Protocol):
    """Provides VM DOM hit probe records captured during a recording."""

    def export_records_for_session(self, session_id: str) -> tuple[dict[str, object], ...]: ...

    def export_event_log_for_session(self, session_id: str) -> tuple[dict[str, object], ...]: ...

    def export_click_log_for_session(self, session_id: str) -> tuple[dict[str, object], ...]: ...

    def sample_point_for_export(
        self,
        *,
        session_id: str,
        occurred_at_monotonic_ms: int | None,
        point_x: float,
        point_y: float,
        coordinate_space: str,
    ) -> dict[str, object] | None: ...


class VideoFrameExtractor(Protocol):
    """Extracts a still image from a recording video."""

    def extract_png(self, *, video_path: Path, media_time_ms: int, output_path: Path) -> bool: ...


class FFmpegVideoFrameExtractor:
    """Best-effort mp4 frame extraction using a local ffmpeg binary."""

    def __init__(self, *, ffmpeg_path: str | None = None) -> None:
        self.ffmpeg_path = ffmpeg_path

    def extract_png(self, *, video_path: Path, media_time_ms: int, output_path: Path) -> bool:
        ffmpeg = self.ffmpeg_path or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
        if not Path(ffmpeg).exists() and shutil.which(ffmpeg) is None:
            return False
        output_path.parent.mkdir(parents=True, exist_ok=True)
        seconds = max(0, media_time_ms) / 1000
        command = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{seconds:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            str(output_path),
        ]
        try:
            completed = subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return False
        return completed.returncode == 0 and output_path.is_file()


_VM_A11Y_EXPORT_EVENT_KINDS = frozenset({"pointer_click", "pointer_drag"})
_VM_A11Y_KEYFRAME_PERIODIC_MATCH_WINDOW_SECONDS = 0.5


@dataclass(frozen=True)
class RecordingExportResult:
    """Outcome of materializing one recording to disk.

    Attributes:
        session_id: Exported recording session id.
        output_dir: Recording root directory that was written.
        keyframe_dir_count: Number of per-keyframe timestamp folders created.
        evidence_file_count: Number of evidence files copied across keyframes.
        action_count: Number of actions written into the trajectory.
        video_file_count: Number of recording video files exported.
    """

    session_id: str
    output_dir: Path
    keyframe_dir_count: int
    evidence_file_count: int
    action_count: int
    video_file_count: int
    vm_a11y_record_count: int = 0
    vm_event_log_count: int = 0
    vm_click_log_count: int = 0
    fallback_warning: str | None = None


_ROLE_BASENAMES: dict[KeyframeEvidenceRole, str] = {
    KeyframeEvidenceRole.SCREENSHOT: "screenshot",
    KeyframeEvidenceRole.SYSTEM_APPSHOT: "system_appshot",
    KeyframeEvidenceRole.A11Y: "a11y",
    KeyframeEvidenceRole.OCR: "ocr",
    KeyframeEvidenceRole.WEB: "web",
    KeyframeEvidenceRole.SELECTION_TEXT: "selection_text",
    KeyframeEvidenceRole.CANONICAL_TEXT: "canonical_text",
    KeyframeEvidenceRole.CLEAN_TEXT: "clean_text",
    KeyframeEvidenceRole.VIDEO: "video",
    KeyframeEvidenceRole.TIMELINE: "timeline",
    KeyframeEvidenceRole.SUMMARY: "summary",
}

_RAW_LOCAL_EXPORT_OMITTED_ROLES = frozenset(
    {
        KeyframeEvidenceRole.A11Y,
        KeyframeEvidenceRole.WEB,
        KeyframeEvidenceRole.SELECTION_TEXT,
        KeyframeEvidenceRole.CANONICAL_TEXT,
        KeyframeEvidenceRole.CLEAN_TEXT,
    }
)

_CONTENT_TYPE_SUFFIXES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "application/json": ".json",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/html": ".html",
    "video/mp4": ".mp4",
}


class RecordingExporter:
    """Project a stored recording graph into a per-recording directory tree."""

    def __init__(
        self,
        *,
        graph_reader: RecordingSessionGraphReader,
        artifacts: ArtifactLookup,
        content_source: ArtifactContentSource,
        vm_a11y_probe: VMAccessibilityExportSource | None = None,
        vm_display: VMDisplayGeometry | None = None,
        allow_live_vm_a11y_export_fallback: bool = False,
        timeline_projector: RecordingTimelineProjector | None = None,
        video_frame_extractor: VideoFrameExtractor | None = None,
    ) -> None:
        self.graph_reader = graph_reader
        self.artifacts = artifacts
        self.content_source = content_source
        self.vm_a11y_probe = vm_a11y_probe
        self.vm_display = vm_display
        self.allow_live_vm_a11y_export_fallback = allow_live_vm_a11y_export_fallback
        self.timeline_projector = timeline_projector or RecordingTimelineProjector()
        self.video_frame_extractor = video_frame_extractor or FFmpegVideoFrameExtractor()

    def export_session(
        self,
        *,
        session_id: str,
        output_root: Path,
        fallback_mode: RecordingExportFallbackMode = RecordingExportFallbackMode.NORMAL,
    ) -> RecordingExportResult:
        """Materialize one recording session under ``output_root``.

        Args:
            session_id: Active-capture recording session id to export.
            output_root: Parent directory; a per-recording subfolder is created.
            fallback_mode: DOM target backfill source selection for unresolved actions.

        Returns:
            Summary counts and the recording root directory that was written.

        Raises:
            RecordingExportError: When the session graph cannot be loaded.
        """

        graph = self.graph_reader.load_for_session(session_id)
        if graph is None:
            raise RecordingExportError(f"recording session not found: {session_id}")

        recording_dir = self._recording_dir(
            output_root=output_root.expanduser(),
            graph=graph,
            fallback_mode=fallback_mode,
        )
        recording_dir.mkdir(parents=True, exist_ok=True)
        try:
            return self._materialize(
                graph=graph,
                recording_dir=recording_dir,
                fallback_mode=fallback_mode,
            )
        except Exception:
            # Never leave behind an empty half-written recording folder on failure.
            with suppress(OSError):
                if not any(recording_dir.iterdir()):
                    recording_dir.rmdir()
            raise

    def _materialize(
        self,
        *,
        graph: RecordingSessionGraph,
        recording_dir: Path,
        fallback_mode: RecordingExportFallbackMode,
    ) -> RecordingExportResult:
        timeline = self.timeline_projector.build(graph)
        step_by_action = {step.action_id: step for step in timeline.steps if step.action_id is not None}
        media_time_by_keyframe = {
            step.keyframe_id: step.media_time_ms
            for step in timeline.steps
            if step.keyframe_id is not None and step.kind == RecordingStoryboardItemKind.KEYFRAME
        }
        exportable_keyframe_ids = self._exportable_keyframe_ids(
            graph=graph,
        )
        export_keyframes = tuple(
            keyframe for keyframe in graph.keyframes if keyframe.keyframe_id in exportable_keyframe_ids
        )
        typed_text_by_action = self._typed_text_by_typing_action(graph, step_by_action)
        links_by_keyframe = self._links_by_keyframe(graph.keyframe_links)
        existing_sidecars = self._existing_export_sidecars(
            recording_dir=recording_dir,
            session_id=graph.session.session_id,
        )
        vm_a11y_records = self._vm_a11y_records(graph=graph)
        if not vm_a11y_records:
            vm_a11y_records = existing_sidecars["records"]
        vm_a11y_by_action = self._vm_a11y_by_action(graph, records=vm_a11y_records)
        if self.allow_live_vm_a11y_export_fallback:
            live_vm_a11y_by_action = self._live_vm_a11y_by_action(graph=graph, existing=vm_a11y_by_action)
            if live_vm_a11y_by_action:
                vm_a11y_by_action = {
                    **vm_a11y_by_action,
                    **live_vm_a11y_by_action,
                }
        if fallback_mode in {
            RecordingExportFallbackMode.EVENT_ONLY,
            RecordingExportFallbackMode.CLICK_ONLY,
        }:
            # Strict single-source exports must rebuild targets from their raw
            # sidecar alone. Recorded/live action samples are a separate input
            # and must not win before event/click log backfill runs below.
            vm_a11y_by_action = {}
        # The live click probe can miss late-rendering targets (e.g. dropdown
        # items) and degrades under fast clicks because it is serial. Recover those
        # targets post-hoc by matching each unresolved click/drag against the full
        # captured event log, which carries the complete, correctly-timed stream.
        vm_event_log = self._vm_event_log(graph=graph)
        if not self._session_window_external_records(graph=graph, records=vm_event_log):
            vm_event_log = existing_sidecars["event_log"]
        if fallback_mode != RecordingExportFallbackMode.CLICK_ONLY:
            if fallback_mode == RecordingExportFallbackMode.EVENT_ONLY:
                backfilled = self._backfill_dom_hits_from_pointer_resolutions(
                    graph=graph,
                    existing=vm_a11y_by_action,
                    event_log=vm_event_log,
                )
            else:
                backfilled = self._backfill_dom_hits_from_event_log(
                    graph=graph,
                    existing=vm_a11y_by_action,
                    event_log=vm_event_log,
                )
            for action_id, records in backfilled.items():
                vm_a11y_by_action.setdefault(action_id, []).extend(records)
        vm_click_log = self._vm_click_log(graph=graph)
        if not self._session_window_external_records(graph=graph, records=vm_click_log):
            vm_click_log = existing_sidecars["click_log"]
        if fallback_mode != RecordingExportFallbackMode.EVENT_ONLY:
            click_backfilled = self._backfill_dom_hits_from_click_log(
                graph=graph,
                existing=vm_a11y_by_action,
                click_log=vm_click_log,
            )
            for action_id, records in click_backfilled.items():
                vm_a11y_by_action.setdefault(action_id, []).extend(records)
        periodic_vm_a11y_by_keyframe = {
            keyframe_id: records
            for keyframe_id, records in self._periodic_vm_a11y_by_keyframe(graph, records=vm_a11y_records).items()
            if keyframe_id in exportable_keyframe_ids
        }
        actions_by_keyframe = self._actions_by_keyframe(
            graph,
            step_by_action,
            typed_text_by_action,
            vm_a11y_by_action=vm_a11y_by_action,
        )
        actions_by_keyframe = {
            keyframe_id: actions
            for keyframe_id, actions in actions_by_keyframe.items()
            if keyframe_id in exportable_keyframe_ids
        }
        primary_keyframe_by_action = self._primary_keyframe_by_action(actions_by_keyframe)
        recording_video_source = self._primary_recording_video_source(graph)

        evidence_file_count = 0
        keyframe_index: list[dict[str, object]] = []
        vm_a11y_files: list[str] = []
        for keyframe in export_keyframes:
            folder_name = self._keyframe_folder_name(keyframe)
            keyframe_dir = recording_dir / folder_name
            keyframe_dir.mkdir(parents=True, exist_ok=True)
            written = self._write_keyframe_evidence(
                keyframe=keyframe,
                links=links_by_keyframe.get(keyframe.keyframe_id, ()),
                keyframe_dir=keyframe_dir,
                video_source=recording_video_source,
                media_time_ms=media_time_by_keyframe.get(keyframe.keyframe_id),
            )
            evidence_file_count += len(written)
            anchored_actions = actions_by_keyframe.get(keyframe.keyframe_id, [])
            keyframe_vm_a11y = self._vm_a11y_records_for_keyframe(
                keyframe_id=keyframe.keyframe_id,
                anchored_actions=anchored_actions,
                primary_keyframe_by_action=primary_keyframe_by_action,
                vm_a11y_by_action=vm_a11y_by_action,
            )
            keyframe_vm_a11y.extend(periodic_vm_a11y_by_keyframe.get(keyframe.keyframe_id, ()))
            if keyframe_vm_a11y:
                written["vm_a11y:jsonl"] = "vm_a11y.jsonl"
                written["vm_a11y:json"] = "vm_a11y.json"
                vm_a11y_files.extend(
                    self._write_keyframe_vm_a11y(
                        keyframe_dir=keyframe_dir,
                        folder_name=folder_name,
                        session_id=graph.session.session_id,
                        records=keyframe_vm_a11y,
                    )
                )
            self._write_json(keyframe_dir / "actions.json", anchored_actions)
            self._write_json(
                keyframe_dir / "meta.json",
                self._keyframe_meta(
                    keyframe=keyframe,
                    media_time_ms=media_time_by_keyframe.get(keyframe.keyframe_id),
                    evidence_files=written,
                ),
            )
            keyframe_index.append(
                {
                    "keyframe_id": keyframe.keyframe_id,
                    "folder": folder_name,
                    "role": keyframe.role.value,
                    "captured_at": _iso(keyframe.captured_at),
                    "media_time_ms": media_time_by_keyframe.get(keyframe.keyframe_id),
                    "evidence_files": sorted(written.values()),
                    "action_count": len(anchored_actions),
                }
            )

        video_file_count = self._write_video(graph=graph, recording_dir=recording_dir)
        root_vm_a11y_records = self._root_vm_a11y_records(
            graph=graph,
            vm_a11y_records=vm_a11y_records,
            vm_a11y_by_action=vm_a11y_by_action,
        )
        vm_a11y_files = [
            *self._write_root_vm_a11y(
                recording_dir=recording_dir,
                session_id=graph.session.session_id,
                records=root_vm_a11y_records,
            ),
            *vm_a11y_files,
        ]

        self._write_json(
            recording_dir / "trajectory.json",
            self._timeline_payload(
                timeline,
                graph=graph,
                vm_a11y_by_action=vm_a11y_by_action,
                exportable_keyframe_ids=exportable_keyframe_ids,
            ),
        )
        input_log_entries = self._input_log_entries(graph=graph, timeline=timeline)
        self._write_input_log(recording_dir / "keylog.jsonl", graph=graph, entries=input_log_entries)
        dom_hit_count, dom_hit_match_count = self._write_dom_hits(
            recording_dir=recording_dir,
            graph=graph,
            step_by_action=step_by_action,
            vm_a11y_by_action=vm_a11y_by_action,
        )
        vm_event_log_count = self._write_vm_event_log(
            events=vm_event_log, recording_dir=recording_dir, graph=graph
        )
        vm_click_log_count = self._write_vm_click_log(
            clicks=vm_click_log, recording_dir=recording_dir, graph=graph
        )
        target_action_count = sum(
            action.kind in {HumanActionKind.CLICK, HumanActionKind.DRAG} for action in graph.actions
        )
        fallback_warning = (
            "该导出模式没有匹配到点击目标；历史 event/click 外部日志可能未保存或已经过期。"
            if target_action_count > 0 and dom_hit_match_count == 0
            else None
        )
        self._write_json(
            recording_dir / "recording.json",
            self._recording_meta(
                graph=graph,
                keyframe_index=keyframe_index,
                video_file_count=video_file_count,
                vm_a11y_files=vm_a11y_files,
                vm_event_log_count=vm_event_log_count,
                vm_click_log_count=vm_click_log_count,
                dom_hit_count=dom_hit_count,
                dom_hit_match_count=dom_hit_match_count,
                fallback_mode=fallback_mode,
                fallback_warning=fallback_warning,
            ),
        )
        (recording_dir / "summary.md").write_text(
            self._render_summary(
                graph=graph,
                timeline=timeline,
                typed_text_by_action=typed_text_by_action,
                vm_a11y_by_action=vm_a11y_by_action,
                exportable_keyframe_ids=exportable_keyframe_ids,
            ),
            encoding="utf-8",
        )

        return RecordingExportResult(
            session_id=graph.session.session_id,
            output_dir=recording_dir,
            keyframe_dir_count=len(export_keyframes),
            evidence_file_count=evidence_file_count,
            action_count=len(graph.actions),
            video_file_count=video_file_count,
            vm_a11y_record_count=len(vm_a11y_records),
            vm_event_log_count=vm_event_log_count,
            vm_click_log_count=vm_click_log_count,
            fallback_warning=fallback_warning,
        )

    def _existing_export_sidecars(
        self,
        *,
        recording_dir: Path,
        session_id: str,
    ) -> dict[str, tuple[dict[str, object], ...]]:
        """Recover probe streams from a prior export before rewriting its files.

        Batch exports write below ``normal/``, ``event_only/``, and ``click_only/``;
        the parent recording export remains a useful recovery source for sessions
        created before probe archives were introduced.
        """

        candidates = [recording_dir]
        if recording_dir.parent.parent != recording_dir.parent:
            candidates.append(recording_dir.parent.parent / recording_dir.name)
        for parent in (recording_dir.parent, recording_dir.parent.parent):
            with suppress(OSError):
                candidates.extend(path for path in parent.iterdir() if path.is_dir())
        candidates = list(dict.fromkeys(candidates))
        for candidate in candidates:
            recording_meta = candidate / "recording.json"
            if not recording_meta.is_file():
                continue
            try:
                metadata = json.loads(recording_meta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(metadata, dict) or metadata.get("session_id") != session_id:
                continue
            records = tuple(
                row
                for row in self._read_jsonl(candidate / "vm_a11y.jsonl")
                if isinstance(row.get("trigger"), dict) or row.get("source") == "periodic_watch"
            )
            sidecars = {
                "records": records,
                "event_log": self._read_jsonl(candidate / "vm_events.jsonl"),
                "click_log": self._read_jsonl(candidate / "vm_clicks.jsonl"),
            }
            if any(sidecars.values()):
                return sidecars
        return {"records": (), "event_log": (), "click_log": ()}

    def _read_jsonl(self, path: Path) -> tuple[dict[str, object], ...]:
        if not path.is_file():
            return ()
        rows: list[dict[str, object]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
        except OSError:
            return ()
        return tuple(rows)

    def _exportable_keyframe_ids(
        self,
        *,
        graph: RecordingSessionGraph,
    ) -> set[str]:
        """Return keyframes that can be located on the exported media timeline."""

        timeline_entries = {entry.keyframe_id: entry for entry in graph.timeline.entries} if graph.timeline else {}
        aligned = {
            keyframe.keyframe_id
            for keyframe in graph.keyframes
            if keyframe.media_time_ms is not None
            or (
                (entry := timeline_entries.get(keyframe.keyframe_id)) is not None
                and entry.media_time_ms is not None
            )
        }
        if not aligned:
            return {keyframe.keyframe_id for keyframe in graph.keyframes}
        return aligned

    def _write_keyframe_evidence(
        self,
        *,
        keyframe: ContextKeyframe,
        links: tuple[KeyframeEvidenceLink, ...],
        keyframe_dir: Path,
        video_source: Path | None,
        media_time_ms: int | None,
    ) -> dict[str, str]:
        """Copy linked artifacts into the keyframe folder, keyed by artifact id."""

        written: dict[str, str] = {}
        # The screenshot is referenced directly on the keyframe even when no
        # typed evidence link is present, so resolve it first.
        if keyframe.screenshot_artifact_id is not None:
            self._copy_artifact(
                artifact_id=keyframe.screenshot_artifact_id,
                keyframe_dir=keyframe_dir,
                basename="screenshot",
                written=written,
            )
        role_seen: dict[str, int] = {}
        for link in links:
            if link.role in _RAW_LOCAL_EXPORT_OMITTED_ROLES:
                continue
            if link.artifact_id is None or link.artifact_id in written:
                continue
            basename = _ROLE_BASENAMES.get(link.role, link.role.value)
            count = role_seen.get(basename, 0)
            role_seen[basename] = count + 1
            unique = basename if count == 0 else f"{basename}_{count}"
            self._copy_artifact(
                artifact_id=link.artifact_id,
                keyframe_dir=keyframe_dir,
                basename=unique,
                written=written,
            )
        if "screenshot.png" not in written.values() and video_source is not None and media_time_ms is not None:
            if self.video_frame_extractor.extract_png(
                video_path=video_source,
                media_time_ms=media_time_ms,
                output_path=keyframe_dir / "screenshot.png",
            ):
                written["video_frame:screenshot"] = "screenshot.png"
        return written

    def _copy_artifact(
        self,
        *,
        artifact_id: str,
        keyframe_dir: Path,
        basename: str,
        written: dict[str, str],
    ) -> None:
        artifact = self.artifacts.get(artifact_id)
        if artifact is None:
            return
        try:
            source = self.content_source.resolve_local_path(artifact.storage_uri)
        except Exception:
            # Fixture URIs or already-pruned blobs are skipped rather than fatal.
            return
        filename = f"{basename}{self._suffix_for(artifact)}"
        shutil.copy2(source, keyframe_dir / filename)
        written[artifact_id] = filename

    def _primary_recording_video_source(self, graph: RecordingSessionGraph) -> Path | None:
        event_id = graph.session.primary_event_id
        if event_id is None:
            return None
        videos = [
            artifact
            for artifact in self.artifacts.list_for_event(event_id)
            if artifact.artifact_type == ArtifactType.RECORDING_VIDEO
        ]
        if not videos:
            return None
        try:
            return self.content_source.resolve_local_path(videos[0].storage_uri)
        except Exception:
            return None

    def _write_video(self, *, graph: RecordingSessionGraph, recording_dir: Path) -> int:
        event_id = graph.session.primary_event_id
        if event_id is None:
            return 0
        videos = [
            artifact
            for artifact in self.artifacts.list_for_event(event_id)
            if artifact.artifact_type == ArtifactType.RECORDING_VIDEO
        ]
        if not videos:
            return 0
        copied = 0
        multi = len(videos) > 1
        target_dir = recording_dir / "video" if multi else recording_dir
        if multi:
            target_dir.mkdir(parents=True, exist_ok=True)
        for index, artifact in enumerate(videos):
            try:
                source = self.content_source.resolve_local_path(artifact.storage_uri)
            except Exception:
                continue
            name = f"{index:02d}.mp4" if multi else "video.mp4"
            shutil.copy2(source, target_dir / name)
            copied += 1
        return copied

    def _vm_a11y_records(self, *, graph: RecordingSessionGraph) -> tuple[dict[str, object], ...]:
        if self.vm_a11y_probe is None:
            return ()
        return self.vm_a11y_probe.export_records_for_session(graph.session.session_id)

    def _vm_event_log(self, *, graph: RecordingSessionGraph) -> tuple[dict[str, object], ...]:
        """Fetch the full captured VM ``/events`` stream for this session, once."""

        probe = self.vm_a11y_probe
        if probe is None or not hasattr(probe, "export_event_log_for_session"):
            return ()
        try:
            return tuple(probe.export_event_log_for_session(graph.session.session_id))
        except Exception:
            return ()

    def _vm_click_log(self, *, graph: RecordingSessionGraph) -> tuple[dict[str, object], ...]:
        """Fetch the host-mirrored VM click watcher stream for this session."""

        probe = self.vm_a11y_probe
        if probe is None or not hasattr(probe, "export_click_log_for_session"):
            return ()
        try:
            return tuple(probe.export_click_log_for_session(graph.session.session_id))
        except Exception:
            return ()

    def _write_vm_event_log(
        self,
        *,
        events: Sequence[Mapping[str, object]],
        recording_dir: Path,
        graph: RecordingSessionGraph,
    ) -> int:
        """Write the full captured VM ``/events`` stream to a sidecar jsonl file.

        This is the raw accessibility event firehose recorded during the session
        (focus/selection/state changes plus clicks), independent of which events
        were matched to actions. It lets a consumer recover a click/drag target
        even when the live click-time probe picked a generic page focus.

        Each event is stamped with ``media_time_ms`` / ``media_time`` relative to
        the actual first video frame, so it lines up with the ``summary.md`` /
        trajectory timeline even when session creation precedes local video
        startup. Stale backlog from before the recording (the first poll grabs the
        VM's rolling buffer) is dropped.
        """

        if not events:
            return 0
        start = graph.session.started_at or graph.session.created_at
        start_epoch = start.timestamp() if start is not None else None
        end = graph.session.ended_at
        lower = start_epoch - _EVENT_LOG_WINDOW_MARGIN_SECONDS if start_epoch is not None else None
        upper = end.timestamp() + _EVENT_LOG_WINDOW_MARGIN_SECONDS if end is not None else None
        enriched: list[Mapping[str, object]] = []
        for event in events:
            ts = _event_log_ts(event)
            if ts is not None:
                if lower is not None and ts < lower:
                    continue
                if upper is not None and ts > upper:
                    continue
            media_time_ms = _wall_clock_media_time_ms(graph=graph, timestamp=ts)
            if media_time_ms is not None:
                enriched.append(
                    {"media_time": _format_media_time_signed(media_time_ms), "media_time_ms": media_time_ms, **event}
                )
            else:
                enriched.append(dict(event))
        if not enriched:
            return 0
        self._write_jsonl(recording_dir / "vm_events.jsonl", enriched)
        return len(enriched)

    def _write_vm_click_log(
        self,
        *,
        clicks: Sequence[Mapping[str, object]],
        recording_dir: Path,
        graph: RecordingSessionGraph,
    ) -> int:
        """Write the raw VM click watcher stream to a sidecar jsonl file."""

        enriched = self._session_window_clicks(graph=graph, clicks=clicks)
        if not enriched:
            return 0
        self._write_jsonl(recording_dir / "vm_clicks.jsonl", enriched)
        return len(enriched)

    def _session_window_clicks(
        self,
        *,
        graph: RecordingSessionGraph,
        clicks: Sequence[Mapping[str, object]],
    ) -> list[Mapping[str, object]]:
        if not clicks:
            return []
        start = graph.session.started_at or graph.session.created_at
        start_epoch = start.timestamp() if start is not None else None
        end = graph.session.ended_at
        lower = start_epoch - _EVENT_LOG_WINDOW_MARGIN_SECONDS if start_epoch is not None else None
        upper = end.timestamp() + _EVENT_LOG_WINDOW_MARGIN_SECONDS if end is not None else None
        enriched: list[Mapping[str, object]] = []
        for click in clicks:
            ts = _event_log_ts(click)
            if ts is not None:
                if lower is not None and ts < lower:
                    continue
                if upper is not None and ts > upper:
                    continue
            media_time_ms = _wall_clock_media_time_ms(graph=graph, timestamp=ts)
            if media_time_ms is not None:
                enriched.append(
                    {"media_time": _format_media_time_signed(media_time_ms), "media_time_ms": media_time_ms, **click}
                )
            else:
                enriched.append(dict(click))
        return enriched

    def _session_window_external_records(
        self,
        *,
        graph: RecordingSessionGraph,
        records: Sequence[Mapping[str, object]],
    ) -> tuple[Mapping[str, object], ...]:
        """Return external rows whose timestamps overlap this recording."""

        if not records:
            return ()
        start = graph.session.started_at or graph.session.created_at
        start_epoch = start.timestamp() if start is not None else None
        end = graph.session.ended_at
        lower = start_epoch - _EVENT_LOG_WINDOW_MARGIN_SECONDS if start_epoch is not None else None
        upper = end.timestamp() + _EVENT_LOG_WINDOW_MARGIN_SECONDS if end is not None else None
        return tuple(
            record
            for record in records
            if (timestamp := _event_log_ts(record)) is not None
            and (lower is None or timestamp >= lower)
            and (upper is None or timestamp <= upper)
        )

    def _root_vm_a11y_records(
        self,
        *,
        graph: RecordingSessionGraph,
        vm_a11y_records: Sequence[Mapping[str, object]],
        vm_a11y_by_action: Mapping[str, Sequence[Mapping[str, object]]],
    ) -> list[Mapping[str, object]]:
        """Return a stable root-level VM a11y stream for quick inspection."""

        rows: list[Mapping[str, object]] = []
        seen: set[int] = set()
        for action in sorted(graph.actions, key=lambda item: item.sequence_index):
            for record in vm_a11y_by_action.get(action.action_id, ()):
                rows.append(record)
                seen.add(id(record))
        for record in vm_a11y_records:
            if id(record) in seen:
                continue
            if record.get("source") == "periodic_watch":
                rows.append(record)
        return rows

    def _write_root_vm_a11y(
        self,
        *,
        recording_dir: Path,
        session_id: str,
        records: Sequence[Mapping[str, object]],
    ) -> list[str]:
        self._write_jsonl(recording_dir / "vm_a11y.jsonl", records)
        self._write_json(
            recording_dir / "vm_a11y.json",
            {
                "session_id": session_id,
                "record_count": len(records),
                "latest": dict(records[-1]) if records else None,
            },
        )
        return ["vm_a11y.json", "vm_a11y.jsonl"]

    def _write_dom_hits(
        self,
        *,
        recording_dir: Path,
        graph: RecordingSessionGraph,
        step_by_action: Mapping[str, RecordingTimelineStepView],
        vm_a11y_by_action: Mapping[str, Sequence[Mapping[str, object]]],
    ) -> tuple[int, int]:
        """Write one normalized, action-aligned DOM hit sidecar.

        This is intentionally smaller than the raw VM event firehose: it only
        includes action targets and miss diagnostics, not raw pages.
        """

        rows: list[dict[str, object]] = []
        for action in graph.actions:
            if action.kind not in {HumanActionKind.CLICK, HumanActionKind.DRAG}:
                continue
            records = vm_a11y_by_action.get(action.action_id, ())
            dom_hit = _dom_hit_for_action_records(records)
            step = step_by_action.get(action.action_id)
            source = _dom_hit_source(records)
            row: dict[str, object] = {
                "action_id": action.action_id,
                "action_kind": action.kind.value,
                "status": "hit" if dom_hit is not None else "miss",
                "sequence_index": action.sequence_index,
                "occurred_at": _iso(action.occurred_at),
                "media_time_ms": step.media_time_ms if step is not None else action.media_time_ms,
            }
            if dom_hit is not None:
                row["dom_hit"] = dom_hit
                row["dom_hit_label"] = _dom_hit_label(dom_hit)
            else:
                row["errors"] = _dom_hit_errors(records) or ["no_vm_a11y_record"]
            if source is not None:
                row["source"] = source
            backfill_delta_ms = _dom_hit_backfill_delta_ms(records)
            if backfill_delta_ms is not None:
                row["backfill_delta_ms"] = backfill_delta_ms
            event_seq = _dom_hit_event_seq(records)
            if event_seq is not None:
                row["event_seq"] = event_seq
            rows.append(row)
        self._write_jsonl(recording_dir / "dom_hits.jsonl", rows)
        return len(rows), sum(1 for row in rows if row["status"] == "hit")

    def _backfill_anchor_ts(self, action: HumanActionEvent) -> float:
        """Wall-clock instant to match an action against the event log.

        A drag is recorded at release, but its target is the element grabbed at the
        start, whose accessibility event fires near the drag start. Anchor the match
        at the grab moment (release minus drag duration) so the dragged element is
        recovered rather than whatever generic focus exists at the drop point.
        """

        base = action.occurred_at.timestamp()
        if action.kind == HumanActionKind.DRAG:
            duration_ms = _metadata_int(action.metadata.get("drag_duration_ms"))
            if duration_ms is not None and duration_ms > 0:
                return base - duration_ms / 1000.0
        return base

    def _backfill_dom_hits_from_event_log(
        self,
        *,
        graph: RecordingSessionGraph,
        existing: dict[str, list[dict[str, object]]],
        event_log: Sequence[Mapping[str, object]],
    ) -> dict[str, list[dict[str, object]]]:
        """Resolve click/drag targets that the live probe missed, from the event log.

        For each click/drag without a DOM hit, pick the nearest-in-time *specific*
        accessibility event (excluding whole-page/window focuses) within a bounded
        window. Each event is consumed at most once so two clicks cannot claim the
        same focus event.
        """

        specifics: list[tuple[float, Mapping[str, object]]] = [
            (ts, event)
            for event in event_log
            if (ts := _event_log_ts(event)) is not None and _event_log_specific_target(event)
        ]
        if not specifics:
            return {}
        matched: dict[str, list[dict[str, object]]] = {}
        used: set[int] = set()
        candidate_actions = [
            action
            for action in graph.actions
            if action.kind in {HumanActionKind.CLICK, HumanActionKind.DRAG}
            and _dom_hit_for_action_records(existing.get(action.action_id, ())) is None
        ]
        for action in sorted(candidate_actions, key=lambda item: item.occurred_at):
            action_ts = self._backfill_anchor_ts(action)
            best_index: int | None = None
            best_delta = _EVENT_LOG_BACKFILL_WINDOW_SECONDS
            for index, (event_ts, _event) in enumerate(specifics):
                if index in used:
                    continue
                delta = abs(event_ts - action_ts)
                if delta <= best_delta:
                    best_index = index
                    best_delta = delta
            if best_index is None:
                continue
            used.add(best_index)
            event_ts, event = specifics[best_index]
            hit_dom = _dom_hit_from_event(event)
            if hit_dom is None:
                continue
            matched[action.action_id] = [
                {
                    "action_id": action.action_id,
                    "action_kind": action.kind.value,
                    "source": "event_log_backfill",
                    "hit_dom": hit_dom,
                    "event_seq": event.get("seq"),
                    "event_ts": event_ts,
                    "backfill_delta_ms": round((event_ts - action_ts) * 1000, 1),
                }
            ]
        return matched

    def _backfill_dom_hits_from_pointer_resolutions(
        self,
        *,
        graph: RecordingSessionGraph,
        existing: dict[str, list[dict[str, object]]],
        event_log: Sequence[Mapping[str, object]],
    ) -> dict[str, list[dict[str, object]]]:
        """Resolve event-only pointer targets strictly from pointer resolutions.

        A ``pointer-resolution`` row can arrive well after the originating
        pointer event. Match actions against the original pointer timestamp via
        ``pointer_seq`` and use only the resolution row for target semantics.
        Other AT-SPI focus/selection/state events are intentionally ignored so
        the event-only export remains a strict single-source ablation.
        """

        pointer_events: dict[int, tuple[float, Mapping[str, object]]] = {}
        for event in event_log:
            event_kind = event.get("event")
            if not isinstance(event_kind, str) or not event_kind.startswith("pointer:"):
                continue
            pointer_seq = _event_log_sequence(event, prefer_source=True)
            pointer_ts = _event_log_ts(event)
            if pointer_seq is None or pointer_ts is None:
                continue
            pointer_events[pointer_seq] = (pointer_ts, event)

        resolutions: dict[int, list[tuple[int, float, Mapping[str, object], dict[str, object]]]] = {}
        for event in event_log:
            if event.get("event") != "pointer-resolution":
                continue
            pointer_seq = _event_log_integer(event.get("pointer_seq"))
            resolution_ts = _event_log_ts(event)
            resolution_status = event.get("resolution")
            if (
                pointer_seq is None
                or pointer_seq not in pointer_events
                or resolution_ts is None
                or resolution_status not in {"resolved", "coarse"}
            ):
                continue
            hit_dom = _dom_hit_from_event(event)
            if hit_dom is None:
                continue
            rank = 0 if resolution_status == "resolved" else 1
            resolutions.setdefault(pointer_seq, []).append((rank, resolution_ts, event, hit_dom))

        candidates: list[
            tuple[float, int, Mapping[str, object], float, Mapping[str, object], dict[str, object]]
        ] = []
        for pointer_seq, rows in resolutions.items():
            pointer_ts, pointer_event = pointer_events[pointer_seq]
            _rank, resolution_ts, resolution_event, hit_dom = min(
                rows,
                key=lambda item: (item[0], abs(item[1] - pointer_ts), _event_log_sequence(item[2]) or 0),
            )
            candidates.append(
                (pointer_ts, pointer_seq, pointer_event, resolution_ts, resolution_event, hit_dom)
            )
        candidates.sort(key=lambda item: (item[0], item[1]))
        if not candidates:
            return {}

        matched: dict[str, list[dict[str, object]]] = {}
        used: set[int] = set()
        candidate_actions = [
            action
            for action in graph.actions
            if action.kind in {HumanActionKind.CLICK, HumanActionKind.DRAG}
            and _dom_hit_for_action_records(existing.get(action.action_id, ())) is None
        ]
        for action in sorted(candidate_actions, key=lambda item: item.occurred_at):
            action_ts = self._backfill_anchor_ts(action)
            best_index: int | None = None
            best_delta = _EVENT_LOG_BACKFILL_WINDOW_SECONDS
            for index, (pointer_ts, _pointer_seq, _pointer_event, _resolution_ts, _resolution_event, _hit) in enumerate(
                candidates
            ):
                if index in used:
                    continue
                delta = abs(pointer_ts - action_ts)
                if delta <= best_delta:
                    best_index = index
                    best_delta = delta
            if best_index is None:
                continue
            used.add(best_index)
            pointer_ts, pointer_seq, pointer_event, resolution_ts, resolution_event, hit_dom = candidates[
                best_index
            ]
            matched[action.action_id] = [
                {
                    "action_id": action.action_id,
                    "action_kind": action.kind.value,
                    "source": "pointer_resolution_backfill",
                    "hit_dom": hit_dom,
                    "event_seq": _event_log_sequence(resolution_event),
                    "event_ts": pointer_ts,
                    "backfill_delta_ms": round((pointer_ts - action_ts) * 1000, 1),
                    "pointer_seq": pointer_seq,
                    "pointer_event_seq": _event_log_sequence(pointer_event),
                    "pointer_event_ts": pointer_ts,
                    "resolution_event_ts": resolution_ts,
                    "resolution": resolution_event.get("resolution"),
                    "resolution_source": resolution_event.get("source"),
                }
            ]
        return matched

    def _backfill_dom_hits_from_click_log(
        self,
        *,
        graph: RecordingSessionGraph,
        existing: dict[str, list[dict[str, object]]],
        click_log: Sequence[Mapping[str, object]],
    ) -> dict[str, list[dict[str, object]]]:
        """Resolve missed/generic click targets from the Firefox DOM click watcher."""

        specifics: list[tuple[float, Mapping[str, object]]] = [
            (ts, click)
            for click in click_log
            if (ts := _event_log_ts(click)) is not None and _dom_hit_from_event(click) is not None
        ]
        if not specifics:
            return {}
        matched: dict[str, list[dict[str, object]]] = {}
        used: set[int] = set()
        candidate_actions = [
            action
            for action in graph.actions
            if action.kind in {HumanActionKind.CLICK, HumanActionKind.DRAG}
            and _dom_hit_for_action_records(existing.get(action.action_id, ())) is None
        ]
        for action in sorted(candidate_actions, key=lambda item: item.occurred_at):
            action_ts = self._backfill_anchor_ts(action)
            best_index: int | None = None
            best_delta = _EVENT_LOG_BACKFILL_WINDOW_SECONDS
            for index, (click_ts, _click) in enumerate(specifics):
                if index in used:
                    continue
                delta = abs(click_ts - action_ts)
                if delta <= best_delta:
                    best_index = index
                    best_delta = delta
            if best_index is None:
                continue
            used.add(best_index)
            click_ts, click = specifics[best_index]
            hit_dom = _dom_hit_from_event(click)
            if hit_dom is None:
                continue
            matched[action.action_id] = [
                {
                    "action_id": action.action_id,
                    "action_kind": action.kind.value,
                    "source": "click_log_backfill",
                    "hit_dom": hit_dom,
                    "event_ts": click_ts,
                    "backfill_delta_ms": round((click_ts - action_ts) * 1000, 1),
                    "raw_click": dict(click),
                }
            ]
        return matched

    def _write_keyframe_vm_a11y(
        self,
        *,
        keyframe_dir: Path,
        folder_name: str,
        session_id: str,
        records: list[dict[str, object]],
    ) -> list[str]:
        self._write_jsonl(keyframe_dir / "vm_a11y.jsonl", records)
        self._write_json(
            keyframe_dir / "vm_a11y.json",
            {
                "session_id": session_id,
                "record_count": len(records),
                "latest": records[-1],
            },
        )
        return [f"{folder_name}/vm_a11y.json", f"{folder_name}/vm_a11y.jsonl"]

    def _links_by_keyframe(
        self,
        links: tuple[KeyframeEvidenceLink, ...],
    ) -> dict[str, tuple[KeyframeEvidenceLink, ...]]:
        grouped: dict[str, list[KeyframeEvidenceLink]] = {}
        for link in links:
            grouped.setdefault(link.keyframe_id, []).append(link)
        return {keyframe_id: tuple(items) for keyframe_id, items in grouped.items()}

    def _actions_by_keyframe(
        self,
        graph: RecordingSessionGraph,
        step_by_action: dict[str, RecordingTimelineStepView],
        typed_text_by_action: dict[str, str],
        *,
        vm_a11y_by_action: dict[str, list[dict[str, object]]],
    ) -> dict[str, list[dict[str, object]]]:
        """Anchor each action to every keyframe it references (before/after/result/target)."""

        actions_by_id = {action.action_id: action for action in graph.actions}
        anchored: dict[str, dict[str, dict[str, object]]] = {}

        def _record(keyframe_id: str, action_id: str, relation: str) -> None:
            action = actions_by_id.get(action_id)
            if action is None:
                return
            bucket = anchored.setdefault(keyframe_id, {})
            entry = bucket.get(action_id)
            if entry is None:
                step = step_by_action.get(action_id)
                entry = {
                    "action_id": action.action_id,
                    "kind": action.kind.value,
                    "caption": self._export_caption(step, dom_hit=None, action=action) if step is not None else None,
                    "sequence_index": action.sequence_index,
                    "occurred_at": _iso(action.occurred_at),
                    "media_time_ms": step.media_time_ms if step is not None else action.media_time_ms,
                    "relations": [],
                }
                coordinates = self._action_coordinates_detail(action, session_scope=graph.session.scope)
                if coordinates is not None:
                    entry["coordinates"] = coordinates
                dom_hit = _dom_hit_for_action_records(vm_a11y_by_action.get(action_id, ()))
                if dom_hit is not None:
                    entry["dom_hit"] = dom_hit
                    entry["dom_hit_label"] = _dom_hit_label(dom_hit)
                    entry["caption"] = (
                        self._export_caption(step, dom_hit=dom_hit, action=action) if step is not None else entry["caption"]
                    )
                keyboard = self._action_keyboard_detail(step)
                typed_text = typed_text_by_action.get(action_id)
                if typed_text is not None:
                    keyboard["typed_text"] = typed_text
                if keyboard:
                    entry["keyboard"] = keyboard
                bucket[action_id] = entry
            relations = entry["relations"]
            assert isinstance(relations, list)
            if relation not in relations:
                relations.append(relation)

        for link in graph.action_links:
            if link.keyframe_id is not None:
                _record(link.keyframe_id, link.action_id, link.role.value)
        for observation in graph.action_observations:
            if observation.result_keyframe_id is not None:
                _record(observation.result_keyframe_id, observation.action_id, "result")

        # Raw key_down/key_up keystrokes (and any other action without a keyframe
        # evidence link) carry no anchor, so fall back to the keyframe whose capture
        # time covers them. This keeps individual typed characters in a per-timestamp
        # folder instead of only the top-level trajectory.
        anchored_action_ids = {action_id for bucket in anchored.values() for action_id in bucket}
        ordered_keyframes = sorted(
            graph.keyframes, key=lambda keyframe: (keyframe.captured_at, keyframe.sequence_index)
        )
        for action in graph.actions:
            if action.action_id in anchored_action_ids:
                continue
            covering = self._keyframe_covering_action(action, ordered_keyframes)
            if covering is not None:
                _record(covering, action.action_id, "occurred_during")

        def _sequence_key(item: dict[str, object]) -> int:
            value = item["sequence_index"]
            return value if isinstance(value, int) else 0

        return {keyframe_id: sorted(bucket.values(), key=_sequence_key) for keyframe_id, bucket in anchored.items()}

    def _timeline_payload(
        self,
        timeline: RecordingTimelineInspectView,
        *,
        graph: RecordingSessionGraph,
        vm_a11y_by_action: dict[str, list[dict[str, object]]],
        exportable_keyframe_ids: set[str],
    ) -> dict[str, object]:
        payload = timeline.model_dump(mode="json")
        steps = payload.get("steps")
        if not isinstance(steps, list):
            return payload
        steps = [
            step
            for step in steps
            if not (
                isinstance(step, dict)
                and step.get("kind") == RecordingStoryboardItemKind.KEYFRAME.value
                and isinstance(step.get("keyframe_id"), str)
                and step["keyframe_id"] not in exportable_keyframe_ids
            )
        ]
        payload["steps"] = steps
        actions_by_id = {action.action_id: action for action in graph.actions}
        step_views_by_id = {step.step_id: step for step in timeline.steps}
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_id = step.get("step_id")
            step_view = step_views_by_id.get(step_id) if isinstance(step_id, str) else None
            dom_hit: Mapping[str, object] | None = None
            action: HumanActionEvent | None = None
            action_id = step.get("action_id")
            if isinstance(action_id, str):
                action = actions_by_id.get(action_id)
                if action is not None:
                    coordinates = self._action_coordinates_detail(action, session_scope=graph.session.scope)
                    if coordinates is not None:
                        step["coordinates"] = coordinates
                dom_hit = _dom_hit_for_action_records(vm_a11y_by_action.get(action_id, ()))
                if dom_hit is not None:
                    step["dom_hit"] = dom_hit
                    step["dom_hit_label"] = _dom_hit_label(dom_hit)
                    self._apply_dom_hit_resolution(step, dom_hit=dom_hit)
                elif step.get("action_kind") == HumanActionKind.SCROLL.value and step.get("media_time_ms") is not None:
                    self._mark_step_ready(step)
            export_caption = self._export_caption(step_view, dom_hit=dom_hit, action=action)
            if export_caption is not None:
                step["safe_caption"] = export_caption
        return payload

    def _apply_dom_hit_resolution(self, step: dict[str, object], *, dom_hit: Mapping[str, object]) -> None:
        """Treat an exported DOM hit as enough evidence for the action target."""

        self._mark_step_ready(step)
        action_summary = step.get("action_summary")
        if not isinstance(action_summary, dict):
            return
        target = action_summary.get("target")
        if isinstance(target, dict):
            resolved = dict(target)
        else:
            resolved = {}
        source_badges = resolved.get("source_badges")
        badges = [badge for badge in source_badges if isinstance(badge, str)] if isinstance(source_badges, list) else []
        if "web_dom" not in badges:
            badges.append("web_dom")
        evidence_keyframes = resolved.get("evidence_keyframe_ids")
        resolved.update(
            {
                "status": "resolved",
                "display_label": _dom_hit_target_display_label(dom_hit),
                "semantic_kind": _dom_hit_semantic_kind(dom_hit),
                "confidence": max(_json_number(resolved.get("confidence")) or 0.0, 0.78),
                "confidence_band": "high",
                "source_badges": badges,
                "needs_review": False,
                "evidence_keyframe_ids": evidence_keyframes if isinstance(evidence_keyframes, list) else [],
                "has_coordinates": bool(resolved.get("has_coordinates") or step.get("coordinates")),
                "suppression_reason": None,
            }
        )
        action_summary["target"] = resolved

    def _mark_step_ready(self, step: dict[str, object]) -> None:
        step["needs_review"] = False
        step["readiness"] = {
            "state": "ready",
            "reasons": [],
            "review_item_count": 0,
            "blocked_item_count": 0,
            "missing_evidence": [],
        }

    def _primary_keyframe_by_action(self, actions_by_keyframe: dict[str, list[dict[str, object]]]) -> dict[str, str]:
        """Pick one folder to own per-action sidecar files such as VM a11y."""

        relation_priority = {
            "result": 0,
            "after_keyframe": 1,
            "occurred_during": 2,
            "target": 3,
            "before_keyframe": 4,
        }
        selected: dict[str, tuple[int, str]] = {}
        for keyframe_id, actions in actions_by_keyframe.items():
            for action in actions:
                action_id = action.get("action_id")
                if not isinstance(action_id, str):
                    continue
                relations = action.get("relations")
                priority = (
                    min(
                        (relation_priority.get(relation, 99) for relation in relations if isinstance(relation, str)),
                        default=99,
                    )
                    if isinstance(relations, list)
                    else 99
                )
                current = selected.get(action_id)
                if current is None or priority < current[0]:
                    selected[action_id] = (priority, keyframe_id)
        return {action_id: keyframe_id for action_id, (_priority, keyframe_id) in selected.items()}

    def _vm_a11y_by_action(
        self,
        graph: RecordingSessionGraph,
        *,
        records: tuple[dict[str, object], ...],
    ) -> dict[str, list[dict[str, object]]]:
        if not records:
            return {}
        action_by_monotonic: dict[tuple[int, str | None], list[HumanActionEvent]] = {}
        fallback_actions: list[HumanActionEvent] = []
        for action in graph.actions:
            fallback_actions.append(action)
            if action.occurred_at_monotonic_ms is None:
                continue
            action_by_monotonic.setdefault((action.occurred_at_monotonic_ms, action.kind.value), []).append(action)
            action_by_monotonic.setdefault((action.occurred_at_monotonic_ms, None), []).append(action)

        matched: dict[str, list[dict[str, object]]] = {}
        used_action_ids: set[str] = set()
        for record in records:
            trigger = record.get("trigger")
            if not isinstance(trigger, dict):
                continue
            event_kind = trigger.get("event_kind")
            if event_kind not in _VM_A11Y_EXPORT_EVENT_KINDS:
                continue
            monotonic = trigger.get("occurred_at_monotonic_ms")
            if not isinstance(monotonic, int):
                continue
            expected_kind = _action_kind_for_vm_event(event_kind)
            candidates = action_by_monotonic.get((monotonic, expected_kind), ()) or action_by_monotonic.get(
                (monotonic, None), ()
            )
            matched_action: HumanActionEvent | None = next(
                (candidate for candidate in candidates if candidate.action_id not in used_action_ids), None
            )
            if matched_action is None:
                matched_action = self._nearest_vm_a11y_action(
                    monotonic=monotonic,
                    expected_kind=expected_kind,
                    actions=fallback_actions,
                    used_action_ids=used_action_ids,
                )
            if matched_action is None:
                continue
            used_action_ids.add(matched_action.action_id)
            enriched = dict(record)
            enriched["action_id"] = matched_action.action_id
            enriched["action_kind"] = matched_action.kind.value
            matched.setdefault(matched_action.action_id, []).append(enriched)
        return matched

    def _live_vm_a11y_by_action(
        self,
        *,
        graph: RecordingSessionGraph,
        existing: dict[str, list[dict[str, object]]],
    ) -> dict[str, list[dict[str, object]]]:
        if self.vm_a11y_probe is None or self.vm_display is None or graph.session.scope is None:
            return {}
        if not hasattr(self.vm_a11y_probe, "sample_point_for_export"):
            return {}
        mapping = build_vm_display_mapping(
            window_bounds=graph.session.scope.bounds,
            vm_width=self.vm_display.vm_width,
            vm_height=self.vm_display.vm_height,
            title_bar_pt=self.vm_display.title_bar_pt,
        )
        if mapping is None:
            return {}
        matched: dict[str, list[dict[str, object]]] = {}
        for action in graph.actions:
            if (
                action.action_id in existing
                or action.kind not in {HumanActionKind.CLICK, HumanActionKind.DRAG}
                or action.coordinates is None
            ):
                continue
            point = action.coordinates.screen_abs
            if point is None:
                continue
            vm_point = mapping.map_point(point.x, point.y)
            if vm_point is None:
                continue
            try:
                record = self.vm_a11y_probe.sample_point_for_export(
                    session_id=graph.session.session_id,
                    occurred_at_monotonic_ms=action.occurred_at_monotonic_ms,
                    point_x=vm_point[0],
                    point_y=vm_point[1],
                    coordinate_space="vm_screen",
                )
            except Exception:
                continue
            if record is None:
                continue
            enriched = dict(record)
            enriched["action_id"] = action.action_id
            enriched["action_kind"] = action.kind.value
            matched[action.action_id] = [enriched]
        return matched

    def _periodic_vm_a11y_by_keyframe(
        self,
        graph: RecordingSessionGraph,
        *,
        records: tuple[dict[str, object], ...],
    ) -> dict[str, list[dict[str, object]]]:
        periodic_records = [record for record in records if record.get("source") == "periodic_watch"]
        if not periodic_records:
            return {}
        grouped: dict[str, list[dict[str, object]]] = {}
        for keyframe in graph.keyframes:
            keyframe_ts = keyframe.captured_at.timestamp()
            nearest: dict[str, object] | None = None
            nearest_delta = float("inf")
            for record in periodic_records:
                sample_ts = _vm_a11y_record_host_ts(record)
                if sample_ts is None:
                    continue
                delta = abs(sample_ts - keyframe_ts)
                if delta < nearest_delta:
                    nearest = record
                    nearest_delta = delta
            if nearest is None or nearest_delta > _VM_A11Y_KEYFRAME_PERIODIC_MATCH_WINDOW_SECONDS:
                continue
            enriched = dict(nearest)
            enriched["keyframe_id"] = keyframe.keyframe_id
            enriched["keyframe_captured_at"] = _iso(keyframe.captured_at)
            enriched["keyframe_to_sample_ms"] = round(nearest_delta * 1000, 3)
            grouped.setdefault(keyframe.keyframe_id, []).append(enriched)
        return grouped

    def _nearest_vm_a11y_action(
        self,
        *,
        monotonic: int,
        expected_kind: str | None,
        actions: list[HumanActionEvent],
        used_action_ids: set[str],
    ) -> HumanActionEvent | None:
        candidates = [
            action
            for action in actions
            if action.action_id not in used_action_ids
            and action.occurred_at_monotonic_ms is not None
            and (expected_kind is None or action.kind.value == expected_kind)
        ]
        if not candidates:
            return None
        nearest = min(candidates, key=lambda action: abs((action.occurred_at_monotonic_ms or 0) - monotonic))
        if nearest.occurred_at_monotonic_ms is None:
            return None
        return nearest if abs(nearest.occurred_at_monotonic_ms - monotonic) <= 2500 else None

    def _vm_a11y_records_for_keyframe(
        self,
        *,
        keyframe_id: str,
        anchored_actions: list[dict[str, object]],
        primary_keyframe_by_action: dict[str, str],
        vm_a11y_by_action: dict[str, list[dict[str, object]]],
    ) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for action in anchored_actions:
            action_id = action.get("action_id")
            if not isinstance(action_id, str):
                continue
            if primary_keyframe_by_action.get(action_id) != keyframe_id:
                continue
            records.extend(vm_a11y_by_action.get(action_id, ()))
        return records

    def _typed_text_by_typing_action(
        self,
        graph: RecordingSessionGraph,
        step_by_action: dict[str, RecordingTimelineStepView],
    ) -> dict[str, str]:
        """Reconstruct best-effort typed text for each typing burst.

        Raw ``key_down``/``key_up`` characters preceding a ``typing_pause`` settle
        marker are reconstructed into the typed string, turning a bare "约 N 字"
        aggregate into the characters that were actually captured. Each physical key
        is one ``key_down`` + ``key_up`` pair: the character is emitted on ``key_down``
        and the matching ``key_up`` is absorbed. If a ``key_up`` has no matching
        ``key_down`` (the press event was dropped at capture time), its character is
        recovered so a single dropped event does not corrupt the text.
        """

        typed: dict[str, str] = {}
        buffer: list[str] = []
        pending_down_positions: dict[str, list[int]] = {}
        for action in sorted(graph.actions, key=lambda item: item.sequence_index):
            if action.kind == HumanActionKind.TYPING_PAUSE:
                if buffer:
                    typed[action.action_id] = "".join(buffer)
                buffer = []
                pending_down_positions.clear()
                continue
            if action.kind not in {HumanActionKind.KEY_DOWN, HumanActionKind.KEY_UP}:
                continue
            step = step_by_action.get(action.action_id)
            chord = step.action_summary.key_chord if step is not None and step.action_summary is not None else None
            characters = chord.characters if chord is not None else None
            characters = _printable_key_text(characters)
            if not characters:
                continue
            if action.kind == HumanActionKind.KEY_DOWN:
                buffer.append(characters)
                pending_down_positions.setdefault(characters, []).append(len(buffer) - 1)
            elif positions := pending_down_positions.get(characters):
                positions.pop(0)
            else:
                insertion_index = min(
                    (positions[0] for positions in pending_down_positions.values() if positions),
                    default=len(buffer),
                )
                buffer.insert(insertion_index, characters)
                for positions in pending_down_positions.values():
                    for index, position in enumerate(positions):
                        if position >= insertion_index:
                            positions[index] = position + 1
        return typed

    def _keyframe_covering_action(
        self,
        action: HumanActionEvent,
        ordered_keyframes: list[ContextKeyframe],
    ) -> str | None:
        """Return the keyframe whose capture time the action falls under, else the first."""

        if not ordered_keyframes:
            return None
        covering = ordered_keyframes[0]
        for keyframe in ordered_keyframes:
            if keyframe.captured_at <= action.occurred_at:
                covering = keyframe
            else:
                break
        return covering.keyframe_id

    def _action_keyboard_detail(self, step: RecordingTimelineStepView | None) -> dict[str, object]:
        """Extract typed characters / key chord / typing counts for a keyboard action.

        Characters are only present when full-keystroke capture is enabled; otherwise
        only the privacy-preserving typing aggregate (character counts) is available.
        """

        if step is None or step.action_summary is None:
            return {}
        summary = step.action_summary
        detail: dict[str, object] = {}
        chord = summary.key_chord
        if chord is not None:
            detail["key_label"] = chord.normalized_key_label
            if chord.characters:
                detail["characters"] = chord.characters
            if chord.modifiers:
                detail["modifiers"] = [modifier.value for modifier in chord.modifiers]
        typing = summary.typing_summary
        if typing is not None:
            detail["typing"] = {
                "character_count": typing.character_count,
                "text_event_count": typing.text_event_count,
                "deletion_key_count": typing.deletion_key_count,
                "submitted_by_enter": typing.submitted_by_enter,
            }
        return detail

    def _action_coordinates_detail(
        self,
        action: HumanActionEvent,
        *,
        session_scope: RecordingScope | None,
    ) -> dict[str, object] | None:
        if action.kind not in {HumanActionKind.CLICK, HumanActionKind.DRAG} or action.coordinates is None:
            return None
        coordinates = action.coordinates
        action_scope = action.scope if action.scope is not None else session_scope
        detail: dict[str, object] = {}
        if coordinates.screenshot_rel is not None:
            point = coordinates.screenshot_rel
            detail["screenshot_rel"] = _action_point_payload(point.x, point.y)
        elif coordinates.screen_abs is not None:
            point = coordinates.screen_abs
            converted = _action_screen_point_to_screenshot_rel(action=action, scope=action_scope, x=point.x, y=point.y)
            if converted is None:
                detail["screen_abs"] = point.model_dump(mode="json", exclude_none=True)
            else:
                detail["screenshot_rel"] = _action_point_payload(*converted)
        elif coordinates.scope_rel is not None:
            point = coordinates.scope_rel
            detail["screenshot_rel"] = _action_point_payload(round(point.x), round(point.y))
        if coordinates.target_bounds is not None:
            detail["target_bounds"] = _action_target_bounds_payload(
                coordinates.target_bounds,
                action=action,
                scope=action_scope,
            )
        return detail or None

    _SUMMARY_KEYFRAME_CAPTIONS: dict[KeyframeRole, str] = {
        KeyframeRole.ANCHOR: "Anchor frame",
        KeyframeRole.START: "Recording started",
        KeyframeRole.FINAL: "Recording ended",
        KeyframeRole.BEFORE_ACTION: "Before action",
        KeyframeRole.RESULT: "Action result",
        KeyframeRole.SETTLE: "Settled state",
        KeyframeRole.CHANGE: "Changed state",
        KeyframeRole.USER_MARK: "User mark",
        KeyframeRole.IDLE_ANCHOR: "Idle anchor",
        KeyframeRole.PROVIDER_COMPLETION: "Provider completion",
        KeyframeRole.PAUSE_BOUNDARY: "Pause boundary",
        KeyframeRole.RESUME_BOUNDARY: "Resume boundary",
        KeyframeRole.ERROR_STATE: "Error state",
        KeyframeRole.SCROLL_MILESTONE: "Scroll milestone",
    }

    _SUMMARY_CONTROL_CAPTIONS: dict[RecordingControlKind, str] = {
        RecordingControlKind.START_SEGMENT: "Segment started",
        RecordingControlKind.END_SEGMENT: "Segment ended",
        RecordingControlKind.PAUSE: "Recording paused",
        RecordingControlKind.RESUME: "Recording resumed",
        RecordingControlKind.USER_MARK: "User mark",
        RecordingControlKind.STOP: "Recording stopped",
        RecordingControlKind.AUTO_STOP: "Recording auto-stopped",
        RecordingControlKind.SCOPE_LOST: "Recording area changed",
    }

    _SUMMARY_HOTKEY_CAPTIONS: dict[HotkeySemantic, str] = {
        HotkeySemantic.COPY: "Copy",
        HotkeySemantic.CUT: "Cut",
        HotkeySemantic.PASTE: "Paste",
        HotkeySemantic.SUBMIT: "Press Enter",
        HotkeySemantic.SEARCH: "Press search shortcut",
        HotkeySemantic.SAVE: "Save",
        HotkeySemantic.CLOSE: "Close",
        HotkeySemantic.NEW_ITEM: "Create new item",
        HotkeySemantic.DELETE: "Delete",
        HotkeySemantic.REFRESH: "Refresh",
        HotkeySemantic.SELECT_ALL: "Select all",
        HotkeySemantic.UNDO: "Undo",
        HotkeySemantic.REDO: "Redo",
        HotkeySemantic.NAVIGATE_BACK: "Navigate back",
        HotkeySemantic.NAVIGATE_FORWARD: "Navigate forward",
        HotkeySemantic.OPEN_COMMAND: "Open command",
        HotkeySemantic.ESCAPE_CANCEL: "Cancel",
    }

    _POINTER_CAPTION_VERBS: dict[HumanActionKind, str] = {
        HumanActionKind.CLICK: "Click",
        HumanActionKind.DRAG: "Drag",
    }
    _POINTER_BUTTON_CAPTION_PREFIXES: dict[str, str] = {
        "left": "Left",
        "right": "Right",
        "middle": "Middle",
    }

    def _export_caption(
        self,
        step: RecordingTimelineStepView | None,
        *,
        dom_hit: Mapping[str, object] | None,
        action: HumanActionEvent | None = None,
    ) -> str | None:
        if step is None:
            return None
        if step.kind == RecordingStoryboardItemKind.KEYFRAME:
            return self._export_keyframe_caption(step.keyframe_role)
        if step.kind == RecordingStoryboardItemKind.CONTROL:
            return self._export_control_caption(step.control_kind)
        if step.kind != RecordingStoryboardItemKind.ACTION:
            return _humanize_enum_value(step.kind.value)
        return self._export_action_caption(step, dom_hit=dom_hit, action=action)

    def _export_action_caption(
        self,
        step: RecordingTimelineStepView,
        *,
        dom_hit: Mapping[str, object] | None,
        action: HumanActionEvent | None = None,
    ) -> str:
        summary = step.action_summary
        action_kind = step.action_kind or (summary.action_kind if summary is not None else None)
        verb = self._pointer_caption_verb(action_kind, action=action)
        if verb is not None and dom_hit is not None:
            return f"{verb} {_summary_dom_hit_label(dom_hit)}"
        if action_kind == HumanActionKind.CLICK:
            target = summary.target if summary is not None else None
            if target is not None and not target.needs_review:
                return f'{verb or "Click"} "{target.display_label}"'
            return f"{verb or 'Click'} (target needs review)"
        if action_kind == HumanActionKind.DRAG:
            return verb or "Drag"
        if action_kind == HumanActionKind.SCROLL:
            return "Scroll stopped"
        if action_kind == HumanActionKind.HOTKEY:
            if summary is not None and summary.key_chord is not None:
                return f"Press {self._export_key_chord_caption(summary.key_chord)}"
            if summary is not None and summary.hotkey_semantic is not None:
                return self._SUMMARY_HOTKEY_CAPTIONS.get(summary.hotkey_semantic, "Keyboard shortcut")
            return "Keyboard shortcut"
        if action_kind in {HumanActionKind.KEY_DOWN, HumanActionKind.KEY_UP}:
            verb = "Press" if action_kind == HumanActionKind.KEY_DOWN else "Release"
            if summary is not None and summary.key_chord is not None:
                return f"{verb} {self._export_key_chord_caption(summary.key_chord)}"
            return f"{verb} key"
        if action_kind == HumanActionKind.TYPING_PAUSE:
            if summary is not None and summary.typing_summary is not None:
                count = summary.typing_summary.character_count
                noun = "character" if count == 1 else "characters"
                return f"Text input - about {count} {noun}"
            if summary is not None and (summary.after_keyframe_ids or summary.result_keyframe_id is not None):
                return "State after input"
            return "Typing summary"
        if action_kind == HumanActionKind.WINDOW_SWITCH:
            return "Window switch"
        if action_kind == HumanActionKind.TAB_SWITCH:
            return "Tab switch"
        if action_kind == HumanActionKind.USER_MARK:
            return "User mark"
        return _humanize_enum_value(action_kind.value) if action_kind is not None else step.safe_caption

    def _pointer_caption_verb(
        self,
        action_kind: HumanActionKind | None,
        *,
        action: HumanActionEvent | None,
    ) -> str | None:
        if action_kind is None:
            return None
        verb = self._POINTER_CAPTION_VERBS.get(action_kind)
        if verb is None:
            return None
        button = _action_pointer_button(action)
        if button is None:
            return verb
        return f"{button} {verb}"

    def _export_keyframe_caption(self, role: KeyframeRole | None) -> str:
        if role is None:
            return "Keyframe"
        return self._SUMMARY_KEYFRAME_CAPTIONS.get(role, _humanize_enum_value(role.value))

    def _export_control_caption(self, kind: RecordingControlKind | None) -> str:
        if kind is None:
            return "Recording control"
        return self._SUMMARY_CONTROL_CAPTIONS.get(kind, _humanize_enum_value(kind.value))

    @staticmethod
    def _export_key_chord_caption(chord: object) -> str:
        characters = getattr(chord, "characters", None)
        label = str(_printable_key_text(characters) or getattr(chord, "normalized_key_label", "key"))
        normalized = label.strip().lower()
        special = {
            "enter": "Enter",
            "return": "Enter",
            "escape": "Esc",
            "esc": "Esc",
            "tab": "Tab",
            "space": "Space",
            "backspace": "Backspace",
            "delete": "Delete",
            "left_arrow": "Left Arrow",
            "right_arrow": "Right Arrow",
            "up_arrow": "Up Arrow",
            "down_arrow": "Down Arrow",
        }
        key_label = special.get(normalized, label.upper() if len(label) == 1 else label)
        modifiers = getattr(chord, "modifiers", ()) or ()
        modifier_labels = [_humanize_enum_value(getattr(modifier, "value", str(modifier))) for modifier in modifiers]
        return "+".join((*modifier_labels, key_label)) if modifier_labels else key_label

    @classmethod
    def _input_log_key_chord_caption(cls, chord: object) -> str:
        characters = _printable_key_text(getattr(chord, "characters", None))
        if characters is None:
            return cls._export_key_chord_caption(chord)
        modifiers = getattr(chord, "modifiers", ()) or ()
        modifier_labels = [_humanize_enum_value(getattr(modifier, "value", str(modifier))) for modifier in modifiers]
        return "+".join((*modifier_labels, characters)) if modifier_labels else characters

    def _keyframe_meta(
        self,
        *,
        keyframe: ContextKeyframe,
        media_time_ms: int | None,
        evidence_files: dict[str, str],
    ) -> dict[str, object]:
        return {
            "keyframe_id": keyframe.keyframe_id,
            "event_id": keyframe.event_id,
            "sequence_index": keyframe.sequence_index,
            "role": keyframe.role.value,
            "trigger_kind": keyframe.trigger_kind.value,
            "keep_reason": keyframe.keep_reason.value,
            "captured_at": _iso(keyframe.captured_at),
            "captured_at_monotonic_ms": keyframe.captured_at_monotonic_ms,
            "media_time_ms": media_time_ms,
            "confidence": keyframe.quality.confidence,
            "evidence_files": sorted(evidence_files.values()),
        }

    def _recording_meta(
        self,
        *,
        graph: RecordingSessionGraph,
        keyframe_index: list[dict[str, object]],
        video_file_count: int,
        vm_a11y_files: list[str],
        vm_event_log_count: int = 0,
        vm_click_log_count: int = 0,
        dom_hit_count: int = 0,
        dom_hit_match_count: int = 0,
        fallback_mode: RecordingExportFallbackMode = RecordingExportFallbackMode.NORMAL,
        fallback_warning: str | None = None,
    ) -> dict[str, object]:
        session = graph.session
        return {
            "session_id": session.session_id,
            "primary_event_id": session.primary_event_id,
            "mode": session.mode.value,
            "status": session.status.value,
            "workspace_id": session.workspace_id,
            "user_note": session.user_note,
            "started_at": _iso(session.started_at),
            "ended_at": _iso(session.ended_at),
            "created_at": _iso(session.created_at),
            "duration_ms": graph.timeline.duration_ms if graph.timeline is not None else None,
            "keyframe_count": len(keyframe_index),
            "total_keyframe_count": graph.total_keyframe_count,
            "omitted_keyframe_count": max(0, len(graph.keyframes) - len(keyframe_index)),
            "action_count": len(graph.actions),
            "total_action_count": graph.total_action_count,
            "control_count": len(graph.controls),
            "video_file_count": video_file_count,
            "fallback_mode": fallback_mode.value,
            "fallback_warning": fallback_warning,
            "vm_a11y_files": vm_a11y_files,
            "vm_events_file": "vm_events.jsonl" if vm_event_log_count > 0 else None,
            "vm_events_count": vm_event_log_count,
            "vm_clicks_file": "vm_clicks.jsonl" if vm_click_log_count > 0 else None,
            "vm_clicks_count": vm_click_log_count,
            "dom_hits_file": "dom_hits.jsonl",
            "dom_hits_count": dom_hit_count,
            "dom_hits_hit_count": dom_hit_match_count,
            "keyframes": keyframe_index,
        }

    def _render_summary(
        self,
        *,
        graph: RecordingSessionGraph,
        timeline: RecordingTimelineInspectView,
        typed_text_by_action: dict[str, str],
        vm_a11y_by_action: dict[str, list[dict[str, object]]],
        exportable_keyframe_ids: set[str],
    ) -> str:
        session = graph.session
        lines: list[str] = []
        lines.append(f"# Recording Summary - {session.session_id}")
        lines.append("")
        lines.append(f"- Mode: {session.mode.value}")
        lines.append(f"- Started: {_iso(session.started_at) or 'unknown'}")
        lines.append(f"- Ended: {_iso(session.ended_at) or 'unknown'}")
        duration_ms = graph.timeline.duration_ms if graph.timeline is not None else None
        lines.append(f"- Duration: {_format_duration(duration_ms)}")
        counts = (
            _count_label(
                sum(1 for keyframe in graph.keyframes if keyframe.keyframe_id in exportable_keyframe_ids),
                "keyframe",
            ),
            _count_label(len(graph.actions), "action"),
            _count_label(len(graph.controls), "control"),
        )
        lines.append(f"- Counts: {', '.join(counts)}")
        if any(_is_input_log_action(step.action_kind) for step in timeline.steps):
            lines.append("- Input log: keylog.jsonl")
        if session.user_note:
            lines.append(f"- User note: {_safe_markdown_inline(session.user_note)}")
        lines.append("")
        lines.append("## Timeline")
        lines.append("")
        actions_by_id = {action.action_id: action for action in graph.actions}
        for step in timeline.steps:
            if not _should_render_summary_step(step):
                continue
            kind = step.kind.value
            action = actions_by_id.get(step.action_id) if step.action_id is not None else None
            dom_hit = (
                _dom_hit_for_action_records(vm_a11y_by_action.get(step.action_id, ()))
                if step.action_id is not None
                else None
            )
            caption = self._export_caption(step, dom_hit=dom_hit, action=action) or kind
            typed_text = typed_text_by_action.get(step.action_id) if step.action_id is not None else None
            if typed_text:
                caption = f"{caption}: {typed_text}"
            caption = _safe_markdown_inline(caption)
            time_label = _format_media_time(step.media_time_ms)
            marker = {"keyframe": "[keyframe]", "action": "[action]", "control": "[control]"}.get(kind, "[item]")
            lines.append(f"- `{time_label}` {marker} {caption}")
        lines.append("")
        return "\n".join(lines)

    def _input_log_entries(
        self,
        *,
        graph: RecordingSessionGraph,
        timeline: RecordingTimelineInspectView,
    ) -> list[dict[str, str]]:
        actions_by_id = {action.action_id: action for action in graph.actions}
        entries: list[dict[str, str]] = []
        initial_window = _scope_window_label(graph.session.scope)
        if initial_window != "unknown":
            entries.append(
                {
                    "timestamp": _format_jsonl_timestamp(0),
                    "message": f"Initial Active Window: {initial_window}",
                    "window": initial_window,
                }
            )
        for step in timeline.steps:
            if step.action_id is None or not _is_input_log_action(step.action_kind):
                continue
            summary = step.action_summary
            action = actions_by_id.get(step.action_id)
            action_scope = action.scope if action is not None and action.scope is not None else graph.session.scope
            window = _scope_window_label(action_scope, fallback=graph.session.scope)
            if step.action_kind == HumanActionKind.CLICK:
                point = _input_log_point(action, scope=action_scope)
                if point is None:
                    continue
                button = _input_log_button(action)
                x, y = point
                entries.append(
                    {
                        "timestamp": _format_jsonl_timestamp(step.media_time_ms),
                        "message": f"{button}Click at ({x}, {y})",
                        "window": window,
                    }
                )
                entries.append(
                    {
                        "timestamp": _format_jsonl_timestamp(_plus_ms(step.media_time_ms, 1)),
                        "message": f"{button}Release at ({x}, {y})",
                        "window": window,
                    }
                )
                continue
            if step.action_kind == HumanActionKind.DRAG:
                drag_entries = _input_log_drag_entries(
                    action=action,
                    media_time_ms=step.media_time_ms,
                    scope=action_scope,
                    window=window,
                )
                entries.extend(drag_entries)
                continue
            if step.action_kind == HumanActionKind.SCROLL:
                point = _input_log_point(action, scope=action_scope)
                if point is None:
                    continue
                x, y = point
                direction = _input_log_scroll_direction(action)
                entries.append(
                    {
                        "timestamp": _format_jsonl_timestamp(step.media_time_ms),
                        "message": f"{direction} at ({x}, {y})",
                        "window": window,
                    }
                )
                continue
            if step.action_kind in {HumanActionKind.KEY_DOWN, HumanActionKind.KEY_UP, HumanActionKind.HOTKEY}:
                chord = summary.key_chord if summary is not None else None
                label = (
                    self._input_log_key_chord_caption(chord)
                    if chord is not None
                    else _input_log_key_label(_input_log_hotkey_label(action))
                )
                if not label:
                    continue
                if step.action_kind == HumanActionKind.HOTKEY:
                    message = f"Hotkey: {label}"
                else:
                    verb = "Press" if step.action_kind == HumanActionKind.KEY_DOWN else "Release"
                    message = f"Key {verb}: {label}"
                entries.append(
                    {
                        "timestamp": _format_jsonl_timestamp(step.media_time_ms),
                        "message": message,
                        "window": window,
                    }
                )
        return entries

    def _keyframe_folder_name(self, keyframe: ContextKeyframe) -> str:
        return f"{keyframe.sequence_index:04d}_{_compact_ts(keyframe.captured_at)}"

    def _recording_slug(
        self,
        graph: RecordingSessionGraph,
        fallback_mode: RecordingExportFallbackMode = RecordingExportFallbackMode.NORMAL,
    ) -> str:
        note = _safe_export_folder_component(graph.session.user_note or "recording")
        return f"{note}+{fallback_mode.value}"

    def _recording_dir(
        self,
        *,
        output_root: Path,
        graph: RecordingSessionGraph,
        fallback_mode: RecordingExportFallbackMode,
    ) -> Path:
        preferred = output_root / self._recording_slug(graph, fallback_mode)
        if not preferred.exists():
            return preferred
        metadata_path = preferred / "recording.json"
        if _exported_session_id(metadata_path) == graph.session.session_id:
            return preferred
        session_suffix = _safe_export_folder_component(graph.session.session_id)
        return output_root / f"{self._recording_slug(graph, fallback_mode)}+{session_suffix}"

    def _suffix_for(self, artifact: Artifact) -> str:
        if artifact.content_type and artifact.content_type in _CONTENT_TYPE_SUFFIXES:
            return _CONTENT_TYPE_SUFFIXES[artifact.content_type]
        uri_suffix = Path(artifact.storage_uri).suffix
        if uri_suffix:
            return uri_suffix
        return ".bin"

    def _write_json(self, path: Path, payload: object) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False, default=str),
            encoding="utf-8",
        )

    def _write_jsonl(self, path: Path, payload: Sequence[Mapping[str, object]]) -> None:
        path.write_text(
            "".join(json.dumps(item, ensure_ascii=False, sort_keys=False) + "\n" for item in payload),
            encoding="utf-8",
        )

    def _write_input_log(
        self,
        path: Path,
        *,
        graph: RecordingSessionGraph,
        entries: Sequence[Mapping[str, object]],
    ) -> None:
        metadata = _input_log_metadata(graph)
        started = _input_log_video_start_wall_time(graph)
        lines = [
            "# Input Recording Log",
            f"# Started: {_input_log_started_at(started)}",
            f"# Metadata: {json.dumps(metadata, ensure_ascii=False, sort_keys=False, default=str)}",
            "# Format: JSON per line",
            "# Fields: timestamp, message, window",
            "",
        ]
        screen_info = metadata.get("screen_info")
        if isinstance(screen_info, dict) and screen_info:
            lines.append(
                json.dumps(
                    {
                        "timestamp": _format_jsonl_timestamp(0),
                        "message": json.dumps(screen_info, ensure_ascii=False, sort_keys=False),
                        "window": "System Info",
                    },
                    ensure_ascii=False,
                    sort_keys=False,
                )
            )
        lines.extend(json.dumps(item, ensure_ascii=False, sort_keys=False) for item in entries)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _compact_ts(value: datetime | None) -> str:
    if value is None:
        return "unknown"
    return value.strftime("%Y%m%dT%H%M%S_%f")[:-3]


def _safe_export_folder_component(value: str, *, max_length: int = 80) -> str:
    normalized = " ".join(value.split())
    safe = "".join(
        "_" if character in "/:\\" or ord(character) < 32 else character
        for character in normalized
    ).strip(" .")
    return (safe[:max_length].rstrip(" .") or "recording")


def _printable_key_text(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value if all(character.isprintable() for character in value) else None


def _safe_markdown_inline(value: str) -> str:
    return "".join(
        character if character.isprintable() else f"\\x{ord(character):02X}"
        for character in value
    )


def _exported_session_id(metadata_path: Path) -> str | None:
    if not metadata_path.is_file():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    session_id = payload.get("session_id")
    return session_id if isinstance(session_id, str) and session_id else None


def _format_media_time(media_time_ms: int | None) -> str:
    if media_time_ms is None:
        return "--:--.---"
    total_seconds, millis = divmod(media_time_ms, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def _format_media_time_signed(media_time_ms: int | None) -> str:
    """Like ``_format_media_time`` but renders pre-recording offsets as ``-MM:SS.mmm``."""

    if media_time_ms is None:
        return _format_media_time(None)
    if media_time_ms < 0:
        return f"-{_format_media_time(-media_time_ms)}"
    return _format_media_time(media_time_ms)


def _should_render_summary_step(step: RecordingTimelineStepView) -> bool:
    if step.media_time_ms is not None:
        return True
    return step.kind != RecordingStoryboardItemKind.KEYFRAME


def _format_jsonl_timestamp(media_time_ms: int | None) -> str:
    if media_time_ms is None:
        return "--:--:--.---"
    total_seconds, millis = divmod(media_time_ms, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _input_log_started_at(value: datetime | None) -> str:
    if value is None:
        return "unknown"
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _input_log_metadata(graph: RecordingSessionGraph) -> dict[str, object]:
    started = _input_log_video_start_wall_time(graph)
    screen_info: dict[str, object] = {}
    scope = graph.session.scope
    reference_region = _input_log_reference_region(scope)
    if reference_region is not None:
        scale_factor = _input_log_scale_factor(scope=scope, action=None)
        display_id = scope.display_id if scope is not None and scope.display_id is not None else "0"
        screen_info[display_id] = {
            "x0": 0,
            "y0": 0,
            "width": round(reference_region.width * scale_factor),
            "height": round(reference_region.height * scale_factor),
            "scale_factor": 1.0,
        }
    return {
        "video_start_time": _input_log_started_at(started),
        "start_message": "Mouse and keyboard monitoring service started",
        "recording_timestamp": started.strftime("%Y%m%d_%H%M%S") if started is not None else "unknown",
        "session_id": graph.session.session_id,
        "screen_info": screen_info,
    }


def _input_log_video_start_wall_time(graph: RecordingSessionGraph) -> datetime | None:
    fallback = graph.session.started_at or graph.session.created_at
    for segment in sorted(graph.segments, key=lambda item: (item.sequence_index, item.started_at)):
        if segment.media_start_wall_time_epoch_ms is not None:
            return datetime.fromtimestamp(
                segment.media_start_wall_time_epoch_ms / 1_000,
                tz=segment.started_at.tzinfo,
            )
        if segment.media_start_monotonic_ms is None or segment.started_at_monotonic_ms is None:
            continue
        return segment.started_at + timedelta(
            milliseconds=segment.media_start_monotonic_ms - segment.started_at_monotonic_ms
        )
    return fallback


def _wall_clock_media_time_ms(
    *,
    graph: RecordingSessionGraph,
    timestamp: float | None,
) -> int | None:
    """Project a wall-clock event timestamp onto stitched recording media time.

    Native input actions already use the first-frame monotonic anchor. VM event
    and click sidecars instead arrive with epoch timestamps, so completed native
    segments carry the matching first-frame epoch anchor for this projection.
    Legacy recordings without that anchor retain the previous session-start
    fallback.
    """

    if timestamp is None:
        return None
    timestamp_ms = round(timestamp * 1_000)
    anchored_segments: list[tuple[int, int, int]] = []
    stitched_offset_ms = 0
    for segment in sorted(
        getattr(graph, "segments", ()),
        key=lambda item: (item.sequence_index, item.started_at),
    ):
        origin_ms = segment.media_start_wall_time_epoch_ms
        duration_ms = _recording_segment_media_duration_ms(segment)
        if duration_ms is None:
            continue
        if origin_ms is not None:
            anchored_segments.append((origin_ms, duration_ms, stitched_offset_ms))
        stitched_offset_ms += duration_ms

    if anchored_segments:
        first_origin_ms, _, first_offset_ms = anchored_segments[0]
        if timestamp_ms < first_origin_ms:
            return timestamp_ms - first_origin_ms if first_offset_ms == 0 else None
        for origin_ms, duration_ms, offset_ms in anchored_segments:
            if origin_ms <= timestamp_ms <= origin_ms + duration_ms:
                return offset_ms + timestamp_ms - origin_ms
        last_origin_ms, last_duration_ms, last_offset_ms = anchored_segments[-1]
        last_end_ms = last_origin_ms + last_duration_ms
        if timestamp_ms > last_end_ms:
            return last_offset_ms + last_duration_ms + timestamp_ms - last_end_ms
        # The event occurred during a pause between stitched segments and has no
        # corresponding media frame.
        return None

    start = graph.session.started_at or graph.session.created_at
    if start is None:
        return None
    return round((timestamp - start.timestamp()) * 1_000)


def _recording_segment_media_duration_ms(segment: object) -> int | None:
    video = getattr(segment, "video", None)
    video_duration_ms = getattr(video, "duration_ms", None)
    if isinstance(video_duration_ms, int):
        return video_duration_ms
    duration_ms = getattr(segment, "duration_ms", None)
    if isinstance(duration_ms, int):
        return duration_ms
    media_start_ms = getattr(segment, "media_start_monotonic_ms", None)
    ended_at_ms = getattr(segment, "ended_at_monotonic_ms", None)
    if isinstance(media_start_ms, int) and isinstance(ended_at_ms, int):
        return max(0, ended_at_ms - media_start_ms)
    return None


def _is_input_log_action(kind: HumanActionKind | None) -> bool:
    return kind in {
        HumanActionKind.CLICK,
        HumanActionKind.DRAG,
        HumanActionKind.SCROLL,
        HumanActionKind.HOTKEY,
        HumanActionKind.KEY_DOWN,
        HumanActionKind.KEY_UP,
    }


def _plus_ms(media_time_ms: int | None, delta_ms: int) -> int | None:
    return None if media_time_ms is None else media_time_ms + delta_ms


def _input_log_point(action: HumanActionEvent | None, *, scope: RecordingScope | None) -> tuple[int, int] | None:
    if action is None or action.coordinates is None:
        return None
    if action.coordinates.screenshot_rel is not None:
        point = action.coordinates.screenshot_rel
        return round(point.x), round(point.y)
    if action.coordinates.screen_abs is not None:
        point = action.coordinates.screen_abs
        return _input_log_screen_point(action=action, scope=scope, x=point.x, y=point.y)
    if action.coordinates.scope_rel is not None:
        point = action.coordinates.scope_rel
        return round(point.x), round(point.y)
    return None


def _action_point_payload(x: float | int, y: float | int) -> dict[str, object]:
    return {"x": x, "y": y, "coordinate_space": "artifact_px"}


def _action_screen_point_to_screenshot_rel(
    *,
    action: HumanActionEvent | None,
    scope: RecordingScope | None,
    x: float,
    y: float,
) -> tuple[int, int] | None:
    if _input_log_reference_region(scope) is None:
        return None
    return _input_log_screen_point(action=action, scope=scope, x=x, y=y)


def _action_target_bounds_payload(
    bounds: BoundingBox,
    *,
    action: HumanActionEvent | None,
    scope: RecordingScope | None,
) -> dict[str, object]:
    reference_region = _input_log_reference_region(scope)
    if reference_region is None or _coordinate_space_value(bounds.coordinate_space) != "macos_global":
        return bounds.model_dump(mode="json", exclude_none=True)
    scale_factor = _input_log_scale_factor(scope=scope, action=action)
    return {
        "x": round((bounds.x - reference_region.x) * scale_factor),
        "y": round((bounds.y - reference_region.y) * scale_factor),
        "width": round(bounds.width * scale_factor),
        "height": round(bounds.height * scale_factor),
        "coordinate_space": "artifact_px",
    }


def _coordinate_space_value(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


def _input_log_button(action: HumanActionEvent | None) -> str:
    raw_button = action.metadata.get("button") if action is not None else None
    if raw_button == "right":
        return "R"
    if raw_button == "middle":
        return "M"
    return "L"


def _action_pointer_button(action: HumanActionEvent | None) -> str | None:
    raw_button = action.metadata.get("button") if action is not None else None
    if not isinstance(raw_button, str):
        return None
    return RecordingExporter._POINTER_BUTTON_CAPTION_PREFIXES.get(raw_button.lower())


def _input_log_drag_entries(
    *,
    action: HumanActionEvent | None,
    media_time_ms: int | None,
    scope: RecordingScope | None,
    window: str,
) -> list[dict[str, str]]:
    if action is None:
        return []
    path = _input_log_drag_path(action, scope=scope)
    if len(path) < 2:
        start = _input_log_drag_start(action, scope=scope)
        end = _input_log_point(action, scope=scope)
        if start is None or end is None or start == end:
            return []
        path = [start, end]
    start = path[0]
    end = path[-1]
    duration_ms = _metadata_int(action.metadata.get("drag_duration_ms"))
    start_time_ms = media_time_ms
    if media_time_ms is not None and duration_ms is not None:
        start_time_ms = max(0, media_time_ms - duration_ms)
    button = _input_log_button(action)
    entries: list[dict[str, str]] = [
        {
            "timestamp": _format_jsonl_timestamp(start_time_ms),
            "message": f"{button}Click at ({start[0]}, {start[1]})",
            "window": window,
        }
    ]
    drag_start_time = _drag_start_log_time(start_time_ms=start_time_ms, end_time_ms=media_time_ms)
    entries.append(
        {
            "timestamp": _format_jsonl_timestamp(drag_start_time),
            "message": f"DragStart at ({start[0]}, {start[1]})",
            "window": window,
        }
    )
    moves = path[1:-1]
    for index, point in enumerate(moves, start=1):
        entries.append(
            {
                "timestamp": _format_jsonl_timestamp(
                    _interpolate_drag_time(
                        start_time_ms=drag_start_time,
                        end_time_ms=media_time_ms,
                        index=index,
                        count=len(moves) + 1,
                    )
                ),
                "message": f"DragMove to ({point[0]}, {point[1]})",
                "window": window,
            }
        )
    entries.append(
        {
            "timestamp": _format_jsonl_timestamp(media_time_ms),
            "message": (
                f"{button}DragEnd: from ({start[0]}, {start[1]}) to ({end[0]}, {end[1]}), "
                f"distance ({end[0] - start[0]}, {end[1] - start[1]})"
            ),
            "window": window,
        }
    )
    return entries


def _input_log_drag_start(action: HumanActionEvent, *, scope: RecordingScope | None) -> tuple[int, int] | None:
    x = _metadata_float(action.metadata.get("drag_start_x"))
    y = _metadata_float(action.metadata.get("drag_start_y"))
    if x is None or y is None:
        return None
    return _input_log_screen_point(action=action, scope=scope, x=x, y=y)


def _input_log_drag_path(action: HumanActionEvent, *, scope: RecordingScope | None) -> list[tuple[int, int]]:
    raw_path = action.metadata.get("drag_path")
    if not isinstance(raw_path, str) or not raw_path:
        start = _input_log_drag_start(action, scope=scope)
        end = _input_log_point(action, scope=scope)
        return [point for point in (start, end) if point is not None]
    points: list[tuple[int, int]] = []
    for chunk in raw_path.split(";"):
        raw_x, separator, raw_y = chunk.partition(",")
        if not separator:
            continue
        try:
            points.append(
                _input_log_screen_point(
                    action=action,
                    scope=scope,
                    x=float(raw_x),
                    y=float(raw_y),
                )
            )
        except ValueError:
            continue
    return points


def _input_log_screen_point(
    *,
    action: HumanActionEvent | None,
    scope: RecordingScope | None,
    x: float,
    y: float,
) -> tuple[int, int]:
    reference_region = _input_log_reference_region(scope)
    if reference_region is None:
        return round(x), round(y)
    scale_factor = _input_log_scale_factor(scope=scope, action=action)
    return (
        round((x - reference_region.x) * scale_factor),
        round((y - reference_region.y) * scale_factor),
    )


def _input_log_reference_region(scope: RecordingScope | None) -> BoundingBox | None:
    if scope is None:
        return None
    return scope.selection_region or scope.bounds


def _input_log_scale_factor(*, scope: RecordingScope | None, action: HumanActionEvent | None) -> float:
    point = action.coordinates.screen_abs if action is not None and action.coordinates is not None else None
    if point is not None and point.scale_factor is not None:
        return point.scale_factor
    if scope is not None and scope.scale_factor is not None:
        return scope.scale_factor
    return 1.0


def _drag_start_log_time(*, start_time_ms: int | None, end_time_ms: int | None) -> int | None:
    if start_time_ms is None or end_time_ms is None:
        return _plus_ms(start_time_ms, 1)
    duration = max(0, end_time_ms - start_time_ms)
    return start_time_ms + min(250, max(1, duration // 8))


def _interpolate_drag_time(
    *,
    start_time_ms: int | None,
    end_time_ms: int | None,
    index: int,
    count: int,
) -> int | None:
    if start_time_ms is None or end_time_ms is None or count <= 0:
        return start_time_ms
    return start_time_ms + round((end_time_ms - start_time_ms) * index / count)


def _metadata_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _metadata_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    if isinstance(value, str):
        try:
            return round(float(value))
        except ValueError:
            return None
    return None


def _input_log_scroll_direction(action: HumanActionEvent | None) -> str:
    delta_y = action.scroll_delta_y if action is not None else None
    if delta_y is None:
        return "Scroll"
    return "ScrollUp" if delta_y > 0 else "ScrollDown"


def _input_log_hotkey_label(action: HumanActionEvent | None) -> str:
    semantic = action.hotkey_semantic if action is not None else None
    if semantic is None:
        return ""
    return semantic.value


def _format_duration(duration_ms: int | None) -> str:
    if duration_ms is None:
        return "unknown"
    return f"{duration_ms / 1000:.1f}s"


def _input_log_key_label(value: str) -> str:
    if value == " ":
        return "SPACE"
    if value == "\t":
        return "TAB"
    if value == "\n" or value == "\r":
        return "ENTER"
    normalized = value.strip()
    if not normalized:
        return ""
    aliases = {
        "backspace": "BACKSPACE",
        "capslock": "CAPS_LOCK",
        "caps_lock": "CAPS_LOCK",
        "delete": "DELETE",
        "escape": "ESCAPE",
        "esc": "ESCAPE",
        "return": "ENTER",
        "enter": "ENTER",
        "space": "SPACE",
        "tab": "TAB",
        "shift": "SHIFT",
        "command": "COMMAND",
        "cmd": "COMMAND",
        "control": "CONTROL",
        "ctrl": "CONTROL",
        "option": "OPTION",
        "alt": "OPTION",
    }
    alias = aliases.get(normalized.lower())
    if alias is not None:
        return alias
    if len(normalized) == 1:
        return normalized
    return normalized.upper() if normalized.replace("_", "").isalpha() else normalized


def _action_kind_for_vm_event(event_kind: object) -> str | None:
    if event_kind == "pointer_click":
        return HumanActionKind.CLICK.value
    if event_kind == "pointer_drag":
        return HumanActionKind.DRAG.value
    if event_kind == "scroll":
        return HumanActionKind.SCROLL.value
    if event_kind == "key_down":
        return HumanActionKind.KEY_DOWN.value
    if event_kind == "key_up":
        return HumanActionKind.KEY_UP.value
    if event_kind == "typing_pause":
        return HumanActionKind.TYPING_PAUSE.value
    return None


def _vm_a11y_record_host_ts(record: dict[str, object]) -> float | None:
    sample_ts = record.get("sample_host_ts") or record.get("received_at_host_ts")
    if isinstance(sample_ts, int | float):
        return float(sample_ts)
    sample = record.get("sample")
    if not isinstance(sample, dict):
        return None
    sample_host_ts = sample.get("host_ts")
    return float(sample_host_ts) if isinstance(sample_host_ts, int | float) else None


_VM_EVENT_LOG_GENERIC_ROLES = frozenset({"document web", "window", "frame"})
_EVENT_LOG_BACKFILL_WINDOW_SECONDS = 3.0
_EVENT_LOG_WINDOW_MARGIN_SECONDS = 2.0


def _event_log_ts(event: Mapping[str, object]) -> float | None:
    for key in ("ts", "host_ts", "timestamp", "time"):
        value = event.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _event_log_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _event_log_sequence(event: Mapping[str, object], *, prefer_source: bool = False) -> int | None:
    keys = ("source_seq", "seq") if prefer_source else ("seq", "source_seq")
    for key in keys:
        value = _event_log_integer(event.get(key))
        if value is not None:
            return value
    return None


def _event_log_specific_target(event: Mapping[str, object]) -> bool:
    """A specific, targetable accessibility event (not a whole-page/window focus)."""

    return _dom_hit_from_event(event) is not None


def _valid_event_log_bbox(bbox: object) -> bool:
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return False
    try:
        _x, _y, width, height = (float(value) for value in bbox[:4])
    except (TypeError, ValueError):
        return False
    # Rejects placeholder boxes such as [-1, -1, -1, -1].
    return width > 0 and height > 0


def _dom_hit_from_event(event: Mapping[str, object]) -> dict[str, object] | None:
    a11y = event.get("a11y")
    if isinstance(a11y, Mapping):
        hit = _a11y_hit_from_mapping(a11y)
        if hit is not None and not _dom_hit_is_generic_focus(hit):
            return hit
    hit = _a11y_hit_from_mapping(event)
    if hit is not None and not _dom_hit_is_generic_focus(hit):
        return hit
    for key in ("hit", "dom", "element", "target", "node", "focused", "focus"):
        value = event.get(key)
        if isinstance(value, Mapping):
            dom_hit = _dom_hit_from_mapping(value)
            if dom_hit is not None:
                return dom_hit
    nested = event.get("event")
    if isinstance(nested, Mapping):
        nested_hit = _dom_hit_from_event(nested)
        if nested_hit is not None:
            return nested_hit
    event_hit = _dom_hit_from_mapping(event)
    if event_hit is not None and not _dom_hit_is_generic_focus(event_hit):
        return event_hit
    return None


def _a11y_hit_from_mapping(value: Mapping[str, object]) -> dict[str, object] | None:
    role = value.get("role")
    role_text = role.strip().lower() if isinstance(role, str) else ""
    if role_text in _VM_EVENT_LOG_GENERIC_ROLES:
        return None
    if not _valid_event_log_bbox(value.get("bbox")):
        return None
    name = value.get("name")
    has_name = isinstance(name, str) and bool(name.strip())
    if not has_name and role_text in ("", "menu"):
        return None
    hit: dict[str, object] = {}
    for key in ("role", "name", "bbox"):
        item = value.get(key)
        if item not in (None, ""):
            hit[key] = item
    return hit or None


def _dom_hit_from_mapping(value: Mapping[str, object]) -> dict[str, object] | None:
    hit: dict[str, object] = {}
    for key in ("tag", "id", "cls", "role", "aria", "name", "href", "text", "rect", "bbox"):
        item = value.get(key)
        if item not in (None, ""):
            hit[key] = item
    if "text" not in hit:
        for key in ("label", "title", "value", "description"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                hit["text"] = item
                break
    if "tag" not in hit:
        for key in ("node_name", "tagName", "type"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                hit["tag"] = item
                break
    if not any(hit.get(key) for key in ("tag", "role", "aria", "name", "text", "href")):
        return None
    return hit


def _dom_hit_is_generic_focus(hit: Mapping[str, object]) -> bool:
    role = hit.get("role")
    role_text = role.strip().lower() if isinstance(role, str) else ""
    return role_text in _VM_EVENT_LOG_GENERIC_ROLES


def _dom_hit_for_action_records(records: Sequence[Mapping[str, object]]) -> dict[str, object] | None:
    for record in records:
        hit_dom = record.get("hit_dom")
        if isinstance(hit_dom, dict) and not _dom_hit_is_generic_focus(hit_dom):
            return dict(hit_dom)
        sample = record.get("sample")
        if not isinstance(sample, dict):
            continue
        hit = sample.get("hit")
        if isinstance(hit, dict) and not _dom_hit_is_generic_focus(hit):
            return dict(hit)
        dom = sample.get("dom")
        if isinstance(dom, dict):
            return dict(dom)
    return None


def _dom_hit_source(records: Sequence[Mapping[str, object]]) -> str | None:
    for record in records:
        hit_dom = record.get("hit_dom")
        sample = record.get("sample")
        sample_hit = sample.get("hit") if isinstance(sample, dict) else None
        sample_dom = sample.get("dom") if isinstance(sample, dict) else None
        if not (
            (isinstance(hit_dom, dict) and not _dom_hit_is_generic_focus(hit_dom))
            or (isinstance(sample_hit, dict) and not _dom_hit_is_generic_focus(sample_hit))
            or isinstance(sample_dom, dict)
        ):
            continue
        source = record.get("source")
        if isinstance(source, str) and source:
            return source
        if isinstance(sample, dict):
            sample_source = sample.get("source")
            if isinstance(sample_source, str) and sample_source:
                return sample_source
    return None


def _dom_hit_errors(records: Sequence[Mapping[str, object]]) -> list[str]:
    errors: list[str] = []
    for record in records:
        error = record.get("error")
        if isinstance(error, str) and error:
            errors.append(error)
    return errors


def _dom_hit_backfill_delta_ms(records: Sequence[Mapping[str, object]]) -> float | None:
    for record in records:
        value = record.get("backfill_delta_ms")
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _dom_hit_event_seq(records: Sequence[Mapping[str, object]]) -> int | None:
    for record in records:
        value = record.get("event_seq")
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
    return None


def _dom_hit_label(dom_hit: Mapping[str, object]) -> str:
    tag = _non_empty_string(dom_hit.get("tag"))
    role = _non_empty_string(dom_hit.get("role"))
    aria = _non_empty_string(dom_hit.get("aria"))
    name = _non_empty_string(dom_hit.get("name"))
    text = _non_empty_string(dom_hit.get("text"))
    href = _non_empty_string(dom_hit.get("href"))
    element_id = _non_empty_string(dom_hit.get("id"))
    label = aria or name or text or href or element_id
    if label:
        normalized = " ".join(label.split())
        if role:
            return f"{role} · {normalized}"
        if tag:
            return f"{tag.lower()} · {normalized}"
        return normalized
    if role:
        return role
    if tag == "TEXTAREA":
        return "文本框"
    if tag == "INPUT":
        return "输入框"
    if tag:
        return tag.lower()
    return "DOM 元素"


def _summary_dom_hit_label(dom_hit: Mapping[str, object]) -> str:
    tag = _non_empty_string(dom_hit.get("tag"))
    role = _non_empty_string(dom_hit.get("role"))
    aria = _non_empty_string(dom_hit.get("aria"))
    name = _non_empty_string(dom_hit.get("name"))
    text = _non_empty_string(dom_hit.get("text"))
    href = _non_empty_string(dom_hit.get("href"))
    element_id = _non_empty_string(dom_hit.get("id"))
    label = aria or name or text or href or element_id
    if label:
        normalized = " ".join(label.split())
        if role:
            return f"{role} - {normalized}"
        if tag:
            return f"{tag.lower()} - {normalized}"
        return normalized
    if role:
        return role
    if tag == "TEXTAREA":
        return "text area"
    if tag == "INPUT":
        return "input"
    if tag:
        return tag.lower()
    return "DOM element"


def _dom_hit_target_display_label(dom_hit: Mapping[str, object]) -> str:
    label = _summary_dom_hit_label(dom_hit)
    return _truncate_label(label, max_length=80)


def _dom_hit_semantic_kind(dom_hit: Mapping[str, object]) -> str:
    role = (_non_empty_string(dom_hit.get("role")) or "").strip().lower()
    tag = (_non_empty_string(dom_hit.get("tag")) or "").strip().lower()
    if "button" in role or tag == "button":
        return "button"
    if "link" in role or tag == "a":
        return "link"
    if "tab" in role:
        return "tab"
    if "menu item" in role:
        return "menu_item"
    if "check" in role:
        return "checkbox"
    if tag in {"input", "textarea", "select"} or "text" in role or "combo box" in role:
        return "input"
    if "window" in role or "root pane" in role:
        return "window"
    return "unknown"


def _truncate_label(value: str, *, max_length: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max(1, max_length - 3)].rstrip() + "..."


def _json_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _humanize_enum_value(value: str) -> str:
    words = [word for word in value.replace("-", "_").split("_") if word]
    return " ".join(word.capitalize() for word in words) if words else value


def _count_label(count: int, singular: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {singular}{suffix}"


def _non_empty_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _scope_window_label(scope: object | None, *, fallback: object | None = None) -> str:
    selected = scope or fallback
    app_name = getattr(selected, "app_name", None) if selected is not None else None
    title = getattr(selected, "title", None) if selected is not None else None
    if app_name and title:
        return f"{app_name} - {title}"
    if title:
        return str(title)
    if app_name:
        return str(app_name)
    return "unknown"
