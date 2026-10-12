from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from packages.contracts import ProviderSessionRegistration
from tests.integration.test_daemon import (
    _a11y_evidence,
    _a11y_text_block,
    _content_path,
    _post_capture_with_web_and_a11y_provider,
)


@dataclass(frozen=True, slots=True)
class A11yBatchCase:
    name: str
    app_name: str
    blocks: tuple[dict[str, Any], ...]
    expected_text: str | None
    query: str
    forbidden: tuple[str, ...] = ()


CASES = (
    A11yBatchCase(
        name="long_web_article",
        app_name="Google Chrome",
        blocks=(
            _a11y_text_block("Browser toolbar SHOULD_NOT_LEAK_LONG_DOC", "AXToolbar", 0, 80, 1440, 44, 0, True),
            _a11y_text_block(
                "Whole article body SHOULD_NOT_LEAK_LONG_DOC",
                "AXWebArea",
                0,
                0,
                1200,
                1800,
                1,
                False,
            ),
            _a11y_text_block("Abstract", "AXStaticText", 130, 150, 90, 20, 2, True),
            _a11y_text_block(
                "WorkRecorder captures context as audit-ready evidence.",
                "AXStaticText",
                130,
                182,
                390,
                36,
                3,
                True,
            ),
            _a11y_text_block("Provider routing selects fresh sessions.", "AXStaticText", 130, 236, 310, 24, 4, True),
        ),
        expected_text=(
            "Abstract\n"
            "WorkRecorder captures context as audit-ready evidence.\n"
            "Provider routing selects fresh sessions."
        ),
        query="audit-ready",
        forbidden=("SHOULD_NOT_LEAK_LONG_DOC", "Browser toolbar"),
    ),
    A11yBatchCase(
        name="arxiv_two_column_html",
        app_name="Google Chrome",
        blocks=(
            _a11y_text_block("Right column theorem", "AXStaticText", 410, 150, 180, 20, 2, True),
            _a11y_text_block("Left column abstract", "AXStaticText", 130, 150, 180, 20, 0, True),
            _a11y_text_block("Left column method", "AXStaticText", 130, 210, 180, 20, 1, True),
            _a11y_text_block("Right column proof", "AXStaticText", 410, 210, 180, 20, 3, True),
        ),
        expected_text="Left column abstract\nLeft column method\nRight column theorem\nRight column proof",
        query="column proof",
    ),
    A11yBatchCase(
        name="duplicate_label_form",
        app_name="Google Chrome",
        blocks=(
            _a11y_text_block("Name", "AXStaticText", 130, 150, 80, 20, 0, True),
            _a11y_text_block("Edit", "AXButton", 250, 150, 52, 22, 1, True),
            _a11y_text_block("Email", "AXStaticText", 130, 190, 80, 20, 2, True),
            _a11y_text_block("Edit", "AXButton", 250, 190, 52, 22, 3, True),
            _a11y_text_block("Save", "AXButton", 130, 236, 74, 28, 4, True),
        ),
        expected_text="Name\nEdit\nEmail\nEdit\nSave",
        query="Email",
    ),
    A11yBatchCase(
        name="native_app_table_shape",
        app_name="Numbers",
        blocks=(
            _a11y_text_block("Project", "AXCell", 130, 150, 90, 20, 0, True, role_path=("AXTable",)),
            _a11y_text_block("Owner", "AXCell", 250, 150, 80, 20, 1, True, role_path=("AXTable",)),
            _a11y_text_block("Action", "AXCell", 370, 150, 80, 20, 2, True, role_path=("AXTable",)),
            _a11y_text_block("WorkRecorder", "AXCell", 130, 190, 110, 20, 3, True, role_path=("AXTable",)),
            _a11y_text_block("Context SDK", "AXCell", 250, 190, 110, 20, 4, True, role_path=("AXTable",)),
            _a11y_text_block("Edit", "AXButton", 370, 190, 52, 22, 5, True, role_path=("AXTable",)),
            _a11y_text_block("Prism", "AXCell", 130, 230, 80, 20, 6, True, role_path=("AXTable",)),
            _a11y_text_block("Capture App", "AXCell", 250, 230, 110, 20, 7, True, role_path=("AXTable",)),
            _a11y_text_block("Edit", "AXButton", 370, 230, 52, 22, 8, True, role_path=("AXTable",)),
        ),
        expected_text=(
            "Project\n" "Owner\n" "Action\n" "WorkRecorder\n" "Context SDK\n" "Edit\n" "Prism\n" "Capture App\n" "Edit"
        ),
        query="Context SDK",
    ),
    A11yBatchCase(
        name="pdf_parent_only",
        app_name="Google Chrome",
        blocks=(
            _a11y_text_block(
                "Whole PDF page SHOULD_NOT_LEAK_PDF",
                "AXDocument",
                0,
                0,
                1600,
                2400,
                0,
                False,
            ),
            _a11y_text_block(
                "Huge renderer text SHOULD_NOT_LEAK_PDF",
                "AXStaticText",
                0,
                0,
                1600,
                2400,
                1,
                True,
            ),
        ),
        expected_text=None,
        query="SHOULD_NOT_LEAK_PDF",
        forbidden=("SHOULD_NOT_LEAK_PDF",),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda item: item.name)
def test_selection_text_batch_e2e_cases(
    client: TestClient,
    token: str,
    capture_save_request: Any,
    provider_session_registration: ProviderSessionRegistration,
    case: A11yBatchCase,
) -> None:
    saved = _post_capture_with_web_and_a11y_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
        a11y_result_builder=_result_builder(case),
    ).json()
    headers = {"authorization": f"Bearer {token}"}
    event_id = saved["data"]["event"]["event_id"]
    artifacts = saved["data"]["artifacts"]
    metadata = json.dumps(
        [
            client.get(f"/v1/events/{event_id}/manifest", headers=headers).json()["data"],
            client.get(f"/v1/evidence?event={event_id}", headers=headers).json()["data"],
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    search = client.get(f"/v1/search?query={case.query.replace(' ', '+')}", headers=headers).json()

    if case.expected_text is None:
        assert not any(artifact["artifact_type"] == "a11y_selection_text" for artifact in artifacts)
        assert search["data"]["events"] == []
    else:
        selection_artifact = next(
            artifact for artifact in artifacts if artifact["artifact_type"] == "a11y_selection_text"
        )
        selection = client.get(_content_path(selection_artifact["artifact_id"], event_id), headers=headers).json()
        assert selection["data"]["text"] == case.expected_text
        assert search["data"]["results"][0]["match_reason"] == "selection_text"
        assert search["data"]["results"][0]["preview_evidence_id"] == selection_artifact["evidence_id"]

    assert "local-artifact://" not in metadata
    for forbidden in case.forbidden:
        assert forbidden not in metadata


def _result_builder(case: A11yBatchCase) -> Callable[[dict[str, Any], ProviderSessionRegistration], dict[str, Any]]:
    def build(command_message: dict[str, Any], registration: ProviderSessionRegistration) -> dict[str, Any]:
        command = command_message["command"]
        command_id = command["command_id"]
        selection = command["attempt"]["selection_geometry"]["selected_region"]
        observed_at = datetime.now(UTC).isoformat()
        snapshot = {
            "permission_state": "granted",
            "app_name": case.app_name,
            "process_id": 4242,
            "window_id": "win_test",
            "selection": selection,
            "root_nodes": [],
            "text_blocks": case.blocks,
            "full_text": "\n".join(block["text"] for block in case.blocks),
            "coverage": {
                "selection": selection,
                "permission_state": "granted",
                "node_count": len(case.blocks),
                "text_block_count": len(case.blocks),
                "covered_area_ratio": 0.82,
                "confidence": 0.9,
                "error_message": None,
            },
        }
        evidence = [
            _a11y_evidence(
                "a11y",
                "a11y_tree",
                "ui_structure",
                snapshot,
                source_uri=f"macos://a11y/4242/{case.name}#tree",
                command_id=command_id,
                session_id=registration.provider_session_id,
                content_type="application/json",
                payload_schema="a11y_snapshot",
                sensitivity="high_sensitivity",
                trust_state_claim="quarantined",
                redaction_state_claim="quarantined",
            ),
            _a11y_evidence(
                "provider_diagnostics",
                "a11y_coverage",
                "provider_diagnostics",
                snapshot["coverage"],
                source_uri=f"macos://a11y/4242/{case.name}#coverage",
                command_id=command_id,
                session_id=registration.provider_session_id,
                content_type="application/json",
                payload_schema="a11y_coverage",
            ),
            _a11y_evidence(
                "a11y",
                "a11y_text",
                "source_text",
                snapshot["full_text"],
                source_uri=f"macos://a11y/4242/{case.name}#text",
                command_id=command_id,
                session_id=registration.provider_session_id,
                content_type="text/plain; charset=utf-8",
                payload_schema="a11y_text",
            ),
        ]
        return {
            "schema_version": 1,
            "message_type": "collect_evidence_result",
            "command_id": command_id,
            "provider_key": "system.macos_a11y",
            "provider_session_id": registration.provider_session_id,
            "status": "succeeded",
            "evidence_kind": "a11y",
            "source_binding": None,
            "evidence_bundle": {
                "provider_key": "system.macos_a11y",
                "provider_session_id": registration.provider_session_id,
                "command_id": command_id,
                "status": "succeeded",
                "evidence_kind": "a11y",
                "source_binding": None,
                "evidence": evidence,
                "diagnostics": {"fixture": True, "case": case.name, "permission_state": "granted"},
                "completed_at": observed_at,
            },
            "diagnostics": {"fixture": True, "case": case.name, "permission_state": "granted"},
            "completed_at": observed_at,
        }

    return build
