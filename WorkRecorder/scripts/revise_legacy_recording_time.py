#!/usr/bin/env python3
"""Copy a legacy recording export, align VM sidecars to media time, and benchmark it."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

from packages.active_capture.application.export.recording_export import _dom_hit_from_event
from scripts.repair_export_dom_hits import (
    _repair_actions,
    _repair_recording_meta,
    _repair_summary,
    _repair_trajectory,
)


JsonObject = dict[str, Any]
VM_SIDECAR_NAMES = ("vm_events.jsonl", "vm_clicks.jsonl")
OFFSET_BIN_MS = 50
OFFSET_CLUSTER_RADIUS_MS = 75
EXCLUSIVE_BACKFILL_WINDOW_SECONDS = 3.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "recording_parent",
        type=Path,
        help="Parent containing the +normal, +event_only, and +click_only exports.",
    )
    parser.add_argument(
        "--videos-output-root",
        type=Path,
        help="Destination root for revised raw exports (default: ../videos_revise_time).",
    )
    parser.add_argument(
        "--benchmark-output-root",
        type=Path,
        help="Destination root for benchmark output (default: ../benchmark_revise_time).",
    )
    parser.add_argument(
        "--pipeline-script",
        type=Path,
        help="Path to highlight_then_benchmark.py (default: ../code/highlight_then_benchmark.py).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing revised task and benchmark episodes.",
    )
    parser.add_argument(
        "--skip-benchmark",
        action="store_true",
        help="Only create the revised raw export.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source_parent = args.recording_parent.expanduser().resolve()
    if not source_parent.is_dir():
        raise SystemExit(f"recording parent is not a directory: {source_parent}")

    project_root = source_parent.parent.parent
    videos_output_root = (
        args.videos_output_root.expanduser().resolve()
        if args.videos_output_root
        else project_root / "videos_revise_time"
    )
    benchmark_output_root = (
        args.benchmark_output_root.expanduser().resolve()
        if args.benchmark_output_root
        else project_root / "benchmark_revise_time"
    )
    pipeline_script = (
        args.pipeline_script.expanduser().resolve()
        if args.pipeline_script
        else project_root / "code" / "highlight_then_benchmark.py"
    )

    recording_dirs = _recording_dirs(source_parent)
    direct_export = recording_dirs == [source_parent]
    destination_parent = videos_output_root / source_parent.name
    if destination_parent.exists():
        if not args.overwrite:
            raise SystemExit(
                f"destination already exists: {destination_parent}; pass --overwrite to replace it"
            )
        shutil.rmtree(destination_parent)
    destination_parent.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_parent, destination_parent)

    reports: list[JsonObject] = []
    for source_dir in recording_dirs:
        revised_dir = destination_parent if direct_export else destination_parent / source_dir.name
        report = revise_recording_dir(revised_dir)
        reports.append(report)
        _write_json(revised_dir / "time_revision.json", report)

    aggregate_report: JsonObject = {
        "source": str(source_parent),
        "destination": str(destination_parent),
        "method": "robust wall-clock click pairing",
        "recordings": reports,
    }
    _write_json(destination_parent / "time_revision_report.json", aggregate_report)

    if not args.skip_benchmark:
        if not pipeline_script.is_file():
            raise SystemExit(f"benchmark pipeline script not found: {pipeline_script}")
        command = [
            sys.executable,
            str(pipeline_script),
            str(destination_parent),
            "--output-root",
            str(benchmark_output_root),
        ]
        if args.overwrite:
            command.append("--overwrite")
        subprocess.run(command, check=True)

    print(json.dumps(aggregate_report, ensure_ascii=False, indent=2))
    if not args.skip_benchmark:
        print(f"benchmark output: {benchmark_output_root / source_parent.name}")
    return 0


def _recording_dirs(parent: Path) -> list[Path]:
    if (parent / "recording.json").is_file():
        return [parent]
    expected_suffixes = ("+normal", "+event_only", "+click_only")
    matches: list[Path] = []
    for suffix in expected_suffixes:
        candidates = [
            child
            for child in sorted(parent.iterdir())
            if child.is_dir()
            and child.name.endswith(suffix)
            and (child / "recording.json").is_file()
        ]
        if len(candidates) != 1:
            raise SystemExit(
                f"expected exactly one {suffix} recording under {parent}, found {len(candidates)}"
            )
        matches.append(candidates[0])
    return sorted(matches)


def revise_recording_dir(recording_dir: Path) -> JsonObject:
    trajectory_path = recording_dir / "trajectory.json"
    clicks_path = recording_dir / "vm_clicks.jsonl"
    if not trajectory_path.is_file() or not clicks_path.is_file():
        raise RuntimeError(f"missing trajectory.json or vm_clicks.jsonl in {recording_dir}")

    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    vm_clicks = _load_jsonl(clicks_path)
    offset_ms, calibration = infer_vm_media_offset_ms(trajectory, vm_clicks)

    revised_counts: dict[str, int] = {}
    before_after: dict[str, JsonObject] = {}
    for name in VM_SIDECAR_NAMES:
        path = recording_dir / name
        if not path.is_file():
            continue
        rows = _load_jsonl(path)
        first_before = _time_fields(rows[0]) if rows else None
        for row in rows:
            old_media_time_ms = row.get("media_time_ms")
            if not isinstance(old_media_time_ms, int):
                continue
            revised_ms = max(0, old_media_time_ms - offset_ms)
            row["media_time_ms"] = revised_ms
            row["media_time"] = format_media_time(revised_ms)
        _write_jsonl(path, rows)
        revised_counts[name] = len(rows)
        before_after[name] = {
            "first_before": first_before,
            "first_after": _time_fields(rows[0]) if rows else None,
        }

    report: JsonObject = {
        "recording_dir": recording_dir.name,
        "offset_subtracted_ms": offset_ms,
        "calibration": calibration,
        "revised_counts": revised_counts,
        "examples": before_after,
        "note": (
            "trajectory/keylog media times were already video-relative and were not changed; "
            "only legacy VM sidecar media times were revised"
        ),
    }
    if recording_dir.name.endswith("+click_only"):
        report["click_only_rebuild"] = rebuild_click_only_dom_hits(recording_dir)
    elif recording_dir.name.endswith("+event_only"):
        report["event_only_rebuild"] = rebuild_event_only_dom_hits(recording_dir)
    return report


def rebuild_click_only_dom_hits(recording_dir: Path) -> JsonObject:
    """Rebuild click-only action targets exclusively from vm_clicks.jsonl."""

    return _rebuild_exclusive_dom_hits(
        recording_dir,
        sidecar_name="vm_clicks.jsonl",
        fallback_mode="click_only",
        source="click_log_backfill",
        unresolved_kind="vm_click",
    )


def rebuild_event_only_dom_hits(recording_dir: Path) -> JsonObject:
    """Rebuild event-only action targets exclusively from vm_events.jsonl."""

    return _rebuild_exclusive_dom_hits(
        recording_dir,
        sidecar_name="vm_events.jsonl",
        fallback_mode="event_only",
        source="event_log_backfill",
        unresolved_kind="vm_event",
    )


def _rebuild_exclusive_dom_hits(
    recording_dir: Path,
    *,
    sidecar_name: str,
    fallback_mode: str,
    source: str,
    unresolved_kind: str,
) -> JsonObject:
    trajectory_path = recording_dir / "trajectory.json"
    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    steps = trajectory.get("steps")
    if not isinstance(steps, list):
        raise RuntimeError(f"trajectory.json has no steps array: {trajectory_path}")

    pointer_steps = [
        step
        for step in steps
        if isinstance(step, dict)
        and step.get("kind") == "action"
        and step.get("action_kind") in {"click", "drag"}
        and isinstance(step.get("action_id"), str)
    ]
    sidecar_rows = _load_jsonl(recording_dir / sidecar_name)
    specific_records = [
        row
        for row in sidecar_rows
        if isinstance(row.get("ts"), int | float) and _dom_hit_from_event(row) is not None
    ]

    used_record_indexes: set[int] = set()
    dom_by_action: dict[str, JsonObject] = {}
    rows: list[JsonObject] = []
    for step in sorted(pointer_steps, key=lambda item: str(item.get("occurred_at") or "")):
        action_id = str(step["action_id"])
        action_ts = _parse_wall_time_s(step.get("occurred_at"))
        best: tuple[float, int, JsonObject] | None = None
        if action_ts is not None:
            for index, record in enumerate(specific_records):
                if index in used_record_indexes:
                    continue
                delta = abs(float(record["ts"]) - action_ts)
                if delta > EXCLUSIVE_BACKFILL_WINDOW_SECONDS:
                    continue
                if best is None or delta < best[0]:
                    best = (delta, index, record)

        row: JsonObject = {
            "action_id": action_id,
            "action_kind": step.get("action_kind"),
            "status": "miss",
            "sequence_index": step.get("sequence_index"),
            "occurred_at": step.get("occurred_at"),
            "media_time_ms": step.get("media_time_ms"),
        }
        if best is None or action_ts is None:
            row["errors"] = [f"no_{unresolved_kind}_match"]
            rows.append(row)
            continue

        _, record_index, record = best
        used_record_indexes.add(record_index)
        dom_hit = _dom_hit_from_event(record)
        if dom_hit is None:
            row["errors"] = [f"{unresolved_kind}_has_no_target"]
            rows.append(row)
            continue
        dom_by_action[action_id] = dom_hit
        row.update(
            {
                "status": "hit",
                "dom_hit": dom_hit,
                "dom_hit_label": _plain_dom_hit_label(dom_hit),
                "source": source,
                "backfill_delta_ms": round((float(record["ts"]) - action_ts) * 1000, 1),
            }
        )
        if source == "event_log_backfill" and record.get("seq") is not None:
            row["event_seq"] = record["seq"]
        rows.append(row)

    _write_jsonl(recording_dir / "dom_hits.jsonl", rows)
    _clear_existing_pointer_targets(recording_dir, unresolved_kind=unresolved_kind)
    action_context = _repair_actions(recording_dir, dom_by_action)
    _repair_trajectory(recording_dir, dom_by_action, action_context)
    _repair_recording_meta(recording_dir, dom_by_action)
    _set_exact_dom_hit_counts(
        recording_dir,
        total=len(rows),
        hits=len(dom_by_action),
        fallback_mode=fallback_mode,
    )
    _repair_summary(recording_dir)
    return {
        "target_source": sidecar_name,
        "pointer_action_count": len(pointer_steps),
        "hit_count": len(dom_by_action),
        "miss_count": len(pointer_steps) - len(dom_by_action),
        "source_counts": {source: len(dom_by_action)},
    }


def _clear_existing_pointer_targets(recording_dir: Path, *, unresolved_kind: str) -> None:
    trajectory_path = recording_dir / "trajectory.json"
    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    steps = trajectory.get("steps") if isinstance(trajectory, dict) else None
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict) or step.get("action_kind") not in {"click", "drag"}:
                continue
            step.pop("dom_hit", None)
            step.pop("dom_hit_label", None)
            step["safe_caption"] = "Drag" if step.get("action_kind") == "drag" else "Click"
            step["needs_review"] = True
            step["readiness"] = {
                "state": "needs_review",
                "reasons": [f"{unresolved_kind}_target_unresolved"],
                "review_item_count": 1,
                "blocked_item_count": 0,
                "missing_evidence": [f"{unresolved_kind}_target"],
            }
            summary = step.get("action_summary")
            if not isinstance(summary, dict):
                continue
            target = summary.get("target")
            unresolved = dict(target) if isinstance(target, dict) else {}
            badges = unresolved.get("source_badges")
            unresolved.update(
                {
                    "status": "unresolved",
                    "display_label": None,
                    "semantic_kind": "unknown",
                    "confidence": 0.0,
                    "confidence_band": "low",
                    "source_badges": (
                        [badge for badge in badges if isinstance(badge, str) and badge != "web_dom"]
                        if isinstance(badges, list)
                        else []
                    ),
                    "needs_review": True,
                    "suppression_reason": f"{unresolved_kind}_target_unresolved",
                }
            )
            summary["target"] = unresolved
        _write_json(trajectory_path, trajectory)

    for actions_path in sorted(recording_dir.glob("*/actions.json")):
        payload = json.loads(actions_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            continue
        for action in payload:
            if not isinstance(action, dict) or action.get("kind") not in {"click", "drag"}:
                continue
            action.pop("dom_hit", None)
            action.pop("dom_hit_label", None)
            action["caption"] = "Drag" if action.get("kind") == "drag" else "Click"
        _write_json(actions_path, payload)


def _set_exact_dom_hit_counts(
    recording_dir: Path,
    *,
    total: int,
    hits: int,
    fallback_mode: str,
) -> None:
    path = recording_dir / "recording.json"
    if not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return
    payload["dom_hits_count"] = total
    payload["dom_hits_hit_count"] = hits
    payload["fallback_mode"] = fallback_mode
    _write_json(path, payload)


def _plain_dom_hit_label(dom_hit: JsonObject) -> str:
    role = dom_hit.get("role")
    tag = dom_hit.get("tag")
    label = next(
        (
            value
            for key in ("aria", "name", "text", "href", "id")
            if isinstance((value := dom_hit.get(key)), str) and value.strip()
        ),
        None,
    )
    prefix = role if isinstance(role, str) and role.strip() else tag
    if isinstance(prefix, str) and prefix.strip() and label:
        return f"{prefix.lower() if prefix == tag else prefix} · {' '.join(label.split())}"
    if label:
        return " ".join(label.split())
    if isinstance(prefix, str) and prefix.strip():
        return prefix.lower() if prefix == tag else prefix
    return "DOM element"


def infer_vm_media_offset_ms(
    trajectory: JsonObject,
    vm_clicks: list[JsonObject],
) -> tuple[int, JsonObject]:
    steps = trajectory.get("steps")
    if not isinstance(steps, list):
        raise RuntimeError("trajectory.json has no steps array")
    timestamped_clicks = [
        row
        for row in vm_clicks
        if isinstance(row.get("ts"), int | float) and isinstance(row.get("media_time_ms"), int)
    ]
    if not timestamped_clicks:
        raise RuntimeError("vm_clicks.jsonl has no timestamped clicks")

    candidates: list[int] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("kind") != "action" or step.get("action_kind") != "click":
            continue
        action_media_ms = step.get("media_time_ms")
        wall_time_s = _parse_wall_time_s(step.get("occurred_at"))
        if not isinstance(action_media_ms, int) or wall_time_s is None:
            continue
        nearest = min(timestamped_clicks, key=lambda row: abs(float(row["ts"]) - wall_time_s))
        if abs(float(nearest["ts"]) - wall_time_s) > 1.25:
            continue
        candidates.append(int(nearest["media_time_ms"]) - action_media_ms)

    if len(candidates) < 3:
        raise RuntimeError(f"not enough click pairs to infer offset (found {len(candidates)})")

    bins = Counter(_round_to_bin(value, OFFSET_BIN_MS) for value in candidates)
    dominant_bin, _ = bins.most_common(1)[0]
    cluster = [
        value for value in candidates if abs(value - dominant_bin) <= OFFSET_CLUSTER_RADIUS_MS
    ]
    if len(cluster) < 3 or len(cluster) * 2 < len(candidates):
        raise RuntimeError(
            "click timing did not form a stable dominant offset "
            f"(candidates={len(candidates)}, dominant={len(cluster)})"
        )
    offset_ms = int(round(median(cluster)))
    if offset_ms <= 0:
        raise RuntimeError(f"inferred non-positive VM offset: {offset_ms} ms")
    return offset_ms, {
        "candidate_pair_count": len(candidates),
        "dominant_pair_count": len(cluster),
        "dominant_bin_ms": dominant_bin,
        "cluster_min_ms": min(cluster),
        "cluster_max_ms": max(cluster),
        "cluster_median_ms": offset_ms,
    }


def _parse_wall_time_s(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _round_to_bin(value: int, bin_size: int) -> int:
    return int(round(value / bin_size) * bin_size)


def format_media_time(media_time_ms: int) -> str:
    total_seconds, milliseconds = divmod(media_time_ms, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def _time_fields(row: JsonObject) -> JsonObject:
    return {
        "media_time": row.get("media_time"),
        "media_time_ms": row.get("media_time_ms"),
    }


def _load_jsonl(path: Path) -> list[JsonObject]:
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
    content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
