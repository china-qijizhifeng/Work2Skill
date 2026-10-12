#!/usr/bin/env python3
"""Mark every action in a media-time range as target-needs-review and rebuild one mode."""

from __future__ import annotations

import argparse
import copy
import json
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.correct_recording_dom_hit import (
    EXPORT_MODES,
    mode_rebuild_commands,
    resolve_recording_dir,
)
from scripts.repair_export_dom_hits import _repair_summary


JsonObject = dict[str, Any]
DEFAULT_CAPTION = "Left Click(target needs review)"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "recording_dir",
        type=Path,
        help="Recording or three-mode task directory under videos or videos_revise_time.",
    )
    parser.add_argument("--mode", choices=EXPORT_MODES, required=True, help="Mode to revise and rebuild.")
    parser.add_argument("--start-media-time-ms", type=int, help="Inclusive range start.")
    parser.add_argument("--end-media-time-ms", type=int, help="Inclusive range end.")
    parser.add_argument(
        "--time-caption",
        type=parse_time_caption,
        action="append",
        metavar="ACTION_MS:CAPTION",
        help="Set one action to one caption; repeat for multiple independent actions.",
    )
    parser.add_argument("--caption", default=DEFAULT_CAPTION, help=f"Replacement caption (default: {DEFAULT_CAPTION!r}).")
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
    parser.add_argument("--skip-rebuild", action="store_true", help="Patch revised raw data without rebuilding.")
    parser.add_argument("--dry-run", action="store_true", help="Show matched actions and commands without writing.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    has_any_range_value = args.start_media_time_ms is not None or args.end_media_time_ms is not None
    has_complete_range = args.start_media_time_ms is not None and args.end_media_time_ms is not None
    has_time_captions = bool(args.time_caption)
    if has_any_range_value and not has_complete_range:
        raise SystemExit("range mode requires both --start-media-time-ms and --end-media-time-ms")
    if has_complete_range == has_time_captions:
        raise SystemExit("use either one complete range or one or more --time-caption values")
    if has_complete_range and args.start_media_time_ms > args.end_media_time_ms:
        raise SystemExit("--start-media-time-ms must be <= --end-media-time-ms")
    input_path = args.recording_dir.expanduser().resolve()
    recording_dir, mode, task_name = resolve_recording_dir(input_path, mode=args.mode)
    if mode is None:
        raise SystemExit("could not determine export mode")

    trajectory = _read_json(recording_dir / "trajectory.json")
    if has_complete_range:
        matches = select_action_steps(
            trajectory,
            start_media_time_ms=args.start_media_time_ms,
            end_media_time_ms=args.end_media_time_ms,
        )
        captions_by_action = {str(step["action_id"]): args.caption for step in matches}
        selection: JsonObject = {
            "type": "range",
            "start_media_time_ms": args.start_media_time_ms,
            "end_media_time_ms": args.end_media_time_ms,
        }
    else:
        matches, captions_by_action = select_time_caption_steps(
            trajectory,
            time_captions=args.time_caption,
        )
        selection = {
            "type": "individual",
            "media_times_ms": [time_ms for time_ms, _caption in args.time_caption],
        }
    preview = {
        "recording_dir": str(recording_dir),
        "mode": mode,
        "selection": selection,
        "action_count": len(matches),
        "actions": [
            {
                "action_id": step["action_id"],
                "media_time_ms": step["media_time_ms"],
                "action_kind": step.get("action_kind"),
                "before": step.get("safe_caption"),
                "after": captions_by_action[str(step["action_id"])],
            }
            for step in matches
        ],
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2), flush=True)

    project_root = _project_root(recording_dir)
    pipeline_script = (
        args.pipeline_script.expanduser().resolve()
        if args.pipeline_script
        else project_root / "code" / "highlight_then_benchmark.py"
    )
    benchmark_output_root = (
        args.benchmark_output_root.expanduser().resolve()
        if args.benchmark_output_root
        else _default_benchmark_output_root(recording_dir, project_root=project_root)
    )
    commands = mode_rebuild_commands(
        pipeline_script=pipeline_script,
        recording_dir=recording_dir,
        benchmark_output_root=benchmark_output_root,
        task_name=task_name,
        mode=mode,
    )
    if args.dry_run:
        if not args.skip_rebuild:
            for command in commands:
                print("$ " + shlex.join(command), flush=True)
        return 0

    apply_needs_review_actions(
        recording_dir,
        captions_by_action=captions_by_action,
        selection=selection,
    )
    if not args.skip_rebuild:
        for command in commands:
            subprocess.run(command, check=True)
    return 0


