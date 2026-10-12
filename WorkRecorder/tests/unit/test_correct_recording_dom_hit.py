from __future__ import annotations

import json
from pathlib import Path

from scripts.correct_recording_dom_hit import (
    _project_root,
    apply_correction,
    build_parser,
    mode_rebuild_commands,
    nearest_sidecar_target,
    parse_time_pair,
    resolve_recording_dir,
    select_action_step,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_nearest_sidecar_target_selects_reviewed_vm_click(tmp_path: Path) -> None:
    path = tmp_path / "vm_clicks.jsonl"
    _write_jsonl(
        path,
        [
            {
                "media_time_ms": 73304,
                "a11y": {
                    "role": "push button",
                    "name": "Review again",
                    "bbox": [600, 706, 136, 42],
                },
            }
        ],
    )

    row, delta_ms, dom_hit = nearest_sidecar_target(
        path,
        media_time_ms=73298,
        max_delta_ms=500,
    )

    assert row["media_time_ms"] == 73304
    assert delta_ms == 6
    assert dom_hit == {
        "role": "push button",
        "name": "Review again",
        "bbox": [600, 706, 136, 42],
    }


def test_nearest_sidecar_target_can_select_raw_click_dom(tmp_path: Path) -> None:
    path = tmp_path / "vm_clicks.jsonl"
    _write_jsonl(
        path,
        [
            {
                "media_time_ms": 18756,
                "dom": {
                    "tag": "SPAN",
                    "text": "Pam Beesly",
                    "rect": [628, 70, 538, 21],
                },
                "a11y": {
                    "role": "entry",
                    "name": "Subject",
                    "bbox": [601, 239, 648, 29],
                },
            }
        ],
    )

    _, delta_ms, dom_hit = nearest_sidecar_target(
        path,
        media_time_ms=18756,
        max_delta_ms=10,
        sidecar_target="dom",
    )

    assert delta_ms == 0
    assert dom_hit == {
        "tag": "SPAN",
        "text": "Pam Beesly",
        "rect": [628, 70, 538, 21],
    }


def test_nearest_sidecar_target_can_accept_generic_raw_event(tmp_path: Path) -> None:
    path = tmp_path / "vm_events.jsonl"
    _write_jsonl(
        path,
        [
            {
                "media_time_ms": 138875,
                "role": "document web",
                "name": "SprintBoard",
                "bbox": [66, 183, 1215, 617],
            }
        ],
    )

    _, delta_ms, dom_hit = nearest_sidecar_target(
        path,
        media_time_ms=138875,
        max_delta_ms=10,
        sidecar_target="raw",
    )

    assert delta_ms == 0
    assert dom_hit == {
        "role": "document web",
        "name": "SprintBoard",
        "bbox": [66, 183, 1215, 617],
    }


def test_parser_accepts_independent_source_media_time() -> None:
    args = build_parser().parse_args(
        [
            "/tmp/recording",
            "--media-time-ms",
            "32468",
            "--from-sidecar",
            "vm_clicks",
            "--source-media-time-ms",
            "30120",
        ]
    )

    assert args.media_time_ms == 32468
    assert args.source_media_time_ms == 30120


def test_parser_accepts_multiple_time_pairs() -> None:
    args = build_parser().parse_args(
        [
            "/tmp/recording",
            "--time-pair",
            "91762:91767",
            "--time-pair",
            "95000:95004",
            "--from-sidecar",
            "vm_events",
        ]
    )

    assert args.time_pair == [(91762, 91767), (95000, 95004)]
    assert parse_time_pair("1:2") == (1, 2)


def test_resolve_recording_dir_selects_requested_mode(tmp_path: Path) -> None:
    task_dir = tmp_path / "videos_revise_time" / "cua_only-f011"
    normal_dir = task_dir / "cua_only-f011+normal"
    normal_dir.mkdir(parents=True)
    (normal_dir / "trajectory.json").write_text("{}", encoding="utf-8")

    recording_dir, mode, task_name = resolve_recording_dir(task_dir, mode="normal")

    assert recording_dir == normal_dir
    assert mode == "normal"
    assert task_name == "cua_only-f011"


def test_project_root_supports_original_and_revised_video_directories(tmp_path: Path) -> None:
    for directory_name in ("videos", "videos_revise_time"):
        recording_dir = tmp_path / directory_name / "task" / "task+event_only"

        assert _project_root(recording_dir) == tmp_path


def test_mode_rebuild_commands_target_only_selected_mode(tmp_path: Path) -> None:
    pipeline_script = tmp_path / "code" / "highlight_then_benchmark.py"
    recording_dir = tmp_path / "videos_revise_time" / "cua_only-f011" / "cua_only-f011+event_only"
    output_root = tmp_path / "benchmark_revise_time"

    commands = mode_rebuild_commands(
        pipeline_script=pipeline_script,
        recording_dir=recording_dir,
        benchmark_output_root=output_root,
        task_name="cua_only-f011",
        mode="event_only",
    )

    assert commands[0][1].endswith("keylog_highlight_frames.py")
    assert commands[0][2] == str(recording_dir)
    assert commands[1][1].endswith("raw_to_benchmark.py")
    assert commands[1][commands[1].index("--output-root") + 1] == str(output_root / "cua_only-f011")
    assert commands[1][commands[1].index("--run-id") + 1] == "event_only"
    assert commands[1][commands[1].index("--condition") + 1] == "cua_only"


def test_apply_correction_updates_source_of_truth_files(tmp_path: Path) -> None:
    recording_dir = tmp_path / "videos_revise_time" / "cua_only-f002"
    keyframe_dir = recording_dir / "0042_frame"
    keyframe_dir.mkdir(parents=True)
    action_id = "act_review"
    trajectory = {
        "steps": [
            {
                "kind": "action",
                "action_id": action_id,
                "action_kind": "click",
                "sequence_index": 68,
                "occurred_at": "2026-07-09T12:55:34Z",
                "media_time_ms": 73298,
                "safe_caption": "Left Click check box - Wrong",
                "dom_hit": {"role": "check box", "name": "Wrong"},
                "dom_hit_label": "check box · Wrong",
                "action_summary": {"target": {"display_label": "check box - Wrong"}},
            }
        ]
    }
    (recording_dir / "trajectory.json").write_text(json.dumps(trajectory), encoding="utf-8")
    _write_jsonl(
        recording_dir / "dom_hits.jsonl",
        [
            {
                "action_id": action_id,
                "status": "hit",
                "dom_hit": {"role": "check box", "name": "Wrong"},
                "source": "event_log_backfill",
                "event_seq": 30,
            }
        ],
    )
    (keyframe_dir / "actions.json").write_text(
        json.dumps(
            [
                {
                    "action_id": action_id,
                    "kind": "click",
                    "caption": "Click check box - Wrong",
                    "dom_hit": {"role": "check box", "name": "Wrong"},
                }
            ]
        ),
        encoding="utf-8",
    )
    (recording_dir / "recording.json").write_text("{}", encoding="utf-8")
    (recording_dir / "summary.md").write_text("# old\n", encoding="utf-8")
    corrected = {
        "role": "push button",
        "name": "Review again",
        "bbox": [600, 706, 136, 42],
    }

    apply_correction(
        recording_dir,
        action_id=action_id,
        dom_hit=corrected,
        source_sidecar="vm_clicks",
        source_record={"media_time_ms": 73304},
        source_delta_ms=6,
    )

    step = select_action_step(
        json.loads((recording_dir / "trajectory.json").read_text()),
        action_id=action_id,
        media_time_ms=None,
    )
    assert step["safe_caption"] == "Click push button - Review again"
    assert step["action_summary"]["target"]["display_label"] == "push button - Review again"
    dom_row = json.loads((recording_dir / "dom_hits.jsonl").read_text().splitlines()[0])
    assert dom_row["source"] == "click_log_backfill"
    assert dom_row["backfill_delta_ms"] == 6
    assert "manual_source" not in dom_row
    assert "event_seq" not in dom_row
    action = json.loads((keyframe_dir / "actions.json").read_text())[0]
    assert action["caption"] == "Click push button - Review again"
    assert (recording_dir / "manual_dom_corrections.jsonl").is_file()


def test_explicit_correction_does_not_add_source_marker(tmp_path: Path) -> None:
    recording_dir = tmp_path / "videos_revise_time" / "task"
    recording_dir.mkdir(parents=True)
    action_id = "act_explicit"
    (recording_dir / "trajectory.json").write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "kind": "action",
                        "action_id": action_id,
                        "action_kind": "click",
                        "sequence_index": 0,
                        "occurred_at": "2026-07-09T12:55:34Z",
                        "media_time_ms": 1000,
                        "safe_caption": "Click",
                        "action_summary": {"target": None},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        recording_dir / "dom_hits.jsonl",
        [{"action_id": action_id, "status": "miss", "errors": ["no_vm_a11y_record"]}],
    )
    (recording_dir / "recording.json").write_text("{}", encoding="utf-8")
    (recording_dir / "summary.md").write_text("# old\n", encoding="utf-8")

    apply_correction(
        recording_dir,
        action_id=action_id,
        dom_hit={"role": "push button", "name": "Reviewed target"},
        source_sidecar=None,
        source_record=None,
        source_delta_ms=None,
    )

    dom_row = json.loads((recording_dir / "dom_hits.jsonl").read_text().splitlines()[0])
    assert dom_row["status"] == "hit"
    assert "source" not in dom_row
    assert "manual_source" not in dom_row
