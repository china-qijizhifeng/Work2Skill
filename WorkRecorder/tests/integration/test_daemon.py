from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from packages.contracts import (
    AccessScope,
    ActiveCaptureBinding,
    ActiveCaptureMode,
    ActorRef,
    Artifact,
    ArtifactType,
    BoundingBox,
    BrowserWindowRef,
    CaptureStrategy,
    CollectEvidenceResult,
    CoordinateSpace,
    KeyframeRole,
    KeyframeTriggerKind,
    NativeCaptureTimingAuthority,
    NativeCaptureTimingReceipt,
    NativeTimingClock,
    ProviderCapability,
    ProviderKind,
    ProviderSessionRegistration,
    RedactionState,
    TriggerType,
    VisualOCRLine,
    VisualOCRQuality,
    VisualOCRResult,
    WindowHint,
)
from packages.contracts.common import JsonScalar
from packages.enrichment.visual_ocr.openai_compatible import OpenAICompatibleVisualOCRProvider
from packages.indexing.contracts import IndexQuery
from packages.shared.config import WorkRecorderSettings
from services.context_daemon.app import DaemonAppFactory
from services.context_daemon.container import DaemonContainer
from services.context_daemon.routers.providers import _authorized_registration

INSTALL_SECRET_HEADER = {"x-workrecorder-install-secret": "test-install-secret"}
NATIVE_CAPTURE_SECRET_HEADER = {"x-workrecorder-native-capture-secret": "test-native-secret"}


def test_health_is_public(client):
    response = client.get("/health")
    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["data"]["service"] == "workrecorder-local-daemon"
    assert payload["data"]["status"] == "ok"


def test_native_capture_authority_is_fail_closed_when_secret_matches_install_secret(tmp_path):
    insecure_settings = WorkRecorderSettings(
        database_path=tmp_path / "workrecorder.sqlite",
        artifact_staging_dir=tmp_path / "staging",
        artifact_vault_dir=tmp_path / "artifacts",
        install_secret="same-secret",
        provider_registration_secret="test-provider-secret",
        native_capture_secret="same-secret",
        disclosure_policy_path=None,
        capture_post_commit_outbox_worker_enabled=False,
    )
    insecure_client = TestClient(DaemonAppFactory(insecure_settings).create())

    response = insecure_client.get(
        "/v1/auth/native-capture-authority",
        headers={"x-workrecorder-native-capture-secret": "same-secret"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.invalid"


def _container(client: TestClient) -> DaemonContainer:
    return cast(DaemonContainer, cast(FastAPI, client.app).state.container)


def test_events_require_auth(client):
    response = client.get("/v1/events")
    payload = response.json()
    assert response.status_code == 403
    assert payload["ok"] is False
    assert payload["error"]["code"] == "auth.missing"


def test_create_and_get_event(client, token, event_create):
    headers = {"authorization": f"Bearer {token}"}
    create_response = client.post("/v1/events", headers=headers, json=event_create.model_dump(mode="json"))
    create_payload = create_response.json()
    assert create_response.status_code == 200
    assert create_payload["ok"] is True
    event_id = create_payload["data"]["event_id"]

    get_response = client.get(f"/v1/events/{event_id}", headers=headers)
    get_payload = get_response.json()
    assert get_response.status_code == 200
    assert get_payload["data"]["event_id"] == event_id
    assert get_payload["audit_id"].startswith("aud_")


def test_create_event_rejects_reserved_os_window_entrypoint(client, token, event_create):
    headers = {"authorization": f"Bearer {token}"}
    os_window_event = event_create.model_copy(
        update={
            "event_type": "screen.window.captured",
            "trigger": event_create.trigger.model_copy(update={"capture_strategy": CaptureStrategy.OS_WINDOW}),
        }
    )

    response = client.post("/v1/events", headers=headers, json=os_window_event.model_dump(mode="json"))
    payload = response.json()

    assert response.status_code == 403
    assert payload["ok"] is False
    assert payload["error"]["code"] == "policy.denied"
    assert "native capture endpoint" in payload["error"]["message"]


def test_vm_a11y_settings_expose_explicit_default_profile(client):
    headers = {"authorization": f"Bearer {_token_with_scopes(client, ('read_metadata',))}"}

    response = client.get("/v1/settings/vm-a11y-probe", headers=headers)
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["data"]["profile"] == "mypcbench_v1"


def test_visual_ocr_settings_are_typed_and_masked(client, token):
    headers = {"authorization": f"Bearer {_token_with_scopes(client, ('read_metadata', 'manage_local_settings'))}"}
    _container(client).visual_ocr_settings.secrets = _MemorySecretStore()
    default_settings = client.get("/v1/settings/visual-ocr", headers=headers).json()

    assert default_settings["ok"] is True
    assert default_settings["data"]["enabled"] is True
    assert default_settings["data"]["auto_run_on_capture"] is True
    assert default_settings["data"]["provider_kind"] == "apple_vision"
    assert default_settings["data"]["api_key_configured"] is False
    default_tested = client.post("/v1/settings/visual-ocr/test", headers=headers).json()
    assert default_tested["data"]["ok"] is True
    assert default_tested["data"]["provider_kind"] == "apple_vision"
    assert "succeeded" in default_tested["data"]["message"]

    update = {
        "enabled": True,
        "auto_run_on_capture": True,
        "provider_kind": "openai_compatible",
        "api_style": "responses",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5.5",
        "timeout_seconds": 90,
        "max_image_long_edge": 1600,
    }
    updated = client.put("/v1/settings/visual-ocr", headers=headers, json=update).json()
    tested = client.post("/v1/settings/visual-ocr/test", headers=headers).json()

    assert updated["ok"] is True
    assert updated["data"]["enabled"] is True
    assert updated["data"]["auto_run_on_capture"] is True
    assert updated["data"]["allow_insecure_remote_base_url"] is False
    assert updated["data"]["api_key_configured"] is False
    assert tested["data"]["ok"] is True
    assert tested["data"]["model"] == "gpt-5.5"
    assert "succeeded" in tested["data"]["message"]

    remote_http_update = update | {
        "base_url": "http://14.103.60.158:3001/v1",
        "allow_insecure_remote_base_url": True,
    }
    remote_http = client.put("/v1/settings/visual-ocr", headers=headers, json=remote_http_update).json()
    assert remote_http["ok"] is True
    assert remote_http["data"]["base_url"] == "http://14.103.60.158:3001/v1"
    assert remote_http["data"]["allow_insecure_remote_base_url"] is True


def test_shortcut_settings_round_trip(client):
    headers = {"authorization": f"Bearer {_token_with_scopes(client, ('read_metadata', 'manage_local_settings'))}"}
    default_settings = client.get("/v1/settings/shortcuts", headers=headers).json()

    assert default_settings["ok"] is True
    assert {binding["command"] for binding in default_settings["data"]["bindings"]} == {
        "current_appshot",
        "region_screenshot",
        "region_recording",
    }
    assert default_settings["data"]["bindings"][0]["shortcut"]["modifiers"] == ["control", "command"]
    default_recording = next(
        binding for binding in default_settings["data"]["bindings"] if binding["command"] == "region_recording"
    )
    assert default_recording["shortcut"]["modifiers"] == ["control", "option", "command"]

    update = {
        "bindings": [
            {
                "command": "current_appshot",
                "enabled": True,
                "shortcut": {"key_code": 18, "key_label": "1", "modifiers": ["control", "option"]},
            },
            {
                "command": "region_screenshot",
                "enabled": True,
                "shortcut": {"key_code": 20, "key_label": "3", "modifiers": ["control", "command"]},
            },
            {
                "command": "region_recording",
                "enabled": False,
                "shortcut": {"key_code": 15, "key_label": "R", "modifiers": ["control", "option", "command"]},
            },
        ]
    }
    saved = client.put("/v1/settings/shortcuts", headers=headers, json=update).json()
    read_back = client.get("/v1/settings/shortcuts", headers=headers).json()

    assert saved["ok"] is True
    assert read_back["data"] == saved["data"]
    appshot = next(binding for binding in read_back["data"]["bindings"] if binding["command"] == "current_appshot")
    recording = next(binding for binding in read_back["data"]["bindings"] if binding["command"] == "region_recording")
    assert appshot["shortcut"]["key_label"] == "1"
    assert recording["enabled"] is False


def test_shortcut_settings_validation_does_not_echo_input_values(client):
    headers = {"authorization": f"Bearer {_token_with_scopes(client, ('read_metadata', 'manage_local_settings'))}"}
    payload = {
        "bindings": [
            {
                "command": "current_appshot",
                "enabled": True,
                "shortcut": {
                    "key_code": 9999,
                    "key_label": "SHOULD_NOT_LEAK_TYPED_TEXT",
                    "modifiers": ["control", "command"],
                },
            }
        ]
    }

    response = client.put("/v1/settings/shortcuts", headers=headers, json=payload)
    body = response.text

    assert response.status_code == 422
    assert "SHOULD_NOT_LEAK_TYPED_TEXT" not in body
    assert "9999" not in body

    scalar_response = client.put(
        "/v1/settings/shortcuts",
        headers=headers,
        json="SHOULD_NOT_LEAK_TOKEN_VALUE",
    )
    scalar_body = scalar_response.text

    assert scalar_response.status_code == 422
    assert "SHOULD_NOT_LEAK_TOKEN_VALUE" not in scalar_body


def test_visual_ocr_job_appends_visual_ocr_text_and_refreshes_inspect(
    client, token, capture_save_request, provider_session_registration, monkeypatch
):
    headers = {
        "authorization": f"Bearer {_token_with_scopes(client, ('read_metadata', 'read_text', 'read_raw_artifact', 'manage_local_settings', 'run_enrichment'))}"
    }
    container = _container(client)
    container.visual_ocr_settings.secrets = _MemorySecretStore()
    settings = {
        "enabled": True,
        "auto_run_on_capture": False,
        "provider_kind": "openai_compatible",
        "api_style": "responses",
        "base_url": "https://api.openai.test/v1",
        "model": "gpt-5.5",
        "timeout_seconds": 90,
        "max_image_long_edge": 1600,
        "api_key": "sk-test",
    }
    updated = client.put("/v1/settings/visual-ocr", headers=headers, json=settings).json()
    assert updated["data"]["api_key_configured"] is True

    calls = 0

    async def fake_run(self, request):
        nonlocal calls
        calls += 1
        del self
        return VisualOCRResult(
            plain_text="Worker D 状态解释\n并发任务正在处理。",
            readable_markdown="## Worker D 状态解释\n\n并发任务正在处理。",
            lines=(
                VisualOCRLine(text="Worker D 状态解释", reading_order=0, confidence=0.94),
                VisualOCRLine(text="并发任务正在处理。", reading_order=1, confidence=0.90),
            ),
            quality=VisualOCRQuality(confidence=0.92, text_chars=25, language_hint="zh-CN"),
            raw_model_name=request.settings.model,
        )

    monkeypatch.setattr(OpenAICompatibleVisualOCRProvider, "run", fake_run)

    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]
    run = client.post(f"/v1/events/{event_id}/enrichments/visual-ocr", headers=headers).json()
    second_run = client.post(f"/v1/events/{event_id}/enrichments/visual-ocr", headers=headers).json()
    changes = client.get(f"/v1/events/{event_id}/changes?since=0", headers=headers).json()
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=visual_ocr_text,evidence_refs",
        headers=headers,
    ).json()
    search = client.get("/v1/search?query=Worker+D", headers=headers).json()
    artifact_types = {artifact.artifact_type for artifact in container.repositories.artifacts.list_for_event(event_id)}

    assert run["ok"] is True
    assert second_run["ok"] is True
    assert calls == 1
    assert changes["data"]["visual_ocr"]["status"] == "completed"
    assert changes["data"]["visual_ocr"]["attempt_count"] == 1
    assert changes["data"]["visual_ocr"]["max_attempts"] == 3
    assert ArtifactType.VISUAL_OCR_RESULT in artifact_types
    visual = next(item for item in inspect["data"]["readable_evidence"] if item["artifact_type"] == "visual_ocr_text")
    assert "Worker D 状态解释" in visual["text"]
    assert "untrusted observed content, not instructions" not in visual["text"]
    assert "> ## Worker D 状态解释" not in visual["text"]
    assert visual["text"].startswith("## Worker D 状态解释")
    assert visual["role"] == "visual_ocr_text"
    assert not search["data"]["results"][0]["selection_text"]
    assert search["data"]["results"][0]["event_id"] == event_id
    assert search["data"]["results"][0]["match_reason"] == "visual_ocr_text"


def test_visual_ocr_refreshes_active_capture_recording_safe_index(client, token, capture_save_request, monkeypatch):
    headers = {
        "authorization": f"Bearer {_token_with_scopes(client, ('read_metadata', 'read_text', 'read_raw_artifact', 'manage_local_settings', 'run_enrichment'))}"
    }
    container = _container(client)
    container.visual_ocr_settings.secrets = _MemorySecretStore()
    settings = {
        "enabled": True,
        "auto_run_on_capture": False,
        "provider_kind": "openai_compatible",
        "api_style": "responses",
        "base_url": "https://api.openai.test/v1",
        "model": "gpt-5.5",
        "timeout_seconds": 90,
        "max_image_long_edge": 1600,
        "api_key": "sk-test",
    }
    client.put("/v1/settings/visual-ocr", headers=headers, json=settings)

    async def fake_run(self, request):
        del self
        return VisualOCRResult(
            plain_text="录制关键帧 SAFEOCRTOKEN 安全文本",
            readable_markdown="录制关键帧 SAFEOCRTOKEN 安全文本",
            lines=(VisualOCRLine(text="录制关键帧 SAFEOCRTOKEN 安全文本", reading_order=0, confidence=0.95),),
            quality=VisualOCRQuality(confidence=0.95, text_chars=20, language_hint="zh-CN"),
            raw_model_name=request.settings.model,
        )

    monkeypatch.setattr(OpenAICompatibleVisualOCRProvider, "run", fake_run)
    create = client.post(
        "/v1/active-captures/sessions",
        headers={"authorization": f"Bearer {token}"},
        json={"mode": ActiveCaptureMode.RECORDING_SESSION.value, "start_recording": True},
    ).json()
    session_id = create["data"]["session"]["session_id"]
    attempt = container.capture_attempts.from_legacy_save_request(capture_save_request).model_copy(
        update={
            "active_capture": ActiveCaptureBinding(
                session_id=session_id,
                role=KeyframeRole.START,
                trigger_kind=KeyframeTriggerKind.RECORDING_START,
            )
        }
    )
    saved = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}"},
        json=attempt.model_dump(mode="json"),
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    container.capture_post_commit_outbox.drain_due(event_id)
    assert container.active_capture.keyframes_for_event(event_id)

    run = client.post(f"/v1/events/{event_id}/enrichments/visual-ocr", headers=headers).json()
    changes = client.get(f"/v1/events/{event_id}/changes?since=0", headers=headers).json()
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=verify_active_capture_ocr"
        "&inspect_views=active_capture_summary,visual_ocr_text,evidence_refs",
        headers=headers,
    ).json()
    with container.repositories.database.transaction() as connection:
        indexed_rows = connection.execute(
            "SELECT event_id, field_kind, search_text FROM keyword_index_documents WHERE search_text LIKE ?",
            ("%SAFEOCRTOKEN%",),
        ).fetchall()
    backend_hits = container.index_backends.default().search(IndexQuery(query="SAFEOCRTOKEN", explain=True))
    search = client.get("/v1/search?query=SAFEOCRTOKEN&limit=10", headers=headers).json()
    result_ids = [item["event_id"] for item in search["data"]["results"]]

    assert run["ok"] is True
    assert changes["data"]["visual_ocr"]["status"] == "completed"
    assert inspect["data"]["active_capture"]["safe_text_blocks"]
    assert indexed_rows
    assert event_id in {str(row["event_id"]) for row in indexed_rows}
    assert backend_hits
    assert any(
        hit.explain is not None and hit.explain.details.get("active_capture_session_id") == session_id
        for hit in backend_hits
    )
    assert event_id in result_ids
    assert result_ids.count(event_id) == 1
    assert search["data"]["results"][0]["match_reason"] == "active_capture_summary"
    assert search["data"]["results"][0]["selection_text"] == ""


def test_visual_ocr_job_retries_transient_provider_errors(
    client, token, capture_save_request, provider_session_registration, monkeypatch
):
    headers = {
        "authorization": f"Bearer {_token_with_scopes(client, ('read_metadata', 'read_text', 'read_raw_artifact', 'manage_local_settings', 'run_enrichment'))}"
    }
    container = _container(client)
    container.visual_ocr_settings.secrets = _MemorySecretStore()
    settings = {
        "enabled": True,
        "auto_run_on_capture": False,
        "provider_kind": "openai_compatible",
        "api_style": "responses",
        "base_url": "https://api.openai.test/v1",
        "model": "gpt-5.5",
        "timeout_seconds": 90,
        "max_image_long_edge": 1600,
        "api_key": "sk-test",
    }
    updated = client.put("/v1/settings/visual-ocr", headers=headers, json=settings).json()
    assert updated["data"]["api_key_configured"] is True

    calls = 0

    async def flaky_run(self, request):
        nonlocal calls
        calls += 1
        del self
        if calls < 3:
            raise RuntimeError("transient visual model error")
        return VisualOCRResult(
            plain_text="第三次识别成功",
            readable_markdown="第三次识别成功",
            lines=(VisualOCRLine(text="第三次识别成功", reading_order=0, confidence=0.91),),
            quality=VisualOCRQuality(confidence=0.91, text_chars=7, language_hint="zh-CN"),
            raw_model_name=request.settings.model,
        )

    monkeypatch.setattr(OpenAICompatibleVisualOCRProvider, "run", flaky_run)

    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]
    run = client.post(f"/v1/events/{event_id}/enrichments/visual-ocr", headers=headers).json()
    changes = client.get(f"/v1/events/{event_id}/changes?since=0", headers=headers).json()

    assert run["ok"] is True
    assert calls == 3
    assert changes["data"]["visual_ocr"]["status"] == "completed"
    assert changes["data"]["visual_ocr"]["attempt_count"] == 3
    assert changes["data"]["visual_ocr"]["max_attempts"] == 3


