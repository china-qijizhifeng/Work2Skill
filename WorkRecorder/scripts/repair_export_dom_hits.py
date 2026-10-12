#!/usr/bin/env python3
"""Backfill DOM hit labels into an already-materialized recording export."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path


_KEYFRAME_CAPTIONS = {
    "anchor": "Anchor frame",
    "start": "Recording started",
    "final": "Recording ended",
    "before_action": "Before action",
    "result": "Action result",
    "settle": "Settled state",
    "change": "Changed state",
    "user_mark": "User mark",
    "idle_anchor": "Idle anchor",
    "provider_completion": "Provider completion",
    "pause_boundary": "Pause boundary",
    "resume_boundary": "Resume boundary",
    "error_state": "Error state",
    "scroll_milestone": "Scroll milestone",
}
_CONTROL_CAPTIONS = {
    "start_segment": "Segment started",
    "end_segment": "Segment ended",
    "pause": "Recording paused",
    "resume": "Recording resumed",
    "user_mark": "User mark",
    "stop": "Recording stopped",
    "auto_stop": "Recording auto-stopped",
    "scope_lost": "Recording area changed",
}
_HOTKEY_CAPTIONS = {
    "copy": "Copy",
    "cut": "Cut",
    "paste": "Paste",
    "submit": "Press Enter",
    "search": "Press search shortcut",
    "save": "Save",
    "close": "Close",
    "new_item": "Create new item",
    "delete": "Delete",
    "refresh": "Refresh",
    "select_all": "Select all",
    "undo": "Undo",
    "redo": "Redo",
    "navigate_back": "Navigate back",
    "navigate_forward": "Navigate forward",
    "open_command": "Open command",
    "escape_cancel": "Cancel",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording_dir", type=Path, help="Path to one exported recording directory.")
    return parser


def main() -> int:
    args = _parser().parse_args()
    recording_dir = args.recording_dir.expanduser()
    if not recording_dir.is_dir():
        raise SystemExit(f"not a directory: {recording_dir}")

    dom_by_action = _load_dom_hits(recording_dir)
    if not dom_by_action:
        print("no DOM hit sidecars found")
        return 0

    action_context = _repair_actions(recording_dir, dom_by_action)
    _repair_trajectory(recording_dir, dom_by_action, action_context)
    _repair_recording_meta(recording_dir, dom_by_action)
    _repair_summary(recording_dir)
    print(f"repaired {len(dom_by_action)} DOM-hit action(s) in {recording_dir}")
    return 0


def _load_dom_hits(recording_dir: Path) -> dict[str, dict[str, object]]:
    dom_by_action: dict[str, dict[str, object]] = {}
    paths = [
        recording_dir / "dom_hits.jsonl",
        recording_dir / "vm_a11y.jsonl",
        *sorted(recording_dir.glob("*/vm_a11y.jsonl")),
    ]
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            action_id = record.get("action_id")
            if not isinstance(action_id, str):
                latest = record.get("latest")
                if isinstance(latest, dict):
                    action_id = latest.get("action_id")
            if not isinstance(action_id, str):
                continue
            dom = _dom_hit(record)
            if dom is not None:
                dom_by_action[action_id] = dom
    return dom_by_action


def _repair_actions(
    recording_dir: Path,
    dom_by_action: Mapping[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    action_context: dict[str, dict[str, object]] = {}
    for path in sorted(recording_dir.glob("*/actions.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, list):
            continue
        changed = False
        for action in payload:
            if not isinstance(action, dict):
                continue
            action_id = action.get("action_id")
            if not isinstance(action_id, str):
                continue
            context = action_context.setdefault(action_id, {})
            coordinates = action.get("coordinates")
            if isinstance(coordinates, dict) and "coordinates" not in context:
                context["coordinates"] = coordinates
            dom = dom_by_action.get(action_id)
            if dom is None:
                continue
            label = _dom_hit_label(dom)
            action["dom_hit"] = dom
            action["dom_hit_label"] = label
            context["dom_hit"] = dom
            context["dom_hit_label"] = label
            if action.get("kind") in {"click", "drag"}:
                action["caption"] = f"{_pointer_verb(action.get('kind'))} {_summary_dom_hit_label(dom)}"
            changed = True
        if changed:
            _write_json(path, payload)
    return action_context


def _repair_trajectory(
    recording_dir: Path,
    dom_by_action: Mapping[str, dict[str, object]],
    action_context: Mapping[str, dict[str, object]],
) -> None:
    path = recording_dir / "trajectory.json"
    if not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    steps = payload.get("steps") if isinstance(payload, dict) else None
    if not isinstance(steps, list):
        return
    changed = False
    for step in steps:
        if not isinstance(step, dict):
            continue
        action_id = step.get("action_id")
        if not isinstance(action_id, str):
            continue
        context = action_context.get(action_id, {})
        coordinates = context.get("coordinates")
        if isinstance(coordinates, dict):
            step["coordinates"] = coordinates
            changed = True
        dom = dom_by_action.get(action_id)
        if dom is None:
            continue
        label = _dom_hit_label(dom)
        step["dom_hit"] = dom
        step["dom_hit_label"] = label
        _mark_step_ready(step)
        if step.get("action_kind") in {"click", "drag"}:
            step["safe_caption"] = f"{_pointer_verb(step.get('action_kind'))} {_summary_dom_hit_label(dom)}"
            _apply_dom_hit_resolution(step, dom)
        changed = True
    if changed:
        _write_json(path, payload)


def _repair_recording_meta(
    recording_dir: Path,
    dom_by_action: Mapping[str, dict[str, object]],
) -> None:
    path = recording_dir / "recording.json"
    if not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
    payload["dom_hits_file"] = "dom_hits.jsonl"
    payload["dom_hits_hit_count"] = len(dom_by_action)
    current_count = payload.get("dom_hits_count")
    payload["dom_hits_count"] = max(current_count if isinstance(current_count, int) else 0, len(dom_by_action))
    _write_json(path, payload)


def _repair_summary(recording_dir: Path) -> None:
    trajectory_path = recording_dir / "trajectory.json"
    summary_path = recording_dir / "summary.md"
    recording_path = recording_dir / "recording.json"
    if not trajectory_path.is_file() or not summary_path.is_file():
        return
    try:
        trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    recording: dict[str, object] = {}
    if recording_path.is_file():
        try:
            loaded = json.loads(recording_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                recording = loaded
        except json.JSONDecodeError:
            pass
    steps = trajectory.get("steps") if isinstance(trajectory, dict) else None
    if not isinstance(steps, list):
        return
    lines = [
        f"# Recording Summary - {recording.get('session_id') or trajectory.get('session_id') or 'unknown'}",
        "",
        f"- Mode: {recording.get('mode') or 'recording_session'}",
        f"- Started: {recording.get('started_at') or 'unknown'}",
        f"- Ended: {recording.get('ended_at') or 'unknown'}",
        f"- Duration: {_duration_label(recording.get('duration_ms') or trajectory.get('duration_ms'))}",
        (
            "- Counts: "
            f"{_count_label(recording.get('keyframe_count') or _count_kind(steps, 'keyframe'), 'keyframe')}, "
            f"{_count_label(recording.get('action_count') or _count_kind(steps, 'action'), 'action')}, "
            f"{_count_label(recording.get('control_count') or _count_kind(steps, 'control'), 'control')}"
        ),
    ]
    if (recording_dir / "keylog.jsonl").is_file():
        lines.append("- Input log: keylog.jsonl")
    lines.extend(["", "## Timeline", ""])
    for step in steps:
        if not isinstance(step, dict):
            continue
        kind = step.get("kind")
        caption = _summary_step_caption(step)
        marker = {"keyframe": "[keyframe]", "action": "[action]", "control": "[control]"}.get(kind, "[item]")
        lines.append(f"- `{_format_media_time(step.get('media_time_ms'))}` {marker} {caption}")
    lines.append("")
    summary_path.write_text("\n".join(lines), encoding="utf-8")


def _dom_hit(record: Mapping[str, object]) -> dict[str, object] | None:
    direct = record.get("dom_hit")
    if isinstance(direct, dict):
        return dict(direct)
    hit_dom = record.get("hit_dom")
    if isinstance(hit_dom, dict):
        return dict(hit_dom)
    latest = record.get("latest")
    if isinstance(latest, dict):
        nested = _dom_hit(latest)
        if nested is not None:
            return nested
    sample = record.get("sample")
    if not isinstance(sample, dict):
        return None
    hit = sample.get("hit")
    if isinstance(hit, dict):
        return dict(hit)
    dom = sample.get("dom")
    if isinstance(dom, dict):
        return dict(dom)
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
        if len(normalized) > 80:
            normalized = normalized[:77].rstrip() + "..."
        if role:
            return f"{role} · {normalized}"
        if tag:
            return f"{tag.lower()} · {normalized}"
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


def _summary_step_caption(step: Mapping[str, object]) -> str:
    kind = _non_empty_string(step.get("kind"))
    if kind == "keyframe":
        role = _non_empty_string(step.get("keyframe_role"))
        return _KEYFRAME_CAPTIONS.get(role or "", _humanize_enum_value(role or "keyframe"))
    if kind == "control":
        control_kind = _non_empty_string(step.get("control_kind"))
        return _CONTROL_CAPTIONS.get(control_kind or "", _humanize_enum_value(control_kind or "recording_control"))
    if kind == "action":
        return _summary_action_caption(step)
    return _humanize_enum_value(kind or "step")


def _summary_action_caption(step: Mapping[str, object]) -> str:
    action_summary = step.get("action_summary")
    if not isinstance(action_summary, Mapping):
        action_summary = {}
    action_kind = _non_empty_string(step.get("action_kind")) or _non_empty_string(action_summary.get("action_kind"))
    dom_hit = step.get("dom_hit")
    if action_kind in {"click", "drag"} and isinstance(dom_hit, Mapping):
        return f"{_pointer_verb(action_kind)} {_summary_dom_hit_label(dom_hit)}"
    if action_kind == "click":
        target = action_summary.get("target")
        if isinstance(target, Mapping) and not target.get("needs_review"):
            label = _non_empty_string(target.get("display_label"))
            if label:
                return f'Click "{label}"'
        return "Click (target needs review)"
    if action_kind == "drag":
        return "Drag"
    if action_kind == "scroll":
        return "Scroll stopped"
    if action_kind == "hotkey":
        key_chord = action_summary.get("key_chord")
        if isinstance(key_chord, Mapping):
            return f"Press {_key_chord_caption(key_chord)}"
        semantic = _non_empty_string(action_summary.get("hotkey_semantic"))
        return _HOTKEY_CAPTIONS.get(semantic or "", "Keyboard shortcut")
    if action_kind in {"key_down", "key_up"}:
        verb = "Press" if action_kind == "key_down" else "Release"
        key_chord = action_summary.get("key_chord")
        if isinstance(key_chord, Mapping):
            return f"{verb} {_key_chord_caption(key_chord)}"
        return f"{verb} key"
    if action_kind == "typing_pause":
        typing = action_summary.get("typing_summary")
        if isinstance(typing, Mapping):
            count = typing.get("character_count")
            if isinstance(count, int):
                noun = "character" if count == 1 else "characters"
                return f"Text input - about {count} {noun}"
        if action_summary.get("after_keyframe_ids") or action_summary.get("result_keyframe_id"):
            return "State after input"
        return "Typing summary"
    if action_kind == "window_switch":
        return "Window switch"
    if action_kind == "tab_switch":
        return "Tab switch"
    if action_kind == "user_mark":
        return "User mark"
    return _humanize_enum_value(action_kind or "action")


def _apply_dom_hit_resolution(step: dict[str, object], dom_hit: Mapping[str, object]) -> None:
    action_summary = step.get("action_summary")
    if not isinstance(action_summary, dict):
        return
    target = action_summary.get("target")
    resolved = dict(target) if isinstance(target, Mapping) else {}
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


def _mark_step_ready(step: dict[str, object]) -> None:
    step["needs_review"] = False
    step["readiness"] = {
        "state": "ready",
        "reasons": [],
        "review_item_count": 0,
        "blocked_item_count": 0,
        "missing_evidence": [],
    }


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
    return _truncate_label(_summary_dom_hit_label(dom_hit), max_length=80)


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
    if isinstance(value, int | float):
        return float(value)
    return None


def _pointer_verb(value: object) -> str:
    return "Drag" if value == "drag" else "Click"


def _key_chord_caption(chord: Mapping[str, object]) -> str:
    raw_label = _non_empty_string(chord.get("characters")) or _non_empty_string(chord.get("normalized_key_label")) or "key"
    normalized = raw_label.strip().lower()
    special = {
        "enter": "Enter",
        "return": "Enter",
        "escape": "Esc",
        "esc": "Esc",
        "tab": "Tab",
        "space": "Space",
        "backspace": "Backspace",
        "delete": "Delete",
    }
    key_label = special.get(normalized, raw_label.upper() if len(raw_label) == 1 else raw_label)
    modifiers = chord.get("modifiers")
    modifier_labels = []
    if isinstance(modifiers, list):
        modifier_labels = [_humanize_enum_value(modifier) for modifier in modifiers if isinstance(modifier, str)]
    return "+".join((*modifier_labels, key_label)) if modifier_labels else key_label


def _humanize_enum_value(value: object) -> str:
    if not isinstance(value, str):
        return "Unknown"
    words = [word for word in value.replace("-", "_").split("_") if word]
    return " ".join(word.capitalize() for word in words) if words else value


def _non_empty_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _duration_label(value: object) -> str:
    if isinstance(value, int | float):
        return f"{value / 1000:.1f}s"
    return "unknown"


def _count_kind(steps: list[object], kind: str) -> int:
    return sum(1 for step in steps if isinstance(step, dict) and step.get("kind") == kind)


def _count_label(value: object, singular: str) -> str:
    count = value if isinstance(value, int) else 0
    suffix = "" if count == 1 else "s"
    return f"{count} {singular}{suffix}"


def _format_media_time(value: object) -> str:
    if not isinstance(value, int):
        return "--:--.---"
    total_seconds, millis = divmod(value, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