def parse_time_caption(value: str) -> tuple[int, str]:
    time_text, separator, caption = value.partition(":")
    if not separator or not caption.strip():
        raise argparse.ArgumentTypeError("expected ACTION_MS:CAPTION")
    try:
        media_time_ms = int(time_text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("ACTION_MS must be an integer") from error
    if media_time_ms < 0:
        raise argparse.ArgumentTypeError("ACTION_MS must be non-negative")
    return media_time_ms, caption.strip()


def select_action_steps(
    trajectory: JsonObject,
    *,
    start_media_time_ms: int,
    end_media_time_ms: int,
) -> list[JsonObject]:
    steps = trajectory.get("steps")
    if not isinstance(steps, list):
        raise RuntimeError("trajectory has no steps array")
    matches = [
        step
        for step in steps
        if isinstance(step, dict)
        and step.get("kind") == "action"
        and isinstance(step.get("action_id"), str)
        and isinstance(step.get("media_time_ms"), int)
        and start_media_time_ms <= step["media_time_ms"] <= end_media_time_ms
    ]
    if not matches:
        raise RuntimeError(
            f"no actions found in inclusive range {start_media_time_ms}..{end_media_time_ms}"
        )
    return matches


def select_time_caption_steps(
    trajectory: JsonObject,
    *,
    time_captions: list[tuple[int, str]],
) -> tuple[list[JsonObject], dict[str, str]]:
    if len({time_ms for time_ms, _caption in time_captions}) != len(time_captions):
        raise RuntimeError("duplicate ACTION_MS values in --time-caption")
    steps = trajectory.get("steps")
    if not isinstance(steps, list):
        raise RuntimeError("trajectory has no steps array")
    matches: list[JsonObject] = []
    captions_by_action: dict[str, str] = {}
    for media_time_ms, caption in time_captions:
        candidates = [
            step
            for step in steps
            if isinstance(step, dict)
            and step.get("kind") == "action"
            and isinstance(step.get("action_id"), str)
            and step.get("media_time_ms") == media_time_ms
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                f"expected exactly one action at {media_time_ms}ms, found {len(candidates)}"
            )
        step = candidates[0]
        matches.append(step)
        captions_by_action[str(step["action_id"])] = caption
    return matches, captions_by_action


def apply_needs_review_range(
    recording_dir: Path,
    *,
    action_ids: set[str],
    start_media_time_ms: int,
    end_media_time_ms: int,
    caption: str,
) -> None:
    apply_needs_review_actions(
        recording_dir,
        captions_by_action={action_id: caption for action_id in action_ids},
        selection={
            "type": "range",
            "start_media_time_ms": start_media_time_ms,
            "end_media_time_ms": end_media_time_ms,
        },
    )


def apply_needs_review_actions(
    recording_dir: Path,
    *,
    captions_by_action: dict[str, str],
    selection: JsonObject,
) -> None:
    action_ids = set(captions_by_action)
    trajectory_path = recording_dir / "trajectory.json"
    trajectory = _read_json(trajectory_path)
    before_steps: list[JsonObject] = []
    patched_ids: set[str] = set()
    for step in trajectory.get("steps", []):
        if not isinstance(step, dict) or step.get("action_id") not in action_ids:
            continue
        action_id = str(step["action_id"])
        before_steps.append(copy.deepcopy(step))
        _mark_step_needs_review(step, caption=captions_by_action[action_id])
        patched_ids.add(action_id)
    if patched_ids != action_ids:
        missing = sorted(action_ids - patched_ids)
        raise RuntimeError(f"trajectory actions disappeared before patch: {missing}")
    _write_json(trajectory_path, trajectory)

    dom_hits_path = recording_dir / "dom_hits.jsonl"
    dom_rows = _read_jsonl(dom_hits_path) if dom_hits_path.is_file() else []
    for row in dom_rows:
        if row.get("action_id") not in action_ids:
            continue
        row["status"] = "miss"
        row["errors"] = ["target_needs_review"]
        for key in (
            "dom_hit",
            "dom_hit_label",
            "source",
            "event_seq",
            "backfill_delta_ms",
            "manual_source",
            "manual_source_delta_ms",
        ):
            row.pop(key, None)
    _write_jsonl(dom_hits_path, dom_rows)

    for path in sorted(recording_dir.glob("*/actions.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            continue
        changed = False
        for action in payload:
            if not isinstance(action, dict) or action.get("action_id") not in action_ids:
                continue
            action["caption"] = captions_by_action[str(action["action_id"])]
            action["needs_review"] = True
            action.pop("dom_hit", None)
            action.pop("dom_hit_label", None)
            changed = True
        if changed:
            _write_json(path, payload)

    _update_recording_hit_count(recording_dir, dom_rows)
    _repair_summary(recording_dir)
    _append_jsonl(
        recording_dir / "needs_review_range_revisions.jsonl",
        {
            "applied_at": datetime.now(UTC).isoformat(),
            "selection": selection,
            "captions_by_action": captions_by_action,
            "action_ids": sorted(action_ids),
            "before_steps": before_steps,
        },
    )


def _mark_step_needs_review(step: JsonObject, *, caption: str) -> None:
    step["safe_caption"] = caption
    step["needs_review"] = True
    step.pop("dom_hit", None)
    step.pop("dom_hit_label", None)

    summary = step.get("action_summary")
    if not isinstance(summary, dict):
        summary = {
            "action_id": step.get("action_id"),
            "action_kind": step.get("action_kind"),
        }
        step["action_summary"] = summary
    current_target = summary.get("target")
    evidence_ids = (
        current_target.get("evidence_keyframe_ids", [])
        if isinstance(current_target, dict)
        else []
    )
    summary["target"] = {
        "status": "low_confidence",
        "display_label": "target needs review",
        "semantic_kind": "unknown",
        "confidence": 0.22,
        "confidence_band": "low",
        "source_badges": ["coordinate_fallback"],
        "needs_review": True,
        "evidence_keyframe_ids": evidence_ids if isinstance(evidence_ids, list) else [],
        "has_coordinates": isinstance(step.get("coordinates"), dict),
        "suppression_reason": "low_confidence",
    }
    step["readiness"] = {
        "state": "needs_review",
        "reasons": ["target needs review"],
        "review_item_count": 1,
        "blocked_item_count": 0,
        "missing_evidence": [],
    }


def _update_recording_hit_count(recording_dir: Path, dom_rows: list[JsonObject]) -> None:
    path = recording_dir / "recording.json"
    if not path.is_file():
        return
    payload = _read_json(path)
    payload["dom_hits_hit_count"] = sum(row.get("status") == "hit" for row in dom_rows)
    _write_json(path, payload)


def _project_root(recording_dir: Path) -> Path:
    for parent in recording_dir.parents:
        if parent.name in {"videos", "videos_revise_time"}:
            return parent.parent
    raise RuntimeError(f"recording is not under videos or videos_revise_time: {recording_dir}")


def _default_benchmark_output_root(recording_dir: Path, *, project_root: Path) -> Path:
    for parent in recording_dir.parents:
        if parent.name == "videos_revise_time":
            return project_root / "benchmark_revise_time"
        if parent.name == "videos":
            return project_root / "benchmark"
    raise RuntimeError(f"recording is not under videos or videos_revise_time: {recording_dir}")


def _read_json(path: Path) -> JsonObject:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def _read_jsonl(path: Path) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise RuntimeError(f"{path}:{line_number} is not a JSON object")
        rows.append(payload)
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[JsonObject]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _append_jsonl(path: Path, payload: JsonObject) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