def test_visual_ocr_unavailable_after_capture_is_skipped_not_blocking(client, token, capture_save_request, monkeypatch):
    headers = {"authorization": f"Bearer {token}"}

    from packages.enrichment.visual_ocr import providers as provider_module

    monkeypatch.setattr(provider_module, "apple_vision_unavailable_reason", lambda: "apple_vision_unavailable")

    saved = client.post(
        "/v1/captures",
        headers=headers,
        json=capture_save_request.model_dump(mode="json"),
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    changes = client.get(f"/v1/events/{event_id}/changes?since=0", headers=headers).json()
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=system_appshot",
        headers=headers,
    ).json()

    assert saved["data"]["status"] == "accepted"
    assert changes["data"]["visual_ocr"]["status"] == "skipped"
    assert changes["data"]["visual_ocr"]["skip_reason"] == "apple_vision_unavailable"
    assert inspect["data"]["system_appshot"]["ocr_job_status"] == "skipped"


def test_manual_visual_ocr_respects_provider_unavailable_reason(client, capture_save_request, monkeypatch):
    headers = {
        "authorization": f"Bearer {_token_with_scopes(client, ('create_event', 'read_metadata', 'read_raw_artifact', 'run_enrichment'))}"
    }

    from packages.enrichment.visual_ocr import providers as provider_module

    monkeypatch.setattr(provider_module, "apple_vision_unavailable_reason", lambda: "config_required")

    saved = client.post(
        "/v1/captures",
        headers=headers,
        json=capture_save_request.model_dump(mode="json"),
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    manual = client.post(f"/v1/events/{event_id}/enrichments/visual-ocr", headers=headers).json()
    changes = client.get(f"/v1/events/{event_id}/changes?since=0", headers=headers).json()

    assert manual["ok"] is True
    assert changes["data"]["visual_ocr"]["status"] == "skipped"
    assert changes["data"]["visual_ocr"]["skip_reason"] == "config_required"


def test_capture_save_creates_event_and_web_artifacts(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    response = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration)
    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["data"]["status"] == "accepted"
    assert payload["data"]["event"]["status"] == "agent_ready"
    assert payload["data"]["event"]["event_type"] == "webpage.selection.captured"
    assert payload["data"]["event"]["source_binding"]["source_ref"]["url"] == "https://example.test/acme"
    artifact_types = {artifact["artifact_type"] for artifact in payload["data"]["artifacts"]}
    assert {"screenshot", "page_metadata", "selection_map", "canonical_text", "browser_full_dom"}.issubset(
        artifact_types
    )
    screenshot = next(
        artifact for artifact in payload["data"]["artifacts"] if artifact["artifact_type"] == "screenshot"
    )
    assert screenshot["redaction_state"] == "quarantined"
    assert screenshot["sha256"]
    assert screenshot["storage_uri"] is None
    assert all(artifact["storage_uri"] is None for artifact in payload["data"]["artifacts"])
    assert "local_path" not in screenshot["metadata"]
    assert payload["data"]["pending_enrichment"] is False


def test_capture_attempt_request_creates_event_and_web_artifacts(
    client, token, capture_save_request, provider_session_registration
):
    attempt = _container(client).capture_attempts.from_legacy_save_request(capture_save_request)

    response = _post_capture_with_web_provider(client, token, attempt, provider_session_registration)
    payload = response.json()

    assert response.status_code == 200
    assert payload["data"]["status"] == "accepted"
    assert payload["data"]["event"]["event_type"] == "webpage.selection.captured"
    assert payload["data"]["event"]["source_binding"]["provider_context_id"] is None
    assert len(payload["data"]["artifacts"]) >= 4


def test_capture_save_is_idempotent_by_trigger_id(client, token, capture_save_request, provider_session_registration):
    first_response = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration)
    first_payload = first_response.json()

    second_response = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}"},
        json=capture_save_request.model_dump(mode="json"),
    )
    second_payload = second_response.json()

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_payload["ok"] is True
    assert second_payload["data"]["status"] == "accepted"
    assert second_payload["data"]["event"]["event_id"] == first_payload["data"]["event"]["event_id"]
    assert second_payload["data"]["artifacts"][0]["artifact_id"] == first_payload["data"]["artifacts"][0]["artifact_id"]
    first_artifact_ids = {artifact["artifact_id"] for artifact in first_payload["data"]["artifacts"]}
    second_artifact_ids = {artifact["artifact_id"] for artifact in second_payload["data"]["artifacts"]}
    assert first_artifact_ids.issubset(second_artifact_ids)
    assert len(second_artifact_ids) == len(second_payload["data"]["artifacts"])


def test_capture_without_web_provider_is_accepted_system_only(client, token, capture_save_request):
    attempt = _container(client).capture_attempts.from_legacy_save_request(capture_save_request)
    hint = WindowHint(
        app_name="Google Chrome",
        title="Local Bundle Path Test",
        process_id=202,
        window_id="win_bundle_path_test",
        bundle_id="com.google.Chrome",
        bundle_url="file:///Applications/Google%20Chrome.app",
        frame=attempt.selection_geometry.selected_region,
        overlap_ratio=1.0,
        confidence=0.91,
    )
    attempt = attempt.model_copy(update={"window_hints": (hint,)})
    response = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}", **INSTALL_SECRET_HEADER},
        json=attempt.model_dump(mode="json"),
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["data"]["status"] == "accepted"
    assert payload["data"]["event"]["event_type"] == "screen.region.captured"
    artifact_types = {artifact["artifact_type"] for artifact in payload["data"]["artifacts"]}
    assert "screenshot" in artifact_types
    assert "system_appshot" in artifact_types
    assert "file:///Applications" not in json.dumps(payload["data"], sort_keys=True)
    assert client.get("/v1/events", headers={"authorization": f"Bearer {token}"}).json()["data"]["events"]

    diagnose = client.get(
        f"/v1/captures/diagnose/{attempt.trigger.trigger_id}",
        headers={"authorization": f"Bearer {token}"},
    ).json()
    assert diagnose["ok"] is True
    assert diagnose["data"]["manifest"]["event_type"] == "screen.region.captured"
    outcomes = diagnose["data"]["manifest"]["provider_outcomes"]
    assert any(
        outcome["provider_key"] == "system.screenshot" and outcome["status"] == "succeeded" for outcome in outcomes
    )
    assert any(outcome["provider_key"] == "system.appshot" and outcome["status"] == "succeeded" for outcome in outcomes)
    assert any(
        outcome["provider_key"] == "web.browser_extension" and outcome["status"] == "stale" for outcome in outcomes
    )
    manifest = diagnose["data"]["manifest"]
    assert manifest["system_appshot_evidence_id"]
    assert manifest["system_evidence_bundle_ids"]
    assert "file:///Applications" not in json.dumps(manifest, sort_keys=True)

    event_id = payload["data"]["event"]["event_id"]
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=system_appshot,artifact_metadata",
        headers={"authorization": f"Bearer {token}"},
    ).json()
    appshot = inspect["data"]["system_appshot"]
    assert appshot["screenshot_evidence_id"]
    assert appshot["primary_app_name"]
    assert appshot["primary_process_id"] is None
    assert appshot["primary_window_id"] is None
    assert appshot["primary_bundle_id"] is None
    assert appshot["surfaces"][0]["identity"]["process_id"] is None
    assert appshot["surfaces"][0]["identity"]["window_id"] is None
    assert appshot["surfaces"][0]["identity"]["frame"] is None
    assert appshot["surfaces"][0]["identity"]["display_id"] is None
    assert appshot["surfaces"][0]["identity"]["bundle_id"] is None
    assert appshot["quality"]["screenshot_present"] is True
    assert appshot["components"][0]["provider_key"] == "system.screenshot"
    for component in appshot["components"]:
        assert component["command_id"] is None
        assert component["provider_session_id"] is None
        assert component["route_id"] is None
        assert component["artifact_ids"] == []
    assert "storage_uri" not in json.dumps(appshot)
    assert "file:///Applications" not in json.dumps(appshot, sort_keys=True)


def test_capture_without_window_hints_saves_desktop_system_only_event(client, token, capture_save_request):
    attempt = _container(client).capture_attempts.from_legacy_save_request(capture_save_request)
    attempt = attempt.model_copy(update={"window_hints": ()})
    response = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}", **INSTALL_SECRET_HEADER},
        json=attempt.model_dump(mode="json"),
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["data"]["status"] == "accepted"
    event = payload["data"]["event"]
    assert event["event_type"] == "screen.region.captured"
    assert event["source_binding"]["source_ref"]["app_name"] == "桌面"
    assert event["source_binding"]["source_ref"]["title"] == "桌面区域"
    artifact_types = {artifact["artifact_type"] for artifact in payload["data"]["artifacts"]}
    assert "screenshot" in artifact_types
    assert "system_appshot" in artifact_types

    diagnose = client.get(
        f"/v1/captures/diagnose/{attempt.trigger.trigger_id}",
        headers={"authorization": f"Bearer {token}"},
    ).json()
    assert diagnose["data"]["manifest"]["route_plan"]["primary_surface_id"] == "surface_desktop"
    outcomes = diagnose["data"]["manifest"]["provider_outcomes"]
    assert any(
        outcome["provider_key"] == "system.screenshot" and outcome["status"] == "succeeded" for outcome in outcomes
    )
    assert any(outcome["provider_key"] == "system.appshot" and outcome["status"] == "succeeded" for outcome in outcomes)
    inspect = client.get(
        f"/v1/events/{event['event_id']}?view=event_inspect&purpose=agent_deep_read&inspect_views=system_appshot,evidence_refs",
        headers={"authorization": f"Bearer {token}"},
    ).json()
    contribution = inspect["data"]["source_contributions"][0]
    assert contribution["role"] == "primary_source"
    assert contribution["app_name"] == "桌面"
    assert contribution["provider_kind"] == "system_evidence"
    assert contribution["status"] is None
    assert contribution["source_kind"] == "desktop_window"
    appshot = inspect["data"]["system_appshot"]
    assert appshot["primary_surface_id"] == "surface_desktop"
    assert appshot["primary_app_name"] == "桌面"


def test_frontmost_window_capture_uses_single_primary_window_route(client, token, capture_save_request):
    attempt = _container(client).capture_attempts.from_legacy_save_request(capture_save_request)
    selected = attempt.selection_geometry.selected_region
    frontmost = WindowHint(
        app_name="Finder",
        title="Downloads",
        process_id=101,
        window_id="finder-1",
        bundle_id="com.apple.finder",
        frame=selected,
        display_id="display_main",
        overlap_ratio=1.0,
        confidence=0.94,
        window_order=4,
        visible_area_ratio=1.0,
        is_frontmost=True,
    )
    background = WindowHint(
        app_name="Google Chrome",
        title="Background",
        process_id=202,
        window_id="chrome-1",
        bundle_id="com.google.Chrome",
        frame=selected,
        overlap_ratio=1.0,
        confidence=0.99,
        window_order=1,
        visible_area_ratio=1.0,
        is_frontmost=False,
    )
    attempt = attempt.model_copy(
        update={
            "trigger": attempt.trigger.model_copy(
                update={
                    "trigger_type": TriggerType.MANUAL_OS_FRONTMOST_WINDOW_HOTKEY,
                    "capture_strategy": CaptureStrategy.OS_WINDOW,
                }
            ),
            "window_hints": (frontmost, background),
            "native_timing_receipt": _native_os_window_receipt(frontmost),
        }
    )

    response = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}", **NATIVE_CAPTURE_SECRET_HEADER},
        json=attempt.model_dump(mode="json"),
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["data"]["event"]["event_type"] == "screen.window.captured"
    assert payload["data"]["event"]["trigger"]["selection"] is None
    assert payload["data"]["event"]["source_binding"]["source_ref"]["app_name"] == "Finder"
    assert payload["data"]["event"]["source_binding"]["source_ref"]["external_id"] is None
    for artifact in payload["data"]["artifacts"]:
        metadata = artifact.get("metadata") or {}
        assert metadata.get("selection_x") is None
        assert metadata.get("selection_y") is None
        assert metadata.get("selection_width") is None
        assert metadata.get("selection_height") is None
    diagnose = client.get(
        f"/v1/captures/diagnose/{attempt.trigger.trigger_id}",
        headers={"authorization": f"Bearer {token}"},
    ).json()
    assert diagnose["data"]["manifest"]["detected_surfaces"] is None
    assert diagnose["data"]["manifest"]["selection_geometry"] is None
    assert diagnose["data"]["first_artifact"]["metadata"]["selection_x"] is None
    persisted_envelope = _container(client).repositories.ledger.get_envelope_by_trigger_id(attempt.trigger.trigger_id)
    assert persisted_envelope is not None
    assert [surface.app_name for surface in persisted_envelope.detected_surfaces] == ["Finder"]
    event_read = client.get(
        f"/v1/events/{payload['data']['event']['event_id']}?include=manifest,artifacts",
        headers={"authorization": f"Bearer {token}"},
    ).json()
    assert event_read["data"]["event"]["trigger"]["selection"] is None
    assert event_read["data"]["event"]["source_binding"]["matched_region"] is None
    assert event_read["data"]["manifest"]["selection_geometry"] is None
    assert event_read["data"]["manifest"]["provider_routes"] is None
    for artifact in event_read["data"]["artifacts"]:
        metadata = artifact.get("metadata") or {}
        assert metadata.get("selection_x") is None
        assert metadata.get("selection_width") is None
    screenshot = next(
        artifact for artifact in payload["data"]["artifacts"] if artifact["artifact_type"] == "screenshot"
    )
    artifact_read = client.get(
        f"/v1/artifacts/{screenshot['artifact_id']}",
        headers={"authorization": f"Bearer {token}"},
    ).json()
    assert artifact_read["data"]["metadata"]["selection_x"] is None
    assert artifact_read["data"]["metadata"]["display_id"] is None
    inspect = client.get(
        f"/v1/events/{payload['data']['event']['event_id']}?view=event_inspect&purpose=agent_deep_read&inspect_views=system_appshot",
        headers={"authorization": f"Bearer {token}"},
    ).json()
    appshot = inspect["data"]["system_appshot"]
    assert appshot["primary_process_id"] is None
    assert appshot["primary_window_id"] is None
    assert appshot["primary_bundle_id"] is None
    assert appshot["selected_region"]["x"] == 0
    assert appshot["selected_region"]["y"] == 0
    assert appshot["selected_region"]["width"] == 1
    assert appshot["selected_region"]["height"] == 1
    assert appshot["surfaces"][0]["identity"]["process_id"] is None
    assert appshot["surfaces"][0]["identity"]["window_id"] is None
    assert appshot["surfaces"][0]["identity"]["frame"] is None
    assert appshot["surfaces"][0]["identity"]["display_id"] is None
    assert appshot["surfaces"][0]["identity"]["bundle_id"] is None
    assert inspect["data"]["selection_bbox"] is None
    search = client.get("/v1/search?query=Downloads", headers={"authorization": f"Bearer {token}"}).json()
    result = next(
        item for item in search["data"]["results"] if item["event_id"] == payload["data"]["event"]["event_id"]
    )
    assert result["selection_bbox"] is None
    share_headers = {
        "authorization": f"Bearer {_token_with_scopes(client, ('create_share', 'read_text', 'read_share'))}"
    }
    create_share = client.post(
        "/v1/shares",
        headers=share_headers,
        json={"event_id": payload["data"]["event"]["event_id"], "purpose": "os_window_privacy_regression"},
    ).json()
    share_id = create_share["data"]["share"]["share_id"]
    resolved = client.post(
        "/v1/shares/resolve",
        headers=share_headers,
        json={"source": f"workrecorder://share/{share_id}", "purpose": "os_window_privacy_regression"},
    ).json()
    safe_context = resolved["data"]["safe_context"]
    assert safe_context["summary_card"]["selection_bbox"] is None
    assert safe_context["system_appshot"]["primary_process_id"] is None
    assert safe_context["system_appshot"]["primary_window_id"] is None
    assert safe_context["system_appshot"]["selected_region"]["width"] == 1


def test_frontmost_window_capture_rejects_forged_os_window_without_native_authority(
    client, token, capture_save_request
):
    attempt = _container(client).capture_attempts.from_legacy_save_request(capture_save_request)
    selected = attempt.selection_geometry.selected_region
    frontmost = WindowHint(
        app_name="Finder",
        title="Downloads",
        process_id=101,
        window_id="finder-1",
        bundle_id="com.apple.finder",
        frame=selected,
        display_id="display_main",
        overlap_ratio=1.0,
        confidence=0.94,
        visible_area_ratio=1.0,
        is_frontmost=True,
    )
    attempt = attempt.model_copy(
        update={
            "trigger": attempt.trigger.model_copy(
                update={
                    "trigger_type": TriggerType.MANUAL_OS_FRONTMOST_WINDOW_HOTKEY,
                    "capture_strategy": CaptureStrategy.OS_WINDOW,
                }
            ),
            "window_hints": (frontmost,),
        }
    )

    response = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}"},
        json=attempt.model_dump(mode="json"),
    )

    assert response.status_code == 403
    payload = response.json()
    assert payload["error"]["code"] == "policy.denied"
    assert _container(client).repositories.ledger.get_envelope_by_trigger_id(attempt.trigger.trigger_id) is None


