#!/usr/bin/env python3
"""Anchor one drag's visual evidence and target localization to DragStart."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from packages.active_capture.application.export.recording_export import _dom_hit_from_event
from scripts.correct_recording_dom_hit import select_action_step
from scripts.repair_export_dom_hits import (
    _dom_hit_label,
    _repair_actions,
    _repair_recording_meta,
    _repair_summary,
    _repair_trajectory,
)


JsonObject = dict[str, Any]
DRAG_START_RE = re.compile(r"DragStart at \((?P<x>-?\d+),\s*(?P<y>-?\d+)\)")
DRAG_END_RE = re.compile(
    r"(?P<button>[A-Za-z]*)DragEnd:\s*from\s*\((?P<x1>-?\d+),\s*(?P<y1>-?\d+)\)"
    r"\s*to\s*\((?P<x2>-?\d+),\s*(?P<y2>-?\d+)\)"
)
SIDECARS = {
    "vm_clicks": ("vm_clicks.jsonl", "click_log_backfill"),
    "vm_events": ("vm_events.jsonl", "event_log_backfill"),
}


@dataclass(frozen=True)
class DragAnchor:
    start_ms: int
    end_ms: int
    start: tuple[int, int]
    end: tuple[int, int]
    button: str | None = None


@dataclass(frozen=True)
class TargetMatch:
    sidecar: str
    source: str
    row: JsonObject
    dom_hit: JsonObject
    delta_ms: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording_dir", type=Path, help="Recording under videos_revise_time.")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--action-id", help="Exact drag action_id.")
    selector.add_argument("--media-time-ms", type=int, help="Exact drag action media_time_ms (normally DragEnd).")
    parser.add_argument(
        "--target-source",
        choices=("auto", "vm_clicks", "vm_events"),
        default="auto",
        help="DOM source at DragStart; auto prefers vm_clicks and falls back to vm_events.",
    )
    parser.add_argument(
        "--max-delta-ms",
        type=int,
        default=750,
        help="Maximum distance from DragStart to the selected sidecar row (default: 750).",
    )
    parser.add_argument(
        "--drag-match-window-ms",
        type=int,
        default=750,
        help="Maximum distance from action time to keylog DragEnd (default: 750).",
    )
    parser.add_argument(
        "--pipeline-script",
        type=Path,
        help="highlight_then_benchmark.py (default: MyPCBench_videos/code).",
    )
    parser.add_argument(
        "--benchmark-output-root",
        type=Path,
        help="Benchmark root (default: MyPCBench_videos/benchmark_revise_time).",
    )
    parser.add_argument("--run-id", default="fine_normal", help="Benchmark run name (default: fine_normal).")
    parser.add_argument(
        "--skip-highlight-refresh",
        action="store_true",
        help="Use the current images/manifest.json instead of regenerating highlights first.",
    )
    parser.add_argument("--skip-rebuild", action="store_true", help="Do not rebuild benchmark output.")
    parser.add_argument("--dry-run", action="store_true", help="Print the proposed revision without writing.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    recording_dir = args.recording_dir.expanduser().resolve()
    trajectory_path = recording_dir / "trajectory.json"
    if not trajectory_path.is_file():
        raise SystemExit(f"trajectory.json not found: {trajectory_path}")

    trajectory = _read_json(trajectory_path)
    step = select_action_step(
        trajectory,
        action_id=args.action_id,
        media_time_ms=args.media_time_ms,
    )
    if step.get("action_kind") != "drag":
        raise SystemExit(f"selected action is {step.get('action_kind')!r}, not 'drag'")

    action_id = str(step["action_id"])
    action_time_ms = int(step["media_time_ms"])
    anchor = find_drag_anchor(
        recording_dir / "keylog.jsonl",
        action_time_ms=action_time_ms,
        max_delta_ms=args.drag_match_window_ms,
    )
    target = choose_target_match(
        recording_dir,
        start_ms=anchor.start_ms,
        target_source=args.target_source,
        max_delta_ms=args.max_delta_ms,
    )

    project_root = _project_root(recording_dir)
    pipeline_script = (
        args.pipeline_script.expanduser().resolve()
        if args.pipeline_script
        else project_root / "code" / "highlight_then_benchmark.py"
    )
    highlighter_script = pipeline_script.parent / "keylog_highlight_frames.py"
    benchmark_output_root = (
        args.benchmark_output_root.expanduser().resolve()
        if args.benchmark_output_root
        else project_root / "benchmark_revise_time"
    )

    preview = {
        "recording_dir": str(recording_dir),
        "action_id": action_id,
        "action_media_time_ms_kept": action_time_ms,
        "drag_start_ms": anchor.start_ms,
        "drag_end_ms": anchor.end_ms,
        "start_coordinates": {"x": anchor.start[0], "y": anchor.start[1]},
        "end_coordinates": {"x": anchor.end[0], "y": anchor.end[1]},
        "target_source": target.sidecar,
        "target_delta_from_start_ms": target.delta_ms,
        "target": target.dom_hit,
        "benchmark": str(benchmark_output_root / recording_dir.name / args.run_id),
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2), flush=True)
    if args.dry_run:
        return 0

    apply_drag_start_target(
        recording_dir,
        action_id=action_id,
        anchor=anchor,
        target=target,
    )

    if not args.skip_highlight_refresh:
        if not highlighter_script.is_file():
            raise SystemExit(f"highlighter script not found: {highlighter_script}")
        _run([sys.executable, str(highlighter_script), str(recording_dir)])

    reanchor_drag_evidence(
        recording_dir,
        action_id=action_id,
        anchor=anchor,
        highlighter_script=highlighter_script,
    )

    if not args.skip_rebuild:
        if not pipeline_script.is_file():
            raise SystemExit(f"pipeline script not found: {pipeline_script}")
        command = [
            sys.executable,
            str(pipeline_script),
            str(recording_dir),
            "--output-root",
            str(benchmark_output_root),
            "--run-id",
            args.run_id,
            "--skip-highlight",
            "--overwrite",
        ]
        _run(command)
    return 0


def find_drag_anchor(path: Path, *, action_time_ms: int, max_delta_ms: int) -> DragAnchor:
    if not path.is_file():
        raise RuntimeError(f"keylog not found: {path}")
    anchors: list[DragAnchor] = []
    pending: tuple[int, tuple[int, int]] | None = None
    for row in _read_jsonl(path):
        timestamp = row.get("timestamp")
        message = row.get("message")
        if not isinstance(timestamp, str) or not isinstance(message, str):
            continue
        timestamp_ms = _parse_timestamp_ms(timestamp)
        start_match = DRAG_START_RE.match(message)
        if start_match is not None:
            pending = (
                timestamp_ms,
                (int(start_match.group("x")), int(start_match.group("y"))),
            )
            continue
        end_match = DRAG_END_RE.match(message)
        if end_match is None or pending is None:
            continue
        end = (int(end_match.group("x2")), int(end_match.group("y2")))
        anchors.append(
            DragAnchor(
                pending[0],
                timestamp_ms,
                pending[1],
                end,
                end_match.group("button") or None,
            )
        )
        pending = None
    if not anchors:
        raise RuntimeError(f"no complete drag found in {path}")
    anchor = min(anchors, key=lambda item: abs(item.end_ms - action_time_ms))
    delta_ms = abs(anchor.end_ms - action_time_ms)
    if delta_ms > max_delta_ms:
        raise RuntimeError(
            f"nearest keylog DragEnd is {delta_ms} ms from action time, above limit {max_delta_ms} ms"
        )
    return anchor


def choose_target_match(
    recording_dir: Path,
    *,
    start_ms: int,
    target_source: str,
    max_delta_ms: int,
) -> TargetMatch:
    sidecars = ("vm_clicks", "vm_events") if target_source == "auto" else (target_source,)
    errors: list[str] = []
    for sidecar in sidecars:
        filename, source = SIDECARS[sidecar]
        path = recording_dir / filename
        if not path.is_file():
            errors.append(f"{filename}: missing")
            continue
        candidates: list[tuple[int, JsonObject, JsonObject]] = []
        for row in _read_jsonl(path):
            media_time_ms = row.get("media_time_ms")
            if not isinstance(media_time_ms, int):
                continue
            dom_hit = _dom_hit_from_event(row)
            if dom_hit is None:
                continue
            candidates.append((abs(media_time_ms - start_ms), row, dom_hit))
        if not candidates:
            errors.append(f"{filename}: no targetable row")
            continue
        distance_ms, row, dom_hit = min(candidates, key=lambda item: item[0])
        if distance_ms > max_delta_ms:
            errors.append(f"{filename}: nearest row is {distance_ms} ms away")
            continue
        return TargetMatch(
            sidecar=sidecar,
            source=source,
            row=row,
            dom_hit=dom_hit,
            delta_ms=int(row["media_time_ms"]) - start_ms,
        )
    raise RuntimeError("could not resolve DragStart target; " + "; ".join(errors))


def apply_drag_start_target(
    recording_dir: Path,
    *,
    action_id: str,
    anchor: DragAnchor,
    target: TargetMatch,
) -> None:
    dom_hits_path = recording_dir / "dom_hits.jsonl"
    rows = _read_jsonl(dom_hits_path) if dom_hits_path.is_file() else []
    matches = [row for row in rows if row.get("action_id") == action_id]
    if len(matches) != 1:
        raise RuntimeError(f"expected one dom_hits row for {action_id}, found {len(matches)}")
    before = copy.deepcopy(matches[0])
    row = matches[0]
    row.update(
        {
            "status": "hit",
            "dom_hit": copy.deepcopy(target.dom_hit),
            "dom_hit_label": _dom_hit_label(target.dom_hit),
            "source": target.source,
            "backfill_delta_ms": target.delta_ms,
        }
    )
    for key in ("errors", "event_seq", "manual_source", "manual_source_delta_ms"):
        row.pop(key, None)
    if isinstance(target.row.get("seq"), int):
        row["event_seq"] = target.row["seq"]
    _write_jsonl(dom_hits_path, rows)

    dom_by_action = {action_id: target.dom_hit}
    action_context = _repair_actions(recording_dir, dom_by_action)
    _repair_trajectory(recording_dir, dom_by_action, action_context)
    _restore_drag_button_caption(recording_dir / "trajectory.json", action_id, anchor.button)
    _patch_action_coordinates(recording_dir / "trajectory.json", action_id, anchor.start)
    for path in sorted(recording_dir.glob("*/actions.json")):
        _restore_drag_button_caption(path, action_id, anchor.button)
        _patch_action_coordinates(path, action_id, anchor.start)
    _repair_recording_meta(recording_dir, dom_by_action)
    _repair_summary(recording_dir)

    _append_jsonl(
        recording_dir / "drag_start_anchor_revisions.jsonl",
        {
            "applied_at": datetime.now(UTC).isoformat(),
            "action_id": action_id,
            "action_media_time_ms": anchor.end_ms,
            "drag_start_ms": anchor.start_ms,
            "drag_end_ms": anchor.end_ms,
            "start_coordinates": {"x": anchor.start[0], "y": anchor.start[1]},
            "end_coordinates": {"x": anchor.end[0], "y": anchor.end[1]},
            "before": before,
            "after": {
                "dom_hit": target.dom_hit,
                "dom_hit_label": _dom_hit_label(target.dom_hit),
                "coordinates": _coordinates(anchor.start),
            },
            "source_sidecar": target.sidecar,
            "source_delta_from_start_ms": target.delta_ms,
            "source_record": target.row,
        },
    )


def reanchor_drag_evidence(
    recording_dir: Path,
    *,
    action_id: str,
    anchor: DragAnchor,
    highlighter_script: Path,
) -> None:
    output_dir = recording_dir / "images"
    manifest_path = output_dir / "manifest.json"
    manifest = _read_json(manifest_path)
    events = manifest.get("events")
    if not isinstance(events, list):
        raise RuntimeError(f"manifest has no events list: {manifest_path}")
    matches = [
        (index, event)
        for index, event in enumerate(events)
        if isinstance(event, dict)
        and event.get("kind") == "drag"
        and (
            event.get("action_id") == action_id
            or event.get("timestamp_ms") == anchor.end_ms
        )
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one drag evidence event for {action_id}, found {len(matches)}")
    index, old_event = matches[0]

    trajectory = _read_json(recording_dir / "trajectory.json")
    step = select_action_step(trajectory, action_id=action_id, media_time_ms=None)
    caption = step.get("safe_caption") if isinstance(step.get("safe_caption"), str) else None
    module = _load_module(highlighter_script)
    event = module.HighlightEvent(
        kind="drag",
        timestamp_ms=anchor.end_ms,
        start_ms=anchor.start_ms,
        end_ms=anchor.end_ms,
        button=old_event.get("button") if isinstance(old_event.get("button"), str) else None,
        points=tuple(
            (int(point["x"]), int(point["y"]))
            for point in old_event.get("points", [])
            if isinstance(point, dict)
            and isinstance(point.get("x"), int)
            and isinstance(point.get("y"), int)
        ),
        label=str(old_event.get("label") or f"Drag {anchor.start_ms} -> {anchor.end_ms}"),
        raw_messages=tuple(
            message for message in old_event.get("raw_messages", []) if isinstance(message, str)
        ),
        action_id=action_id,
        action_kind="drag",
        action_caption=caption,
        action_delta_ms=old_event.get("action_delta_ms")
        if isinstance(old_event.get("action_delta_ms"), int)
        else 0,
        image_action_caption=caption,
        image_action_source="drag_start_anchor",
    )
    filename = (
        f"{index + 1:04d}_drag_{anchor.start_ms:08d}ms_"
        f"{module.safe_name(event.label)[:48]}.png"
    )
    output_path = output_dir / filename
    video_path = Path(str(manifest.get("video") or recording_dir / "video.mp4"))
    frame = module.extract_frame(video_path, anchor.start_ms, fast_seek=False)
    module.render_event(frame, event, anchor.start_ms).save(output_path)

    old_image = old_event.get("image")
    events[index] = module.event_manifest(event, output_path, anchor.start_ms)
    manifest["drag_frame_anchor"] = "start"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    module.write_image_action_outputs(output_dir, manifest)
    if isinstance(old_image, str) and old_image != filename:
        old_path = output_dir / old_image
        if old_path.is_file():
            old_path.unlink()


def _patch_action_coordinates(path: Path, action_id: str, point: tuple[int, int]) -> None:
    if not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    matched = 0

    def visit(value: Any) -> None:
        nonlocal matched
        if isinstance(value, dict):
            if value.get("action_id") == action_id and "coordinates" in value:
                value["coordinates"] = _coordinates(point)
                matched += 1
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    if matched:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _restore_drag_button_caption(path: Path, action_id: str, button: str | None) -> None:
    button_name = {
        "L": "Left",
        "R": "Right",
        "M": "Middle",
    }.get(button or "")
    if button_name is None or not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    changed = False

    def visit(value: Any) -> None:
        nonlocal changed
        if isinstance(value, dict):
            if value.get("action_id") == action_id:
                for key in ("caption", "safe_caption"):
                    caption = value.get(key)
                    if isinstance(caption, str) and caption.startswith("Drag "):
                        value[key] = f"{button_name} {caption}"
                        changed = True
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    if changed:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _coordinates(point: tuple[int, int]) -> JsonObject:
    return {
        "screenshot_rel": {
            "x": point[0],
            "y": point[1],
            "coordinate_space": "artifact_px",
        }
    }


def _load_module(path: Path) -> ModuleType:
    if not path.is_file():
        raise RuntimeError(f"highlighter script not found: {path}")
    module_name = "_mypcbench_keylog_highlight_frames"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import highlighter: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _project_root(recording_dir: Path) -> Path:
    for parent in recording_dir.parents:
        if parent.name == "videos_revise_time":
            return parent.parent
    raise RuntimeError(f"recording is not under videos_revise_time: {recording_dir}")


def _parse_timestamp_ms(value: str) -> int:
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError(f"unsupported timestamp: {value}")
    hours, minutes = int(parts[0]), int(parts[1])
    seconds = float(parts[2])
    return round((hours * 3600 + minutes * 60 + seconds) * 1000)


def _read_json(path: Path) -> JsonObject:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def _read_jsonl(path: Path) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise RuntimeError(f"{path}:{line_number} is not a JSON object")
        rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: list[JsonObject]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _append_jsonl(path: Path, payload: JsonObject) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _run(command: list[str]) -> None:
    print("$ " + shlex.join(command), flush=True)
    subprocess.run(command, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
