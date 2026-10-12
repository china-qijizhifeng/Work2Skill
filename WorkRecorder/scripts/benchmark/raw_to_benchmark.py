#!/usr/bin/env python3
"""Convert WorkRecorder raw recording exports into lean MyPCBench benchmark episodes.

The converter keeps the raw export untouched and materializes a normalized
benchmark package with:

  - task metadata copied from MyPCBench without grading rubrics
  - a canonical normalized action trace plus raw keylog
  - all highlighted image frames copied from the raw export
  - a compact episode manifest that points at the normalized artifacts

Example:
  python raw_to_benchmark.py ../videos/cua_only-f003 --condition cua_only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_TASKS_FILE = None
CONVERTER_VERSION = "0.2.4"
CLICK_LOG_RE = re.compile(r"^(?P<button>[LRM])Click at \(")
BUTTON_NAMES = {
    "L": "Left",
    "R": "Right",
    "M": "Middle",
}
ACTION_BUTTON_MATCH_WINDOW_MS = 750


JsonObject = dict[str, Any]


@dataclass(frozen=True)
class KeyframeRef:
    keyframe_id: str
    folder: str
    media_time_ms: int
    role: str | None
    screenshot: Path | None
    evidence_files: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceCandidate:
    evidence_id: str
    label: str
    source_path: Path
    filename: str
    source_kind: str
    media_time_ms: int | None = None
    keyframe_id: str | None = None
    action_id: str | None = None
    reason: str | None = None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    raw_dirs = [path.expanduser().resolve() for path in args.raw_dirs]
    output_root = default_output_root(raw_dirs[0]) if args.output_root is None else args.output_root.expanduser().resolve()
    run_id = args.run_id or build_run_id(args, raw_dirs)
    run_dir = output_root / run_id

    if run_dir.exists() and not args.overwrite:
        raise SystemExit(f"output run already exists: {run_dir}\nUse --overwrite or choose --run-id.")
    if run_dir.exists() and args.overwrite:
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    task_index = load_task_index(args.tasks_file)
    episodes: list[JsonObject] = []

    for raw_dir in raw_dirs:
        if not raw_dir.is_dir():
            raise SystemExit(f"raw export directory does not exist: {raw_dir}")
        episode = convert_one_raw_export(
            raw_dir=raw_dir,
            run_dir=run_dir,
            args=args,
            task_index=task_index,
        )
        episodes.append(episode)

    manifest = {
        "converter": {
            "name": "raw_to_benchmark.py",
            "version": CONVERTER_VERSION,
        },
        "generated_at": utc_now(),
        "run_id": run_id,
        "source_type": "human_recording",
        "condition": args.condition,
        "tasks_file": str(args.tasks_file.expanduser().resolve()) if args.tasks_file else None,
        "file_mode": args.file_mode,
        "episode_count": len(episodes),
        "episodes": episodes,
    }
    write_json(run_dir / "run_manifest.json", manifest)
    print(f"Wrote benchmark run: {run_dir}")
    for episode in episodes:
        print(f"  - {episode['task_id']}: {episode['episode_dir']}")
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert WorkRecorder raw exports to normalized MyPCBench benchmark episodes."
    )
    parser.add_argument(
        "raw_dirs",
        type=Path,
        nargs="+",
        help="One or more raw recording export directories, e.g. videos/cua_only-f003.",
    )
    parser.add_argument(
        "--tasks-file",
        type=Path,
        default=DEFAULT_TASKS_FILE,
        help=f"MyPCBench task file with grading. Default: {DEFAULT_TASKS_FILE}",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Output root. Default: <MyPCBench_videos>/benchmark next to videos/.",
    )
    parser.add_argument("--run-id", help="Benchmark run id. Default: timestamp + condition/task id.")
    parser.add_argument("--task-id", help="Force one task id for all raw dirs. Otherwise inferred per raw dir.")
    parser.add_argument("--condition", default=None, help="Comparison condition, e.g. cua_only or cuabash.")
    parser.add_argument(
        "--file-mode",
        choices=("copy", "hardlink", "symlink"),
        default="copy",
        help="How media/evidence files are materialized. copy is portable; hardlink saves space.",
    )
    parser.add_argument(
        "--include-all-keyframes",
        action="store_true",
        help="Also materialize every keyframe screenshot under evidence/all_keyframes/.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output run directory.")
    return parser.parse_args(argv)


def default_output_root(raw_dir: Path) -> Path:
    try:
        videos_dir = raw_dir.parents[0]
        if videos_dir.name == "videos":
            return videos_dir.parent / "benchmark"
    except IndexError:
        pass
    return raw_dir.parent / "benchmark"


def build_run_id(args: argparse.Namespace, raw_dirs: list[Path]) -> str:
    condition = args.condition or infer_task_id(raw_dirs[0], read_json(raw_dirs[0] / "recording.json", default={}))
    parts = [
        datetime.now().strftime("%Y%m%dT%H%M%S"),
        safe_slug(condition),
    ]
    return "_".join(part for part in parts if part)


def convert_one_raw_export(
    raw_dir: Path,
    run_dir: Path,
    args: argparse.Namespace,
    task_index: dict[str, JsonObject],
) -> JsonObject:
    recording = read_json(raw_dir / "recording.json", default={})
    trajectory = read_json(raw_dir / "trajectory.json", default={})
    task_id = args.task_id or infer_task_id(raw_dir, recording)
    task = task_index.get(task_id) or build_task_stub(task_id)
    episode_dir = run_dir / "episodes" / safe_slug(task_id)
    make_episode_dirs(episode_dir)

    keyframes = load_keyframes(raw_dir, recording)
    action_steps = extract_action_steps(trajectory)
    click_buttons = load_keylog_click_buttons(raw_dir / "keylog.jsonl")
    normalized_actions = list(normalize_actions(action_steps, task, click_buttons))
    evidence_ref = materialize_evidence(
        episode_dir=episode_dir,
        raw_dir=raw_dir,
        file_mode=args.file_mode,
        overwrite=True,
    )

    if args.include_all_keyframes:
        materialize_all_keyframes(
            keyframes=keyframes,
            episode_dir=episode_dir,
            raw_dir=raw_dir,
            file_mode=args.file_mode,
        )

    video_ref = materialize_video(raw_dir, episode_dir, args.file_mode)
    keylog_ref = materialize_keylog(raw_dir, episode_dir, args.file_mode)
    summary_ref = materialize_summary(raw_dir, episode_dir, args.file_mode)
    write_json(episode_dir / "task.json", public_task_payload(task))
    write_jsonl(episode_dir / "trace" / "actions.jsonl", normalized_actions)

    episode_summary = build_episode_summary(
        raw_dir=raw_dir,
        task_id=task_id,
        recording=recording,
        trajectory=trajectory,
        keyframes=keyframes,
        evidence_ref=evidence_ref,
        video_ref=video_ref,
        keylog_ref=keylog_ref,
        summary_ref=summary_ref,
        normalized_actions=normalized_actions,
    )
    write_json(episode_dir / "episode.json", episode_summary)

    return {
        "task_id": task_id,
        "raw_dir": str(raw_dir),
        "episode_dir": str(episode_dir),
        "session_id": recording.get("session_id"),
        "duration_ms": recording.get("duration_ms"),
        "action_count": recording.get("action_count") or len(action_steps),
        "keyframe_count": recording.get("keyframe_count") or len(keyframes),
    }


def make_episode_dirs(episode_dir: Path) -> None:
    for child in ("trace", "evidence"):
        (episode_dir / child).mkdir(parents=True, exist_ok=True)


def load_task_index(path: Path | None) -> dict[str, JsonObject]:
    if path is None:
        return {}
    path = path.expanduser()
    if not path.exists():
        print(f"warning: task file not found: {path}", file=sys.stderr)
        return {}
    payload = read_json(path)
    tasks: list[JsonObject]
    if isinstance(payload, list):
        tasks = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("tasks"), list):
        tasks = [item for item in payload["tasks"] if isinstance(item, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("id"), str):
        tasks = [payload]
    else:
        raise SystemExit(f"unsupported task file shape: {path}")
    return {str(task["id"]): task for task in tasks if isinstance(task.get("id"), str)}


def infer_task_id(raw_dir: Path, recording: JsonObject) -> str:
    for key in ("task_id", "user_note"):
        value = recording.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return raw_dir.name


def build_task_stub(task_id: str) -> JsonObject:
    return {
        "id": task_id,
        "grading": {"type": "unknown", "rubrics": []},
        "_warning": "Task id was inferred, but no matching task definition was found.",
    }


def public_task_payload(task: JsonObject) -> JsonObject:
    return {key: value for key, value in task.items() if key != "grading"}


def load_keyframes(raw_dir: Path, recording: JsonObject) -> list[KeyframeRef]:
    raw_keyframes = recording.get("keyframes")
    if not isinstance(raw_keyframes, list):
        raw_keyframes = []

    keyframes: list[KeyframeRef] = []
    for item in raw_keyframes:
        if not isinstance(item, dict):
            continue
        folder = item.get("folder")
        keyframe_id = item.get("keyframe_id")
        if not isinstance(folder, str) or not isinstance(keyframe_id, str):
            continue
        media_time_ms = int_or_none(item.get("media_time_ms")) or 0
        screenshot = raw_dir / folder / "screenshot.png"
        evidence_files = tuple(str(value) for value in item.get("evidence_files", []) if isinstance(value, str))
        keyframes.append(
            KeyframeRef(
                keyframe_id=keyframe_id,
                folder=folder,
                media_time_ms=media_time_ms,
                role=item.get("role") if isinstance(item.get("role"), str) else None,
                screenshot=screenshot if screenshot.exists() else None,
                evidence_files=evidence_files,
            )
        )
    return sorted(keyframes, key=lambda item: item.media_time_ms)


def extract_action_steps(trajectory: JsonObject) -> list[JsonObject]:
    steps = trajectory.get("steps")
    if not isinstance(steps, list):
        return []
    actions = [step for step in steps if isinstance(step, dict) and step.get("kind") == "action"]
    return sorted(actions, key=lambda item: int_or_none(item.get("media_time_ms")) or 0)


def select_evidence(
    raw_dir: Path,
    task: JsonObject,
    keyframes: list[KeyframeRef],
    action_steps: list[JsonObject],
) -> tuple[list[EvidenceCandidate], list[str]]:
    warnings: list[str] = []
    candidates: list[EvidenceCandidate] = []
    keyframe_by_id = {item.keyframe_id: item for item in keyframes}
    task_terms = extract_task_terms(task)
    board_terms = board_specific_terms(task_terms)

    open_board_action = first_action_matching(action_steps, board_terms)
    if open_board_action is None:
        open_board_action = first_action_matching(action_steps, task_terms)
    open_board_keyframe = result_keyframe_for_action(open_board_action, keyframe_by_id)
    if open_board_keyframe is not None and open_board_keyframe.screenshot is not None:
        candidates.append(
            highlighted_or_keyframe_candidate(
                raw_dir=raw_dir,
                action_step=open_board_action,
                evidence_id="open_board",
                label="Correct board opened",
                filename="00_open_board_highlight.png",
                keyframe=open_board_keyframe,
                reason="first action result mentioning a task/project term",
            )
        )
    elif keyframes:
        warnings.append("Could not identify an open-board keyframe from task terms.")

    first_drag = next((step for step in action_steps if step.get("action_kind") == "drag"), None)
    before_drag_keyframe = keyframe_before_action(first_drag, keyframes)
    drag_result_keyframe = result_keyframe_for_action(first_drag, keyframe_by_id)

    if before_drag_keyframe is not None and before_drag_keyframe.screenshot is not None:
        before_drag_action = action_with_highlight_before(raw_dir, first_drag, action_steps)
        candidates.append(
            highlighted_or_keyframe_candidate(
                raw_dir=raw_dir,
                action_step=before_drag_action,
                evidence_id="todo_card_before_drag",
                label="Todo card before drag",
                filename="01_todo_card_before_drag_highlight.png",
                keyframe=before_drag_keyframe,
                reason="last keyframe before the first drag action",
            )
        )
    else:
        warnings.append("Could not identify the keyframe immediately before the first drag.")

    drag_image = highlighted_drag_image(raw_dir, first_drag)
    if drag_image is not None:
        candidates.append(
            EvidenceCandidate(
                evidence_id="drag_action",
                label="Highlighted drag action",
                source_path=drag_image["path"],
                filename="02_drag_action_highlight.png",
                source_kind="highlight_image",
                media_time_ms=int_or_none(drag_image.get("timestamp_ms")),
                action_id=str(first_drag.get("action_id")) if first_drag else None,
                reason="closest highlighted drag image from images/manifest.json",
            )
        )
    elif first_drag is not None:
        warnings.append("No highlighted drag image was found in images/manifest.json.")

    if drag_result_keyframe is not None and drag_result_keyframe.screenshot is not None:
        if drag_image is not None:
            candidates.append(
                EvidenceCandidate(
                    evidence_id="after_drag_in_progress",
                    label="Board after drag release",
                    source_path=drag_image["path"],
                    filename="03_after_drag_in_progress_highlight.png",
                    source_kind="highlight_image",
                    media_time_ms=int_or_none(drag_image.get("timestamp_ms")),
                    keyframe_id=drag_result_keyframe.keyframe_id,
                    action_id=str(first_drag.get("action_id")) if first_drag else None,
                    reason="drag highlight image linked to the result keyframe after release",
                )
            )
        else:
            candidates.append(
                keyframe_candidate(
                    evidence_id="after_drag_in_progress",
                    label="Board after drag release",
                    filename="03_after_drag_in_progress.png",
                    keyframe=drag_result_keyframe,
                    reason="result keyframe for the first drag action; no drag highlight image available",
                )
            )
    else:
        warnings.append("Could not identify the result keyframe after the first drag.")

    if not candidates and keyframes:
        fallback = keyframes[-1]
        if fallback.screenshot is not None:
            candidates.append(
                keyframe_candidate(
                    evidence_id="fallback_final_keyframe",
                    label="Final keyframe fallback",
                    filename="99_final_keyframe.png",
                    keyframe=fallback,
                    reason="fallback because no rubric-specific evidence was selected",
                )
            )
    return candidates, warnings


def highlighted_or_keyframe_candidate(
    raw_dir: Path,
    action_step: JsonObject | None,
    evidence_id: str,
    label: str,
    filename: str,
    keyframe: KeyframeRef,
    reason: str,
) -> EvidenceCandidate:
    image = highlighted_image_for_action(raw_dir, action_step)
    if image is not None:
        return EvidenceCandidate(
            evidence_id=evidence_id,
            label=label,
            source_path=image["path"],
            filename=filename,
            source_kind="highlight_image",
            media_time_ms=int_or_none(image.get("timestamp_ms")),
            keyframe_id=keyframe.keyframe_id,
            action_id=str(action_step.get("action_id")) if action_step else None,
            reason=f"{reason}; highlighted image from images/manifest.json",
        )
    return keyframe_candidate(
        evidence_id=evidence_id,
        label=label,
        filename=filename.replace("_highlight", ""),
        keyframe=keyframe,
        reason=f"{reason}; no highlighted image available, fell back to keyframe screenshot",
    )


def keyframe_candidate(
    evidence_id: str,
    label: str,
    filename: str,
    keyframe: KeyframeRef,
    reason: str,
) -> EvidenceCandidate:
    if keyframe.screenshot is None:
        raise ValueError(f"keyframe has no screenshot: {keyframe.keyframe_id}")
    return EvidenceCandidate(
        evidence_id=evidence_id,
        label=label,
        source_path=keyframe.screenshot,
        filename=filename,
        source_kind="keyframe_screenshot",
        media_time_ms=keyframe.media_time_ms,
        keyframe_id=keyframe.keyframe_id,
        reason=reason,
    )


def extract_task_terms(task: JsonObject) -> list[str]:
    terms: list[str] = []
    for key in ("id", "instruction"):
        value = task.get(key)
        if isinstance(value, str):
            terms.extend(extract_useful_phrases(value))
    for key in ("required_subtasks", "apps_involved"):
        values = task.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str):
                    terms.extend(extract_useful_phrases(value))
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        normalized = term.casefold()
        if len(normalized) < 4 or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(term)
    return unique


def board_specific_terms(terms: list[str]) -> list[str]:
    generic = {
        "sprintboard",
        "todo",
        "in progress",
    }
    specific = [term for term in terms if term.casefold() not in generic and not re.fullmatch(r"[a-z_]+-f\d+", term)]
    return specific or terms


def extract_useful_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    quoted = re.findall(r"'([^']{4,})'|\"([^\"]{4,})\"", text)
    for left, right in quoted:
        phrases.append(left or right)
    # Keep canonical seeded project/app phrases without trying to NLP the whole task.
    for pattern in (
        r"Diversity Day Planning 2026",
        r"Team Morale Initiative Q2",
        r"Movie Monday Program",
        r"SprintBoard",
        r"Todo",
        r"In Progress",
    ):
        if re.search(pattern, text, flags=re.IGNORECASE):
            phrases.append(pattern)
    task_id_match = re.search(r"\b[a-z_]+-f\d+\b", text, flags=re.IGNORECASE)
    if task_id_match:
        phrases.append(task_id_match.group(0))
    return phrases


def first_action_matching(action_steps: list[JsonObject], terms: list[str]) -> JsonObject | None:
    if not terms:
        return None
    lowered_terms = [term.casefold() for term in terms]
    for step in action_steps:
        haystack = action_text(step).casefold()
        if any(term in haystack for term in lowered_terms):
            return step
    return None


def action_text(step: JsonObject | None) -> str:
    if step is None:
        return ""
    parts: list[str] = []
    for key in ("safe_caption", "dom_hit_label"):
        value = step.get(key)
        if isinstance(value, str):
            parts.append(value)
    summary = step.get("action_summary")
    if isinstance(summary, dict):
        target = summary.get("target")
        if isinstance(target, dict) and isinstance(target.get("display_label"), str):
            parts.append(target["display_label"])
    dom_hit = step.get("dom_hit")
    if isinstance(dom_hit, dict):
        for key in ("role", "name"):
            value = dom_hit.get(key)
            if isinstance(value, str):
                parts.append(value)
    return " ".join(parts)


def parse_timestamp_ms(value: str) -> int:
    parts = value.split(":")
    if len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    elif len(parts) == 2:
        hours = 0
        minutes = int(parts[0])
        seconds = float(parts[1])
    else:
        hours = 0
        minutes = 0
        seconds = float(parts[0])
    return int(round(((hours * 60 + minutes) * 60 + seconds) * 1000))


def load_keylog_click_buttons(path: Path) -> list[JsonObject]:
    if not path.exists():
        return []
    rows: list[JsonObject] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = payload.get("timestamp")
            message = payload.get("message")
            if not isinstance(timestamp, str) or not isinstance(message, str):
                continue
            match = CLICK_LOG_RE.match(message)
            if match is None:
                continue
            rows.append(
                {
                    "timestamp_ms": parse_timestamp_ms(timestamp),
                    "button": match.group("button"),
                }
            )
    return rows


def button_name(button: str | None) -> str | None:
    if button is None:
        return None
    return BUTTON_NAMES.get(button, button)


def click_button_for_action(step: JsonObject, click_buttons: list[JsonObject]) -> str | None:
    if step.get("action_kind") != "click":
        return None
    action_time = int_or_none(step.get("media_time_ms"))
    if action_time is None or not click_buttons:
        return None
    best = min(
        click_buttons,
        key=lambda item: abs((int_or_none(item.get("timestamp_ms")) or action_time) - action_time),
    )
    best_time = int_or_none(best.get("timestamp_ms"))
    if best_time is None or abs(best_time - action_time) > ACTION_BUTTON_MATCH_WINDOW_MS:
        return None
    button = best.get("button")
    return button if isinstance(button, str) else None


def caption_with_button(caption: str | None, button: str | None) -> str | None:
    if caption is None:
        return None
    name = button_name(button)
    if name is None:
        return caption
    known_prefixes = tuple(f"{known_name} Click" for known_name in BUTTON_NAMES.values())
    if caption.startswith(known_prefixes):
        return caption
    if caption == "Click":
        return f"{name} Click"
    if caption.startswith("Click "):
        return f"{name} Click {caption[len('Click ') :]}"
    return f"{name} Click - {caption}"


def result_keyframe_for_action(step: JsonObject | None, keyframe_by_id: dict[str, KeyframeRef]) -> KeyframeRef | None:
    if step is None:
        return None
    summary = step.get("action_summary")
    result_id = None
    if isinstance(summary, dict):
        value = summary.get("result_keyframe_id")
        result_id = value if isinstance(value, str) else None
    if result_id and result_id in keyframe_by_id:
        return keyframe_by_id[result_id]

    after_ids = []
    if isinstance(summary, dict) and isinstance(summary.get("after_keyframe_ids"), list):
        after_ids = [value for value in summary["after_keyframe_ids"] if isinstance(value, str)]
    for keyframe_id in after_ids:
        if keyframe_id in keyframe_by_id:
            return keyframe_by_id[keyframe_id]
    return None


def keyframe_before_action(step: JsonObject | None, keyframes: list[KeyframeRef]) -> KeyframeRef | None:
    if step is None:
        return None
    action_time = int_or_none(step.get("media_time_ms"))
    if action_time is None:
        return None
    before = [keyframe for keyframe in keyframes if keyframe.media_time_ms < action_time and keyframe.screenshot]
    return before[-1] if before else None


def action_with_highlight_before(
    raw_dir: Path,
    step: JsonObject | None,
    action_steps: list[JsonObject],
) -> JsonObject | None:
    if step is None:
        return None
    action_time = int_or_none(step.get("media_time_ms"))
    if action_time is None:
        return None
    for candidate in reversed(action_steps):
        candidate_time = int_or_none(candidate.get("media_time_ms"))
        if candidate_time is None or candidate_time >= action_time:
            continue
        if highlighted_image_for_action(raw_dir, candidate) is not None:
            return candidate
    return None


def highlighted_image_for_action(raw_dir: Path, action_step: JsonObject | None) -> JsonObject | None:
    if action_step is None:
        return None
    action_time = int_or_none(action_step.get("media_time_ms"))
    action_kind = action_step.get("action_kind")
    events = highlighted_image_events(raw_dir)
    if not events:
        return None

    kind_matches = [
        event
        for event in events
        if isinstance(action_kind, str) and event.get("kind") == action_kind
    ]
    candidates = kind_matches or events
    if action_time is None:
        return candidates[0]
    return min(candidates, key=lambda item: abs((int_or_none(item.get("timestamp_ms")) or action_time) - action_time))


def highlighted_image_events(raw_dir: Path) -> list[JsonObject]:
    manifest_path = raw_dir / "images" / "manifest.json"
    if not manifest_path.exists():
        return []
    manifest = read_json(manifest_path, default={})
    events = manifest.get("events")
    if not isinstance(events, list):
        return []
    normalized: list[JsonObject] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        image = event.get("image")
        if not isinstance(image, str):
            continue
        path = raw_dir / "images" / image
        if not path.exists():
            continue
        item = dict(event)
        item["path"] = path
        normalized.append(item)
    return normalized


def highlighted_drag_image(raw_dir: Path, drag_step: JsonObject | None) -> JsonObject | None:
    if drag_step is None:
        return None
    drag_time = int_or_none(drag_step.get("media_time_ms"))
    candidates = [event for event in highlighted_image_events(raw_dir) if event.get("kind") == "drag"]
    if not candidates:
        return None
    if drag_time is None:
        return candidates[0]
    return min(candidates, key=lambda item: abs((int_or_none(item.get("timestamp_ms")) or drag_time) - drag_time))


def materialize_evidence(
    episode_dir: Path,
    raw_dir: Path,
    file_mode: str,
    overwrite: bool,
) -> JsonObject:
    evidence_dir = episode_dir / "evidence"
    images_dir = raw_dir / "images"
    copied_count = 0
    manifest_ref: str | None = None
    sidecar_refs: dict[str, str] = {}

    if images_dir.exists():
        manifest_path = images_dir / "manifest.json"
        if manifest_path.exists():
            manifest_dest = evidence_dir / "manifest.json"
            materialize_file(manifest_path, manifest_dest, file_mode=file_mode, overwrite=overwrite)
            manifest_ref = relative_posix(manifest_dest, episode_dir)
        sidecars = (
            ("actions.jsonl", "image_actions.jsonl", "image_actions"),
        )
        for source_name, dest_name, ref_key in sidecars:
            sidecar_path = images_dir / source_name
            if sidecar_path.exists():
                sidecar_dest = evidence_dir / dest_name
                materialize_file(sidecar_path, sidecar_dest, file_mode=file_mode, overwrite=overwrite)
                sidecar_refs[ref_key] = relative_posix(sidecar_dest, episode_dir)
        for source in sorted(images_dir.glob("*.png")):
            dest = evidence_dir / source.name
            materialize_file(source, dest, file_mode=file_mode, overwrite=overwrite)
            copied_count += 1

    return {
        "path": "evidence/",
        "manifest": manifest_ref,
        "sidecars": sidecar_refs,
        "image_count": copied_count,
    }


def materialize_all_keyframes(
    keyframes: list[KeyframeRef],
    episode_dir: Path,
    raw_dir: Path,
    file_mode: str,
) -> None:
    all_dir = episode_dir / "evidence" / "all_keyframes"
    all_dir.mkdir(parents=True, exist_ok=True)
    items: list[JsonObject] = []
    for index, keyframe in enumerate(keyframes):
        if keyframe.screenshot is None:
            continue
        filename = f"{index:04d}_{keyframe.folder}.png"
        dest = all_dir / filename
        materialize_file(keyframe.screenshot, dest, file_mode=file_mode, overwrite=True)
        items.append(
            {
                "keyframe_id": keyframe.keyframe_id,
                "folder": keyframe.folder,
                "media_time_ms": keyframe.media_time_ms,
                "path": relative_posix(dest, episode_dir),
                "raw_path": relative_or_absolute(keyframe.screenshot, raw_dir),
            }
        )
    write_json(all_dir / "manifest.json", {"items": items})


def materialize_video(raw_dir: Path, episode_dir: Path, file_mode: str) -> str | None:
    video = raw_dir / "video.mp4"
    if not video.exists():
        return None
    dest = episode_dir / "video.mp4"
    materialize_file(video, dest, file_mode=file_mode, overwrite=True)
    return relative_posix(dest, episode_dir)


def materialize_keylog(raw_dir: Path, episode_dir: Path, file_mode: str) -> str | None:
    keylog = raw_dir / "keylog.jsonl"
    if not keylog.exists():
        return None
    dest = episode_dir / "trace" / "keylog.jsonl"
    materialize_file(keylog, dest, file_mode=file_mode, overwrite=True)
    return relative_posix(dest, episode_dir)


def materialize_summary(raw_dir: Path, episode_dir: Path, file_mode: str) -> str | None:
    summary = raw_dir / "summary.md"
    if not summary.exists():
        return None
    dest = episode_dir / "summary.md"
    materialize_file(summary, dest, file_mode=file_mode, overwrite=True)
    return relative_posix(dest, episode_dir)


def materialize_file(source: Path, dest: Path, file_mode: str, overwrite: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        if not overwrite:
            raise FileExistsError(dest)
        dest.unlink()
    if file_mode == "copy":
        shutil.copy2(source, dest)
    elif file_mode == "hardlink":
        try:
            os.link(source, dest)
        except OSError:
            shutil.copy2(source, dest)
    elif file_mode == "symlink":
        os.symlink(source, dest)
    else:
        raise ValueError(f"unsupported file mode: {file_mode}")


def normalize_steps(trajectory: JsonObject) -> Iterable[JsonObject]:
    steps = trajectory.get("steps")
    if not isinstance(steps, list):
        return []
    normalized: list[JsonObject] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        normalized.append(
            {
                "step_id": step.get("step_id"),
                "kind": step.get("kind"),
                "media_time_ms": step.get("media_time_ms"),
                "occurred_at": step.get("occurred_at"),
                "caption": step.get("safe_caption"),
                "action_kind": step.get("action_kind"),
                "action_id": step.get("action_id"),
                "control_kind": step.get("control_kind"),
                "keyframe_id": step.get("keyframe_id"),
                "keyframe_role": step.get("keyframe_role"),
                "target_label": target_label(step),
                "dom_hit_label": step.get("dom_hit_label"),
                "coordinates": step.get("coordinates"),
                "needs_review": step.get("needs_review"),
            }
        )
    return normalized


def normalize_actions(
    action_steps: list[JsonObject],
    task: JsonObject,
    click_buttons: list[JsonObject],
) -> Iterable[JsonObject]:
    task_terms = [term.casefold() for term in extract_task_terms(task)]
    rows: list[JsonObject] = []
    for step in action_steps:
        text = action_text(step)
        raw_caption = step.get("safe_caption") if isinstance(step.get("safe_caption"), str) else None
        button = click_button_for_action(step, click_buttons)
        caption = caption_with_button(raw_caption, button)
        rows.append(
            {
                "sequence_index": step.get("sequence_index"),
                "action_id": step.get("action_id"),
                "kind": step.get("action_kind"),
                "media_time_ms": step.get("media_time_ms"),
                "occurred_at": step.get("occurred_at"),
                "caption": caption,
                "button": button,
                "button_name": button_name(button),
                "target_label": target_label(step),
                "dom_hit_label": step.get("dom_hit_label"),
                "dom_hit": dom_hit_without_bbox(step),
                "coordinates": step.get("coordinates"),
                "rubric_tags": rubric_tags(step, text, task_terms),
            }
        )
    return rows


def rubric_tags(step: JsonObject, text: str, task_terms: list[str]) -> list[str]:
    tags: list[str] = []
    lowered = text.casefold()
    if any(term in lowered for term in task_terms):
        tags.append("mentions_task_term")
    if "sprintboard" in lowered:
        tags.append("sprintboard")
    if "diversity day planning 2026" in lowered:
        tags.append("diversity_day_board")
    if "todo" in lowered:
        tags.append("todo_card")
    if "in progress" in lowered:
        tags.append("in_progress")
    if step.get("action_kind") == "drag":
        tags.append("drag")
    if step.get("action_kind") == "click":
        tags.append("click")
    return tags


def target_label(step: JsonObject) -> str | None:
    summary = step.get("action_summary")
    if isinstance(summary, dict):
        target = summary.get("target")
        if isinstance(target, dict) and isinstance(target.get("display_label"), str):
            return target["display_label"]
    return None


def dom_hit_without_bbox(step: JsonObject) -> JsonObject | None:
    dom_hit = step.get("dom_hit")
    if not isinstance(dom_hit, dict):
        return None
    return {key: value for key, value in dom_hit.items() if key != "bbox"}


def build_episode_summary(
    raw_dir: Path,
    task_id: str,
    recording: JsonObject,
    trajectory: JsonObject,
    keyframes: list[KeyframeRef],
    evidence_ref: JsonObject,
    video_ref: str | None,
    keylog_ref: str | None,
    summary_ref: str | None,
    normalized_actions: list[JsonObject],
) -> JsonObject:
    trace_files = {
        "actions": "trace/actions.jsonl",
    }
    if keylog_ref is not None:
        trace_files["keylog"] = keylog_ref
    keylog_event_count = count_jsonl_rows(raw_dir / "keylog.jsonl") if keylog_ref is not None else 0
    return {
        "generated_at": utc_now(),
        "task_id": task_id,
        "session_id": recording.get("session_id"),
        "status": recording.get("status"),
        "mode": recording.get("mode"),
        "started_at": recording.get("started_at"),
        "ended_at": recording.get("ended_at"),
        "duration_ms": recording.get("duration_ms") or trajectory.get("duration_ms"),
        "task": "task.json",
        "counts": {
            "actions": len(normalized_actions),
            "keylog_events": keylog_event_count,
            "evidence_images": evidence_ref.get("image_count"),
            "keyframes": recording.get("keyframe_count") or len(keyframes),
            "controls": recording.get("control_count"),
        },
        "trace": trace_files,
        "video": video_ref,
        "summary": summary_ref,
        "evidence": evidence_ref,
        "source": {
            "raw_dir": str(raw_dir),
        },
    }


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def write_jsonl(path: Path, rows: Iterable[JsonObject]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            json.dump(row, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")


def count_jsonl_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "_", text)
    return text.strip("._-") or "unknown"


def relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def relative_or_absolute(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
