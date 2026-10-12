"""Create structured release-lab reports for physical macOS recording cases.

This helper intentionally does not automate the physical recording matrix. It
turns the release-lab operator's observed facts into the strict JSON shape that
``verify_macos_app_e2e_manifest.py`` validates. Boolean proof fields default to
``false`` so a report only passes after the operator explicitly records each
observed UI state.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class PhysicalRecordingCase(StrEnum):
    """Physical recording rows accepted by the release manifest."""

    RECORDING_REGION = "recording_region"
    RECORDING_DISCARD = "recording_discard"
    RECORDING_CONTROLS = "recording_controls"


@dataclass(frozen=True, slots=True)
class CommonPhysicalRecordingEvidence:
    """Evidence common to every physical recording release row.

    Attributes:
        case: Manifest row being proven.
        app_bundle: Bundle used for the run; strict reports use ``dist/WorkRecorder.app``.
        trigger_shortcut: Shortcut observed by the operator.
        opened_via_physical_shortcut: Whether the flow started from the real hotkey.
        region_selection_confirmed: Whether the selected region was confirmed.
        hud_visible: Whether the recording HUD was visible while recording.
        recording_boundary_visible: Whether the selected boundary stayed visible.
        completion_sheet_visible: Whether the post-recording sheet appeared.
        session_id: Active-capture session identifier.
        started_at: ISO timestamp for recording start.
        ended_at: ISO timestamp for recording completion or discard.
        privacy_check_no_storage_uri: Whether the report omits storage URIs.
        privacy_check_no_local_path: Whether the report omits local paths.
        operator_note: Human release-lab note explaining the observation.
    """

    case: PhysicalRecordingCase
    app_bundle: str
    trigger_shortcut: str
    opened_via_physical_shortcut: bool
    region_selection_confirmed: bool
    hud_visible: bool
    recording_boundary_visible: bool
    completion_sheet_visible: bool
    session_id: str
    started_at: str
    ended_at: str
    privacy_check_no_storage_uri: bool
    privacy_check_no_local_path: bool
    operator_note: str


@dataclass(frozen=True, slots=True)
class SaveEvidence:
    """Evidence required when a recording is saved.

    Attributes:
        save_clicked: Whether Save was clicked in the completion sheet.
        discard_clicked: Whether Discard was clicked; must remain false here.
        completion_final_status: Final session status after Save.
        video_state: Safe video state reported by inspect.
        appears_in_recording_library: Whether Workbench shows it in recording library.
        appears_in_screenshot_library: Whether it incorrectly appears in screenshot library.
        event_id: Completed recording event identifier.
        video_artifact_id: Video artifact identifier attached after Save.
        duration_ms: Recorded video duration in milliseconds.
        segment_count: Number of committed recording segments.
        keyframe_count: Number of keyframes linked to the session.
    """

    save_clicked: bool
    discard_clicked: bool
    completion_final_status: str
    video_state: str
    appears_in_recording_library: bool
    appears_in_screenshot_library: bool
    event_id: str
    video_artifact_id: str
    duration_ms: int
    segment_count: int
    keyframe_count: int


@dataclass(frozen=True, slots=True)
class DiscardEvidence:
    """Evidence required when a recording is discarded.

    Attributes:
        save_clicked: Whether Save was clicked; must remain false here.
        discard_clicked: Whether Discard was clicked.
        completion_final_status: Final session status after discard.
        appears_in_recording_library: Whether a discarded recording still appears in recording library.
        appears_in_screenshot_library: Whether a discarded recording appears in screenshot library.
        completed_event_created: Whether a completed event was incorrectly created.
        staged_video_deleted: Whether staged local video was removed.
    """

    save_clicked: bool
    discard_clicked: bool
    completion_final_status: str
    appears_in_recording_library: bool
    appears_in_screenshot_library: bool
    completed_event_created: bool
    staged_video_deleted: bool


@dataclass(frozen=True, slots=True)
class ControlsEvidence:
    """Evidence required when recording controls are exercised.

    Attributes:
        pause_clicked: Whether the HUD Pause control was clicked.
        resume_clicked: Whether the HUD Resume control was clicked.
        mark_clicked: Whether the HUD Mark control was clicked.
        pause_stopped_capture: Whether pause stopped video/input capture.
        resume_started_new_segment: Whether resume started a new segment.
        mark_created_keyframe: Whether Mark produced a session keyframe.
        save_clicked: Whether the controlled recording was saved.
        completion_final_status: Final session status after Save.
        video_state: Safe video state reported by inspect.
        appears_in_recording_library: Whether Workbench shows it in recording library.
        appears_in_screenshot_library: Whether it incorrectly appears in screenshot library.
        event_id: Completed recording event identifier.
        video_artifact_id: Video artifact identifier attached after Save.
        manual_mark_keyframe_id: Keyframe identifier created by Mark.
        duration_ms: Recorded video duration in milliseconds.
        segment_count: Number of committed recording segments; must be at least two.
        keyframe_count: Number of keyframes linked to the session.
    """

    pause_clicked: bool
    resume_clicked: bool
    mark_clicked: bool
    pause_stopped_capture: bool
    resume_started_new_segment: bool
    mark_created_keyframe: bool
    save_clicked: bool
    completion_final_status: str
    video_state: str
    appears_in_recording_library: bool
    appears_in_screenshot_library: bool
    event_id: str
    video_artifact_id: str
    manual_mark_keyframe_id: str
    duration_ms: int
    segment_count: int
    keyframe_count: int


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line interface.

    Returns:
        Configured parser for physical recording report generation.
    """

    parser = argparse.ArgumentParser(description="Create a physical recording E2E report JSON.")
    parser.add_argument("--case", choices=[case.value for case in PhysicalRecordingCase], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--app-bundle", default="dist/WorkRecorder.app")
    parser.add_argument("--trigger-shortcut", default="⌃⌥⌘R")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--ended-at", required=True)
    parser.add_argument("--operator-note", required=True)
    _add_common_confirmation_flags(parser)
    _add_save_arguments(parser)
    _add_discard_arguments(parser)
    _add_controls_arguments(parser)
    return parser


def main() -> int:
    """Create the requested report file.

    Returns:
        Process exit status.
    """

    args = build_argument_parser().parse_args()
    payload = build_report(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote physical recording report: {args.output}")
    return 0


def build_report(args: argparse.Namespace) -> dict[str, JsonValue]:
    """Build a typed physical recording report from parsed arguments.

    Args:
        args: Parsed arguments from ``build_argument_parser``.

    Returns:
        JSON-serializable physical recording evidence.
    """

    case = PhysicalRecordingCase(args.case)
    payload = _common_payload(args=args, case=case)
    if case is PhysicalRecordingCase.RECORDING_REGION:
        payload.update(asdict(_save_evidence(args)))
    elif case is PhysicalRecordingCase.RECORDING_DISCARD:
        payload.update(asdict(_discard_evidence(args)))
    elif case is PhysicalRecordingCase.RECORDING_CONTROLS:
        payload.update(asdict(_controls_evidence(args)))
    return payload


def _add_common_confirmation_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--opened-via-physical-shortcut", action="store_true")
    parser.add_argument("--region-selection-confirmed", action="store_true")
    parser.add_argument("--hud-visible", action="store_true")
    parser.add_argument("--recording-boundary-visible", action="store_true")
    parser.add_argument("--completion-sheet-visible", action="store_true")
    parser.add_argument("--privacy-check-no-storage-uri", action="store_true")
    parser.add_argument("--privacy-check-no-local-path", action="store_true")


def _add_save_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--save-clicked", action="store_true")
    parser.add_argument("--discard-clicked", action="store_true")
    parser.add_argument("--completion-final-status", default="")
    parser.add_argument("--video-state", default="")
    parser.add_argument("--appears-in-recording-library", action="store_true")
    parser.add_argument("--appears-in-screenshot-library", action="store_true")
    parser.add_argument("--event-id", default="")
    parser.add_argument("--video-artifact-id", default="")
    parser.add_argument("--duration-ms", type=int, default=0)
    parser.add_argument("--segment-count", type=int, default=0)
    parser.add_argument("--keyframe-count", type=int, default=0)


def _add_discard_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--completed-event-created", action="store_true")
    parser.add_argument("--staged-video-deleted", action="store_true")


def _add_controls_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pause-clicked", action="store_true")
    parser.add_argument("--resume-clicked", action="store_true")
    parser.add_argument("--mark-clicked", action="store_true")
    parser.add_argument("--pause-stopped-capture", action="store_true")
    parser.add_argument("--resume-started-new-segment", action="store_true")
    parser.add_argument("--mark-created-keyframe", action="store_true")
    parser.add_argument("--manual-mark-keyframe-id", default="")


def _common_payload(*, args: argparse.Namespace, case: PhysicalRecordingCase) -> dict[str, JsonValue]:
    evidence = CommonPhysicalRecordingEvidence(
        case=case,
        app_bundle=args.app_bundle,
        trigger_shortcut=args.trigger_shortcut,
        opened_via_physical_shortcut=args.opened_via_physical_shortcut,
        region_selection_confirmed=args.region_selection_confirmed,
        hud_visible=args.hud_visible,
        recording_boundary_visible=args.recording_boundary_visible,
        completion_sheet_visible=args.completion_sheet_visible,
        session_id=args.session_id,
        started_at=args.started_at,
        ended_at=args.ended_at,
        privacy_check_no_storage_uri=args.privacy_check_no_storage_uri,
        privacy_check_no_local_path=args.privacy_check_no_local_path,
        operator_note=args.operator_note,
    )
    return asdict(evidence)


def _save_evidence(args: argparse.Namespace) -> SaveEvidence:
    return SaveEvidence(
        save_clicked=args.save_clicked,
        discard_clicked=args.discard_clicked,
        completion_final_status=args.completion_final_status,
        video_state=args.video_state,
        appears_in_recording_library=args.appears_in_recording_library,
        appears_in_screenshot_library=args.appears_in_screenshot_library,
        event_id=args.event_id,
        video_artifact_id=args.video_artifact_id,
        duration_ms=args.duration_ms,
        segment_count=args.segment_count,
        keyframe_count=args.keyframe_count,
    )


def _discard_evidence(args: argparse.Namespace) -> DiscardEvidence:
    return DiscardEvidence(
        save_clicked=args.save_clicked,
        discard_clicked=args.discard_clicked,
        completion_final_status=args.completion_final_status,
        appears_in_recording_library=args.appears_in_recording_library,
        appears_in_screenshot_library=args.appears_in_screenshot_library,
        completed_event_created=args.completed_event_created,
        staged_video_deleted=args.staged_video_deleted,
    )


def _controls_evidence(args: argparse.Namespace) -> ControlsEvidence:
    return ControlsEvidence(
        pause_clicked=args.pause_clicked,
        resume_clicked=args.resume_clicked,
        mark_clicked=args.mark_clicked,
        pause_stopped_capture=args.pause_stopped_capture,
        resume_started_new_segment=args.resume_started_new_segment,
        mark_created_keyframe=args.mark_created_keyframe,
        save_clicked=args.save_clicked,
        completion_final_status=args.completion_final_status,
        video_state=args.video_state,
        appears_in_recording_library=args.appears_in_recording_library,
        appears_in_screenshot_library=args.appears_in_screenshot_library,
        event_id=args.event_id,
        video_artifact_id=args.video_artifact_id,
        manual_mark_keyframe_id=args.manual_mark_keyframe_id,
        duration_ms=args.duration_ms,
        segment_count=args.segment_count,
        keyframe_count=args.keyframe_count,
    )


if __name__ == "__main__":
    raise SystemExit(main())
