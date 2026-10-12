from __future__ import annotations

import json
from pathlib import Path

from scripts.revise_legacy_recording_time import (
    format_media_time,
    infer_vm_media_offset_ms,
    rebuild_click_only_dom_hits,
    rebuild_event_only_dom_hits,
    revise_recording_dir,
)


def _trajectory() -> dict[str, object]:
    return {
        "steps": [
            {
                "kind": "action",
                "action_kind": "click",
                "occurred_at": f"2026-07-19T14:35:{second:02d}Z",
                "media_time_ms": media_time_ms,
            }
            for second, media_time_ms in ((23, 5038), (27, 8822), (31, 12274), (36, 17710))
        ]
    }


def _vm_clicks() -> list[dict[str, object]]:
    return [
        {"ts": 1784471723.861, "media_time_ms": 7027, "media_time": "00:07.027"},
        {"ts": 1784471727.662, "media_time_ms": 10828, "media_time": "00:10.828"},
        {"ts": 1784471731.107, "media_time_ms": 14273, "media_time": "00:14.273"},
        {"ts": 1784471736.558, "media_time_ms": 19724, "media_time": "00:19.724"},
    ]


def test_infer_vm_media_offset_uses_dominant_click_cluster() -> None:
    offset_ms, report = infer_vm_media_offset_ms(_trajectory(), _vm_clicks())

    assert offset_ms == 2002
    assert report["candidate_pair_count"] == 4
    assert report["dominant_pair_count"] == 4


def test_revise_recording_dir_only_changes_vm_sidecar_time(tmp_path: Path) -> None:
    recording_dir = tmp_path / "sample+normal"
    recording_dir.mkdir()
    trajectory = _trajectory()
    (recording_dir / "trajectory.json").write_text(json.dumps(trajectory), encoding="utf-8")
    rows = _vm_clicks()
    jsonl = "".join(json.dumps(row) + "\n" for row in rows)
    (recording_dir / "vm_clicks.jsonl").write_text(jsonl, encoding="utf-8")
    (recording_dir / "vm_events.jsonl").write_text(
        json.dumps({"media_time_ms": 7035, "media_time": "00:07.035"}) + "\n",
        encoding="utf-8",
    )

    report = revise_recording_dir(recording_dir)

    assert json.loads((recording_dir / "trajectory.json").read_text(encoding="utf-8")) == trajectory
    revised_click = json.loads((recording_dir / "vm_clicks.jsonl").read_text().splitlines()[0])
    revised_event = json.loads((recording_dir / "vm_events.jsonl").read_text().splitlines()[0])
    assert revised_click["media_time_ms"] == 5025
    assert revised_click["media_time"] == "00:00:05.025"
    assert revised_event["media_time_ms"] == 5033
    assert report["offset_subtracted_ms"] == 2002


def test_format_media_time_supports_hours() -> None:
    assert format_media_time(3_723_004) == "01:02:03.004"


