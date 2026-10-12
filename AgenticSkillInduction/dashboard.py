"""Streamlit dashboard for NexAU skill extraction runs."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import cast

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_RUNS_ROOT = PROJECT_ROOT / "generated_skills" / "agentic_skill_induction"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from examples.agentic_skill_induction.dashboard_data import (  # noqa: E402
    RunData,
    discover_runs,
    event_rows,
    load_run,
    token_rows,
    tool_rows,
)


def _integer(mapping: dict[str, object], key: str) -> int:
    value = mapping.get(key, 0)
    return value if isinstance(value, int) else 0


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in cast(dict[object, object], value).items()}


def _format_duration(duration_ms: int) -> str:
    seconds = duration_ms / 1000
    return f"{seconds:.1f}s" if seconds < 60 else f"{seconds / 60:.1f}m"


def _run_label(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


@st.cache_data(show_spinner=False)
def _cached_load_run(path: str, summary_mtime_ns: int, events_mtime_ns: int) -> RunData:
    del summary_mtime_ns, events_mtime_ns
    return load_run(Path(path))


def _load_selected_run(path: Path) -> RunData:
    summary_path = path / "run-summary.json"
    events_path = path / "run-events.jsonl"
    return _cached_load_run(
        str(path),
        summary_path.stat().st_mtime_ns,
        events_path.stat().st_mtime_ns if events_path.exists() else 0,
    )


def _overview(run: RunData) -> None:
    summary = run.summary
    usage = _mapping(summary.get("token_usage"))
    total_tokens = _integer(usage, "total_tokens")
    input_tokens = _integer(usage, "input_tokens")
    cache_tokens = _integer(usage, "cache_read_tokens")
    model_calls = _integer(summary, "model_call_count")
    tool_calls = _integer(summary, "tool_call_count")

    columns = st.columns(6)
    columns[0].metric("Status", str(summary.get("status", "unknown")).upper())
    columns[1].metric("Duration", _format_duration(_integer(summary, "duration_ms")))
    columns[2].metric("Model calls", f"{model_calls:,}")
    columns[3].metric("Tool calls", f"{tool_calls:,}")
    columns[4].metric("Total tokens", f"{total_tokens:,}")
    columns[5].metric("Events", f"{_integer(summary, 'event_count'):,}")

    left, right = st.columns([1.15, 1])
    with left:
        st.subheader("Tool usage")
        raw_counts = _mapping(summary.get("tool_counts"))
        counts = [{"tool": name, "calls": value} for name, value in raw_counts.items() if isinstance(value, int)]
        if counts:
            st.bar_chart(pd.DataFrame(counts).set_index("tool"), horizontal=True, color="#2563eb")
        else:
            st.info("No tool calls recorded.")
    with right:
        st.subheader("Token composition")
        token_composition = pd.DataFrame(
            [
                {"category": "Input", "tokens": input_tokens},
                {"category": "Cache read", "tokens": cache_tokens},
                {"category": "Completion", "tokens": _integer(usage, "completion_tokens")},
                {"category": "Reasoning", "tokens": _integer(usage, "reasoning_tokens")},
            ]
        ).set_index("category")
        st.bar_chart(token_composition, horizontal=True, color="#0f766e")

    effective_input = input_tokens + cache_tokens
    cache_rate = cache_tokens / effective_input if effective_input else 0
    tokens_per_call = total_tokens / model_calls if model_calls else 0
    tools_per_call = tool_calls / model_calls if model_calls else 0
    st.subheader("Efficiency")
    efficiency_columns = st.columns(4)
    efficiency_columns[0].metric("Tokens / model call", f"{tokens_per_call:,.0f}")
    efficiency_columns[1].metric("Tools / model call", f"{tools_per_call:.2f}")
    efficiency_columns[2].metric("Cache share", f"{cache_rate:.1%}")
    efficiency_columns[3].metric("Input share", f"{input_tokens / total_tokens:.1%}" if total_tokens else "0%")

    with st.expander("Run identity"):
        st.json(
            {
                "model": summary.get("model"),
                "run_id": summary.get("run_id"),
                "trace_id": summary.get("trace_id"),
                "started_at": summary.get("started_at"),
                "finished_at": summary.get("finished_at"),
                "input_root": summary.get("input_root"),
                "output_root": summary.get("output_root"),
            }
        )


def _tokens(run: RunData) -> None:
    rows = token_rows(run.summary)
    if not rows:
        st.info("No per-call token usage recorded.")
        return
    frame = pd.DataFrame(rows)
    chart_columns = ["input_tokens", "cache_read_tokens", "completion_tokens", "reasoning_tokens"]
    st.subheader("Usage by model call")
    st.bar_chart(frame.set_index("call")[chart_columns], color=["#2563eb", "#0f766e", "#d97706", "#7c3aed"])
    cumulative = frame[["call", "total_tokens"]].copy()
    cumulative["cumulative_tokens"] = cumulative["total_tokens"].cumsum()
    st.subheader("Cumulative provider tokens")
    st.line_chart(cumulative.set_index("call")[["cumulative_tokens"]], color="#b42318")
    st.dataframe(frame, width="stretch", hide_index=True)


def _tools(run: RunData) -> None:
    rows = tool_rows(run.summary)
    if not rows:
        st.info("No tool calls recorded.")
        return
    table = pd.DataFrame(
        [
            {
                "#": row["index"],
                "Tool": row["name"],
                "Status": row["status"],
                "Duration (ms)": row["duration_ms"],
                "Arguments": json.dumps(row["arguments"], ensure_ascii=False),
            }
            for row in rows
        ]
    )
    st.dataframe(table, width="stretch", hide_index=True, height=440)
    labels = [f"{row['index']:02d} · {row['name']} · {row['status']}" for row in rows]
    selected_label = st.selectbox("Inspect tool call", labels)
    selected = rows[labels.index(selected_label)]
    left, right = st.columns(2)
    with left:
        st.caption("Arguments")
        st.json(selected["arguments"])
    with right:
        st.caption("Result preview")
        st.code(str(selected["result_preview"] or ""), language="text", wrap_lines=True)


def _events(run: RunData) -> None:
    rows = event_rows(run.events)
    if not rows:
        st.info("No events recorded.")
        return
    event_types = sorted({str(row["type"]) for row in rows})
    filter_columns = st.columns([2, 2, 1])
    selected_types = filter_columns[0].multiselect("Event types", event_types, default=event_types)
    query = filter_columns[1].text_input("Search details")
    row_limit = filter_columns[2].number_input("Row limit", min_value=10, max_value=5000, value=500, step=50)
    effective_limit = int(row_limit) if isinstance(row_limit, (int, float)) else 500
    filtered = [row for row in rows if str(row["type"]) in selected_types and (not query or query.lower() in str(row["detail"]).lower())][
        :effective_limit
    ]
    st.dataframe(pd.DataFrame(filtered), width="stretch", hide_index=True, height=500)
    if filtered:
        line_numbers = [int(row["line"]) for row in filtered if isinstance(row.get("line"), int)]
        selected_line = st.selectbox("Inspect raw event", line_numbers)
        raw_event = next(event for event in run.events if event.get("line_number") == selected_line)
        st.json(raw_event)


def _artifacts(run: RunData) -> None:
    if not run.artifacts:
        st.info("No generated text artifacts found.")
        return
    labels = [artifact.relative_to(run.path).as_posix() for artifact in run.artifacts]
    selected_label = st.selectbox("Artifact", labels)
    selected = run.artifacts[labels.index(selected_label)]
    content = selected.read_text(encoding="utf-8", errors="replace")
    language = {
        ".json": "json",
        ".jsonl": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".md": "markdown",
    }.get(selected.suffix.lower(), "text")
    st.code(content, language=language, line_numbers=True, wrap_lines=True)


def main() -> None:
    st.set_page_config(page_title="Skill Extraction Runs", page_icon=":material/monitoring:", layout="wide")
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.4rem; padding-bottom: 2rem; max-width: 1500px;}
        [data-testid="stMetric"] {border: 1px solid #d7dce2; padding: 0.75rem 0.9rem; border-radius: 6px;}
        [data-testid="stMetricLabel"] {font-size: 0.78rem;}
        h1, h2, h3 {letter-spacing: 0;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("Skill Extraction Runs")

    configured_root = os.environ.get("NEXAU_SKILL_RUNS_ROOT", str(DEFAULT_RUNS_ROOT))
    root_text = st.sidebar.text_input("Runs root", configured_root)
    root = Path(root_text).expanduser().resolve(strict=False)
    runs = discover_runs(root)
    if not runs:
        st.warning(f"No run-summary.json files found under {root}.")
        return
    run_labels = [_run_label(path, root) for path in runs]
    selected_label = st.sidebar.selectbox("Run", run_labels)
    if st.sidebar.button("Refresh", icon=":material/refresh:", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    selected_path = runs[run_labels.index(selected_label)]

    try:
        run = _load_selected_run(selected_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        st.error(f"Failed to load run: {exc}")
        return

    st.caption(str(run.path))
    overview_tab, tokens_tab, tools_tab, events_tab, artifacts_tab = st.tabs(
        ["Overview", "Tokens", "Tool calls", "Event stream", "Artifacts"]
    )
    with overview_tab:
        _overview(run)
    with tokens_tab:
        _tokens(run)
    with tools_tab:
        _tools(run)
    with events_tab:
        _events(run)
    with artifacts_tab:
        _artifacts(run)


if __name__ == "__main__":
    main()
