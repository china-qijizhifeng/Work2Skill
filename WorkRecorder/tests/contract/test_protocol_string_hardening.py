from __future__ import annotations

from pathlib import Path

from packages.contracts import EventInspectSection, SearchFieldKind, SearchMatchReason
from services.context_daemon.routers.events import _parse_inspect_sections

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_event_inspect_sections_parse_to_enum_values() -> None:
    sections = _parse_inspect_sections("selection_text,clean_page_text,screenshot_ref")

    assert sections == (
        EventInspectSection.SELECTION_TEXT,
        EventInspectSection.CLEAN_PAGE_TEXT,
        EventInspectSection.SCREENSHOT_REF,
    )


def test_search_field_and_match_reason_contracts_serialize_as_stable_values() -> None:
    assert SearchFieldKind.SELECTION_TEXT.value == "selection_text"
    assert SearchMatchReason.SELECTION_TEXT.value == "selection_text"
    assert SearchMatchReason.CANONICAL_TEXT.value == "canonical_text"


def test_core_python_reader_paths_do_not_reintroduce_quoted_protocol_literals() -> None:
    hardening_targets = (
        "services/context_daemon/routers/events.py",
        "packages/indexing/service.py",
        "packages/indexing/backends/sqlite_keyword.py",
        "packages/disclosure/service.py",
        "apps/cli/main.py",
    )
    risky_literals = (
        '"selection_text"',
        '"canonical_text"',
        '"clean_page_text"',
        '"screenshot_ref"',
        '"evidence_refs"',
        '"artifact_metadata"',
        '"user_note"',
        '"read_raw_artifact"',
    )

    offenders: list[str] = []
    for relative in hardening_targets:
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        offenders.extend(f"{relative}: {literal}" for literal in risky_literals if literal in source)

    assert offenders == []


def test_browser_extension_uses_contract_constants_for_core_evidence_values() -> None:
    source = (REPO_ROOT / "apps/browser_extension/src/background.ts").read_text(encoding="utf-8")
    risky_literals = (
        '"page_metadata"',
        '"selection_map"',
        '"full_dom"',
        '"browser_full_dom"',
        '"visible_text"',
        '"selected_text"',
        '"source_text"',
        '"provider_redacted"',
        '"quarantined"',
    )

    assert [literal for literal in risky_literals if literal in source] == []