def test_frontmost_window_capture_rejects_mismatched_native_receipt(client, token, capture_save_request):
    attempt = _container(client).capture_attempts.from_legacy_save_request(capture_save_request)
    selected = attempt.selection_geometry.selected_region
    frontmost = WindowHint(
        app_name="Finder",
        title="Downloads",
        process_id=101,
        window_id="finder-1",
        bundle_id="com.apple.finder",
        frame=selected,
        display_id="display_main",
        overlap_ratio=1.0,
        confidence=0.94,
        visible_area_ratio=1.0,
        is_frontmost=True,
    )
    receipt = _native_os_window_receipt(frontmost)
    receipt = receipt.model_copy(update={"metadata": receipt.metadata | {"os_window_window_id": "other-window"}})
    attempt = attempt.model_copy(
        update={
            "trigger": attempt.trigger.model_copy(
                update={
                    "trigger_type": TriggerType.MANUAL_OS_FRONTMOST_WINDOW_HOTKEY,
                    "capture_strategy": CaptureStrategy.OS_WINDOW,
                }
            ),
            "window_hints": (frontmost,),
            "native_timing_receipt": receipt,
        }
    )

    response = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}", **NATIVE_CAPTURE_SECRET_HEADER},
        json=attempt.model_dump(mode="json"),
    )

    assert response.status_code == 403
    payload = response.json()
    assert payload["error"]["code"] == "policy.denied"
    audits = tuple(
        audit
        for audit in _container(client).repositories.audits.list(limit=20)
        if audit.audit_id == payload["audit_id"]
    )
    assert audits[0].details["reason"] == "os_window_native_receipt_mismatch"


def test_frontmost_window_capture_rejects_incomplete_native_identity(client, token, capture_save_request):
    attempt = _container(client).capture_attempts.from_legacy_save_request(capture_save_request)
    selected = attempt.selection_geometry.selected_region
    incomplete = WindowHint(
        app_name="Finder",
        title="Downloads",
        process_id=101,
        window_id=None,
        bundle_id="com.apple.finder",
        frame=selected,
        display_id="display_main",
        overlap_ratio=1.0,
        confidence=0.94,
        visible_area_ratio=1.0,
        is_frontmost=True,
    )
    receipt = _native_os_window_receipt(incomplete.model_copy(update={"window_id": "finder-1"}))
    attempt = attempt.model_copy(
        update={
            "trigger": attempt.trigger.model_copy(
                update={
                    "trigger_type": TriggerType.MANUAL_OS_FRONTMOST_WINDOW_HOTKEY,
                    "capture_strategy": CaptureStrategy.OS_WINDOW,
                }
            ),
            "window_hints": (incomplete,),
            "native_timing_receipt": receipt,
        }
    )

    response = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}", **NATIVE_CAPTURE_SECRET_HEADER},
        json=attempt.model_dump(mode="json"),
    )

    assert response.status_code == 403
    payload = response.json()
    audits = tuple(
        audit
        for audit in _container(client).repositories.audits.list(limit=20)
        if audit.audit_id == payload["audit_id"]
    )
    assert audits[0].details["reason"] == "os_window_primary_hint_missing"


def _native_os_window_receipt(hint: WindowHint) -> NativeCaptureTimingReceipt:
    assert hint.frame is not None
    metadata: dict[str, JsonScalar] = {
        "capture_strategy": CaptureStrategy.OS_WINDOW.value,
        "os_window_app_name": hint.app_name,
        "os_window_process_id": hint.process_id,
        "os_window_frame_x": hint.frame.x,
        "os_window_frame_y": hint.frame.y,
        "os_window_frame_width": hint.frame.width,
        "os_window_frame_height": hint.frame.height,
        "os_window_frame_space": hint.frame.coordinate_space.value,
    }
    if hint.window_id is not None:
        metadata["os_window_window_id"] = hint.window_id
    if hint.bundle_id is not None:
        metadata["os_window_bundle_id"] = hint.bundle_id
    if hint.display_id is not None:
        metadata["os_window_display_id"] = hint.display_id
    return NativeCaptureTimingReceipt(
        authority=NativeCaptureTimingAuthority.MACOS_CAPTURE,
        captured_at_monotonic_ms=123_456,
        source_clock=NativeTimingClock.SYSTEM_UPTIME_MS,
        metadata=metadata,
    )


def test_primary_non_provider_surface_keeps_primary_source_when_secondary_web_succeeds(
    client, token, capture_save_request, provider_session_registration
):
    attempt = _container(client).capture_attempts.from_legacy_save_request(capture_save_request)
    region = attempt.selection_geometry.selected_region
    preview_hint = WindowHint(
        app_name="Preview",
        title="Quarterly Plan.pdf",
        process_id=101,
        window_id="preview_main",
        frame=region,
        overlap_ratio=1.0,
        confidence=0.9,
    )
    chrome_hint = WindowHint(
        app_name="Google Chrome",
        title="ACME Pricing Dashboard",
        process_id=202,
        window_id="win_test",
        frame=region,
        overlap_ratio=0.32,
        confidence=0.96,
    )
    attempt = attempt.model_copy(update={"window_hints": (preview_hint, chrome_hint)})

    response = _post_capture_with_web_provider(client, token, attempt, provider_session_registration)
    payload = response.json()

    assert response.status_code == 200
    assert payload["data"]["status"] == "accepted"
    event = payload["data"]["event"]
    assert event["source_binding"]["source_ref"]["app_name"] == "Preview"
    assert event["source_binding"]["source_ref"]["title"] == "Quarterly Plan.pdf"
    assert event["event_type"] == "screen.region.captured"

    diagnose = client.get(
        f"/v1/captures/diagnose/{attempt.trigger.trigger_id}",
        headers={"authorization": f"Bearer {token}"},
    ).json()
    manifest = diagnose["data"]["manifest"]
    assert manifest["route_plan"]["primary_surface_id"] == "surface_0"
    outcomes = manifest["provider_outcomes"]
    assert any(
        outcome["provider_key"] == "web.browser_extension"
        and outcome["role"] == "secondary_source"
        and outcome["status"] == "succeeded"
        for outcome in outcomes
    )

    inspect = client.get(
        f"/v1/events/{event['event_id']}?view=event_inspect&purpose=agent_deep_read",
        headers={"authorization": f"Bearer {token}"},
    ).json()
    contributions = inspect["data"]["source_contributions"]
    assert contributions[0]["role"] == "primary_source"
    assert contributions[0]["app_name"] == "Preview"
    assert contributions[0]["provider_kind"] == "system_evidence"
    assert contributions[0]["status"] is None
    assert contributions[0]["overlap_ratio"] == 1.0
    assert any(
        contribution["role"] == "secondary_source"
        and contribution["app_name"] == "Google Chrome"
        and contribution["provider_key"] == "web.browser_extension"
        and contribution["status"] == "succeeded"
        for contribution in contributions
    )


def test_capture_canonical_text_is_searchable(client, token, capture_save_request, provider_session_registration):
    headers = {"authorization": f"Bearer {token}"}
    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]

    search = client.get("/v1/search?query=Budget+variance", headers=headers)
    payload = search.json()

    assert search.status_code == 200
    assert payload["ok"] is True
    assert payload["data"]["events"] == []
    assert payload["data"]["results"][0]["event_id"] == event_id
    assert payload["data"]["results"][0]["user_note"] == "用于 ACME 续约 brief"
    assert payload["data"]["results"][0]["user_note_truncated"] is False
    assert "Budget variance" in payload["data"]["results"][0]["canonical_text_snippet"]
    assert payload["data"]["results"][0]["match_reason"] == "canonical_text"


def test_search_entities_redacts_echoed_query(client, token):
    headers = {"authorization": f"Bearer {token}"}
    response = client.get(
        "/v1/search/entities",
        headers=headers,
        params={
            "query": (
                "/Users/example/private.txt Bearer SHOULD_NOT_LEAK_ENTITY_BEARER "
                "https://example.test/entity?token=SHOULD_NOT_LEAK_ENTITY_URL#frag"
            )
        },
    )
    payload = response.json()
    serialized = json.dumps(payload["data"], sort_keys=True)

    assert response.status_code == 200
    assert "SHOULD_NOT_LEAK" not in serialized
    assert "/Users/example" not in serialized
    assert "token=" not in serialized
    assert "frag" not in serialized
    assert "https://example.test/entity" in serialized


def test_search_filters_explain_and_user_note_keyword_index(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]

    filtered = client.get(
        "/v1/search?query=Budget+variance&app=Chrome&domain=example.test&source=web&status=agent_ready&explain=true",
        headers=headers,
    ).json()
    workspace = client.get("/v1/search?query=Budget+variance&workspace=auto", headers=headers).json()
    wrong_workspace = client.get("/v1/search?query=Budget+variance&workspace=ws_missing", headers=headers).json()
    wrong_app = client.get("/v1/search?query=Budget+variance&app=Safari", headers=headers).json()
    note = client.get("/v1/search?query=续约&explain=true", headers=headers).json()
    wrong_entity = client.get("/v1/search?query=Budget+variance&entity=Globex", headers=headers).json()
    facets = client.get("/v1/search/facets?domain=example.test", headers=headers).json()

    assert filtered["data"]["backend"] == "sqlite_keyword"
    assert filtered["data"]["results"][0]["event_id"] == event_id
    assert filtered["data"]["results"][0]["match_reason"] == "canonical_text"
    assert workspace["data"]["results"][0]["event_id"] == event_id
    assert wrong_workspace["data"]["results"] == []
    assert filtered["data"]["explain"][0]["backend"] == "sqlite_keyword"
    assert filtered["data"]["explain"][0]["matched_fields"]
    assert wrong_app["data"]["results"] == []
    assert wrong_entity["data"]["results"] == []
    assert note["data"]["results"][0]["event_id"] == event_id
    assert note["data"]["results"][0]["match_reason"] == "user_note"
    assert "Chrome" in facets["data"]["facets"]["apps"]
    assert "https://example.test" in facets["data"]["facets"]["origins"]


def test_capture_with_a11y_derives_selection_text_preview(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    saved = _post_capture_with_web_and_a11y_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    artifacts = saved["data"]["artifacts"]
    selection_text = next(artifact for artifact in artifacts if artifact["artifact_type"] == "a11y_selection_text")
    canonical = next(artifact for artifact in artifacts if artifact["artifact_type"] == "canonical_text")

    selection_content = client.get(_content_path(selection_text["artifact_id"], event_id), headers=headers).json()
    canonical_content = client.get(_content_path(canonical["artifact_id"], event_id), headers=headers).json()
    search = client.get("/v1/search?query=Procurement+delayed", headers=headers).json()
    inspect_refs = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_citations&inspect_views=evidence_refs",
        headers=headers,
    ).json()
    manifest = client.get(f"/v1/events/{event_id}/manifest", headers=headers).json()
    evidence_metadata = client.get(f"/v1/evidence?event={event_id}", headers=headers).json()

    assert selection_text["role"] == "selection_text"
    assert selection_text["provider_key"] == "system.enrichment.selection_text"
    assert selection_text["ingest_state"] == "dlp_passed"
    assert selection_text["allowed_scopes"] == ["read_metadata", "read_text"]
    assert selection_text["metadata"]["source_block_count"] >= 4
    assert selection_text["metadata"]["text_length"] == len(
        "Account\nStatus\nACME\nProcurement delayed\nAPI token: [REDACTED]"
    )
    assert selection_content["data"]["text"] == ("Account\nStatus\nACME\nProcurement delayed\nAPI token: [REDACTED]")
    assert "SHOULD_NOT_LEAK" not in selection_content["data"]["text"]
    assert "Procurement delayed" in canonical_content["data"]["text"]
    assert "Full page text that must not enter preview" not in canonical_content["data"]["text"]
    assert "Browser toolbar" not in canonical_content["data"]["text"]
    assert search["data"]["events"] == []
    assert search["data"]["results"][0]["event_id"] == event_id
    assert search["data"]["results"][0]["event_id"] == event_id
    assert search["data"]["results"][0]["user_note"] == "用于 ACME 续约 brief"
    assert "Procurement delayed" in search["data"]["results"][0]["selection_text_snippet"]
    assert search["data"]["results"][0]["match_reason"] == "selection_text"
    assert search["data"]["results"][0]["selection_text_snippet"].startswith("Account")
    assert any(item["artifact_type"] == "a11y_selection_text" for item in inspect_refs["data"]["readable_evidence"])
    assert "Procurement delayed" not in json.dumps(manifest["data"], sort_keys=True)
    assert "Procurement delayed" not in json.dumps(evidence_metadata["data"], sort_keys=True)


