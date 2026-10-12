from __future__ import annotations

import json
from pathlib import Path

from scripts.revise_drag_start_anchor import (
    choose_target_match,
    find_drag_anchor,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_find_drag_anchor_matches_action_by_drag_end(tmp_path: Path) -> None:
    keylog = tmp_path / "keylog.jsonl"
    _write_jsonl(
        keylog,
        [
            {"timestamp": "00:00:58.492", "message": "DragStart at (1624, 1444)"},
            {"timestamp": "00:01:02.493", "message": "LDragEnd: from (1624, 1444) to (2322, 1198), distance (698, -246)"},
        ],
    )

    anchor = find_drag_anchor(keylog, action_time_ms=62_493, max_delta_ms=10)

    assert anchor.start_ms == 58_492
    assert anchor.end_ms == 62_493
    assert anchor.start == (1624, 1444)
    assert anchor.end == (2322, 1198)
    assert anchor.button == "L"


def test_auto_target_prefers_vm_clicks_at_drag_start(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "vm_clicks.jsonl",
        [
            {
                "media_time_ms": 58_323,
                "a11y": {"role": "link", "name": "DDP-12", "bbox": [699, 668, 327, 108]},
            }
        ],
    )
    _write_jsonl(
        tmp_path / "vm_events.jsonl",
        [
            {
                "media_time_ms": 58_329,
                "role": "link",
                "name": "another event",
                "bbox": [1, 2, 3, 4],
            }
        ],
    )

    match = choose_target_match(
        tmp_path,
        start_ms=58_492,
        target_source="auto",
        max_delta_ms=750,
    )

    assert match.sidecar == "vm_clicks"
    assert match.source == "click_log_backfill"
    assert match.delta_ms == -169
    assert match.dom_hit["name"] == "DDP-12"
