from __future__ import annotations

from pathlib import Path

from scripts.revise_all_legacy_recordings import (
    benchmark_command,
    discover_tasks,
    revision_command,
)


def _recording(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "recording.json").write_text("{}", encoding="utf-8")


def test_discover_tasks_supports_direct_and_three_mode_exports(tmp_path: Path) -> None:
    _recording(tmp_path / "cua_only-f001")
    parent = tmp_path / "situated_action-f007"
    for mode in ("normal", "event_only", "click_only"):
        _recording(parent / f"situated_action-f007+{mode}")
    _recording(tmp_path / "incomplete" / "incomplete+normal")

    tasks, invalid = discover_tasks(tmp_path, patterns=[])

    assert [task.name for task in tasks] == ["cua_only-f001", "situated_action-f007"]
    assert [(path.name, reason) for path, reason in invalid] == [
        ("incomplete", "missing or duplicate modes: event_only, click_only")
    ]


def test_discover_tasks_supports_repeatable_patterns(tmp_path: Path) -> None:
    _recording(tmp_path / "cua_only-f001")
    _recording(tmp_path / "hard_app-f001")

    tasks, invalid = discover_tasks(tmp_path, patterns=["cua_*"])

    assert [task.name for task in tasks] == ["cua_only-f001"]
    assert invalid == []


def test_commands_keep_revision_and_benchmark_as_separate_phases(tmp_path: Path) -> None:
    source = tmp_path / "videos" / "task-f001"
    revised_root = tmp_path / "videos_revise_time"
    benchmark_root = tmp_path / "benchmark_revise_time"
    pipeline = tmp_path / "code" / "highlight_then_benchmark.py"

    revise = revision_command(
        task=source,
        videos_output_root=revised_root,
        benchmark_output_root=benchmark_root,
        pipeline_script=pipeline,
        overwrite=True,
    )
    benchmark = benchmark_command(
        revised_task=revised_root / source.name,
        benchmark_output_root=benchmark_root,
        pipeline_script=pipeline,
        overwrite=True,
    )

    assert "--skip-benchmark" in revise
    assert str(source) in revise
    assert str(revised_root / source.name) in benchmark
    assert str(source) not in benchmark
    assert revise[-1] == "--overwrite"
    assert benchmark[-1] == "--overwrite"