def test_overbroad_a11y_text_does_not_fallback_into_canonical(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    saved = _post_capture_with_web_and_a11y_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
        a11y_result_builder=_a11y_overbroad_collect_result,
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    artifacts = saved["data"]["artifacts"]
    canonical = next(artifact for artifact in artifacts if artifact["artifact_type"] == "canonical_text")
    canonical_content = client.get(_content_path(canonical["artifact_id"], event_id), headers=headers).json()
    leak_search = client.get("/v1/search?query=SHOULD_NOT_LEAK_OVERBROAD_A11Y", headers=headers).json()

    assert not any(artifact["artifact_type"] == "a11y_selection_text" for artifact in artifacts)
    assert "SHOULD_NOT_LEAK_OVERBROAD_A11Y" not in canonical_content["data"]["text"]
    assert leak_search["data"]["events"] == []


def test_capture_normalizes_provider_artifact_policy(
    client, token, capture_save_request, provider_session_registration
):
    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    artifacts = saved["data"]["artifacts"]

    full_dom = next(artifact for artifact in artifacts if artifact["artifact_type"] == "browser_full_dom")
    visible_text = next(artifact for artifact in artifacts if artifact["artifact_type"] == "browser_visible_text")
    canonical = next(artifact for artifact in artifacts if artifact["artifact_type"] == "canonical_text")

    assert full_dom["ingest_state"] == "quarantined"
    assert full_dom["redaction_state"] == "quarantined"
    assert full_dom["allowed_scopes"] == ["read_metadata"]
    assert visible_text["ingest_state"] == "quarantined"
    assert visible_text["allowed_scopes"] == ["read_metadata"]
    assert canonical["ingest_state"] == "dlp_passed"
    assert canonical["allowed_scopes"] == ["read_metadata", "read_text"]


def test_browser_region_selection_text_is_promoted_when_page_evidence_agrees(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    saved = _post_capture_with_web_and_a11y_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
        selected_text="Procurement delayed",
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    artifacts = saved["data"]["artifacts"]
    selection_text = next(artifact for artifact in artifacts if artifact["artifact_type"] == "dom_selection_text")
    selection_content = client.get(_content_path(selection_text["artifact_id"], event_id), headers=headers).json()
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=selection_text,evidence_refs",
        headers=headers,
    ).json()
    assert selection_text["role"] == "selection_text"
    assert selection_text["provider_key"] == "system.enrichment.selection_text"
    assert selection_text["metadata"]["page_support_count"] >= 1
    assert selection_text["metadata"]["system_evidence_supported"] is True
    assert selection_text["metadata"]["selection_map_evidence_id"]
    assert "Procurement delayed" in selection_content["data"]["text"]
    readable_selection = next(
        item for item in inspect["data"]["readable_evidence"] if item["artifact_type"] == "dom_selection_text"
    )
    assert readable_selection["text"] == "Procurement delayed"


def test_browser_region_selection_map_uses_pixel_region_when_coordinate_space_is_screen_px(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    pixel_region = BoundingBox(x=240, y=280, width=1040, height=560, coordinate_space=CoordinateSpace.SCREEN_PX)
    request = capture_save_request.model_copy(
        update={
            "selection_geometry": capture_save_request.selection_geometry.model_copy(
                update={"pixel_region": pixel_region}
            )
        }
    )

    saved = _post_capture_with_web_and_a11y_provider(
        client,
        token,
        request,
        provider_session_registration,
        selected_text="Procurement delayed",
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    selection_text = next(
        artifact for artifact in saved["data"]["artifacts"] if artifact["artifact_type"] == "dom_selection_text"
    )
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=selection_text,evidence_refs",
        headers=headers,
    ).json()

    assert selection_text["metadata"]["selection_map_evidence_id"]
    assert selection_text["metadata"]["system_evidence_supported"] is True
    readable_selection = next(
        item for item in inspect["data"]["readable_evidence"] if item["artifact_type"] == "dom_selection_text"
    )
    assert readable_selection["text"] == "Procurement delayed"


def test_screen_px_selection_map_must_match_pixel_region_not_macos_region(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    pixel_region = BoundingBox(x=240, y=280, width=1040, height=560, coordinate_space=CoordinateSpace.SCREEN_PX)
    request = capture_save_request.model_copy(
        update={
            "selection_geometry": capture_save_request.selection_geometry.model_copy(
                update={"pixel_region": pixel_region}
            )
        }
    )
    source_binding_id = "src_test_web_command"
    command_id = "cmd_screen_px_wrong_region"
    selected_text = "SCREEN_PX_MAP_MUST_MATCH_PIXEL_REGION"
    selected_region_claimed_as_pixels = capture_save_request.selection_geometry.selected_region.model_dump(mode="json")
    selected_region_claimed_as_pixels["coordinate_space"] = CoordinateSpace.SCREEN_PX.value
    selected = _text_evidence(
        "selected_text",
        "browser_selected_text",
        selected_text,
        "https://example.test/acme#wrong-screen-px-selection",
        command_id,
        provider_session_registration.provider_session_id,
        source_binding_id,
        metadata={"selection_source": "browser_dom_region", "selection_confidence": 0.99},
    )
    wrong_map = _json_evidence(
        "selection_map",
        "selection_map",
        "selection_map",
        {
            "binding_id": source_binding_id,
            "screen_region": selected_region_claimed_as_pixels,
            "viewport_region": {
                "x": 40,
                "y": 80,
                "width": 320,
                "height": 44,
                "coordinate_space": "viewport_css_px",
            },
            "transforms": [],
            "spans": [{"selector": "#wrong-map", "start": 0, "end": len(selected_text), "text": selected_text}],
            "confidence": 0.99,
        },
        source_uri="https://example.test/acme#wrong-screen-px-map",
        command_id=command_id,
        session_id=provider_session_registration.provider_session_id,
        source_binding_id=source_binding_id,
    )
    supporting_page_text = _json_evidence(
        "page_text",
        "browser_readability_markdown",
        "source_text",
        {
            "markdown": selected_text,
            "plain_text": selected_text,
            "method": "dom_text_snapshot_v1",
            "title": "Wrong screen_px map",
            "content_hash": "wrong-screen-px-map",
        },
        source_uri="https://example.test/acme#wrong-screen-px-page",
        command_id=command_id,
        session_id=provider_session_registration.provider_session_id,
        source_binding_id=source_binding_id,
    )

    def a11y_supporting_selected_text(
        command_message: dict[str, Any],
        registration: ProviderSessionRegistration,
    ) -> dict[str, Any]:
        command = command_message["command"]
        command_id = command["command_id"]
        selection = command["attempt"]["selection_geometry"]["selected_region"]
        observed_at = datetime.now(UTC).isoformat()
        blocks = [_a11y_text_block(selected_text, "AXStaticText", 130, 150, 360, 24, 0, True)]
        snapshot = {
            "permission_state": "granted",
            "app_name": "Google Chrome",
            "process_id": 4242,
            "window_id": "win_test",
            "selection": selection,
            "root_nodes": [],
            "text_blocks": blocks,
            "full_text": selected_text,
            "coverage": {
                "selection": selection,
                "permission_state": "granted",
                "node_count": 1,
                "text_block_count": 1,
                "covered_area_ratio": 1.0,
                "confidence": 0.99,
                "error_message": None,
            },
        }
        evidence = [
            _a11y_evidence(
                "a11y",
                "a11y_tree",
                "ui_structure",
                snapshot,
                source_uri="macos://a11y/4242/win_test#wrong-screen-px-tree",
                command_id=command_id,
                session_id=registration.provider_session_id,
                content_type="application/json",
                payload_schema="a11y_snapshot",
            ),
            _a11y_evidence(
                "a11y",
                "a11y_text",
                "source_text",
                selected_text,
                source_uri="macos://a11y/4242/win_test#wrong-screen-px-text",
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
                "diagnostics": {"fixture": True, "permission_state": "granted", "actual_window_id": "win_test"},
                "completed_at": observed_at,
            },
            "diagnostics": {"fixture": True, "permission_state": "granted", "actual_window_id": "win_test"},
            "completed_at": observed_at,
        }

    saved = _post_capture_with_web_and_a11y_provider(
        client,
        token,
        request,
        provider_session_registration,
        a11y_result_builder=a11y_supporting_selected_text,
        extra_evidence=(selected, wrong_map, supporting_page_text),
        selected_text="",
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=selection_text,canonical",
        headers=headers,
    ).json()

    assert not any(artifact["artifact_type"] == "dom_selection_text" for artifact in saved["data"]["artifacts"])
    assert selected_text not in json.dumps(inspect["data"], sort_keys=True)


def test_browser_selection_cannot_extend_beyond_system_supported_text(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    source_binding_id = "src_test_web_command"
    command_id = "cmd_partial_system_support_browser_selection"
    selected_text = "Procurement delayed Quarterly Alpha Echo 4729"
    selected_region = capture_save_request.selection_geometry.selected_region
    selected = _text_evidence(
        "selected_text",
        "browser_selected_text",
        selected_text,
        "https://example.test/acme#partial-system-selection",
        command_id,
        provider_session_registration.provider_session_id,
        source_binding_id,
        metadata={"selection_source": "browser_dom_region", "selection_confidence": 0.99},
    )
    selection_map = _json_evidence(
        "selection_map",
        "selection_map",
        "selection_map",
        {
            "binding_id": source_binding_id,
            "screen_region": selected_region.model_dump(mode="json"),
            "viewport_region": {
                "x": 40,
                "y": 80,
                "width": 320,
                "height": 44,
                "coordinate_space": "viewport_css_px",
            },
            "transforms": [],
            "spans": [{"selector": "#partial", "start": 0, "end": len(selected_text), "text": selected_text}],
            "confidence": 0.99,
        },
        source_uri="https://example.test/acme#partial-system-selection-map",
        command_id=command_id,
        session_id=provider_session_registration.provider_session_id,
        source_binding_id=source_binding_id,
    )
    supporting_page_text = _json_evidence(
        "page_text",
        "browser_readability_markdown",
        "source_text",
        {
            "markdown": selected_text,
            "plain_text": selected_text,
            "method": "dom_text_snapshot_v1",
            "title": "Partial support page",
            "content_hash": "partial-system-support",
        },
        source_uri="https://example.test/acme#partial-system-page",
        command_id=command_id,
        session_id=provider_session_registration.provider_session_id,
        source_binding_id=source_binding_id,
    )

    saved = _post_capture_with_web_and_a11y_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
        extra_evidence=(selected, selection_map, supporting_page_text),
        selected_text="",
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=selection_text,evidence_refs",
        headers=headers,
    ).json()

    assert not any(artifact["artifact_type"] == "dom_selection_text" for artifact in saved["data"]["artifacts"])
    assert selected_text not in json.dumps(inspect["data"], sort_keys=True)


def test_screen_px_selection_map_requires_pixel_region_reference(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    source_binding_id = "src_test_web_command"
    command_id = "cmd_screen_px_without_pixel_region"
    selected_text = "Procurement delayed"
    screen_region = capture_save_request.selection_geometry.selected_region.model_dump(mode="json")
    screen_region["coordinate_space"] = CoordinateSpace.SCREEN_PX.value
    selected = _text_evidence(
        "selected_text",
        "browser_selected_text",
        selected_text,
        "https://example.test/acme#screen-px-without-pixel-region",
        command_id,
        provider_session_registration.provider_session_id,
        source_binding_id,
        metadata={"selection_source": "browser_dom_region", "selection_confidence": 0.99},
    )
    selection_map = _json_evidence(
        "selection_map",
        "selection_map",
        "selection_map",
        {
            "binding_id": source_binding_id,
            "screen_region": screen_region,
            "viewport_region": {
                "x": 40,
                "y": 80,
                "width": 320,
                "height": 44,
                "coordinate_space": "viewport_css_px",
            },
            "transforms": [],
            "spans": [{"selector": "#screen-px", "start": 0, "end": len(selected_text), "text": selected_text}],
            "confidence": 0.99,
        },
        source_uri="https://example.test/acme#screen-px-without-pixel-region-map",
        command_id=command_id,
        session_id=provider_session_registration.provider_session_id,
        source_binding_id=source_binding_id,
    )
    supporting_page_text = _json_evidence(
        "page_text",
        "browser_readability_markdown",
        "source_text",
        {
            "markdown": selected_text,
            "plain_text": selected_text,
            "method": "dom_text_snapshot_v1",
            "title": "Screen px without pixel region",
            "content_hash": "screen-px-without-pixel-region",
        },
        source_uri="https://example.test/acme#screen-px-without-pixel-region-page",
        command_id=command_id,
        session_id=provider_session_registration.provider_session_id,
        source_binding_id=source_binding_id,
    )

    saved = _post_capture_with_web_and_a11y_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
        extra_evidence=(selected, selection_map, supporting_page_text),
        selected_text="",
    ).json()

    assert not any(artifact["artifact_type"] == "dom_selection_text" for artifact in saved["data"]["artifacts"])


@pytest.mark.parametrize("coordinate_space", ["viewport_css_px", "page_css_px", "unknown"])
def test_selection_map_rejects_non_screen_coordinate_spaces_for_screen_region(
    client, token, capture_save_request, provider_session_registration, coordinate_space
):
    source_binding_id = "src_test_web_command"
    command_id = f"cmd_invalid_screen_region_space_{coordinate_space}"
    selected_text = "Procurement delayed"
    screen_region = capture_save_request.selection_geometry.selected_region.model_dump(mode="json")
    screen_region["coordinate_space"] = coordinate_space
    selected = _text_evidence(
        "selected_text",
        "browser_selected_text",
        selected_text,
        f"https://example.test/acme#invalid-screen-region-space-{coordinate_space}",
        command_id,
        provider_session_registration.provider_session_id,
        source_binding_id,
        metadata={"selection_source": "browser_dom_region", "selection_confidence": 0.99},
    )
    selection_map = _json_evidence(
        "selection_map",
        "selection_map",
        "selection_map",
        {
            "binding_id": source_binding_id,
            "screen_region": screen_region,
            "viewport_region": {
                "x": 40,
                "y": 80,
                "width": 320,
                "height": 44,
                "coordinate_space": "viewport_css_px",
            },
            "transforms": [],
            "spans": [{"selector": "#invalid-space", "start": 0, "end": len(selected_text), "text": selected_text}],
            "confidence": 0.99,
        },
        source_uri=f"https://example.test/acme#invalid-screen-region-space-{coordinate_space}-map",
        command_id=command_id,
        session_id=provider_session_registration.provider_session_id,
        source_binding_id=source_binding_id,
    )
    supporting_page_text = _json_evidence(
        "page_text",
        "browser_readability_markdown",
        "source_text",
        {
            "markdown": selected_text,
            "plain_text": selected_text,
            "method": "dom_text_snapshot_v1",
            "title": "Invalid screen region coordinate space",
            "content_hash": f"invalid-screen-region-space-{coordinate_space}",
        },
        source_uri=f"https://example.test/acme#invalid-screen-region-space-{coordinate_space}-page",
        command_id=command_id,
        session_id=provider_session_registration.provider_session_id,
        source_binding_id=source_binding_id,
    )

    saved = _post_capture_with_web_and_a11y_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
        extra_evidence=(selected, selection_map, supporting_page_text),
        selected_text="",
    ).json()

    assert not any(artifact["artifact_type"] == "dom_selection_text" for artifact in saved["data"]["artifacts"])


def test_capture_manifest_and_metadata_do_not_leak_text(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]
    canonical = next(
        artifact for artifact in saved["data"]["artifacts"] if artifact["artifact_type"] == "canonical_text"
    )

    manifest = client.get(f"/v1/events/{event_id}/manifest", headers=headers).json()
    evidence = client.get(f"/v1/evidence?event={event_id}", headers=headers).json()
    artifact = client.get(f"/v1/artifacts/{canonical['artifact_id']}", headers=headers).json()
    metadata_payload = json.dumps([manifest["data"], evidence["data"], artifact["data"]], sort_keys=True)

    assert "Budget variance" not in metadata_payload
    assert "Procurement delayed" not in metadata_payload
    assert "local-artifact://" not in metadata_payload

    text = client.get(_content_path(canonical["artifact_id"], event_id), headers=headers).json()
    assert "Budget variance" in text["data"]["text"]
    assert "SHOULD_NOT_LEAK" not in text["data"]["text"]
    assert "Authorization: Bearer SHOULD_NOT_LEAK_VISIBLE_BEARER" not in text["data"]["text"]


def test_metadata_views_sanitize_url_queries_and_vault_handles(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    tab = provider_session_registration.tab
    assert tab is not None
    secret_registration = provider_session_registration.model_copy(
        update={
            "tab": tab.model_copy(
                update={"url": "https://example.test/acme?token=SHOULD_NOT_LEAK_URL_TOKEN#secret-fragment"}
            )
        }
    )
    saved = _post_capture_with_web_provider(client, token, capture_save_request, secret_registration).json()
    event_id = saved["data"]["event"]["event_id"]
    manifest = client.get(f"/v1/events/{event_id}/manifest", headers=headers).json()
    evidence = client.get(f"/v1/evidence?event={event_id}", headers=headers).json()
    search = client.get("/v1/search?query=Budget+variance", headers=headers).json()
    metadata_payload = json.dumps([manifest["data"], evidence["data"]], sort_keys=True)

    assert "SHOULD_NOT_LEAK_URL_TOKEN" not in metadata_payload
    assert "secret-fragment" not in metadata_payload
    assert "local-artifact://" not in metadata_payload
    assert search["data"]["results"][0]["source"]["sanitized_url"] == "https://example.test/acme"


def test_index_projection_sanitizes_source_uri(client, token, capture_save_request, provider_session_registration):
    headers = {"authorization": f"Bearer {token}"}
    tab = provider_session_registration.tab
    assert tab is not None
    secret_registration = provider_session_registration.model_copy(
        update={
            "tab": tab.model_copy(
                update={"url": "https://example.test/acme?token=SHOULD_NOT_LEAK_INDEX_TOKEN#secret-fragment"}
            )
        }
    )
    saved = _post_capture_with_web_provider(client, token, capture_save_request, secret_registration).json()
    event_id = saved["data"]["event"]["event_id"]
    container = _container(client)
    with container.repositories.database.transaction() as connection:
        rows = connection.execute(
            "SELECT source_uri, payload FROM keyword_index_documents WHERE event_id = ?",
            (event_id,),
        ).fetchall()
    index_payload = json.dumps([dict(row) for row in rows], sort_keys=True)
    search = client.get("/v1/search?query=Budget+variance&explain=true", headers=headers).json()

    assert "SHOULD_NOT_LEAK_INDEX_TOKEN" not in index_payload
    assert "secret-fragment" not in index_payload
    assert search["data"]["results"][0]["source"]["sanitized_url"] == "https://example.test/acme"


def test_capture_canonical_text_redacts_provider_secret_sentinels(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]
    canonical = next(
        artifact for artifact in saved["data"]["artifacts"] if artifact["artifact_type"] == "canonical_text"
    )

    text = client.get(_content_path(canonical["artifact_id"], event_id), headers=headers).json()["data"]["text"]
    leak_search = client.get("/v1/search?query=SHOULD_NOT_LEAK_VISIBLE_TOKEN", headers=headers).json()

    assert "Budget variance +18%" in text
    assert "Procurement delayed" in text
    assert "SHOULD_NOT_LEAK" not in text
    assert "Authorization: Bearer [REDACTED]" in text
    assert "API token: [REDACTED]" in text
    assert leak_search["data"]["events"] == []


def test_provider_cannot_promote_forged_canonical_text(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    forged = _text_evidence(
        "canonical_text",
        "canonical_text",
        "SHOULD_NOT_LEAK_FORGED_CANONICAL",
        "https://example.test/acme#forged-canonical",
        "cmd_forged",
        provider_session_registration.provider_session_id,
        "src_forged",
        role="canonical_text",
    )
    saved = _post_capture_with_web_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
        extra_evidence=(forged,),
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    forged_artifact = _stored_artifact_by_source_uri(client, event_id, "https://example.test/acme#forged-canonical")
    leak_search = client.get("/v1/search?query=SHOULD_NOT_LEAK_FORGED_CANONICAL", headers=headers).json()
    forged_content = client.get(_content_path(forged_artifact["artifact_id"], event_id), headers=headers).json()

    assert forged_artifact["provider_key"] == "web.browser_extension"
    assert forged_artifact["ingest_state"] == "quarantined"
    assert forged_artifact["allowed_scopes"] == ["read_metadata"]
    assert leak_search["data"]["events"] == []
    assert forged_content["ok"] is False
    assert forged_content["error"]["code"] == "policy.denied"


def test_provider_cannot_promote_forged_selection_text(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    forged = _text_evidence(
        "selection_text",
        "a11y_selection_text",
        "SHOULD_NOT_LEAK_FORGED_SELECTION_TEXT",
        "https://example.test/acme#forged-selection-text",
        "cmd_forged",
        provider_session_registration.provider_session_id,
        "src_forged",
        role="selection_text",
    )
    saved = _post_capture_with_web_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
        extra_evidence=(forged,),
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    forged_artifact = _stored_artifact_by_source_uri(
        client,
        event_id,
        "https://example.test/acme#forged-selection-text",
    )
    leak_search = client.get("/v1/search?query=SHOULD_NOT_LEAK_FORGED_SELECTION_TEXT", headers=headers).json()
    forged_content = client.get(_content_path(forged_artifact["artifact_id"], event_id), headers=headers).json()

    assert forged_artifact["provider_key"] == "web.browser_extension"
    assert forged_artifact["ingest_state"] == "quarantined"
    assert forged_artifact["allowed_scopes"] == ["read_metadata"]
    assert leak_search["data"]["events"] == []
    assert forged_content["ok"] is False
    assert forged_content["error"]["code"] == "policy.denied"


def test_provider_cannot_pollute_system_appshot_refs(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    forged_snapshot = {
        "schema_version": 1,
        "capture_revision": "forged-source-appshot",
        "selected_region": capture_save_request.selection_geometry.selected_region.model_dump(mode="json"),
        "primary_surface_id": "forged_surface",
        "primary_app_name": "Forged Browser",
        "surfaces": [],
        "quality": {
            "screenshot_present": False,
            "a11y_supported": False,
            "surface_count": 0,
            "text_block_count": 0,
            "primary_confidence": 0,
            "coverage_confidence": 0,
            "diagnostics": [],
        },
        "permissions": {
            "screen_recording": "unknown",
            "accessibility": "unknown",
            "target_app_allowed": None,
            "blocked_reason": None,
        },
        "components": [],
        "metadata": {"vault_path": "/tmp/SHOULD_NOT_LEAK"},
    }
    forged = _json_evidence(
        "system_appshot",
        "system_appshot",
        "system_appshot",
        forged_snapshot,
        source_uri="https://example.test/acme#forged-system-appshot",
        command_id="cmd_forged",
        session_id=provider_session_registration.provider_session_id,
        source_binding_id="src_forged",
    )
    saved = _post_capture_with_web_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
        extra_evidence=(forged,),
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    forged_artifact = _stored_artifact_by_source_uri(
        client,
        event_id,
        "https://example.test/acme#forged-system-appshot",
    )
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=system_appshot",
        headers=headers,
    ).json()
    manifest = client.get(f"/v1/events/{event_id}/manifest", headers=headers).json()

    assert forged_artifact["provider_key"] == "web.browser_extension"
    assert forged_artifact["ingest_state"] == "dlp_passed"
    assert inspect["data"]["system_appshot"]["capture_revision"] != "forged-source-appshot"
    assert manifest["data"]["system_appshot_evidence_id"] != forged_artifact["evidence_id"]
    assert "/tmp/SHOULD_NOT_LEAK" not in json.dumps(inspect["data"]["system_appshot"], sort_keys=True)


def test_provider_cannot_promote_forged_browser_region_selection_text(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    source_binding_id = "src_test_web_command"
    command_id = "cmd_forged_browser_selection"
    forged_text = "SHOULD_NOT_LEAK_FORGED_BROWSER_SELECTION"
    forged_selected = _text_evidence(
        "selected_text",
        "browser_selected_text",
        forged_text,
        "https://example.test/acme#forged-browser-selection",
        command_id,
        provider_session_registration.provider_session_id,
        source_binding_id,
        metadata={"selection_source": "browser_dom_region", "selection_confidence": 0.99},
    )
    forged_map = _json_evidence(
        "selection_map",
        "selection_map",
        "selection_map",
        {
            "binding_id": source_binding_id,
            "screen_region": {
                "x": 9999,
                "y": 9999,
                "width": 100,
                "height": 80,
                "coordinate_space": "screen_px",
            },
            "viewport_region": {
                "x": 1,
                "y": 1,
                "width": 100,
                "height": 80,
                "coordinate_space": "viewport_css_px",
            },
            "transforms": [],
            "spans": [{"selector": "#forged", "start": 0, "end": len(forged_text), "text": forged_text}],
            "confidence": 0.99,
        },
        source_uri="https://example.test/acme#forged-browser-selection-map",
        command_id=command_id,
        session_id=provider_session_registration.provider_session_id,
        source_binding_id=source_binding_id,
    )
    saved = _post_capture_with_web_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
        selected_text="",
        extra_evidence=(forged_selected, forged_map),
    ).json()
    event_id = saved["data"]["event"]["event_id"]

    leak_search = client.get(f"/v1/search?query={forged_text}", headers=headers).json()
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=selection_text,canonical",
        headers=headers,
    ).json()

    assert leak_search["data"]["events"] == []
    assert forged_text not in json.dumps(inspect["data"], sort_keys=True)


def test_provider_cannot_promote_browser_selection_without_page_support(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    source_binding_id = "src_test_web_command"
    command_id = "cmd_unsupported_browser_selection"
    forged_text = "SHOULD_NOT_LEAK_UNSUPPORTED_BROWSER_SELECTION"
    forged_selected = _text_evidence(
        "selected_text",
        "browser_selected_text",
        forged_text,
        "https://example.test/acme#unsupported-browser-selection",
        command_id,
        provider_session_registration.provider_session_id,
        source_binding_id,
        metadata={"selection_source": "browser_dom_region", "selection_confidence": 0.99},
    )
    selected_region = (
        capture_save_request.selection_geometry.pixel_region or capture_save_request.selection_geometry.selected_region
    )
    forged_map = _json_evidence(
        "selection_map",
        "selection_map",
        "selection_map",
        {
            "binding_id": source_binding_id,
            "screen_region": selected_region.model_dump(mode="json"),
            "viewport_region": {
                "x": 40,
                "y": 80,
                "width": 320,
                "height": 44,
                "coordinate_space": "viewport_css_px",
            },
            "transforms": [],
            "spans": [{"selector": "#forged", "start": 0, "end": len(forged_text), "text": forged_text}],
            "confidence": 0.99,
        },
        source_uri="https://example.test/acme#unsupported-browser-selection-map",
        command_id=command_id,
        session_id=provider_session_registration.provider_session_id,
        source_binding_id=source_binding_id,
    )
    saved = _post_capture_with_web_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
        selected_text="",
        extra_evidence=(forged_selected, forged_map),
    ).json()
    event_id = saved["data"]["event"]["event_id"]

    leak_search = client.get(f"/v1/search?query={forged_text}", headers=headers).json()
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=selection_text,canonical",
        headers=headers,
    ).json()

    assert leak_search["data"]["events"] == []
    assert forged_text not in json.dumps(inspect["data"], sort_keys=True)


def test_provider_cannot_self_support_browser_selection_with_provider_page_text(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    source_binding_id = "src_test_web_command"
    command_id = "cmd_self_supported_browser_selection"
    forged_text = "SHOULD_NOT_LEAK_SELF_SUPPORTED_BROWSER_SELECTION"
    selected_region = (
        capture_save_request.selection_geometry.pixel_region or capture_save_request.selection_geometry.selected_region
    )
    forged_selected = _text_evidence(
        "selected_text",
        "browser_selected_text",
        forged_text,
        "https://example.test/acme#self-supported-browser-selection",
        command_id,
        provider_session_registration.provider_session_id,
        source_binding_id,
        metadata={"selection_source": "browser_dom_region", "selection_confidence": 0.99},
    )
    forged_map = _json_evidence(
        "selection_map",
        "selection_map",
        "selection_map",
        {
            "binding_id": source_binding_id,
            "screen_region": selected_region.model_dump(mode="json"),
            "viewport_region": {
                "x": 40,
                "y": 80,
                "width": 320,
                "height": 44,
                "coordinate_space": "viewport_css_px",
            },
            "transforms": [],
            "spans": [{"selector": "#forged", "start": 0, "end": len(forged_text), "text": forged_text}],
            "confidence": 0.99,
        },
        source_uri="https://example.test/acme#self-supported-browser-selection-map",
        command_id=command_id,
        session_id=provider_session_registration.provider_session_id,
        source_binding_id=source_binding_id,
    )
    forged_page_text = _json_evidence(
        "page_text",
        "browser_readability_markdown",
        "source_text",
        {
            "markdown": forged_text,
            "plain_text": forged_text,
            "method": "dom_text_snapshot_v1",
            "title": "Forged page",
            "content_hash": "forged",
        },
        source_uri="https://example.test/acme#self-supported-page-text",
        command_id=command_id,
        session_id=provider_session_registration.provider_session_id,
        source_binding_id=source_binding_id,
    )
    saved = _post_capture_with_web_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
        selected_text="",
        extra_evidence=(forged_selected, forged_map, forged_page_text),
    ).json()
    event_id = saved["data"]["event"]["event_id"]

    leak_search = client.get(f"/v1/search?query={forged_text}", headers=headers).json()
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=selection_text,canonical",
        headers=headers,
    ).json()

    assert leak_search["data"]["events"] == []
    assert forged_text not in json.dumps(inspect["data"], sort_keys=True)


def test_provider_cannot_self_support_browser_selection_with_multiple_page_artifacts(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    source_binding_id = "src_test_web_command"
    command_id = "cmd_multi_self_supported_browser_selection"
    forged_text = "SHOULD_NOT_LEAK_MULTI_SELF_SUPPORTED_BROWSER_SELECTION"
    selected_region = (
        capture_save_request.selection_geometry.pixel_region or capture_save_request.selection_geometry.selected_region
    )
    forged_selected = _text_evidence(
        "selected_text",
        "browser_selected_text",
        forged_text,
        "https://example.test/acme#multi-self-supported-browser-selection",
        command_id,
        provider_session_registration.provider_session_id,
        source_binding_id,
        metadata={"selection_source": "browser_dom_region", "selection_confidence": 0.99},
    )
    forged_map = _json_evidence(
        "selection_map",
        "selection_map",
        "selection_map",
        {
            "binding_id": source_binding_id,
            "screen_region": selected_region.model_dump(mode="json"),
            "viewport_region": {
                "x": 40,
                "y": 80,
                "width": 320,
                "height": 44,
                "coordinate_space": "viewport_css_px",
            },
            "transforms": [],
            "spans": [{"selector": "#forged", "start": 0, "end": len(forged_text), "text": forged_text}],
            "confidence": 0.99,
        },
        source_uri="https://example.test/acme#multi-self-supported-browser-selection-map",
        command_id=command_id,
        session_id=provider_session_registration.provider_session_id,
        source_binding_id=source_binding_id,
    )
    forged_page_text = _json_evidence(
        "page_text",
        "browser_readability_markdown",
        "source_text",
        {
            "markdown": forged_text,
            "plain_text": forged_text,
            "method": "dom_text_snapshot_v1",
            "title": "Forged page",
            "content_hash": "forged",
        },
        source_uri="https://example.test/acme#multi-self-supported-page-text",
        command_id=command_id,
        session_id=provider_session_registration.provider_session_id,
        source_binding_id=source_binding_id,
    )
    forged_visible_text = _text_evidence(
        "visible_text",
        "browser_visible_text",
        forged_text,
        "https://example.test/acme#multi-self-supported-visible-text",
        command_id,
        provider_session_registration.provider_session_id,
        source_binding_id,
    )
    saved = _post_capture_with_web_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
        selected_text="",
        extra_evidence=(forged_selected, forged_map, forged_page_text, forged_visible_text),
    ).json()
    event_id = saved["data"]["event"]["event_id"]

    leak_search = client.get(f"/v1/search?query={forged_text}", headers=headers).json()
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=selection_text,canonical",
        headers=headers,
    ).json()

    assert leak_search["data"]["events"] == []
    assert forged_text not in json.dumps(inspect["data"], sort_keys=True)


def test_legacy_browser_window_selection_metadata_is_not_promoted(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    source_binding_id = "src_test_web_command"
    command_id = "cmd_legacy_window_selection"
    legacy_text = "SHOULD_NOT_LEAK_LEGACY_WINDOW_SELECTION"
    selected_region = (
        capture_save_request.selection_geometry.pixel_region or capture_save_request.selection_geometry.selected_region
    )
    legacy_selected = _text_evidence(
        "selected_text",
        "browser_selected_text",
        legacy_text,
        "https://example.test/acme#legacy-window-selection",
        command_id,
        provider_session_registration.provider_session_id,
        source_binding_id,
        metadata={"selection_source": "window_selection", "selection_confidence": 0.99},
    )
    legacy_map = _json_evidence(
        "selection_map",
        "selection_map",
        "selection_map",
        {
            "binding_id": source_binding_id,
            "screen_region": selected_region.model_dump(mode="json"),
            "viewport_region": {
                "x": 40,
                "y": 80,
                "width": 320,
                "height": 44,
                "coordinate_space": "viewport_css_px",
            },
            "transforms": [],
            "spans": [{"selector": "#legacy", "start": 0, "end": len(legacy_text), "text": legacy_text}],
            "confidence": 0.99,
        },
        source_uri="https://example.test/acme#legacy-window-selection-map",
        command_id=command_id,
        session_id=provider_session_registration.provider_session_id,
        source_binding_id=source_binding_id,
    )
    saved = _post_capture_with_web_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
        selected_text="",
        extra_evidence=(legacy_selected, legacy_map),
    ).json()
    event_id = saved["data"]["event"]["event_id"]

    leak_search = client.get(f"/v1/search?query={legacy_text}", headers=headers).json()
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=selection_text,canonical",
        headers=headers,
    ).json()

    assert leak_search["data"]["events"] == []
    assert legacy_text not in json.dumps(inspect["data"], sort_keys=True)


