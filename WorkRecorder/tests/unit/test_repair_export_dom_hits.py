"""Unit tests for recording export DOM-hit repair helpers."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.repair_export_dom_hits import _load_dom_hits, _repair_recording_meta, _repair_trajectory, _repair_summary


def test_repair_trajectory_clears_review_from_root_dom_hits(tmp_path: Path) -> None:
    (tmp_path / "dom_hits.jsonl").write_text(
        json.dumps(
            {
                "action_id": "act_click",
                "status": "hit",
                "dom_hit": {"role": "push button", "name": "Save"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "recording.json").write_text(
        json.dumps({"session_id": "acs_demo", "dom_hits_count": 1, "dom_hits_hit_count": 0}),
        encoding="utf-8",
    )
    trajectory = {
        "steps": [
            {
                "kind": "action",
                "action_id": "act_click",
                "action_kind": "click",
                "media_time_ms": 600,
                "safe_caption": "点击（目标待确认）",
                "needs_review": True,
                "readiness": {"state": "needs_review", "review_item_count": 1},
                "action_summary": {
                    "target": {
                        "status": "ambiguous",
                        "display_label": "目标待确认",
                        "needs_review": True,
                    }
                },
            }
        ]
    }
    (tmp_path / "trajectory.json").write_text(json.dumps(trajectory), encoding="utf-8")

    dom_by_action = _load_dom_hits(tmp_path)
    _repair_trajectory(tmp_path, dom_by_action, {})
    _repair_recording_meta(tmp_path, dom_by_action)

    repaired = json.loads((tmp_path / "trajectory.json").read_text(encoding="utf-8"))
    step = repaired["steps"][0]
    assert step["safe_caption"] == "Click push button - Save"
    assert step["needs_review"] is False
    assert step["readiness"]["state"] == "ready"
    assert step["action_summary"]["target"]["status"] == "resolved"
    assert step["action_summary"]["target"]["display_label"] == "push button - Save"
    assert step["action_summary"]["target"]["needs_review"] is False
    recording = json.loads((tmp_path / "recording.json").read_text(encoding="utf-8"))
    assert recording["dom_hits_hit_count"] == 1


def test_repair_summary_renders_english_from_structured_steps(tmp_path: Path) -> None:
    recording = {
        "session_id": "acs_demo",
        "mode": "recording_session",
        "started_at": "2026-06-30T09:52:44.726259+00:00",
        "ended_at": "2026-06-30T09:53:36.236736+00:00",
        "duration_ms": 44_100,
        "keyframe_count": 2,
        "action_count": 1,
        "control_count": 1,
    }
    trajectory = {
        "session_id": "acs_demo",
        "duration_ms": 44_100,
        "steps": [
            {
                "kind": "control",
                "media_time_ms": 0,
                "control_kind": "start_segment",
                "safe_caption": "开始片段",
            },
            {
                "kind": "keyframe",
                "media_time_ms": 357,
                "keyframe_role": "start",
                "safe_caption": "开始录制",
            },
            {
                "kind": "action",
                "media_time_ms": 2_655,
                "action_kind": "click",
                "safe_caption": "点击 page tab · Hooliwork",
                "dom_hit": {"role": "page tab", "name": "Hooliwork"},
            },
            {
                "kind": "keyframe",
                "media_time_ms": 2_655,
                "keyframe_role": "result",
                "safe_caption": "动作结果",
            },
        ],
    }
    (tmp_path / "recording.json").write_text(json.dumps(recording), encoding="utf-8")
    (tmp_path / "trajectory.json").write_text(json.dumps(trajectory), encoding="utf-8")
    (tmp_path / "summary.md").write_text("# old", encoding="utf-8")
    (tmp_path / "keylog.jsonl").write_text("", encoding="utf-8")

    _repair_summary(tmp_path)

    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "# Recording Summary - acs_demo" in summary
    assert "- Counts: 2 keyframes, 1 action, 1 control" in summary
    assert "- Input log: keylog.jsonl" in summary
    assert "## Timeline" in summary
    assert "[control] Segment started" in summary
    assert "[keyframe] Recording started" in summary
    assert "[action] Click page tab - Hooliwork" in summary
    assert "[keyframe] Action result" in summary
    assert not any("\u4e00" <= char <= "\u9fff" for char in summary)
