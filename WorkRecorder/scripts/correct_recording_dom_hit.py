#!/usr/bin/env python3
"""Apply one reviewed DOM-target correction and rebuild its benchmark artifacts."""

from __future__ import annotations

import argparse
import copy
import json
import re
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from packages.active_capture.application.export.recording_export import (
    _a11y_hit_from_mapping,
    _dom_hit_from_event,
    _dom_hit_from_mapping,
)
from scripts.repair_export_dom_hits import (
    _dom_hit_label,
    _repair_actions,
    _repair_recording_meta,
    _repair_summary,
    _repair_trajectory,
)


JsonObject = dict[str, Any]
SIDECARS = {
    "vm_clicks": "vm_clicks.jsonl",
    "vm_events": "vm_events.jsonl",
}
EXPORT_MODES = ("normal", "event_only", "click_only")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "recording_dir",
        type=Path,
        help="Recording or three-mode task directory under videos_revise_time.",
    )
    parser.add_argument(
        "--mode",
        choices=EXPORT_MODES,
        help="Select and rebuild only this mode from a three-mode task directory.",
    )
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument("--action-id", help="Exact action_id to correct.")
    selector.add_argument("--media-time-ms", type=int, help="Exact action media_time_ms to correct.")
    parser.add_argument(
        "--time-pair",
        type=parse_time_pair,
        action="append",
        metavar="ACTION_MS:SOURCE_MS",
        help="Correct one action from one sidecar time; repeat to batch multiple corrections.",
    )
    parser.add_argument(
        "--from-sidecar",
        choices=tuple(SIDECARS),
        help="Use the nearest targetable vm_clicks/vm_events record as the reviewed target.",
    )
    parser.add_argument(
        "--source-media-time-ms",
        type=int,
        help=(
            "Independently select the vm_clicks/vm_events record near this media time. "
            "Without this option, the action media time is used."
        ),
    )
    parser.add_argument(
        "--sidecar-target",
        choices=("auto", "dom", "a11y", "raw"),
        default="auto",
        help=(
            "Choose which target payload to use inside the selected sidecar row. "
            "Use raw to accept a specifically selected generic vm_events row (default: auto)."
        ),
    )
    parser.add_argument("--role", help="Explicit corrected role, e.g. 'push button'.")
    parser.add_argument("--name", help="Explicit corrected accessible name.")
    parser.add_argument(
        "--bbox",
        type=int,
        nargs=4,
        metavar=("X", "Y", "WIDTH", "HEIGHT"),
        help="Optional corrected VM-space bounding box.",
    )
    parser.add_argument(
        "--max-delta-ms",
        type=int,
        default=500,
        help="Maximum media-time distance when selecting a sidecar record (default: 500).",
    )
    parser.add_argument(
        "--pipeline-input",
        type=Path,
        help="Input passed to highlight_then_benchmark.py (default: recording_dir).",
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
    parser.add_argument("--run-id", help="Benchmark run directory name, e.g. fine_normal.")
    parser.add_argument("--skip-rebuild", action="store_true", help="Patch revised raw data without rebuilding.")
    parser.add_argument("--dry-run", action="store_true", help="Show the correction and rebuild command only.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    has_single_selector = args.action_id is not None or args.media_time_ms is not None
    has_time_pairs = bool(args.time_pair)
    if has_single_selector == has_time_pairs:
        raise SystemExit(
            "provide exactly one of --action-id/--media-time-ms or one or more --time-pair values"
        )
    if has_time_pairs and args.source_media_time_ms is not None:
        raise SystemExit("--source-media-time-ms cannot be combined with --time-pair")
    if has_time_pairs and args.from_sidecar is None:
        raise SystemExit("--time-pair requires --from-sidecar")
    input_path = args.recording_dir.expanduser().resolve()
    recording_dir, selected_mode, task_name = resolve_recording_dir(
        input_path,
        mode=args.mode,
    )
    if selected_mode is not None and args.pipeline_input is not None:
        raise SystemExit("--pipeline-input is unnecessary and cannot be combined with a selected mode")
    if selected_mode is not None and args.run_id not in (None, selected_mode):
        raise SystemExit(
            f"--run-id {args.run_id!r} conflicts with mode {selected_mode!r}; "
            "omit --run-id because the mode supplies it"
        )
    trajectory_path = recording_dir / "trajectory.json"
    if args.from_sidecar is None and not any((args.role, args.name, args.bbox)):
        raise SystemExit("provide --from-sidecar and/or an explicit --role/--name/--bbox")
    if args.source_media_time_ms is not None and args.from_sidecar is None:
        raise SystemExit("--source-media-time-ms requires --from-sidecar")
    if args.sidecar_target != "auto" and args.from_sidecar is None:
        raise SystemExit("--sidecar-target requires --from-sidecar")
    if args.sidecar_target == "dom" and args.from_sidecar != "vm_clicks":
        raise SystemExit("--sidecar-target dom is only supported with --from-sidecar vm_clicks")

    trajectory = _read_json(trajectory_path)
    selectors = (
        [(args.action_id, args.media_time_ms, args.source_media_time_ms)]
        if has_single_selector
        else [(None, action_ms, source_ms) for action_ms, source_ms in args.time_pair]
    )
    corrections: list[JsonObject] = []
    for action_id, media_time_ms, source_media_time_ms in selectors:
        selector_label = (
            f"action_id={action_id}"
            if action_id is not None
            else f"time_pair={media_time_ms}:{source_media_time_ms}"
        )
        try:
            correction = prepare_correction(
                recording_dir,
                trajectory=trajectory,
                action_id=action_id,
                media_time_ms=media_time_ms,
                source_media_time_ms=source_media_time_ms,
                from_sidecar=args.from_sidecar,
                sidecar_target=args.sidecar_target,
                max_delta_ms=args.max_delta_ms,
                role=args.role,
                name=args.name,
                bbox=args.bbox,
            )
        except RuntimeError as error:
            raise RuntimeError(f"failed to prepare {selector_label}: {error}") from error
        corrections.append(correction)
    action_ids = [str(item["action_id"]) for item in corrections]
    if len(set(action_ids)) != len(action_ids):
        raise SystemExit("multiple selectors resolved to the same action")
    preview: JsonObject = {
        "recording_dir": str(recording_dir),
        "mode": selected_mode,
        "correction_count": len(corrections),
        "corrections": [{key: value for key, value in item.items() if not key.startswith("_")} for item in corrections],
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
        else project_root / "benchmark_revise_time"
    )
    if selected_mode is not None:
        commands = mode_rebuild_commands(
            pipeline_script=pipeline_script,
            recording_dir=recording_dir,
            benchmark_output_root=benchmark_output_root,
            task_name=task_name,
            mode=selected_mode,
        )
    else:
        pipeline_input = (
            args.pipeline_input.expanduser().resolve()
            if args.pipeline_input
            else recording_dir
        )
        commands = [
            rebuild_command(
                pipeline_script=pipeline_script,
                pipeline_input=pipeline_input,
                benchmark_output_root=benchmark_output_root,
                run_id=args.run_id,
            )
        ]
    if args.dry_run:
        if not args.skip_rebuild:
            for command in commands:
                print("$ " + shlex.join(command), flush=True)
        return 0

    for correction in corrections:
        apply_correction(
            recording_dir,
            action_id=str(correction["action_id"]),
            dom_hit=correction["_dom_hit"],
            source_sidecar=args.from_sidecar,
            source_record=correction["_selected_record"],
            source_delta_ms=correction["source_delta_from_action_ms"],
        )
    if not args.skip_rebuild:
        if not pipeline_script.is_file():
            raise SystemExit(f"pipeline script not found: {pipeline_script}")
        for command in commands:
            subprocess.run(command, check=True)
    return 0


def parse_time_pair(value: str) -> tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("expected ACTION_MS:SOURCE_MS")
    try:
        action_ms, source_ms = (int(part) for part in parts)
    except ValueError as error:
        raise argparse.ArgumentTypeError("both time-pair values must be integers") from error
    if action_ms < 0 or source_ms < 0:
        raise argparse.ArgumentTypeError("time-pair values must be non-negative")
    return action_ms, source_ms


def prepare_correction(
    recording_dir: Path,
    *,
    trajectory: JsonObject,
    action_id: str | None,
    media_time_ms: int | None,
    source_media_time_ms: int | None,
    from_sidecar: str | None,
    sidecar_target: str,
    max_delta_ms: int,
    role: str | None,
    name: str | None,
    bbox: list[int] | None,
) -> JsonObject:
    step = select_action_step(
        trajectory,
        action_id=action_id,
        media_time_ms=media_time_ms,
    )
    resolved_action_id = str(step["action_id"])
    action_media_time_ms = int(step["media_time_ms"])
    selected_record: JsonObject | None = None
    selected_match_delta_ms: int | None = None
    selected_action_delta_ms: int | None = None
    dom_hit: JsonObject = {}
    source_lookup_time_ms = source_media_time_ms if source_media_time_ms is not None else action_media_time_ms
    if from_sidecar is not None:
        sidecar_path = recording_dir / SIDECARS[from_sidecar]
        selected_record, selected_match_delta_ms, dom_hit = nearest_sidecar_target(
            sidecar_path,
            media_time_ms=source_lookup_time_ms,
            max_delta_ms=max_delta_ms,
            sidecar_target=sidecar_target,
        )
        selected_action_delta_ms = int(selected_record["media_time_ms"]) - action_media_time_ms
    if role is not None:
        dom_hit["role"] = role
    if name is not None:
        dom_hit["name"] = name
    if bbox is not None:
        dom_hit["bbox"] = list(bbox)
    if not dom_hit:
        raise RuntimeError(f"correction for action {resolved_action_id} did not produce a DOM target")
    existing_row = _find_dom_hit_row(recording_dir / "dom_hits.jsonl", resolved_action_id)
    return {
        "action_id": resolved_action_id,
        "media_time_ms": action_media_time_ms,
        "before": existing_row.get("dom_hit") if existing_row else step.get("dom_hit"),
        "after": dom_hit,
        "from_sidecar": from_sidecar,
        "sidecar_target": sidecar_target,
        "source_lookup_media_time_ms": source_lookup_time_ms,
        "matched_source_media_time_ms": selected_record.get("media_time_ms") if selected_record else None,
        "source_match_delta_ms": selected_match_delta_ms,
        "source_delta_from_action_ms": selected_action_delta_ms,
        "_dom_hit": dom_hit,
        "_selected_record": selected_record,
    }


def resolve_recording_dir(
    input_path: Path,
    *,
    mode: str | None,
) -> tuple[Path, str | None, str]:
    if (input_path / "trajectory.json").is_file():
        inferred_mode = _mode_from_recording_name(input_path.name)
        if mode is not None and inferred_mode is not None and mode != inferred_mode:
            raise SystemExit(
                f"requested mode {mode!r} does not match recording {input_path.name!r}"
            )
        selected_mode = mode or inferred_mode
        task_name = input_path.parent.name if inferred_mode is not None else input_path.name
        return input_path, selected_mode, task_name

    if mode is None:
        raise SystemExit(
            f"trajectory.json not found under {input_path}; "
            f"if this is a three-mode task directory, add --mode {'|'.join(EXPORT_MODES)}"
        )
    candidates = sorted(
        child
        for child in input_path.iterdir()
        if child.is_dir()
        and child.name.endswith(f"+{mode}")
        and (child / "trajectory.json").is_file()
    ) if input_path.is_dir() else []
    if len(candidates) != 1:
        raise SystemExit(
            f"expected exactly one +{mode} recording under {input_path}, found {len(candidates)}"
        )
    return candidates[0], mode, input_path.name


def select_action_step(
    trajectory: JsonObject,
    *,
    action_id: str | None,
    media_time_ms: int | None,
) -> JsonObject:
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
        and (action_id is None or step["action_id"] == action_id)
        and (media_time_ms is None or step["media_time_ms"] == media_time_ms)
    ]
    if len(matches) != 1:
        selector = f"action_id={action_id!r}" if action_id is not None else f"media_time_ms={media_time_ms}"
        raise RuntimeError(f"expected exactly one action for {selector}, found {len(matches)}")
    return matches[0]


def nearest_sidecar_target(
    path: Path,
    *,
    media_time_ms: int,
    max_delta_ms: int,
    sidecar_target: str = "auto",
) -> tuple[JsonObject, int, JsonObject]:
    if not path.is_file():
        raise RuntimeError(f"sidecar not found: {path}")
    candidates: list[tuple[int, JsonObject, JsonObject]] = []
    for row in _read_jsonl(path):
        row_time = row.get("media_time_ms")
        if not isinstance(row_time, int):
            continue
        dom_hit = _sidecar_target_from_row(row, sidecar_target=sidecar_target)
        if dom_hit is None:
            continue
        candidates.append((abs(row_time - media_time_ms), row, dom_hit))
    if not candidates:
        raise RuntimeError(f"no targetable records in {path}")
    delta_ms, row, dom_hit = min(candidates, key=lambda item: item[0])
    if delta_ms > max_delta_ms:
        raise RuntimeError(
            f"nearest target in {path.name} is {delta_ms} ms away, above limit {max_delta_ms} ms"
        )
    return row, int(row["media_time_ms"]) - media_time_ms, dom_hit


def _sidecar_target_from_row(row: JsonObject, *, sidecar_target: str) -> JsonObject | None:
    if sidecar_target == "auto":
        return _dom_hit_from_event(row)
    if sidecar_target == "dom":
        dom = row.get("dom")
        return _dom_hit_from_mapping(dom) if isinstance(dom, dict) else None
    if sidecar_target == "a11y":
        a11y = row.get("a11y")
        if isinstance(a11y, dict):
            return _a11y_hit_from_mapping(a11y)
        return _a11y_hit_from_mapping(row)
    if sidecar_target == "raw":
        return _dom_hit_from_mapping(row)
    raise ValueError(f"unsupported sidecar target: {sidecar_target}")


def apply_correction(
    recording_dir: Path,
    *,
    action_id: str,
    dom_hit: JsonObject,
    source_sidecar: str | None,
    source_record: JsonObject | None,
    source_delta_ms: int | None,
) -> None:
    dom_hits_path = recording_dir / "dom_hits.jsonl"
    rows = _read_jsonl(dom_hits_path) if dom_hits_path.is_file() else []
    before_row: JsonObject | None = None
    matched = False
    corrected_source = {
        "vm_clicks": "click_log_backfill",
        "vm_events": "event_log_backfill",
    }.get(source_sidecar)
    for row in rows:
        if row.get("action_id") != action_id:
            continue
        if matched:
            raise RuntimeError(f"duplicate dom_hits rows for action {action_id}")
        matched = True
        before_row = copy.deepcopy(row)
        row.update(
            {
                "status": "hit",
                "dom_hit": copy.deepcopy(dom_hit),
                "dom_hit_label": _dom_hit_label(dom_hit),
            }
        )
        for key in (
            "errors",
            "event_seq",
            "backfill_delta_ms",
            "source",
            "manual_source",
            "manual_source_delta_ms",
        ):
            row.pop(key, None)
        if corrected_source is not None:
            row["source"] = corrected_source
        if source_delta_ms is not None:
            row["backfill_delta_ms"] = source_delta_ms
    if not matched:
        trajectory = _read_json(recording_dir / "trajectory.json")
        step = select_action_step(trajectory, action_id=action_id, media_time_ms=None)
        rows.append(
            {
                "action_id": action_id,
                "action_kind": step.get("action_kind"),
                "status": "hit",
                "sequence_index": step.get("sequence_index"),
                "occurred_at": step.get("occurred_at"),
                "media_time_ms": step.get("media_time_ms"),
                "dom_hit": copy.deepcopy(dom_hit),
                "dom_hit_label": _dom_hit_label(dom_hit),
                **({"source": corrected_source} if corrected_source is not None else {}),
                **(
                    {"backfill_delta_ms": source_delta_ms}
                    if source_delta_ms is not None
                    else {}
                ),
            }
        )
    _write_jsonl(dom_hits_path, rows)

    dom_by_action = {action_id: dom_hit}
    action_context = _repair_actions(recording_dir, dom_by_action)
    _repair_trajectory(recording_dir, dom_by_action, action_context)
    all_dom_by_action = {
        str(row["action_id"]): row["dom_hit"]
        for row in rows
        if row.get("status") == "hit"
        and isinstance(row.get("action_id"), str)
        and isinstance(row.get("dom_hit"), dict)
    }
    _repair_recording_meta(recording_dir, all_dom_by_action)
    _repair_summary(recording_dir)
    _append_audit_record(
        recording_dir / "manual_dom_corrections.jsonl",
        {
            "applied_at": datetime.now(UTC).isoformat(),
            "action_id": action_id,
            "before": before_row,
            "after": {
                "dom_hit": dom_hit,
                "dom_hit_label": _dom_hit_label(dom_hit),
            },
            "source_sidecar": source_sidecar,
            "source_delta_ms": source_delta_ms,
            "source_record": source_record,
        },
    )


def rebuild_command(
    *,
    pipeline_script: Path,
    pipeline_input: Path,
    benchmark_output_root: Path,
    run_id: str | None,
) -> list[str]:
    command = [
        sys.executable,
        str(pipeline_script),
        str(pipeline_input),
        "--output-root",
        str(benchmark_output_root),
    ]
    if run_id:
        command.extend(("--run-id", run_id))
    command.append("--overwrite")
    return command


def mode_rebuild_commands(
    *,
    pipeline_script: Path,
    recording_dir: Path,
    benchmark_output_root: Path,
    task_name: str,
    mode: str,
) -> list[list[str]]:
    code_dir = pipeline_script.parent
    highlighter_script = code_dir / "keylog_highlight_frames.py"
    benchmark_script = code_dir / "raw_to_benchmark.py"
    return [
        [
            sys.executable,
            str(highlighter_script),
            str(recording_dir),
        ],
        [
            sys.executable,
            str(benchmark_script),
            str(recording_dir),
            "--output-root",
            str(benchmark_output_root / task_name),
            "--run-id",
            mode,
            "--condition",
            infer_condition(task_name),
            "--overwrite",
        ],
    ]


def infer_condition(task_name: str) -> str:
    base = task_name.split("+", 1)[0]
    match = re.match(r"^(?P<condition>.+?)-f\d+$", base, flags=re.IGNORECASE)
    return match.group("condition") if match else base


def _mode_from_recording_name(name: str) -> str | None:
    return next(
        (mode for mode in EXPORT_MODES if name.endswith(f"+{mode}")),
        None,
    )


def _find_dom_hit_row(path: Path, action_id: str) -> JsonObject | None:
    if not path.is_file():
        return None
    matches = [row for row in _read_jsonl(path) if row.get("action_id") == action_id]
    if len(matches) > 1:
        raise RuntimeError(f"duplicate dom_hits rows for action {action_id}")
    return matches[0] if matches else None


def _project_root(recording_dir: Path) -> Path:
    for parent in recording_dir.parents:
        if parent.name in {"videos_revise_time", "videos"}:
            return parent.parent
    raise RuntimeError(
        f"recording is not under videos_revise_time or videos: {recording_dir}"
    )


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


def _write_jsonl(path: Path, rows: list[JsonObject]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _append_audit_record(path: Path, payload: JsonObject) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
