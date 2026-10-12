#!/usr/bin/env python3
"""Extract key frames from a WorkRecorder keylog and draw event highlights.

Usage:
  python keylog_highlight_frames.py /path/to/recording
  python keylog_highlight_frames.py /path/to/recording --frame-offset-ms -100

The script expects:
  recording/
    keylog.jsonl
    video.mp4

It writes highlighted PNGs and a manifest to:
  recording/images/
"""

from __future__ import annotations

import argparse
import io
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Pillow is required. Try running with the WorkRecorder environment:\n"
        "  cd /path/to/WorkRecorder\n"
        "  uv run python scripts/benchmark/keylog_highlight_frames.py /path/to/recording"
    ) from exc


CLICK_RE = re.compile(r"^(?P<button>[LRM])Click at \((?P<x>-?\d+),\s*(?P<y>-?\d+)\)")
DRAG_START_RE = re.compile(r"^DragStart at \((?P<x>-?\d+),\s*(?P<y>-?\d+)\)")
DRAG_MOVE_RE = re.compile(r"^DragMove to \((?P<x>-?\d+),\s*(?P<y>-?\d+)\)")
DRAG_END_RE = re.compile(
    r"^(?P<button>[LRM])DragEnd: from \((?P<x1>-?\d+),\s*(?P<y1>-?\d+)\) "
    r"to \((?P<x2>-?\d+),\s*(?P<y2>-?\d+)\)"
)
KEY_PRESS_RE = re.compile(r"^Key\s+(?:Press|Down):\s*(?P<key>.+)$", re.IGNORECASE)
KEY_RELEASE_RE = re.compile(r"^Key\s+(?:Release|Up):\s*(?P<key>.+)$", re.IGNORECASE)

SPECIAL_KEY_NAMES = {
    "enter",
    "return",
    "escape",
    "esc",
    "tab",
    "backspace",
    "delete",
    "left arrow",
    "right arrow",
    "up arrow",
    "down arrow",
}
BUTTON_NAMES = {
    "L": "Left",
    "R": "Right",
    "M": "Middle",
}
DRAG_VISUAL_TARGET_WINDOW_MS = 10_000
DRAG_VISUAL_TARGET_RADIUS_PX = 180


@dataclass(frozen=True)
class RawEntry:
    index: int
    timestamp_ms: int
    message: str
    window: str | None


@dataclass(frozen=True)
class HighlightEvent:
    kind: str
    timestamp_ms: int
    label: str
    button: str | None = None
    points: tuple[tuple[int, int], ...] = ()
    start_ms: int | None = None
    end_ms: int | None = None
    raw_messages: tuple[str, ...] = ()
    action_id: str | None = None
    action_kind: str | None = None
    action_caption: str | None = None
    action_delta_ms: int | None = None
    image_action_caption: str | None = None
    image_action_source: str | None = None
    point_source: str | None = None


@dataclass(frozen=True)
class KeyPressUnit:
    press: RawEntry
    key: str
    release: RawEntry | None = None


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


def format_time(ms: int) -> str:
    ms = max(0, ms)
    whole, frac = divmod(ms, 1000)
    minutes, seconds = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{frac:03d}"
    return f"{minutes:02d}:{seconds:02d}.{frac:03d}"