def test_provider_cannot_promote_forged_a11y_tree_into_selection_text(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    selection = capture_save_request.selection_geometry.selected_region.model_dump(mode="json")
    forged_snapshot = {
        "permission_state": "granted",
        "app_name": "Google Chrome",
        "process_id": 4242,
        "window_id": "win_test",
        "selection": selection,
        "root_nodes": [],
        "text_blocks": [
            _a11y_text_block(
                "SHOULD_NOT_LEAK_FORGED_A11Y_TREE",
                "AXStaticText",
                130,
                150,
                280,
                20,
                0,
                True,
            )
        ],
        "full_text": "SHOULD_NOT_LEAK_FORGED_A11Y_TREE",
        "coverage": {
            "selection": selection,
            "permission_state": "granted",
            "node_count": 1,
            "text_block_count": 1,
            "covered_area_ratio": 1.0,
            "confidence": 0.99,
            "error_message": None,
        },
    }
    forged = _a11y_evidence(
        "a11y",
        "a11y_tree",
        "ui_structure",
        forged_snapshot,
        source_uri="https://example.test/acme#forged-a11y-tree",
        command_id="cmd_forged",
        session_id=provider_session_registration.provider_session_id,
        content_type="application/json",
        payload_schema="a11y_snapshot",
        sensitivity="high_sensitivity",
        trust_state_claim="quarantined",
        redaction_state_claim="quarantined",
    )
    saved = _post_capture_with_web_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
        extra_evidence=(forged,),
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    artifacts = saved["data"]["artifacts"]
    forged_artifact = _stored_artifact_by_source_uri(client, event_id, "https://example.test/acme#forged-a11y-tree")
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=system_appshot",
        headers=headers,
    ).json()
    leak_search = client.get("/v1/search?query=SHOULD_NOT_LEAK_FORGED_A11Y_TREE", headers=headers).json()
    forged_content = client.get(_content_path(forged_artifact["artifact_id"], event_id), headers=headers).json()

    assert forged_artifact["provider_key"] == "web.browser_extension"
    assert forged_artifact["ingest_state"] == "quarantined"
    assert forged_artifact["evidence_id"] not in inspect["data"]["system_appshot"]["a11y_evidence_ids"]
    assert not any(artifact["artifact_type"] == "a11y_selection_text" for artifact in artifacts)
    assert leak_search["data"]["events"] == []
    assert forged_content["ok"] is False
    assert forged_content["error"]["code"] == "policy.denied"


def test_provider_registration_rejects_a11y_actor_impersonation(
    client, provider_session_registration, capture_save_request
):
    container = _container(client)
    a11y_registration = _a11y_provider_session_registration(capture_save_request)
    _, browser_claims = container.tokens.issue(
        actor=ActorRef(actor_id="browser-extension"),
        scopes=(AccessScope.REGISTER_PROVIDER_CONTEXT,),
    )
    _, a11y_claims = container.tokens.issue(
        actor=ActorRef(actor_id="macos-a11y-provider"),
        scopes=(AccessScope.REGISTER_PROVIDER_CONTEXT,),
    )

    with pytest.raises(ValueError):
        _authorized_registration(container, a11y_registration, browser_claims)

    authorized = _authorized_registration(container, a11y_registration, a11y_claims)
    assert authorized.provider_key == "system.macos_a11y"
    assert authorized.capabilities == (ProviderCapability.READ_A11Y,)
    assert (
        _authorized_registration(container, provider_session_registration, browser_claims).provider_kind
        == ProviderKind.SOURCE
    )


def test_register_provider_scope_is_limited_to_provider_actors(client):
    rejected = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "test-cli", "scopes": ["register_provider_context"]},
    )
    accepted = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-provider-secret": "test-provider-secret"},
        json={"actor_id": "macos-a11y-provider", "scopes": ["register_provider_context"]},
    )

    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "policy.denied"
    assert accepted.status_code == 200
    assert accepted.json()["data"]["claims"]["actor"]["actor_id"] == "macos-a11y-provider"


def test_provider_sessions_diagnostic_redacts_native_and_tab_identity(client, token, provider_session_registration):
    container = _container(client)
    tab = provider_session_registration.tab
    assert tab is not None
    secret_registration = provider_session_registration.model_copy(
        update={
            "display_name": "/Users/example/provider token=SHOULD_NOT_LEAK_SESSION_DISPLAY",
            "app_name": "/Users/example/app token=SHOULD_NOT_LEAK_SESSION_APP",
            "process_id": 12345,
            "window_id": "native-window-secret",
            "tab": tab.model_copy(
                update={
                    "tab_id": "tab-secret",
                    "window_id": "browser-window-secret",
                    "url": "https://example.test/acme?token=SHOULD_NOT_LEAK_SESSION_URL",
                    "origin": "file:///Users/example/private?token=SHOULD_NOT_LEAK_SESSION_ORIGIN",
                    "title": "/Users/example/private token=SHOULD_NOT_LEAK_SESSION_TITLE",
                }
            ),
        }
    )
    asyncio.run(
        container.provider_sessions.register(
            websocket=_FakeWebProviderSocket(container.provider_sessions, secret_registration),
            registration=secret_registration,
        )
    )

    response = client.get(
        "/v1/providers/sessions",
        headers={"authorization": f"Bearer {token}"},
    )
    payload = response.json()
    serialized = json.dumps(payload)

    assert response.status_code == 200
    assert "SHOULD_NOT_LEAK_SESSION_URL" not in serialized
    assert "SHOULD_NOT_LEAK_SESSION_ORIGIN" not in serialized
    assert "SHOULD_NOT_LEAK_SESSION_TITLE" not in serialized
    assert "SHOULD_NOT_LEAK_SESSION_DISPLAY" not in serialized
    assert "SHOULD_NOT_LEAK_SESSION_APP" not in serialized
    assert "/Users/example" not in serialized
    assert "file:///Users/example" not in serialized
    assert "tab-secret" not in serialized
    assert "browser-window-secret" not in serialized
    assert "native-window-secret" not in serialized
    assert "screen_rect" not in serialized
    assert "viewport" not in serialized
    assert '"metadata":' not in serialized
    assert "provider_session_id" not in serialized
    session = payload["data"]["sessions"][0]
    assert session["process_id"] is None
    assert session["window_id"] is None
    assert session["has_tab"] is True
    assert session["tab"] == {
        "browser": tab.browser,
        "origin": "[uri:redacted]",
        "title": "[path:redacted] [secret:redacted]",
    }
    assert session["display_name"] == "[path:redacted] [secret:redacted]"
    assert session["app_name"] == "[path:redacted] [secret:redacted]"