def test_rebuild_click_only_targets_uses_only_vm_clicks(tmp_path: Path) -> None:
    recording_dir = tmp_path / "sample+click_only"
    recording_dir.mkdir()
    steps = [
        {
            "kind": "action",
            "action_id": "act_hit",
            "action_kind": "click",
            "sequence_index": 0,
            "occurred_at": "2026-07-19T14:35:23Z",
            "media_time_ms": 5038,
            "safe_caption": "Click event target",
            "dom_hit": {"role": "button", "name": "Event target"},
            "dom_hit_label": "button · Event target",
            "action_summary": {"target": {"display_label": "button - Event target"}},
        },
        {
            "kind": "action",
            "action_id": "act_miss",
            "action_kind": "click",
            "sequence_index": 1,
            "occurred_at": "2026-07-19T14:35:30Z",
            "media_time_ms": 12000,
            "safe_caption": "Click another event target",
            "dom_hit": {"role": "button", "name": "Another event target"},
            "dom_hit_label": "button · Another event target",
            "action_summary": {"target": {"display_label": "button - Another event target"}},
        },
    ]
    (recording_dir / "trajectory.json").write_text(
        json.dumps({"steps": steps}),
        encoding="utf-8",
    )
    (recording_dir / "vm_clicks.jsonl").write_text(
        json.dumps(
            {
                "ts": 1784471723.861,
                "media_time_ms": 5025,
                "a11y": {"role": "push button", "name": "Click target", "bbox": [1, 2, 30, 40]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (recording_dir / "dom_hits.jsonl").write_text("", encoding="utf-8")
    (recording_dir / "recording.json").write_text(
        json.dumps({"dom_hits_count": 2, "dom_hits_hit_count": 2}),
        encoding="utf-8",
    )
    (recording_dir / "summary.md").write_text("# old\n", encoding="utf-8")

    report = rebuild_click_only_dom_hits(recording_dir)

    rows = [json.loads(line) for line in (recording_dir / "dom_hits.jsonl").read_text().splitlines()]
    assert rows[0]["source"] == "click_log_backfill"
    assert rows[0]["dom_hit"]["name"] == "Click target"
    assert rows[1]["status"] == "miss"
    assert "source" not in rows[1]
    revised = json.loads((recording_dir / "trajectory.json").read_text(encoding="utf-8"))
    assert revised["steps"][0]["action_summary"]["target"]["display_label"] == "push button - Click target"
    assert revised["steps"][1]["action_summary"]["target"]["display_label"] is None
    assert report["hit_count"] == 1
    assert report["miss_count"] == 1


def test_rebuild_event_only_targets_uses_only_vm_events(tmp_path: Path) -> None:
    recording_dir = tmp_path / "sample+event_only"
    recording_dir.mkdir()
    steps = [
        {
            "kind": "action",
            "action_id": "act_hit",
            "action_kind": "click",
            "sequence_index": 0,
            "occurred_at": "2026-07-19T14:35:23Z",
            "media_time_ms": 5038,
            "safe_caption": "Click click-log target",
            "dom_hit": {"role": "button", "name": "Click-log target"},
            "dom_hit_label": "button · Click-log target",
            "action_summary": {"target": {"display_label": "button - Click-log target"}},
        },
        {
            "kind": "action",
            "action_id": "act_miss",
            "action_kind": "click",
            "sequence_index": 1,
            "occurred_at": "2026-07-19T14:35:30Z",
            "media_time_ms": 12000,
            "safe_caption": "Click recorded target",
            "dom_hit": {"role": "button", "name": "Recorded target"},
            "dom_hit_label": "button · Recorded target",
            "action_summary": {"target": {"display_label": "button - Recorded target"}},
        },
    ]
    (recording_dir / "trajectory.json").write_text(
        json.dumps({"steps": steps}),
        encoding="utf-8",
    )
    (recording_dir / "vm_events.jsonl").write_text(
        json.dumps(
            {
                "seq": 42,
                "ts": 1784471723.869,
                "media_time_ms": 5033,
                "role": "menu item",
                "name": "Event target",
                "bbox": [1, 2, 30, 40],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (recording_dir / "dom_hits.jsonl").write_text("", encoding="utf-8")
    (recording_dir / "recording.json").write_text(
        json.dumps({"dom_hits_count": 2, "dom_hits_hit_count": 2}),
        encoding="utf-8",
    )
    (recording_dir / "summary.md").write_text("# old\n", encoding="utf-8")

    report = rebuild_event_only_dom_hits(recording_dir)

    rows = [json.loads(line) for line in (recording_dir / "dom_hits.jsonl").read_text().splitlines()]
    assert rows[0]["source"] == "event_log_backfill"
    assert rows[0]["event_seq"] == 42
    assert rows[0]["dom_hit"]["name"] == "Event target"
    assert rows[1]["status"] == "miss"
    assert "source" not in rows[1]
    revised = json.loads((recording_dir / "trajectory.json").read_text(encoding="utf-8"))
    assert revised["steps"][0]["action_summary"]["target"]["display_label"] == "menu item - Event target"
    assert revised["steps"][1]["action_summary"]["target"]["display_label"] is None
    assert report["target_source"] == "vm_events.jsonl"
    assert report["hit_count"] == 1
    assert report["miss_count"] == 1