def safe_name(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "event"


def button_name(button: str | None) -> str | None:
    if button is None:
        return None
    return BUTTON_NAMES.get(button, button)


def caption_with_button(caption: str, button: str | None, event_kind: str) -> str:
    name = button_name(button)
    if name is None or event_kind not in {"click", "double_click", "drag"}:
        return caption
    known_prefixes = tuple(
        f"{known_name} {verb}" for known_name in BUTTON_NAMES.values() for verb in ("Click", "Double Click", "Drag")
    )
    if caption.startswith(known_prefixes):
        return caption
    if event_kind == "double_click":
        return replace_action_verb(caption, source_verb="Click", target_verb="Double Click", button=name)
    if event_kind == "drag":
        if caption.startswith("Drag"):
            return replace_action_verb(caption, source_verb="Drag", target_verb="Drag", button=name)
        return replace_action_verb(caption, source_verb="Click", target_verb="Drag", button=name)
    return replace_action_verb(caption, source_verb="Click", target_verb="Click", button=name)


def replace_action_verb(caption: str, source_verb: str, target_verb: str, button: str) -> str:
    if caption == source_verb:
        return f"{button} {target_verb}"
    prefix = f"{source_verb} "
    if caption.startswith(prefix):
        return f"{button} {target_verb} {caption[len(prefix):]}"
    return f"{button} {target_verb} - {caption}"


def read_keylog(path: Path) -> list[RawEntry]:
    entries: list[RawEntry] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = payload.get("timestamp")
            message = payload.get("message")
            if not isinstance(timestamp, str) or not isinstance(message, str):
                continue
            window = payload.get("window") if isinstance(payload.get("window"), str) else None
            entries.append(
                RawEntry(
                    index=len(entries),
                    timestamp_ms=parse_timestamp_ms(timestamp),
                    message=message,
                    window=window,
                )
            )
    return entries



def load_action_overlays(recording_dir: Path) -> list[dict[str, Any]]:
    trajectory_path = recording_dir / "trajectory.json"
    if not trajectory_path.exists():
        return []
    try:
        payload = json.loads(trajectory_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return []
    actions: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict) or step.get("kind") != "action":
            continue
        media_time_ms = step.get("media_time_ms")
        if not isinstance(media_time_ms, int):
            continue
        caption = step.get("safe_caption")
        if not isinstance(caption, str) or not caption.strip():
            caption = str(step.get("action_kind") or "action")
        actions.append(
            {
                "action_id": step.get("action_id") if isinstance(step.get("action_id"), str) else None,
                "action_kind": step.get("action_kind") if isinstance(step.get("action_kind"), str) else None,
                "caption": caption.strip(),
                "media_time_ms": media_time_ms,
            }
        )
    return sorted(actions, key=lambda item: int(item["media_time_ms"]))


def annotate_events_with_actions(
    events: list[HighlightEvent],
    actions: list[dict[str, Any]],
    match_window_ms: int,
) -> list[HighlightEvent]:
    if not actions:
        return events
    annotated: list[HighlightEvent] = []
    for event in events:
        match = nearest_action_for_event(event, actions, match_window_ms)
        if match is None:
            annotated.append(event)
            continue
        delta = int(event.timestamp_ms) - int(match["media_time_ms"])
        raw_caption = str(match["caption"])
        image_caption = caption_with_button(raw_caption, event.button, event.kind)
        caption_source = "trajectory_time_match"
        if image_caption != raw_caption:
            caption_source += "+keylog_button"
        annotated.append(
            replace(
                event,
                action_id=match.get("action_id"),
                action_kind=match.get("action_kind"),
                action_caption=raw_caption,
                action_delta_ms=delta,
                image_action_caption=image_caption,
                image_action_source=caption_source,
            )
        )
    return improve_drag_action_captions_from_nearby_clicks(annotated)


def improve_drag_action_captions_from_nearby_clicks(events: list[HighlightEvent]) -> list[HighlightEvent]:
    improved: list[HighlightEvent] = []
    prior_clicks: list[HighlightEvent] = []
    for event in events:
        if event.kind == "drag" and event.points and event.start_ms is not None:
            click = nearest_prior_click_for_drag(event, prior_clicks)
            if click is not None and click.image_action_caption:
                corrected = click_to_drag_caption(click.image_action_caption)
                if corrected and corrected != event.image_action_caption:
                    event = replace(
                        event,
                        image_action_caption=corrected,
                        image_action_source=f"nearby_prior_click:{click.action_id or click.timestamp_ms}",
                    )
        improved.append(event)
        if event.kind in {"click", "double_click"} and event.points and event.image_action_caption:
            prior_clicks.append(event)
    return improved


def nearest_prior_click_for_drag(event: HighlightEvent, prior_clicks: list[HighlightEvent]) -> HighlightEvent | None:
    if not event.points or event.start_ms is None:
        return None
    start = event.points[0]
    candidates: list[tuple[float, int, HighlightEvent]] = []
    for click in prior_clicks:
        if not click.points:
            continue
        time_delta = event.start_ms - click.timestamp_ms
        if time_delta < 0 or time_delta > DRAG_VISUAL_TARGET_WINDOW_MS:
            continue
        distance = point_distance(start, click.points[0])
        if distance > DRAG_VISUAL_TARGET_RADIUS_PX:
            continue
        candidates.append((distance, time_delta, click))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def point_distance(a: tuple[int, int], b: tuple[int, int]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def click_to_drag_caption(caption: str) -> str:
    for name in BUTTON_NAMES.values():
        if caption == f"{name} Click":
            return f"{name} Drag"
        if caption.startswith(f"{name} Click "):
            return f"{name} Drag " + caption[len(f"{name} Click ") :]
        if caption == f"{name} Double Click":
            return f"{name} Drag"
        if caption.startswith(f"{name} Double Click "):
            return f"{name} Drag " + caption[len(f"{name} Double Click ") :]
    if caption.startswith("Click "):
        return "Drag " + caption[len("Click ") :]
    return caption


def nearest_action_for_event(
    event: HighlightEvent,
    actions: list[dict[str, Any]],
    match_window_ms: int,
) -> dict[str, Any] | None:
    preferred = action_kind_for_event(event.kind)
    candidates = [action for action in actions if preferred is None or action.get("action_kind") == preferred]
    if not candidates:
        candidates = actions
    best = min(candidates, key=lambda action: abs(int(action["media_time_ms"]) - event.timestamp_ms), default=None)
    if best is None:
        return None
    if abs(int(best["media_time_ms"]) - event.timestamp_ms) > match_window_ms:
        return None
    return best


def action_kind_for_event(kind: str) -> str | None:
    if kind in {"click", "double_click"}:
        return "click"
    if kind == "drag":
        return "drag"
    return None

def key_is_special(key: str) -> bool:
    normalized = key.strip().lower()
    normalized = normalized.replace("key.", "").replace("keyboard.", "")
    return normalized in SPECIAL_KEY_NAMES or ("+" in normalized and not normalized.startswith("shift+"))


def typing_key_text(key: str) -> str | None:
    normalized = key.strip()
    lowered = normalized.lower().replace("key.", "").replace("keyboard.", "")
    if lowered.startswith("shift+"):
        produced = normalized.split("+", 1)[1]
        return produced if len(produced) == 1 and produced.isprintable() else None
    if key_is_special(normalized):
        return None
    if lowered.startswith(("shift", "control", "ctrl", "option", "alt", "command", "cmd", "function")):
        return None
    return normalized if normalized and all(character.isprintable() for character in normalized) else None


def key_is_typing(key: str) -> bool:
    return typing_key_text(key) is not None


def build_drag_events(entries: list[RawEntry]) -> tuple[list[HighlightEvent], set[int]]:
    events: list[HighlightEvent] = []
    consumed: set[int] = set()
    i = 0
    while i < len(entries):
        entry = entries[i]
        start_match = DRAG_START_RE.match(entry.message)
        if start_match is None:
            i += 1
            continue

        start = (int(start_match.group("x")), int(start_match.group("y")))
        path = [start]
        raw_messages = [entry.message]
        consumed.add(entry.index)
        end_ms: int | None = None
        end_point: tuple[int, int] | None = None
        button: str | None = None
        j = i + 1
        while j < len(entries):
            current = entries[j]
            move_match = DRAG_MOVE_RE.match(current.message)
            if move_match is not None:
                path.append((int(move_match.group("x")), int(move_match.group("y"))))
                raw_messages.append(current.message)
                consumed.add(current.index)
                j += 1
                continue

            end_match = DRAG_END_RE.match(current.message)
            if end_match is not None:
                button = end_match.group("button")
                end_ms = current.timestamp_ms
                end_point = (int(end_match.group("x2")), int(end_match.group("y2")))
                path.append(end_point)
                raw_messages.append(current.message)
                consumed.add(current.index)
                break

            if current.timestamp_ms - entry.timestamp_ms > 10_000:
                break
            j += 1

        if end_ms is not None and end_point is not None:
            events.append(
                HighlightEvent(
                    kind="drag",
                    timestamp_ms=end_ms,
                    start_ms=entry.timestamp_ms,
                    end_ms=end_ms,
                    button=button,
                    points=tuple(path),
                    label=f"{button or ''}Drag {format_time(entry.timestamp_ms)} -> {format_time(end_ms)}",
                    raw_messages=tuple(raw_messages),
                )
            )
            i = j + 1
        else:
            i += 1
    return events, consumed


def suppress_drag_mousedown(entries: list[RawEntry], drags: list[HighlightEvent], window_ms: int) -> set[int]:
    suppressed: set[int] = set()
    for drag in drags:
        if not drag.points or drag.start_ms is None:
            continue
        start = drag.points[0]
        for entry in entries:
            if entry.timestamp_ms > drag.start_ms:
                break
            if drag.start_ms - entry.timestamp_ms > window_ms:
                continue
            match = CLICK_RE.match(entry.message)
            if match is None:
                continue
            point = (int(match.group("x")), int(match.group("y")))
            if point == start:
                suppressed.add(entry.index)
    return suppressed


def build_click_events(
    entries: list[RawEntry],
    suppressed_indices: set[int],
    double_click_window_ms: int,
) -> list[HighlightEvent]:
    click_entries: list[tuple[RawEntry, str, tuple[int, int]]] = []
    for entry in entries:
        if entry.index in suppressed_indices:
            continue
        match = CLICK_RE.match(entry.message)
        if match is None:
            continue
        click_entries.append((entry, match.group("button"), (int(match.group("x")), int(match.group("y")))))

    events: list[HighlightEvent] = []
    i = 0
    while i < len(click_entries):
        entry, button, point = click_entries[i]
        if i + 1 < len(click_entries):
            next_entry, next_button, next_point = click_entries[i + 1]
            if (
                button == next_button
                and point == next_point
                and next_entry.timestamp_ms - entry.timestamp_ms <= double_click_window_ms
            ):
                events.append(
                    HighlightEvent(
                        kind="double_click",
                        timestamp_ms=next_entry.timestamp_ms,
                        start_ms=entry.timestamp_ms,
                        end_ms=next_entry.timestamp_ms,
                        button=button,
                        points=(point,),
                        label=(
                            f"{button}DoubleClick {format_time(entry.timestamp_ms)}"
                            f" -> {format_time(next_entry.timestamp_ms)} at {point}"
                        ),
                        raw_messages=(entry.message, next_entry.message),
                    )
                )
                i += 2
                continue
        events.append(
            HighlightEvent(
                kind="click",
                timestamp_ms=entry.timestamp_ms,
                button=button,
                points=(point,),
                label=f"{button}Click {format_time(entry.timestamp_ms)} at {point}",
                raw_messages=(entry.message,),
            )
        )
        i += 1
    return events


def key_press_units(entries: list[RawEntry]) -> list[KeyPressUnit]:
    units: list[KeyPressUnit] = []
    for index, entry in enumerate(entries):
        press_match = KEY_PRESS_RE.match(entry.message)
        if press_match is None:
            continue
        key = press_match.group("key").strip()
        release: RawEntry | None = None
        for candidate in entries[index + 1 :]:
            if candidate.timestamp_ms - entry.timestamp_ms > 2_000:
                break
            next_press = KEY_PRESS_RE.match(candidate.message)
            if next_press is not None and next_press.group("key").strip() == key:
                break
            release_match = KEY_RELEASE_RE.match(candidate.message)
            if release_match is not None and release_match.group("key").strip() == key:
                release = candidate
                break
        units.append(KeyPressUnit(press=entry, key=key, release=release))
    return units


def key_unit_end_ms(unit: KeyPressUnit) -> int:
    return unit.release.timestamp_ms if unit.release is not None else unit.press.timestamp_ms


def key_unit_messages(unit: KeyPressUnit) -> tuple[str, ...]:
    if unit.release is None:
        return (unit.press.message,)
    return (unit.press.message, unit.release.message)


def build_key_events(entries: list[RawEntry], typing_gap_ms: int, redact_typing: bool) -> list[HighlightEvent]:
    events: list[HighlightEvent] = []
    typing_group: list[KeyPressUnit] = []

    def flush_typing() -> None:
        nonlocal typing_group
        if not typing_group:
            return
        start_ms = typing_group[0].press.timestamp_ms
        end_ms = key_unit_end_ms(typing_group[-1])
        keys = [typing_key_text(unit.key) or unit.key for unit in typing_group]
        if redact_typing:
            key_text = f"{len(keys)} key press(es)"
        else:
            key_text = " ".join(keys)
            if len(key_text) > 40:
                key_text = key_text[:37] + "..."
        raw_messages: list[str] = []
        for unit in typing_group:
            raw_messages.extend(key_unit_messages(unit))
        events.append(
            HighlightEvent(
                kind="typing",
                timestamp_ms=end_ms,
                start_ms=start_ms,
                end_ms=end_ms,
                label=f"Typing {format_time(start_ms)} -> {format_time(end_ms)}: {key_text}",
                raw_messages=tuple(raw_messages),
            )
        )
        typing_group = []

    for unit in key_press_units(entries):
        key = unit.key
        if key_is_special(key):
            flush_typing()
            events.append(
                HighlightEvent(
                    kind="key",
                    timestamp_ms=key_unit_end_ms(unit),
                    label=f"Key: {key} at {format_time(key_unit_end_ms(unit))}",
                    raw_messages=key_unit_messages(unit),
                )
            )
            continue
        if not key_is_typing(key):
            flush_typing()
            continue
        if typing_group and unit.press.timestamp_ms - typing_group[-1].press.timestamp_ms > typing_gap_ms:
            flush_typing()
        typing_group.append(unit)
    flush_typing()
    return events


def build_events(
    entries: list[RawEntry],
    typing_gap_ms: int,
    drag_click_window_ms: int,
    double_click_window_ms: int,
    redact_typing: bool,
) -> list[HighlightEvent]:
    drags, drag_consumed = build_drag_events(entries)
    suppressed = drag_consumed | suppress_drag_mousedown(entries, drags, drag_click_window_ms)
    events = []
    events.extend(build_click_events(entries, suppressed, double_click_window_ms))
    events.extend(drags)
    events.extend(build_key_events(entries, typing_gap_ms, redact_typing))
    events.sort(key=lambda event: (event.timestamp_ms, event.kind))
    return events


def supplement_timeline_events(
    recording_dir: Path, video_path: Path, events: list[HighlightEvent]
) -> list[HighlightEvent]:
    """Fill mouse events absent from keyboard-only Mac keylogs, once per action."""
    actions = load_action_overlays(recording_dir)
    missing_candidates = [a for a in actions if a["action_kind"] in {"click", "scroll"}]
    if not missing_candidates:
        return events
    details: dict[str, dict[str, Any]] = {}
    index = recording_dir / "action_evidence.jsonl"
    if index.exists():
        for line in index.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if isinstance(row.get("action_id"), str):
                    details[row["action_id"]] = row
    # Older exports may only carry coordinates in the per-frame actions.
    for path in sorted(recording_dir.glob("[0-9]*_*/actions.json")):
        for row in json.loads(path.read_text(encoding="utf-8")):
            action_id = row.get("action_id")
            if isinstance(action_id, str):
                detail = details.setdefault(action_id, dict(row))
                if not detail.get("coordinates") and row.get("coordinates"):
                    detail["coordinates"] = row["coordinates"]
                detail.setdefault("evidence_refs", []).append({"folder": path.parent.name})
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "json", str(video_path)],
        check=True, text=True, capture_output=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    video_size = (int(stream["width"]), int(stream["height"]))
    result = list(events)
    matched_indices: dict[int, int] = {}
    for action in missing_candidates:
        action_id = action["action_id"]
        timestamp = action["media_time_ms"]
        compatible = {"click", "double_click"} if action["action_kind"] == "click" else {"scroll"}
        candidates = [
            (abs(event.timestamp_ms - timestamp), i)
            for i, event in enumerate(events)
            if matched_indices.get(i, 0) < (2 if event.kind == "double_click" else 1) and event.kind in compatible
            and (event.action_id == action_id or
                 ((event.action_id is None or event.kind == "double_click")
                  and abs(event.timestamp_ms - timestamp) <= 200))
        ]
        if candidates:
            index = min(candidates)[1]
            matched_indices[index] = matched_indices.get(index, 0) + 1
            continue
        points, point_source = timeline_video_point(recording_dir, details.get(action_id, {}), video_size)
        caption = action["caption"]
        result.append(HighlightEvent(
            kind=action["action_kind"], timestamp_ms=timestamp, label=caption,
            points=points, action_id=action_id, action_kind=action["action_kind"],
            action_caption=caption, action_delta_ms=0, image_action_caption=caption,
            image_action_source="trajectory_exact_action", point_source=point_source,
        ))
    return sorted(result, key=lambda event: (event.timestamp_ms, event.kind))


def timeline_video_point(
    recording_dir: Path, detail: dict[str, Any], video_size: tuple[int, int]
) -> tuple[tuple[tuple[int, int], ...], str]:
    """Map capture coordinates through explicit frame geometry; never guess global pixels."""
    coordinates = detail.get("coordinates") or {}
    geometry_path = recording_dir / "video_geometry.json"
    geometry = json.loads(geometry_path.read_text(encoding="utf-8")) if geometry_path.exists() else {}
    for ref in detail.get("evidence_refs", []):
        folder_name = ref.get("folder")
        if not isinstance(folder_name, str) or Path(folder_name).name != folder_name:
            continue
        folder = recording_dir / folder_name
        relative = coordinates.get("screenshot_rel")
        if relative and relative.get("coordinate_space") == "artifact_px":
            screenshot = folder / "screenshot.png"
            if screenshot.exists():
                with Image.open(screenshot) as image:
                    x = relative["x"] * video_size[0] / image.width
                    y = relative["y"] * video_size[1] / image.height
                source = "artifact_px_to_video_px"
            else:
                continue
        else:
            point = coordinates.get("screen_abs")
            appshot = folder / "system_appshot.json"
            if not point or point.get("coordinate_space") != "macos_global" or not appshot.exists():
                continue
            region = geometry.get("capture_region") or json.loads(appshot.read_text(encoding="utf-8")).get("selected_region", {})
            if region.get("coordinate_space") != "macos_global" or not region.get("width") or not region.get("height"):
                continue
            x = (point["x"] - region["x"]) * video_size[0] / region["width"]
            y = (point["y"] - region["y"]) * video_size[1] / region["height"]
            source = "macos_global_via_selected_region_to_video_px"
            if geometry.get("capture_region"):
                source = "macos_global_via_video_geometry_to_video_px"
        if 0 <= x < video_size[0] and 0 <= y < video_size[1]:
            return ((min(round(x), video_size[0] - 1), min(round(y), video_size[1] - 1)),), source
    return (), "unavailable_or_outside_capture"


def ffprobe_duration_seconds(video_path: Path) -> float | None:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        result = subprocess.run(command, check=True, text=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def extract_frame(video_path: Path, timestamp_ms: int, fast_seek: bool) -> Image.Image:
    seconds = max(0.0, timestamp_ms / 1000.0)
    seek = f"{seconds:.3f}"
    if fast_seek:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            seek,
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-",
        ]
    else:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-ss",
            seek,
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-",
        ]
    try:
        result = subprocess.run(command, check=True, capture_output=True)
    except FileNotFoundError as exc:
        raise SystemExit("ffmpeg is required but was not found on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"ffmpeg failed at {seek}s: {stderr}") from exc
    if not result.stdout:
        raise RuntimeError(f"ffmpeg returned no frame at {seek}s")
    return Image.open(io.BytesIO(result.stdout)).convert("RGBA")


def load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def wrap_label_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [text]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = word
        else:
            lines.append(word)
            current = ""
        if len(lines) >= 4:
            break
    if current and len(lines) < 4:
        lines.append(current)
    if len(lines) == 4:
        joined_used = " ".join(lines)
        if len(joined_used) < len(text):
            lines[-1] = trim_to_width(draw, lines[-1] + "...", font, max_width)
    return lines


def trim_to_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    value = text
    while value:
        bbox = draw.textbbox((0, 0), value, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return value
        value = value[:-4].rstrip() + "..."
        if value == "...":
            return value
    return text


def draw_label(draw: ImageDraw.ImageDraw, text: str, image_size: tuple[int, int], accent: tuple[int, int, int]) -> None:
    font = load_font(max(18, min(image_size) // 46))
    padding = max(12, min(image_size) // 90)
    margin = max(14, min(image_size) // 80)
    max_text_width = image_size[0] - margin * 2 - padding * 2
    lines = wrap_label_lines(draw, text, font, max_text_width)
    boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    widths = [box[2] - box[0] for box in boxes]
    heights = [box[3] - box[1] for box in boxes]
    line_gap = max(4, padding // 3)
    width = min(max(widths) if widths else 0, max_text_width)
    height = sum(heights) + line_gap * max(0, len(lines) - 1)
    box = (margin, margin, margin + width + padding * 2, margin + height + padding * 2)
    draw.rounded_rectangle(box, radius=10, fill=(8, 24, 32, 230), outline=accent + (255,), width=3)
    y = margin + padding
    for line, line_height in zip(lines, heights):
        draw.text((margin + padding, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_height + line_gap

def draw_click(draw: ImageDraw.ImageDraw, point: tuple[int, int], image_size: tuple[int, int]) -> None:
    x, y = point
    radius = max(28, min(image_size) // 32)
    outer = (255, 63, 84, 255)
    inner = (255, 236, 66, 255)
    shadow = (0, 0, 0, 145)
    draw.ellipse((x - radius - 4, y - radius - 4, x + radius + 4, y + radius + 4), outline=shadow, width=10)
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=outer, width=8)
    draw.ellipse((x - radius // 3, y - radius // 3, x + radius // 3, y + radius // 3), fill=inner, outline=outer, width=4)
    line = radius + 18
    draw.line((x - line, y, x + line, y), fill=outer, width=5)
    draw.line((x, y - line, x, y + line), fill=outer, width=5)


def draw_drag(draw: ImageDraw.ImageDraw, points: tuple[tuple[int, int], ...], image_size: tuple[int, int]) -> None:
    if not points:
        return
    width = max(10, min(image_size) // 140)
    shadow_width = width + 8
    if len(points) >= 2:
        draw.line(points, fill=(0, 0, 0, 150), width=shadow_width, joint="curve")
        draw.line(points, fill=(30, 190, 220, 255), width=width, joint="curve")
        for idx, (a, b) in enumerate(zip(points, points[1:])):
            if idx % max(1, len(points) // 10) == 0:
                draw_arrow_head(draw, a, b, width * 2)
    draw_marker(draw, points[0], image_size, "START", (46, 204, 113))
    draw_marker(draw, points[-1], image_size, "END", (255, 63, 84))


def draw_arrow_head(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], size: int) -> None:
    sx, sy = start
    ex, ey = end
    angle = math.atan2(ey - sy, ex - sx)
    if abs(ex - sx) + abs(ey - sy) < 2:
        return
    left = (ex - size * math.cos(angle - math.pi / 6), ey - size * math.sin(angle - math.pi / 6))
    right = (ex - size * math.cos(angle + math.pi / 6), ey - size * math.sin(angle + math.pi / 6))
    draw.polygon([(ex, ey), left, right], fill=(30, 190, 220, 255))


def draw_marker(
    draw: ImageDraw.ImageDraw,
    point: tuple[int, int],
    image_size: tuple[int, int],
    label: str,
    color: tuple[int, int, int],
) -> None:
    x, y = point
    radius = max(18, min(image_size) // 48)
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color + (230,), outline=(255, 255, 255, 255), width=4)
    font = load_font(max(15, min(image_size) // 52))
    bbox = draw.textbbox((0, 0), label, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    tx = min(max(10, x + radius + 10), image_size[0] - text_w - 22)
    ty = min(max(10, y - text_h // 2 - 8), image_size[1] - text_h - 18)
    draw.rounded_rectangle((tx - 8, ty - 6, tx + text_w + 8, ty + text_h + 8), radius=7, fill=(8, 24, 32, 230))
    draw.text((tx, ty), label, font=font, fill=(255, 255, 255, 255))


def draw_key_frame(draw: ImageDraw.ImageDraw, image_size: tuple[int, int]) -> None:
    margin = max(18, min(image_size) // 80)
    draw.rectangle((margin, margin, image_size[0] - margin, image_size[1] - margin), outline=(255, 204, 64, 255), width=8)


def render_event(
    image: Image.Image,
    event: HighlightEvent,
    frame_time_ms: int,
) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    label = f"{event.label} | frame {format_time(frame_time_ms)}"
    action_caption = event.image_action_caption or event.action_caption
    if action_caption is not None:
        delta = f"{event.action_delta_ms:+d}ms" if event.action_delta_ms is not None else "matched"
        label = f"{label} | Action: {action_caption} ({delta})"
    if event.kind == "click":
        draw_label(draw, label, image.size, (255, 63, 84))
        if event.points:
            draw_click(draw, event.points[0], image.size)
    elif event.kind == "double_click":
        draw_label(draw, label, image.size, (255, 126, 36))
        if event.points:
            draw_click(draw, event.points[0], image.size)
            draw_marker(draw, event.points[0], image.size, "2x", (255, 126, 36))
    elif event.kind == "drag":
        draw_label(draw, label, image.size, (30, 190, 220))
        draw_drag(draw, event.points, image.size)
    elif event.kind == "key":
        draw_label(draw, label, image.size, (255, 204, 64))
        draw_key_frame(draw, image.size)
    elif event.kind == "typing":
        draw_label(draw, label, image.size, (144, 119, 255))
        draw_key_frame(draw, image.size)
    elif event.kind == "scroll":
        draw_label(draw, label, image.size, (30, 190, 220))
        if event.points:
            draw_marker(draw, event.points[0], image.size, "Scroll", (30, 190, 220))
    else:
        draw_label(draw, label, image.size, (255, 255, 255))
    return Image.alpha_composite(image, overlay).convert("RGB")


def event_manifest(event: HighlightEvent, output_path: Path, frame_time_ms: int) -> dict[str, Any]:
    image_action_caption = event.image_action_caption or event.action_caption
    return {
        "image": output_path.name,
        "kind": event.kind,
        "timestamp_ms": event.timestamp_ms,
        "timestamp": format_time(event.timestamp_ms),
        "frame_time_ms": frame_time_ms,
        "frame_time": format_time(frame_time_ms),
        "start_ms": event.start_ms,
        "end_ms": event.end_ms,
        "points": [{"x": x, "y": y} for x, y in event.points],
        "point_source": event.point_source,
        "label": event.label,
        "button": event.button,
        "button_name": button_name(event.button),
        "raw_messages": list(event.raw_messages),
        "action_id": event.action_id,
        "action_kind": event.action_kind,
        "action_caption": image_action_caption,
        "action_delta_ms": event.action_delta_ms,
        "action_caption_source": event.image_action_source,
        "trajectory_action_caption": event.action_caption,
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def image_action_row(index: int, event: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": index,
        "image": event.get("image"),
        "time_ms": event.get("timestamp_ms"),
        "time": event.get("timestamp"),
        "frame_time_ms": event.get("frame_time_ms"),
        "frame_time": event.get("frame_time"),
        "event_kind": event.get("kind"),
        "keylog_label": event.get("label"),
        "button": event.get("button"),
        "button_name": event.get("button_name"),
        "action_id": event.get("action_id"),
        "action_kind": event.get("action_kind"),
        "action_caption": event.get("action_caption"),
        "action_delta_ms": event.get("action_delta_ms"),
        "action_caption_source": event.get("action_caption_source"),
        "trajectory_action_caption": event.get("trajectory_action_caption"),
        "points": event.get("points", []),
        "raw_messages": event.get("raw_messages", []),
    }


def write_image_action_outputs(output_dir: Path, manifest: dict[str, Any]) -> None:
    events = [event for event in manifest.get("events", []) if isinstance(event, dict)]
    rows = [image_action_row(index, event) for index, event in enumerate(events, start=1)]
    write_jsonl(output_dir / "actions.jsonl", rows)
    (output_dir / "image_text_trajectory.md").write_text(
        build_image_text_trajectory(manifest, rows),
        encoding="utf-8",
    )


def build_image_text_trajectory(manifest: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Image/Text Trajectory",
        "",
        f"Recording: `{manifest.get('recording_dir', '')}`",
        f"Keylog: `{manifest.get('keylog', '')}`",
        f"Video: `{manifest.get('video', '')}`",
        f"Frame offset: `{manifest.get('frame_offset_ms', 0)}ms`",
        f"Events: `{len(rows)}`",
        "",
    ]
    for row in rows:
        index = int(row.get("index") or 0)
        image = str(row.get("image") or "")
        event_kind = str(row.get("event_kind") or "event")
        time_text = str(row.get("time") or "")
        action_caption = row.get("action_caption")
        action_delta = row.get("action_delta_ms")
        caption_source = row.get("action_caption_source")
        trajectory_caption = row.get("trajectory_action_caption")
        button = row.get("button_name") or row.get("button")
        action_text = str(action_caption) if action_caption else "(no matched trajectory action)"
        delta_text = f"{int(action_delta):+d}ms" if isinstance(action_delta, int) else "unmatched"
        lines.extend(
            [
                f"## {index:04d} {time_text} {event_kind}",
                "",
                f"- Image: `{image}`",
                f"- Keylog: {row.get('keylog_label') or ''}",
                f"- Button: {button or 'n/a'}",
                f"- Action: {action_text}",
                f"- Action delta: `{delta_text}`",
                f"- Action source: `{caption_source or 'unmatched'}`",
            ]
        )
        if trajectory_caption and trajectory_caption != action_caption:
            lines.append(f"- Raw trajectory action: {trajectory_caption}")
        lines.extend(["", f"![{index:04d} {event_kind}]({image})", ""])
    return "\n".join(lines)


def clean_previous_outputs(output_dir: Path) -> None:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    events = manifest.get("events")
    if not isinstance(events, list):
        return
    for event in events:
        if not isinstance(event, dict):
            continue
        image_name = event.get("image")
        if not isinstance(image_name, str):
            continue
        image_path = output_dir / image_name
        try:
            image_path.relative_to(output_dir)
        except ValueError:
            continue
        if image_path.is_file() and image_path.suffix.lower() == ".png":
            image_path.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording_dir", type=Path, help="WorkRecorder recording export directory")
    parser.add_argument("--keylog", type=Path, default=None, help="Override keylog.jsonl path")
    parser.add_argument("--video", type=Path, default=None, help="Override video.mp4 path")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory, default: recording/images")
    parser.add_argument(
        "--frame-offset-ms",
        type=int,
        default=0,
        help="Offset applied when extracting frames. Use -100 for 100ms before each event.",
    )
    parser.add_argument(
        "--typing-gap-ms",
        type=int,
        default=900,
        help="Merge typing key presses separated by at most this many ms.",
    )
    parser.add_argument(
        "--drag-click-window-ms",
        type=int,
        default=800,
        help="Suppress a click if a drag starts at the same point within this window.",
    )
    parser.add_argument(
        "--double-click-window-ms",
        type=int,
        default=200,
        help="Merge two same-button same-point clicks at most this many ms apart into one double_click event.",
    )
    parser.add_argument(
        "--action-match-window-ms",
        type=int,
        default=750,
        help="Overlay the nearest trajectory action when it is within this many ms. Use 0 to disable.",
    )
    parser.add_argument("--redact-typing", action="store_true", help="Do not print typed key labels on image banners.")
    parser.add_argument("--fast-seek", action="store_true", help="Use faster but less exact ffmpeg seeking.")
    parser.add_argument("--keep-existing", action="store_true", help="Do not remove images listed in an existing manifest.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    recording_dir = args.recording_dir.expanduser().resolve()
    keylog_path = args.keylog.expanduser().resolve() if args.keylog else recording_dir / "keylog.jsonl"
    video_path = args.video.expanduser().resolve() if args.video else recording_dir / "video.mp4"
    output_dir = args.output_dir.expanduser().resolve() if args.output_dir else recording_dir / "images"

    if not keylog_path.exists():
        raise SystemExit(f"keylog not found: {keylog_path}")
    if not video_path.exists():
        raise SystemExit(f"video not found: {video_path}")

    entries = read_keylog(keylog_path)
    events = build_events(
        entries,
        typing_gap_ms=args.typing_gap_ms,
        drag_click_window_ms=args.drag_click_window_ms,
        double_click_window_ms=args.double_click_window_ms,
        redact_typing=args.redact_typing,
    )
    if args.action_match_window_ms > 0:
        events = annotate_events_with_actions(
            events,
            load_action_overlays(recording_dir),
            match_window_ms=args.action_match_window_ms,
        )
    events = supplement_timeline_events(recording_dir, video_path, events)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not args.keep_existing:
        clean_previous_outputs(output_dir)

    duration_seconds = ffprobe_duration_seconds(video_path)
    duration_ms = int(duration_seconds * 1000) if duration_seconds is not None else None
    manifest: dict[str, Any] = {
        "recording_dir": str(recording_dir),
        "keylog": str(keylog_path),
        "video": str(video_path),
        "frame_offset_ms": args.frame_offset_ms,
        "event_count": len(events),
        "events": [],
    }

    for idx, event in enumerate(events, start=1):
        frame_time_ms = max(0, event.timestamp_ms + args.frame_offset_ms)
        if duration_ms is not None:
            frame_time_ms = min(frame_time_ms, max(0, duration_ms - 1))
        filename = f"{idx:04d}_{event.kind}_{frame_time_ms:08d}ms_{safe_name(event.label)[:48]}.png"
        output_path = output_dir / filename
        frame = extract_frame(video_path, frame_time_ms, fast_seek=args.fast_seek)
        rendered = render_event(frame, event, frame_time_ms)
        rendered.save(output_path)
        manifest["events"].append(event_manifest(event, output_path, frame_time_ms))

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_image_action_outputs(output_dir, manifest)

    print(f"Wrote {len(events)} highlighted image(s) to {output_dir}")
    print(f"Wrote manifest to {manifest_path}")
    print(f"Wrote image action timeline to {output_dir / 'actions.jsonl'}")
    print(f"Wrote image/text trajectory to {output_dir / 'image_text_trajectory.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