def test_artifact_verify_recomputes_content_hash(client, token, capture_save_request, provider_session_registration):
    headers = {"authorization": f"Bearer {token}"}
    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]
    canonical = next(
        artifact for artifact in saved["data"]["artifacts"] if artifact["artifact_type"] == "canonical_text"
    )

    verify = client.get(
        f"/v1/artifacts/{canonical['artifact_id']}/verify",
        headers=headers,
    ).json()
    audit = client.get(f"/v1/audit?event={event_id}", headers=headers).json()

    assert verify["ok"] is True
    assert verify["data"]["ok"] is True
    assert verify["data"]["actual_sha256"] == canonical["sha256"]
    assert verify["audit_id"] is not None
    assert canonical["artifact_id"] in audit["data"]["resource_ids"]
    assert any(event["resource_id"] == canonical["artifact_id"] for event in audit["data"]["audit"])


def test_event_inspect_discloses_canonical_clean_page_and_screenshot_ref(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]

    default_inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read",
        headers=headers,
    ).json()
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read"
        "&inspect_views=canonical,clean_page_text,screenshot_ref",
        headers=headers,
    ).json()

    assert default_inspect["ok"] is True
    assert default_inspect["data"]["clean_page_text"] == ""
    assert default_inspect["data"]["raw_artifacts"] == []
    assert all(
        item["text"] == ""
        for item in default_inspect["data"]["readable_evidence"]
        if item["disclosure_class"] == "clean_page_text"
    )
    assert inspect["ok"] is True
    assert "Budget variance +18%" in inspect["data"]["canonical_text"]
    assert "Deep page text outside the screenshot" in inspect["data"]["clean_page_text"]
    assert "SHOULD_NOT_LEAK_PAGE_BEARER" not in inspect["data"]["clean_page_text"]
    assert inspect["data"]["raw_artifacts"][0]["artifact_type"] == "screenshot"
    assert inspect["data"]["raw_artifacts"][0]["requires_scope"] == "read_raw_artifact"
    assert "content_base64" not in json.dumps(inspect["data"], sort_keys=True)


def test_event_inspect_evidence_refs_do_not_disclose_text(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    saved = _post_capture_with_web_and_a11y_provider(
        client, token, capture_save_request, provider_session_registration
    ).json()
    event_id = saved["data"]["event"]["event_id"]

    refs_only = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_citations&inspect_views=evidence_refs",
        headers=headers,
    ).json()

    assert refs_only["ok"] is True
    assert refs_only["data"]["readable_evidence"]
    assert all(item["text"] == "" for item in refs_only["data"]["readable_evidence"])
    assert "Procurement delayed" not in json.dumps(refs_only["data"], sort_keys=True)


def test_screenshot_thumbnail_endpoint_returns_thumbnail_scoped_image(
    client, token, capture_save_request, provider_session_registration
):
    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]
    screenshot = next(artifact for artifact in saved["data"]["artifacts"] if artifact["artifact_type"] == "screenshot")
    thumb_token = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "workbench", "scopes": ["read_thumbnail"]},
    ).json()["data"]["access_token"]

    unbound_response = client.get(
        f"/v1/artifacts/{screenshot['artifact_id']}/thumbnail",
        headers={"authorization": f"Bearer {thumb_token}"},
    )
    assert unbound_response.status_code == 422

    thumbnail = client.get(
        f"/v1/artifacts/{screenshot['artifact_id']}/thumbnail?event_id={event_id}",
        headers={"authorization": f"Bearer {thumb_token}"},
    ).json()

    assert thumbnail["ok"] is True
    assert thumbnail["data"]["artifact_id"] == screenshot["artifact_id"]
    assert thumbnail["data"]["content_type"] == "image/png"
    assert thumbnail["data"]["byte_size"] > 0
    assert thumbnail["data"]["data_base64"].startswith("iVBOR")
    thumbnail_image = Image.open(BytesIO(base64.b64decode(thumbnail["data"]["data_base64"])))
    assert max(thumbnail_image.size) <= 360
    assert screenshot["byte_size"] > thumbnail["data"]["byte_size"]


def test_legacy_include_evidence_is_rejected_for_agent_facing_reads(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]

    legacy = client.get(f"/v1/events/{event_id}?include=evidence", headers=headers).json()

    assert legacy["ok"] is False
    assert legacy["error"]["code"] == "validation_error"
    assert "event_inspect" in legacy["error"]["message"]


def test_event_inspect_rejects_unknown_views(client, token, capture_save_request, provider_session_registration):
    headers = {"authorization": f"Bearer {token}"}
    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]

    response = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=debug_provenance",
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_event_metadata_views_sanitize_url_query(client, token, event_create):
    headers = {"authorization": f"Bearer {token}"}
    secret_event = event_create.model_copy(
        update={
            "source_binding": event_create.source_binding.model_copy(
                update={
                    "source_ref": event_create.source_binding.source_ref.model_copy(
                        update={
                            "app_name": "/Users/example/App token=SHOULD_NOT_LEAK_EVENT_APP",
                            "title": "/Users/example/Window token=SHOULD_NOT_LEAK_EVENT_TITLE",
                            "url": "https://example.test/acme?token=SHOULD_NOT_LEAK_EVENT_URL#frag",
                            "origin": "https://example.test?token=SHOULD_NOT_LEAK_EVENT_ORIGIN#frag",
                        }
                    )
                }
            )
        }
    )
    created = client.post("/v1/events", headers=headers, json=secret_event.model_dump(mode="json")).json()
    event_id = created["data"]["event_id"]

    listed = client.get("/v1/events", headers=headers).json()
    got = client.get(f"/v1/events/{event_id}", headers=headers).json()
    payload = json.dumps([created["data"], listed["data"], got["data"]], sort_keys=True)

    assert "SHOULD_NOT_LEAK_EVENT_APP" not in payload
    assert "SHOULD_NOT_LEAK_EVENT_TITLE" not in payload
    assert "SHOULD_NOT_LEAK_EVENT_URL" not in payload
    assert "SHOULD_NOT_LEAK_EVENT_ORIGIN" not in payload
    assert "/Users/example" not in payload
    assert "frag" not in payload
    assert "https://example.test/acme" in payload


def test_raw_screenshot_requires_explicit_event_bound_disclosure(
    client, token, capture_save_request, provider_session_registration
):
    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]
    screenshot = next(artifact for artifact in saved["data"]["artifacts"] if artifact["artifact_type"] == "screenshot")
    raw_token = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "test-cli", "scopes": ["read_raw_artifact"]},
    ).json()["data"]["access_token"]
    headers = {"authorization": f"Bearer {raw_token}"}
    begin = client.post(
        "/v1/agent-runs",
        headers={"authorization": f"Bearer {token}"},
        json={"agent": "codex", "purpose": "raw_visual_check", "user_question": "Need screenshot"},
    ).json()
    run_id = begin["data"]["agent_run_id"]
    client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=screenshot_ref",
        headers={"authorization": f"Bearer {token}", "x-workrecorder-agent-run-id": run_id},
    )

    denied = client.get(
        f"/v1/artifacts/{screenshot['artifact_id']}/raw?event_id=evt_wrong&purpose=agent_deep_read&agent_run_id={run_id}",
        headers=headers,
    )
    allowed = client.get(
        f"/v1/artifacts/{screenshot['artifact_id']}/raw?event_id={event_id}&purpose=agent_deep_read&agent_run_id={run_id}",
        headers=headers,
    ).json()
    audit = client.get(
        f"/v1/audit?event={screenshot['artifact_id']}",
        headers={"authorization": f"Bearer {token}"},
    ).json()

    assert denied.status_code == 403
    assert "read_raw_artifact" in screenshot["allowed_scopes"]
    assert allowed["ok"] is True
    assert allowed["data"]["artifact_type"] == "screenshot"
    assert allowed["data"]["content_base64"]
    assert allowed["data"]["disclosure_decision"]["view"] == "raw_artifact"
    assert any(event["action"] == "disclosure_evaluated" for event in audit["data"]["audit"])


def test_raw_screenshot_denial_does_not_self_prime_delivery(
    client, token, capture_save_request, provider_session_registration
):
    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]
    screenshot = next(artifact for artifact in saved["data"]["artifacts"] if artifact["artifact_type"] == "screenshot")
    raw_token = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "test-cli", "scopes": ["read_raw_artifact"]},
    ).json()["data"]["access_token"]
    run_id = client.post(
        "/v1/agent-runs",
        headers={"authorization": f"Bearer {token}"},
        json={"agent": "codex", "purpose": "raw_visual_check", "user_question": "Need screenshot"},
    ).json()["data"]["agent_run_id"]
    path = (
        f"/v1/artifacts/{screenshot['artifact_id']}/raw?"
        f"event_id={event_id}&purpose=agent_deep_read&agent_run_id={run_id}"
    )

    first = client.get(path, headers={"authorization": f"Bearer {raw_token}"}).json()
    second = client.get(path, headers={"authorization": f"Bearer {raw_token}"}).json()

    assert first["ok"] is False
    assert first["error"]["code"] == "policy.denied"
    assert second["ok"] is False
    assert second["error"]["code"] == "policy.denied"


def test_raw_screenshot_requires_explicit_agent_run(client, token, capture_save_request, provider_session_registration):
    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]
    screenshot = next(artifact for artifact in saved["data"]["artifacts"] if artifact["artifact_type"] == "screenshot")
    raw_token = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "test-cli", "scopes": ["read_raw_artifact"]},
    ).json()["data"]["access_token"]

    raw = client.get(
        f"/v1/artifacts/{screenshot['artifact_id']}/raw?event_id={event_id}&purpose=agent_deep_read",
        headers={"authorization": f"Bearer {raw_token}"},
    ).json()

    assert raw["ok"] is False
    assert raw["error"]["code"] == "policy.denied"
    assert "explicit agent run" in raw["error"]["message"]


def test_workbench_screenshot_prefetch_does_not_prime_raw_screenshot_gate(
    client, token, capture_save_request, provider_session_registration
):
    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]
    screenshot = next(artifact for artifact in saved["data"]["artifacts"] if artifact["artifact_type"] == "screenshot")
    workbench_token = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "workbench", "scopes": ["read_metadata", "read_text", "read_raw_artifact"]},
    ).json()["data"]["access_token"]
    headers = {"authorization": f"Bearer {workbench_token}"}

    prefetch = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=workbench_inspect&inspect_views=screenshot_ref",
        headers=headers,
    ).json()
    run_id = prefetch["agent_run_id"]
    denied = client.get(
        f"/v1/artifacts/{screenshot['artifact_id']}/raw?"
        f"event_id={event_id}&purpose=agent_deep_read&agent_run_id={run_id}",
        headers=headers,
    ).json()

    client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read&inspect_views=screenshot_ref",
        headers={**headers, "x-workrecorder-agent-run-id": run_id},
    )
    allowed = client.get(
        f"/v1/artifacts/{screenshot['artifact_id']}/raw?"
        f"event_id={event_id}&purpose=agent_deep_read&agent_run_id={run_id}",
        headers=headers,
    ).json()

    assert denied["ok"] is False
    assert denied["error"]["code"] == "policy.denied"
    assert allowed["ok"] is True
    assert allowed["data"]["artifact_type"] == "screenshot"


def test_agent_run_replays_search_inspect_bundle_usage_and_raw_snapshot(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    saved = _post_capture_with_web_and_a11y_provider(
        client,
        token,
        capture_save_request,
        provider_session_registration,
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    screenshot = next(artifact for artifact in saved["data"]["artifacts"] if artifact["artifact_type"] == "screenshot")
    begin = client.post(
        "/v1/agent-runs",
        headers=headers,
        json={"agent": "codex", "purpose": "customer_brief", "user_question": "ACME procurement status?"},
    ).json()
    run_id = begin["data"]["agent_run_id"]
    trace_headers = {**headers, "x-workrecorder-agent-run-id": run_id}

    search = client.get("/v1/search?query=Procurement+delayed&explain=true", headers=trace_headers).json()
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read"
        "&inspect_views=selection_text,evidence_refs,screenshot_ref",
        headers=trace_headers,
    ).json()
    resolved = client.get(
        f"/v1/citations/{inspect['data']['readable_evidence'][0]['citation_id']}",
        headers=trace_headers,
    ).json()
    bundle = client.post(
        "/v1/context-bundles",
        headers=trace_headers,
        json={"query": "ACME procurement status", "purpose": "customer_brief"},
    ).json()
    usage = client.post(
        "/v1/agent-usage-events",
        headers=trace_headers,
        json={
            "bundle_id": bundle["data"]["bundle_id"],
            "agent": "codex",
            "purpose": "customer_brief",
            "output_ref": "answer_1",
            "citation_ids": [inspect["data"]["readable_evidence"][0]["citation_id"]],
        },
    ).json()
    raw_token = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "test-cli", "scopes": ["read_raw_artifact"]},
    ).json()["data"]["access_token"]
    raw = client.get(
        f"/v1/artifacts/{screenshot['artifact_id']}/raw?event_id={event_id}&purpose=user_requested_visual_check",
        headers={"authorization": f"Bearer {raw_token}", "x-workrecorder-agent-run-id": run_id},
    ).json()
    replay = client.get(f"/v1/agent-runs/{run_id}/replay", headers=headers).json()
    replay_text = json.dumps(replay["data"], sort_keys=True)

    assert search["agent_run_id"] == run_id
    assert search["retrieval_call_id"].startswith("ret_")
    assert search["snapshot_id"].startswith("snap_")
    assert search["data"]["results"][0]["preview_citation_id"].startswith("cit_")
    assert inspect["data"]["readable_evidence"][0]["citation_id"].startswith("cit_")
    assert resolved["ok"] is True
    assert resolved["retrieval_call_id"].startswith("ret_")
    assert "Procurement delayed" in resolved["data"]["text"]
    assert bundle["data"]["items"][0]["citation_ids"]
    assert usage["data"]["agent_run_id"] == run_id
    assert raw["snapshot_id"].startswith("snap_")
    assert replay["ok"] is True
    assert {call["kind"] for call in replay["data"]["retrieval_calls"]}.issuperset(
        {"search", "event_inspect", "citation_resolve", "bundle_create", "usage_record", "artifact_raw"}
    )
    assert "Procurement delayed" in replay_text
    assert "content_base64" in raw["data"]
    assert "content_base64" not in replay_text
    assert "local-artifact://" not in replay_text


def test_agent_run_replay_redacts_caller_query_and_user_text(client, token):
    headers = {"authorization": f"Bearer {token}"}
    begin = client.post(
        "/v1/agent-runs",
        headers=headers,
        json={
            "agent": "codex",
            "purpose": "customer_brief token=SHOULD_NOT_LEAK_RUN_PURPOSE",
            "user_question": (
                "/Users/example/private.txt Authorization: Bearer SHOULD_NOT_LEAK_USER_QUESTION "
                "https://example.test/path?token=SHOULD_NOT_LEAK_USER_URL#frag"
            ),
        },
    ).json()
    run_id = begin["data"]["agent_run_id"]
    trace_headers = {**headers, "x-workrecorder-agent-run-id": run_id}

    client.get(
        "/v1/search",
        headers=trace_headers,
        params={
            "query": (
                "Procurement delayed api_key=SHOULD_NOT_LEAK_SEARCH_QUERY "
                "https://example.test/search?token=SHOULD_NOT_LEAK_SEARCH_URL#frag"
            )
        },
    )
    replay = client.get(f"/v1/agent-runs/{run_id}/replay", headers=headers).json()
    serialized = json.dumps([begin["data"], replay["data"]], sort_keys=True)

    assert begin["ok"] is True
    assert replay["ok"] is True
    assert "SHOULD_NOT_LEAK" not in serialized
    assert "/Users/example" not in serialized
    assert "token=" not in serialized
    assert "frag" not in serialized
    assert "https://example.test/path" in serialized
    assert "https://example.test/search" in serialized


def test_agent_run_ids_are_actor_bound(client, token):
    headers = {"authorization": f"Bearer {token}"}
    other_token = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "other-cli", "display_name": "Other CLI"},
    ).json()["data"]["access_token"]
    other_headers = {"authorization": f"Bearer {other_token}"}
    begin = client.post(
        "/v1/agent-runs",
        headers=headers,
        json={"agent": "codex", "purpose": "owner_run", "user_question": "owned?"},
    ).json()
    run_id = begin["data"]["agent_run_id"]

    replay = client.get(f"/v1/agent-runs/{run_id}/replay", headers=other_headers)
    hijack = client.get("/v1/search?query=ACME", headers={**other_headers, "x-workrecorder-agent-run-id": run_id})

    assert replay.status_code == 404
    assert replay.json()["error"]["code"] == "not_found"
    assert hijack.status_code == 404
    assert hijack.json()["error"]["code"] == "not_found"


def test_context_query_ids_must_belong_to_current_run(client, token):
    headers = {"authorization": f"Bearer {token}"}
    first = client.post(
        "/v1/agent-runs",
        headers=headers,
        json={"agent": "codex", "purpose": "first", "user_question": "first?"},
    ).json()["data"]["agent_run_id"]
    first_search = client.get("/v1/search?query=first", headers={**headers, "x-workrecorder-agent-run-id": first}).json()
    second = client.post(
        "/v1/agent-runs",
        headers=headers,
        json={"agent": "codex", "purpose": "second", "user_question": "second?"},
    ).json()["data"]["agent_run_id"]

    reused_query = client.get(
        "/v1/search?query=second",
        headers={
            **headers,
            "x-workrecorder-agent-run-id": second,
            "x-workrecorder-context-query-id": first_search["context_query_id"],
        },
    )

    assert reused_query.status_code == 404
    assert reused_query.json()["error"]["code"] == "not_found"


def test_disclosure_profiles_route_exposes_sdk_profiles(client, token):
    payload = client.get("/v1/disclosure/profiles", headers={"authorization": f"Bearer {token}"}).json()

    profile_keys = {profile["profile_key"] for profile in payload["data"]["profiles"]}
    assert "default.context_capture" in profile_keys
    assert "app.chrome.web_capture" in profile_keys


