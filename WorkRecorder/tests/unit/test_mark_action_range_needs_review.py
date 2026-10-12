from __future__ import annotations

import json
from pathlib import Path

from scripts.mark_action_range_needs_review import (
    DEFAULT_CAPTION,
    _default_benchmark_output_root,
    _project_root,
    apply_needs_review_actions,
    apply_needs_review_range,
    parse_time_caption,
    select_action_steps,
    select_time_caption_steps,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_source_root_selects_matching_benchmark_tree(tmp_path: Path) -> None:
    original = tmp_path / "videos" / "task" / "task+normal"
    revised = tmp_path / "videos_revise_time" / "task" / "task+normal"

    assert _project_root(original) == tmp_path
    assert _project_root(revised) == tmp_path
    assert _default_benchmark_output_root(original, project_root=tmp_path) == tmp_path / "benchmark"
    assert _default_benchmark_output_root(revised, project_root=tmp_path) == tmp_path / "benchmark_revise_time"


def test_apply_needs_review_range_clears_dom_and_updates_captions(tmp_path: Path) -> None:
    recording_dir = tmp_path / "videos_revise_time" / "task" / "task+normal"
    frame_dir = recording_dir / "0001_frame"
    frame_dir.mkdir(parents=True)
    steps = [
        {
            "kind": "action",
            "action_id": "before",
            "action_kind": "click",
            "media_time_ms": 68000,
            "safe_caption": "Left Click button - Before",
        },
        {
            "kind": "action",
            "action_id": "inside",
            "action_kind": "click",
            "media_time_ms": 69000,
            "safe_caption": "Left Click button - Wrong",
            "dom_hit": {"role": "button", "name": "Wrong"},
            "dom_hit_label": "button · Wrong",
            "coordinates": {"screenshot_rel": {"x": 1, "y": 2}},
            "action_summary": {
                "action_id": "inside",
                "action_kind": "click",
                "target": {"status": "resolved", "needs_review": False},
            },
        },
    ]
    (recording_dir / "trajectory.json").write_text(
        json.dumps({"steps": steps}),
        encoding="utf-8",
    )
    _write_jsonl(
        recording_dir / "dom_hits.jsonl",
        [
            {"action_id": "before", "status": "hit", "dom_hit": {"name": "Before"}},
            {
                "action_id": "inside",
                "status": "hit",
                "dom_hit": {"role": "button", "name": "Wrong"},
                "source": "event_watch",
            },
        ],
    )
    (frame_dir / "actions.json").write_text(
        json.dumps(
            [
                {
                    "action_id": "inside",
                    "caption": "Click button - Wrong",
                    "dom_hit": {"role": "button", "name": "Wrong"},
                    "dom_hit_label": "button · Wrong",
                }
            ]
        ),
        encoding="utf-8",
    )
    (recording_dir / "recording.json").write_text(
        json.dumps({"dom_hits_hit_count": 2}),
        encoding="utf-8",
    )
    (recording_dir / "summary.md").write_text("# old\n", encoding="utf-8")

    trajectory = json.loads((recording_dir / "trajectory.json").read_text())
    matches = select_action_steps(
        trajectory,
        start_media_time_ms=68228,
        end_media_time_ms=71318,
    )
    apply_needs_review_range(
        recording_dir,
        action_ids={str(step["action_id"]) for step in matches},
        start_media_time_ms=68228,
        end_media_time_ms=71318,
        caption=DEFAULT_CAPTION,
    )

    updated = json.loads((recording_dir / "trajectory.json").read_text())
    inside = next(step for step in updated["steps"] if step["action_id"] == "inside")
    assert inside["safe_caption"] == DEFAULT_CAPTION
    assert inside["needs_review"] is True
    assert inside["action_summary"]["target"]["needs_review"] is True
    assert "dom_hit" not in inside
    assert "dom_hit_label" not in inside

    dom_rows = [
        json.loads(line)
        for line in (recording_dir / "dom_hits.jsonl").read_text().splitlines()
    ]
    inside_dom = next(row for row in dom_rows if row["action_id"] == "inside")
    assert inside_dom == {
        "action_id": "inside",
        "status": "miss",
        "errors": ["target_needs_review"],
    }
    action = json.loads((frame_dir / "actions.json").read_text())[0]
    assert action["caption"] == DEFAULT_CAPTION
    assert action["needs_review"] is True
    assert "dom_hit" not in action
    assert json.loads((recording_dir / "recording.json").read_text())["dom_hits_hit_count"] == 1


def test_individual_times_support_different_captions(tmp_path: Path) -> None:
    recording_dir = tmp_path / "videos_revise_time" / "task" / "task+normal"
    recording_dir.mkdir(parents=True)
    trajectory = {
        "steps": [
            {
                "kind": "action",
                "action_id": "first",
                "action_kind": "click",
                "media_time_ms": 1000,
                "safe_caption": "Wrong first",
            },
            {
                "kind": "action",
                "action_id": "second",
                "action_kind": "click",
                "media_time_ms": 2000,
                "safe_caption": "Wrong second",
            },
        ]
    }
    (recording_dir / "trajectory.json").write_text(json.dumps(trajectory), encoding="utf-8")
    (recording_dir / "dom_hits.jsonl").write_text("", encoding="utf-8")
    (recording_dir / "recording.json").write_text("{}", encoding="utf-8")
    (recording_dir / "summary.md").write_text("# old\n", encoding="utf-8")

    parsed = [parse_time_caption("1000:Left Click(target needs review)"), parse_time_caption("2000:Right Click")]
    matches, captions = select_time_caption_steps(trajectory, time_captions=parsed)
    apply_needs_review_actions(
        recording_dir,
        captions_by_action=captions,
        selection={"type": "individual"},
    )

    assert [step["action_id"] for step in matches] == ["first", "second"]
    revised = json.loads((recording_dir / "trajectory.json").read_text())
    assert revised["steps"][0]["safe_caption"] == "Left Click(target needs review)"
    assert revised["steps"][1]["safe_caption"] == "Right Click"