def test_workspace_disclosure_override_limits_summary_selection_text(
    tmp_path, capture_save_request, provider_session_registration
):
    override_path = tmp_path / "disclosure_overrides.json"
    override_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profiles": [
                    {
                        "profile_key": "workspace.chrome.short_summary",
                        "extends_profile_key": "app.chrome.web_capture",
                        "display_name": "Chrome Short Summary Override",
                        "provider_keys": ["web.browser_extension"],
                        "app_names": ["Google Chrome", "Chrome"],
                        "source_types": ["web"],
                        "rules": [
                            {
                                "rule_id": "default.summary.selection_text",
                                "view": "summary_card",
                                "disclosure_class": "selection_bound_text",
                                "artifact_types": ["a11y_selection_text"],
                                "artifact_roles": ["selection_text"],
                                "evidence_kinds": ["selection_text"],
                                "allowed_scopes": ["read_text"],
                                "max_chars": 12,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    client_with_override, token = _client_with_settings(tmp_path, override_path)
    request = _request_for_client_settings(capture_save_request, _container(client_with_override).settings)
    saved = _post_capture_with_web_and_a11y_provider(
        client_with_override,
        token,
        request,
        provider_session_registration,
    ).json()
    event_id = saved["data"]["event"]["event_id"]

    search = client_with_override.get(
        "/v1/search?query=Procurement+delayed",
        headers={"authorization": f"Bearer {token}"},
    ).json()
    profiles = client_with_override.get(
        "/v1/disclosure/profiles",
        headers={"authorization": f"Bearer {token}"},
    ).json()

    card = search["data"]["results"][0]
    assert card["event_id"] == event_id
    assert card["selection_text"].startswith("Account")
    assert card["selection_text_truncated"] is True
    assert "Procurement delayed" not in card["selection_text"]
    assert "workspace.chrome.short_summary" in {profile["profile_key"] for profile in profiles["data"]["profiles"]}


def test_workspace_disclosure_override_cannot_expose_raw_full_dom(
    tmp_path, capture_save_request, provider_session_registration
):
    override_path = tmp_path / "disclosure_overrides.json"
    override_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profiles": [
                    {
                        "profile_key": "workspace.chrome.bad_raw_dom",
                        "extends_profile_key": "app.chrome.web_capture",
                        "display_name": "Unsafe Raw DOM Override",
                        "provider_keys": ["web.browser_extension"],
                        "app_names": ["Google Chrome", "Chrome"],
                        "source_types": ["web"],
                        "rules": [
                            {
                                "rule_id": "bad.raw.full_dom",
                                "view": "raw_artifact",
                                "disclosure_class": "raw_source",
                                "artifact_types": ["browser_full_dom"],
                                "artifact_roles": ["full_dom"],
                                "evidence_kinds": ["full_dom"],
                                "allowed_scopes": ["read_raw_artifact"],
                                "allow_raw": True,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    client_with_override, token = _client_with_settings(tmp_path, override_path)
    request = _request_for_client_settings(capture_save_request, _container(client_with_override).settings)
    saved = _post_capture_with_web_provider(
        client_with_override,
        token,
        request,
        provider_session_registration,
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    full_dom = next(
        artifact for artifact in saved["data"]["artifacts"] if artifact["artifact_type"] == "browser_full_dom"
    )
    raw_token = client_with_override.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "test-cli", "scopes": ["read_raw_artifact"]},
    ).json()["data"]["access_token"]
    run_id = client_with_override.post(
        "/v1/agent-runs",
        headers={"authorization": f"Bearer {token}"},
        json={"agent": "codex", "purpose": "raw_dom_denial", "user_question": "inspect raw dom?"},
    ).json()["data"]["agent_run_id"]

    denied = client_with_override.get(
        f"/v1/artifacts/{full_dom['artifact_id']}/raw?event_id={event_id}"
        f"&purpose=agent_deep_read&agent_run_id={run_id}",
        headers={"authorization": f"Bearer {raw_token}"},
    ).json()
    profiles = client_with_override.get(
        "/v1/disclosure/profiles",
        headers={"authorization": f"Bearer {token}"},
    ).json()

    assert denied["ok"] is False
    assert denied["error"]["code"] == "policy.denied"
    assert "SHOULD_NOT_LEAK" not in json.dumps(denied, sort_keys=True)
    assert any("bad.raw.full_dom" in warning for warning in profiles["data"]["workspace_override_warnings"])


def test_capture_save_rejects_files_outside_staging(client, token, capture_save_request, tmp_path):
    outside_file = tmp_path / "outside.png"
    outside_file.write_bytes(b"unsafe")
    unsafe_request = capture_save_request.model_copy(
        update={
            "staged_artifact": capture_save_request.staged_artifact.model_copy(update={"local_path": str(outside_file)})
        }
    )
    response = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}"},
        json=unsafe_request.model_dump(mode="json"),
    )
    payload = response.json()
    assert response.status_code == 422
    assert payload["ok"] is False
    assert payload["error"]["code"] == "validation_error"


def test_capture_save_rejects_non_png_bytes(client, token, capture_save_request, settings):
    bad_file = settings.artifact_staging_dir / "capture-not-png.png"
    bad_file.write_bytes(b"not-a-png")
    bad_request = capture_save_request.model_copy(
        update={
            "staged_artifact": capture_save_request.staged_artifact.model_copy(update={"local_path": str(bad_file)})
        }
    )

    response = client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}"},
        json=bad_request.model_dump(mode="json"),
    )

    payload = response.json()
    assert response.status_code == 422
    assert payload["ok"] is False
    assert payload["error"]["code"] == "validation_error"
    assert payload["audit_id"] is None or payload["audit_id"].startswith("aud_")


def test_bundle_create_is_audited(client, token, event_create):
    headers = {"authorization": f"Bearer {token}"}
    client.post("/v1/events", headers=headers, json=event_create.model_dump(mode="json"))
    response = client.post(
        "/v1/context-bundles",
        headers=headers,
        json={"query": "生成 ACME brief", "purpose": "customer_brief"},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["data"]["bundle_id"].startswith("cb_")
    assert payload["data"]["degraded"] is True


def test_bundle_routes_redact_query_and_purpose_echoes(client, token, event_create):
    headers = {"authorization": f"Bearer {token}"}
    client.post("/v1/events", headers=headers, json=event_create.model_dump(mode="json"))
    response = client.post(
        "/v1/context-bundles",
        headers=headers,
        json={
            "query": (
                "生成 ACME brief api_key=SHOULD_NOT_LEAK_BUNDLE_QUERY "
                "https://example.test/acme?token=SHOULD_NOT_LEAK_BUNDLE_URL#frag"
            ),
            "purpose": "customer_brief Authorization: Bearer SHOULD_NOT_LEAK_BUNDLE_PURPOSE",
        },
    )
    created = response.json()
    bundle_id = created["data"]["bundle_id"]
    shown = client.get(f"/v1/context-bundles/{bundle_id}", headers=headers).json()
    exported = client.get(f"/v1/context-bundles/{bundle_id}/export?format=markdown", headers=headers).json()
    serialized = json.dumps([created["data"], shown["data"], exported["data"]], sort_keys=True)

    assert response.status_code == 200
    assert "SHOULD_NOT_LEAK" not in serialized
    assert "token=" not in serialized
    assert "frag" not in serialized
    assert "https://example.test/acme" in serialized


def test_bundle_create_requires_text_scope(client, event_create):
    create_only_token = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "test-cli", "scopes": ["create_bundle"]},
    ).json()["data"]["access_token"]

    response = client.post(
        "/v1/context-bundles",
        headers={"authorization": f"Bearer {create_only_token}"},
        json={"query": "生成 ACME brief", "purpose": "customer_brief"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "policy.denied"


def test_bundle_show_and_export_hide_deleted_event_items(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    saved = _post_capture_with_web_and_a11y_provider(
        client, token, capture_save_request, provider_session_registration
    ).json()
    event_id = saved["data"]["event"]["event_id"]
    created = client.post(
        "/v1/context-bundles",
        headers=headers,
        json={"query": "Procurement delayed", "purpose": "customer_brief"},
    ).json()
    bundle_id = created["data"]["bundle_id"]

    assert created["data"]["items"][0]["event_id"] == event_id
    assert created["data"]["items"][0]["citations"]
    client.delete(f"/v1/events/{event_id}", headers=headers)
    shown = client.get(f"/v1/context-bundles/{bundle_id}", headers=headers).json()
    exported = client.get(f"/v1/context-bundles/{bundle_id}/export?format=markdown", headers=headers).json()

    assert shown["data"]["items"] == []
    assert shown["data"]["degraded"] is True
    assert "Procurement delayed" not in exported["data"]["content"]


def test_artifact_content_is_denied_by_default(client, token, event_create):
    headers = {"authorization": f"Bearer {token}"}
    created = client.post("/v1/events", headers=headers, json=event_create.model_dump(mode="json")).json()
    event_id = created["data"]["event_id"]
    container = _container(client)
    artifact = Artifact(
        artifact_id="art_fixture",
        event_id=event_id,
        artifact_type=ArtifactType.BROWSER_DOM_SNAPSHOT,
        role="source_text",
        storage_uri="fixture://dom",
        redaction_state=RedactionState.NONE,
        allowed_scopes=(AccessScope.READ_TEXT,),
        metadata={},
        created_at=event_create.trigger.occurred_at,
    )
    container.repositories.artifacts.save(artifact)

    response = client.get(_content_path("art_fixture", event_id), headers=headers)
    payload = response.json()
    assert response.status_code == 403
    assert payload["ok"] is False
    assert payload["error"]["code"] == "policy.denied"


def test_summary_card_marks_recording_video_as_recording_context(client, token, event_create):
    headers = {"authorization": f"Bearer {token}"}
    created = client.post("/v1/events", headers=headers, json=event_create.model_dump(mode="json")).json()
    event_id = created["data"]["event_id"]
    container = _container(client)
    container.repositories.artifacts.save(
        Artifact(
            artifact_id="art_recording_card_marker",
            event_id=event_id,
            artifact_type=ArtifactType.RECORDING_VIDEO,
            role="recording_video",
            storage_uri="fixture://recording-video",
            redaction_state=RedactionState.NONE,
            allowed_scopes=(),
            content_type="video/mp4",
            metadata={},
            created_at=event_create.trigger.occurred_at,
        )
    )
    event = container.repositories.events.get(event_id)
    assert event is not None

    card = container.disclosure.summary_card(event=event)

    assert "recording_video" in card.hidden_artifacts
    assert "active_capture_recording" in card.hidden_artifacts


def test_deleted_event_hides_artifacts(client, token, event_create):
    headers = {"authorization": f"Bearer {token}"}
    created = client.post("/v1/events", headers=headers, json=event_create.model_dump(mode="json")).json()
    event_id = created["data"]["event_id"]
    container = _container(client)
    artifact = Artifact(
        artifact_id="art_deleted_parent",
        event_id=event_id,
        artifact_type=ArtifactType.CANONICAL_TEXT,
        role="canonical_text",
        storage_uri="fixture://text",
        redaction_state=RedactionState.REDACTED,
        allowed_scopes=(AccessScope.READ_TEXT,),
        content_type="text/plain",
        metadata={},
        created_at=event_create.trigger.occurred_at,
    )
    container.repositories.artifacts.save(artifact)

    delete_response = client.delete(f"/v1/events/{event_id}", headers=headers)
    artifact_response = client.get("/v1/artifacts/art_deleted_parent", headers=headers)
    content_response = client.get(_content_path("art_deleted_parent", event_id), headers=headers)

    assert delete_response.status_code == 200
    assert artifact_response.status_code == 404
    assert content_response.status_code == 404


def test_deleted_capture_hides_manifest_and_evidence(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]

    delete_response = client.delete(f"/v1/events/{event_id}", headers=headers)
    manifest_response = client.get(f"/v1/events/{event_id}/manifest", headers=headers)
    evidence_response = client.get(f"/v1/evidence?event={event_id}", headers=headers)

    assert delete_response.status_code == 200
    assert manifest_response.status_code == 404
    assert evidence_response.status_code == 404


def test_deleted_capture_is_removed_from_keyword_index(
    client, token, capture_save_request, provider_session_registration
):
    headers = {"authorization": f"Bearer {token}"}
    saved = _post_capture_with_web_provider(client, token, capture_save_request, provider_session_registration).json()
    event_id = saved["data"]["event"]["event_id"]

    before = client.get("/v1/search?query=Budget+variance", headers=headers).json()
    delete_response = client.delete(f"/v1/events/{event_id}", headers=headers)
    after = client.get("/v1/search?query=Budget+variance", headers=headers).json()

    assert before["data"]["results"][0]["event_id"] == event_id
    assert delete_response.status_code == 200
    assert after["data"]["results"] == []


def test_raw_artifact_scope_can_be_issued_to_local_cli(client):
    response = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "test-cli", "scopes": ["read_raw_artifact"]},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["data"]["claims"]["scopes"] == ["read_raw_artifact"]


def test_provider_actor_cannot_escalate_with_install_secret(client):
    response = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "browser-extension", "scopes": ["create_event"]},
    )
    payload = response.json()

    assert response.status_code == 401
    assert payload["ok"] is False
    assert payload["error"]["code"] == "auth.invalid"


def test_provider_actor_cannot_escalate_with_provider_secret(client):
    response = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-provider-secret": "test-provider-secret"},
        json={"actor_id": "browser-extension", "scopes": ["create_event"]},
    )
    payload = response.json()

    assert response.status_code == 403
    assert payload["ok"] is False
    assert payload["error"]["code"] == "policy.denied"


def test_browser_extension_origin_cannot_spoof_cli_actor_with_install_secret(client):
    response = client.post(
        "/v1/auth/tokens",
        headers={
            "origin": "chrome-extension://cccccccccccccccccccccccccccccccc",
            "x-workrecorder-install-secret": "test-install-secret",
        },
        json={"actor_id": "local-cli", "scopes": ["create_event"]},
    )
    payload = response.json()

    assert response.status_code == 403
    assert payload["ok"] is False
    assert payload["error"]["code"] == "policy.denied"


def test_default_cli_token_does_not_include_raw_artifact_scope(client):
    response = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "test-cli"},
    )
    scopes = response.json()["data"]["claims"]["scopes"]

    assert "read_raw_artifact" not in scopes
    assert "read_image" not in scopes


def _post_capture_with_web_provider(
    client: TestClient,
    token: str,
    capture_request: Any,
    registration: ProviderSessionRegistration,
    *,
    extra_evidence: tuple[dict[str, Any], ...] = (),
    selected_text: str | None = None,
):
    container = _container(client)
    fake_socket = _FakeWebProviderSocket(
        container.provider_sessions,
        registration,
        extra_evidence=extra_evidence,
        selected_text=selected_text,
    )
    asyncio.run(container.provider_sessions.register(websocket=fake_socket, registration=registration))
    return client.post(
        "/v1/captures",
        headers={"authorization": f"Bearer {token}"},
        json=capture_request.model_dump(mode="json"),
    )


def _post_capture_with_web_and_a11y_provider(
    client: TestClient,
    token: str,
    capture_request: Any,
    web_registration: ProviderSessionRegistration,
    *,
    a11y_result_builder: Any = None,
    extra_evidence: tuple[dict[str, Any], ...] = (),
    selected_text: str = "",
):
    container = _container(client)
    a11y_registration = _a11y_provider_session_registration(capture_request)
    a11y_socket = _FakeA11yProviderSocket(
        container.provider_sessions,
        a11y_registration,
        result_builder=a11y_result_builder or _a11y_collect_result,
    )
    asyncio.run(container.provider_sessions.register(websocket=a11y_socket, registration=a11y_registration))
    return _post_capture_with_web_provider(
        client,
        token,
        capture_request,
        web_registration,
        extra_evidence=extra_evidence,
        selected_text=selected_text,
    )


def _a11y_provider_session_registration(capture_request: Any) -> ProviderSessionRegistration:
    selected = capture_request.selection_geometry.selected_region
    return ProviderSessionRegistration(
        provider_key="system.macos_a11y",
        provider_session_id="ctx_system_a11y_test",
        provider_kind=ProviderKind.SYSTEM_EVIDENCE,
        display_name="macOS Accessibility Provider",
        app_name="macOS Accessibility",
        window_id="win_test",
        window=BrowserWindowRef(window_id="win_test", screen_rect=selected),
        capabilities=(ProviderCapability.READ_A11Y,),
        registered_at=datetime.now(UTC),
        ttl_ms=60000,
    )


class _FakeWebProviderSocket:
    def __init__(
        self,
        provider_sessions: Any,
        registration: ProviderSessionRegistration,
        *,
        extra_evidence: tuple[dict[str, Any], ...] = (),
        selected_text: str | None = None,
    ) -> None:
        self.provider_sessions = provider_sessions
        self.registration = registration
        self.extra_evidence = extra_evidence
        self.selected_text = selected_text

    async def send_text(self, data: str) -> None:
        import json

        command = json.loads(data)
        result = CollectEvidenceResult.model_validate(
            _web_collect_result(
                command,
                self.registration,
                extra_evidence=self.extra_evidence,
                selected_text=self.selected_text,
            )
        )
        await self.provider_sessions.handle_collect_result(
            result,
            provider_session_id=self.registration.provider_session_id,
        )


class _FakeA11yProviderSocket:
    def __init__(
        self,
        provider_sessions: Any,
        registration: ProviderSessionRegistration,
        *,
        result_builder: Any,
    ) -> None:
        self.provider_sessions = provider_sessions
        self.registration = registration
        self.result_builder = result_builder

    async def send_text(self, data: str) -> None:
        import json

        command = json.loads(data)
        result = CollectEvidenceResult.model_validate(self.result_builder(command, self.registration))
        await self.provider_sessions.handle_collect_result(
            result,
            provider_session_id=self.registration.provider_session_id,
        )


def _web_collect_result(
    command_message: dict[str, Any],
    registration: ProviderSessionRegistration,
    *,
    extra_evidence: tuple[dict[str, Any], ...] = (),
    selected_text: str | None = None,
) -> dict[str, Any]:
    command = command_message["command"]
    command_id = command["command_id"]
    tab = registration.tab
    assert tab is not None
    source_binding_id = "src_test_web_command"
    selection = (
        command.get("selection_in_surface")
        or command["attempt"]["selection_geometry"].get("pixel_region")
        or command["attempt"]["selection_geometry"]["selected_region"]
    )
    selected_text = selected_text if selected_text is not None else "Budget variance +18%"
    visible_text = "\n".join(
        [
            "ACME renewal dashboard",
            "Budget variance +18%",
            "Authorization: Bearer SHOULD_NOT_LEAK_VISIBLE_BEARER",
            "API token: SHOULD_NOT_LEAK_VISIBLE_TOKEN",
            "csrf=SHOULD_NOT_LEAK_CSRF",
            "Procurement delayed",
        ]
    )
    full_dom = (
        "<!doctype html><html><body><main><h1>ACME renewal dashboard</h1>"
        "<section id='variance'>Budget variance +18%</section>"
        "<section id='deep'>Deep page text outside the screenshot but useful for inspect</section>"
        "<p>Authorization: REDACTED REDACTED</p>"
        "<input type='REDACTED' value='REDACTED'>"
        "</main></body></html>"
    )
    page_text = {
        "markdown": "\n".join(
            [
                "# ACME renewal dashboard",
                "Budget variance +18%",
                "Procurement delayed",
                "Deep page text outside the screenshot but useful for inspect",
                "Authorization: Bearer SHOULD_NOT_LEAK_PAGE_BEARER",
                "API token: SHOULD_NOT_LEAK_PAGE_TOKEN",
            ]
        ),
        "plain_text": "\n".join(
            [
                "ACME renewal dashboard",
                "Budget variance +18%",
                "Procurement delayed",
                "Deep page text outside the screenshot but useful for inspect",
                "API token: SHOULD_NOT_LEAK_PAGE_TOKEN",
            ]
        ),
        "method": "dom_text_snapshot_v1",
        "title": tab.title,
        "site_name": "ACME",
        "language": "en",
        "content_hash": "fixture_hash",
        "char_count": 168,
        "truncated": False,
        "omitted_reasons": [],
        "frame_count": 0,
        "shadow_root_count": 0,
        "extractor_version": "browser_page_text_v1",
    }
    source_binding = {
        "binding_id": source_binding_id,
        "source_ref": {
            "source_type": "web",
            "title": tab.title,
            "app_name": "Google Chrome",
            "url": tab.url,
            "origin": tab.origin,
            "connector_name": "web.browser_extension",
            "external_id": tab.tab_id,
            "version": "test",
        },
        "confidence": 0.95,
        "resolved_at": datetime.now(UTC).isoformat(),
        "provider_key": "web.browser_extension",
        "provider_context_id": registration.provider_session_id,
        "capabilities": [capability.value for capability in registration.capabilities],
    }
    evidence = [
        _json_evidence(
            "page_metadata",
            "page_metadata",
            "page_metadata",
            {
                "url": tab.url,
                "origin": tab.origin,
                "title": tab.title,
                "browser": tab.browser,
                "tab_id": tab.tab_id,
                "window_id": tab.window_id,
                "provider": "web.browser_extension",
            },
            source_uri=tab.url,
            command_id=command_id,
            session_id=registration.provider_session_id,
            source_binding_id=source_binding_id,
        ),
        _json_evidence(
            "full_dom",
            "browser_full_dom",
            "full_dom",
            {
                "capture_mode": "full",
                "html": full_dom,
                "text_content": "ACME renewal dashboard Budget variance +18% Authorization: REDACTED REDACTED",
                "node_count": 5,
                "truncated": False,
                "sanitizer_version": "full_dom_v2_privacy",
            },
            source_uri=f"{tab.url}#dom",
            command_id=command_id,
            session_id=registration.provider_session_id,
            source_binding_id=source_binding_id,
            sensitivity="high_sensitivity",
            trust_state_claim="quarantined",
            redaction_state_claim="quarantined",
        ),
        _json_evidence(
            "page_text",
            "browser_readability_markdown",
            "source_text",
            page_text,
            source_uri=f"{tab.url}#page_text",
            command_id=command_id,
            session_id=registration.provider_session_id,
            source_binding_id=source_binding_id,
        ),
        _text_evidence(
            "visible_text",
            "browser_visible_text",
            visible_text,
            tab.url,
            command_id,
            registration.provider_session_id,
            source_binding_id,
        ),
    ]
    if selected_text.strip():
        evidence.append(
            _json_evidence(
                "selection_map",
                "selection_map",
                "selection_map",
                {
                    "binding_id": source_binding_id,
                    "screen_region": selection,
                    "viewport_region": {
                        "x": 40,
                        "y": 80,
                        "width": 320,
                        "height": 44,
                        "coordinate_space": "viewport_css_px",
                    },
                    "transforms": [],
                    "spans": [{"selector": "#variance", "start": 0, "end": len(selected_text), "text": selected_text}],
                    "confidence": 0.92,
                },
                source_uri=f"{tab.url}#selection",
                command_id=command_id,
                session_id=registration.provider_session_id,
                source_binding_id=source_binding_id,
            )
        )
        evidence.append(
            _text_evidence(
                "selected_text",
                "browser_selected_text",
                selected_text,
                f"{tab.url}#selection_text",
                command_id,
                registration.provider_session_id,
                source_binding_id,
                metadata={"selection_source": "browser_dom_region", "selection_confidence": 0.92},
            )
        )
    evidence.extend(extra_evidence)
    return {
        "schema_version": 1,
        "message_type": "collect_evidence_result",
        "command_id": command_id,
        "provider_key": "web.browser_extension",
        "provider_session_id": registration.provider_session_id,
        "status": "succeeded",
        "evidence_kind": "web",
        "source_binding": source_binding,
        "evidence_bundle": {
            "provider_key": "web.browser_extension",
            "provider_session_id": registration.provider_session_id,
            "command_id": command_id,
            "status": "succeeded",
            "evidence_kind": "web",
            "source_binding": source_binding,
            "evidence": evidence,
            "diagnostics": {"fixture": True, "actual_window_id": tab.window_id},
            "completed_at": datetime.now(UTC).isoformat(),
        },
        "diagnostics": {"fixture": True, "actual_tab_id": tab.tab_id, "actual_window_id": tab.window_id},
        "completed_at": datetime.now(UTC).isoformat(),
    }


def _a11y_collect_result(
    command_message: dict[str, Any],
    registration: ProviderSessionRegistration,
) -> dict[str, Any]:
    command = command_message["command"]
    command_id = command["command_id"]
    selection = command["attempt"]["selection_geometry"]["selected_region"]
    observed_at = datetime.now(UTC).isoformat()
    blocks = [
        _a11y_text_block("Full page text that must not enter preview", "AXWebArea", 0, 0, 1400, 1600, 0, False),
        _a11y_text_block("Account", "AXCell", 130, 150, 80, 20, 1, True, role_path=("AXTable",)),
        _a11y_text_block("Status", "AXCell", 250, 150, 80, 20, 2, True, role_path=("AXTable",)),
        _a11y_text_block("ACME", "AXCell", 130, 180, 80, 20, 3, True, role_path=("AXTable",)),
        _a11y_text_block("Procurement delayed", "AXCell", 250, 180, 170, 20, 4, True, role_path=("AXTable",)),
        _a11y_text_block(
            "API token: SHOULD_NOT_LEAK_A11Y_TOKEN",
            "AXStaticText",
            130,
            210,
            260,
            20,
            5,
            True,
        ),
        _a11y_text_block("Browser toolbar", "AXToolbar", 0, 80, 1440, 44, 6, True),
    ]
    snapshot = {
        "permission_state": "granted",
        "app_name": "Google Chrome",
        "process_id": 4242,
        "window_id": "win_test",
        "selection": selection,
        "root_nodes": [],
        "text_blocks": blocks,
        "full_text": "\n".join(block["text"] for block in blocks),
        "coverage": {
            "selection": selection,
            "permission_state": "granted",
            "node_count": 12,
            "text_block_count": len(blocks),
            "covered_area_ratio": 0.86,
            "confidence": 0.91,
            "error_message": None,
        },
    }
    evidence = [
        _a11y_evidence(
            "a11y",
            "a11y_tree",
            "ui_structure",
            snapshot,
            source_uri="macos://a11y/4242/win_test#tree",
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
            source_uri="macos://a11y/4242/win_test#coverage",
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
            source_uri="macos://a11y/4242/win_test#text",
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
            "diagnostics": {"fixture": True, "permission_state": "granted", "actual_window_id": "win_test"},
            "completed_at": observed_at,
        },
        "diagnostics": {"fixture": True, "permission_state": "granted", "actual_window_id": "win_test"},
        "completed_at": observed_at,
    }


def _a11y_overbroad_collect_result(
    command_message: dict[str, Any],
    registration: ProviderSessionRegistration,
) -> dict[str, Any]:
    command = command_message["command"]
    command_id = command["command_id"]
    selection = command["attempt"]["selection_geometry"]["selected_region"]
    observed_at = datetime.now(UTC).isoformat()
    blocks = [
        _a11y_text_block(
            "SHOULD_NOT_LEAK_OVERBROAD_A11Y",
            "AXWebArea",
            0,
            0,
            1800,
            2200,
            0,
            False,
        )
    ]
    snapshot = {
        "permission_state": "granted",
        "app_name": "Google Chrome",
        "process_id": 4242,
        "window_id": "win_test",
        "selection": selection,
        "root_nodes": [],
        "text_blocks": blocks,
        "full_text": "SHOULD_NOT_LEAK_OVERBROAD_A11Y",
        "coverage": {
            "selection": selection,
            "permission_state": "granted",
            "node_count": 1,
            "text_block_count": 1,
            "covered_area_ratio": 0.1,
            "confidence": 0.2,
            "error_message": None,
        },
    }
    evidence = [
        _a11y_evidence(
            "a11y",
            "a11y_tree",
            "ui_structure",
            snapshot,
            source_uri="macos://a11y/4242/win_test#tree",
            command_id=command_id,
            session_id=registration.provider_session_id,
            content_type="application/json",
            payload_schema="a11y_snapshot",
            sensitivity="high_sensitivity",
            trust_state_claim="quarantined",
            redaction_state_claim="quarantined",
        ),
        _a11y_evidence(
            "a11y",
            "a11y_text",
            "source_text",
            snapshot["full_text"],
            source_uri="macos://a11y/4242/win_test#text",
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
            "diagnostics": {"fixture": True, "permission_state": "granted", "actual_window_id": "win_test"},
            "completed_at": observed_at,
        },
        "diagnostics": {"fixture": True, "permission_state": "granted", "actual_window_id": "win_test"},
        "completed_at": observed_at,
    }


def _a11y_text_block(
    text: str,
    role: str,
    x: int,
    y: int,
    width: int,
    height: int,
    order_index: int,
    is_leaf_text: bool,
    *,
    role_path: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "text": text,
        "block_id": f"a11y_block_{order_index}",
        "role": role,
        "node_path": f"0/{order_index}",
        "role_path": list(role_path) + [role],
        "text_source": "value",
        "frame": {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "coordinate_space": "macos_global",
        },
        "selection_overlap_ratio": 1.0,
        "element_overlap_ratio": 1.0,
        "order_index": order_index,
        "is_leaf_text": is_leaf_text,
        "edge_recovered": False,
        "confidence": 0.9,
    }


def _a11y_evidence(
    kind: str,
    artifact_type: str,
    role: str,
    content: dict[str, Any] | str,
    *,
    source_uri: str,
    command_id: str,
    session_id: str,
    content_type: str,
    payload_schema: str,
    sensitivity: str = "internal",
    trust_state_claim: str = "provider_redacted",
    redaction_state_claim: str = "redacted",
) -> dict[str, Any]:
    inline_content = json.dumps(content, ensure_ascii=False, sort_keys=True) if isinstance(content, dict) else content
    return {
        "phase": "captured",
        "kind": kind,
        "artifact_type": artifact_type,
        "role": role,
        "payload": {
            "content_type": content_type,
            "inline_content": inline_content,
            "payload_schema": payload_schema,
            "payload_version": "1",
        },
        "locator": {"source_uri": source_uri, "source_type": "desktop_window"},
        "observed_at": datetime.now(UTC).isoformat(),
        "captured_at": datetime.now(UTC).isoformat(),
        "provenance": {
            "provider_key": "system.macos_a11y",
            "provider_kind": "system_evidence",
            "provider_session_id": session_id,
            "command_id": command_id,
            "extractor": {"name": "system.macos_a11y", "version": "p3_test_v1"},
        },
        "sensitivity": sensitivity,
        "trust_state_claim": trust_state_claim,
        "redaction_state_claim": redaction_state_claim,
        "metadata": {},
    }


def _json_evidence(
    kind: str,
    artifact_type: str,
    role: str,
    content: dict[str, Any],
    *,
    source_uri: str,
    command_id: str,
    session_id: str,
    source_binding_id: str,
    sensitivity: str = "internal",
    trust_state_claim: str = "provider_redacted",
    redaction_state_claim: str = "redacted",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import json

    return {
        "phase": "captured",
        "kind": kind,
        "artifact_type": artifact_type,
        "role": role,
        "payload": {
            "content_type": "application/json",
            "inline_content": json.dumps(content, ensure_ascii=False, sort_keys=True),
            "payload_schema": kind,
            "payload_version": "1",
        },
        "locator": {"source_uri": source_uri, "source_type": "web"},
        "observed_at": datetime.now(UTC).isoformat(),
        "captured_at": datetime.now(UTC).isoformat(),
        "provenance": {
            "provider_key": "web.browser_extension",
            "provider_kind": "source",
            "provider_session_id": session_id,
            "command_id": command_id,
            "source_binding_id": source_binding_id,
            "extractor": {"name": "web.browser_extension", "version": "p3_test_v1"},
        },
        "sensitivity": sensitivity,
        "trust_state_claim": trust_state_claim,
        "redaction_state_claim": redaction_state_claim,
        "metadata": metadata or {},
    }


def _text_evidence(
    kind: str,
    artifact_type: str,
    content: str,
    source_uri: str,
    command_id: str,
    session_id: str,
    source_binding_id: str,
    *,
    role: str = "source_text",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "phase": "captured",
        "kind": kind,
        "artifact_type": artifact_type,
        "role": role,
        "payload": {
            "content_type": "text/plain; charset=utf-8",
            "inline_content": content,
            "payload_schema": kind,
            "payload_version": "1",
        },
        "locator": {"source_uri": source_uri, "source_type": "web"},
        "observed_at": datetime.now(UTC).isoformat(),
        "captured_at": datetime.now(UTC).isoformat(),
        "provenance": {
            "provider_key": "web.browser_extension",
            "provider_kind": "source",
            "provider_session_id": session_id,
            "command_id": command_id,
            "source_binding_id": source_binding_id,
            "extractor": {"name": "web.browser_extension", "version": "p3_test_v1"},
        },
        "sensitivity": "internal",
        "trust_state_claim": "provider_redacted",
        "redaction_state_claim": "redacted",
        "metadata": metadata or {},
    }


def _content_path(artifact_id: str, event_id: str, *, purpose: str = "test_read") -> str:
    return f"/v1/artifacts/{artifact_id}/content?event_id={event_id}&purpose={purpose}"


def _stored_artifact_by_source_uri(client: TestClient, event_id: str, source_uri: str) -> dict[str, Any]:
    artifacts = _container(client).repositories.artifacts.list_for_event(event_id)
    artifact = next(item for item in artifacts if item.source_uri == source_uri)
    return artifact.model_dump(mode="json")


def _client_with_settings(tmp_path, disclosure_policy_path):
    settings = WorkRecorderSettings(
        database_path=tmp_path / "override.sqlite",
        artifact_staging_dir=tmp_path / "override_staging",
        artifact_vault_dir=tmp_path / "override_artifacts",
        install_secret="test-install-secret",
        native_capture_secret="test-native-secret",
        disclosure_policy_path=disclosure_policy_path,
    )
    client = TestClient(DaemonAppFactory(settings).create())
    token = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "test-cli", "display_name": "Test CLI"},
    ).json()["data"]["access_token"]
    return client, token


def _token_with_scopes(client: TestClient, scopes: tuple[str, ...]) -> str:
    response = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "test-cli", "display_name": "Test CLI", "scopes": list(scopes)},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    return str(payload["data"]["access_token"])


def _request_for_client_settings(capture_request: Any, settings: WorkRecorderSettings) -> Any:
    settings.artifact_staging_dir.mkdir(parents=True, exist_ok=True)
    staged_file = settings.artifact_staging_dir / f"{capture_request.trigger.trigger_id}.png"
    staged_file.write_bytes(b"\x89PNG\r\n\x1a\nworkrecorder-test-png")
    return capture_request.model_copy(
        update={"staged_artifact": capture_request.staged_artifact.model_copy(update={"local_path": str(staged_file)})}
    )


class _MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get(self, *, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set(self, *, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def delete(self, *, service: str, account: str) -> None:
        self.values.pop((service, account), None)


def test_policy_check_binds_actor_to_token(client, token):
    headers = {"authorization": f"Bearer {token}"}
    response = client.post(
        "/v1/policy/check-access",
        headers=headers,
        json={
            "actor": {"actor_id": "spoofed-user", "display_name": "Spoofed"},
            "action": "read_metadata",
            "resource_type": "event",
            "resource_id": "evt_fake",
            "reason": "spoof attempt",
        },
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["data"]["actor"]["actor_id"] == "test-cli"
