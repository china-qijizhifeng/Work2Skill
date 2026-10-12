from __future__ import annotations

import asyncio
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.contracts import ProviderSessionRegistration
from services.context_daemon.container import DaemonContainer


def test_provider_websocket_registers_with_workrecorder_auth_protocol(
    client: TestClient, provider_session_registration: ProviderSessionRegistration
) -> None:
    response = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-provider-secret": "test-provider-secret"},
        json={
            "actor_id": "browser-extension",
            "display_name": "WorkRecorder Browser",
            "scopes": ["register_provider_context"],
        },
    )
    assert response.status_code == 200
    token = response.json()["data"]["access_token"]
    with client.websocket_connect(
        "/v1/providers/sessions/ws",
        subprotocols=["workrecorder-provider-v1", f"workrecorder-token.{token}"],
    ) as websocket:
        assert websocket.accepted_subprotocol == "workrecorder-provider-v1"
        websocket.send_json({"registration": provider_session_registration.model_dump(mode="json")})
        accepted = websocket.receive_json()
        assert accepted["message_type"] == "provider_session_accepted"
        assert accepted["session"]["provider_session_id"] == provider_session_registration.provider_session_id


def test_provider_definitions_include_builtin_and_browser(client: TestClient, token: str) -> None:
    response = client.get("/v1/providers/definitions", headers={"authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    definitions = {item["provider_key"]: item for item in payload["data"]["definitions"]}
    assert {"system.screenshot", "system.macos_a11y", "system.appshot", "web.browser_extension"} <= set(definitions)
    assert definitions["system.screenshot"]["install"]["install_kind"] == "built_in"
    assert definitions["system.screenshot"]["source_types"] == ["desktop_window", "web", "document"]
    assert definitions["system.appshot"]["install"]["install_kind"] == "built_in"
    assert definitions["system.appshot"]["provider_kind"] == "system_evidence"
    assert definitions["system.appshot"]["metadata"]["read_only"] is True
    assert definitions["web.browser_extension"]["install"]["install_kind"] == "manual_unpacked_browser_extension"
    assert definitions["web.browser_extension"]["install"]["supports_auto_install"] is False
    targets = {
        target["target_key"]: target for target in definitions["web.browser_extension"]["install"]["runtime_targets"]
    }
    assert {"chrome", "chrome_for_testing", "edge"} <= set(targets)
    assert targets["chrome"]["open_url"] == "chrome://extensions"
    assert targets["chrome_for_testing"]["open_url"] == "chrome://extensions"
    assert targets["edge"]["open_url"] == "edge://extensions"


def test_provider_status_distinguishes_builtin_and_offline_browser(client: TestClient, token: str) -> None:
    response = client.get("/v1/providers/status", headers={"authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    providers = {item["provider_key"]: item for item in payload["data"]["providers"]}
    assert providers["system.screenshot"]["runtime"]["state"] == "ready"
    assert providers["system.screenshot"]["installed"] is True
    assert providers["system.appshot"]["runtime"]["state"] == "ready"
    assert providers["system.appshot"]["installed"] is True
    assert providers["system.appshot"]["configured"] is True
    assert providers["system.macos_a11y"]["installed"] is True
    assert providers["system.macos_a11y"]["configured"] is False
    assert providers["system.macos_a11y"]["runtime"]["state"] == "needs_setup"
    assert providers["web.browser_extension"]["installed"] is True
    assert providers["web.browser_extension"]["configured"] is False
    assert providers["web.browser_extension"]["runtime"]["state"] == "offline"
    assert providers["web.browser_extension"]["runtime"]["connected_session_count"] == 0
    assert providers["web.browser_extension"]["sessions"] == []


def test_provider_status_reports_online_browser_session(
    client: TestClient,
    token: str,
    provider_session_registration: ProviderSessionRegistration,
) -> None:
    container = cast(DaemonContainer, cast(FastAPI, client.app).state.container)
    asyncio.run(
        container.provider_sessions.register(
            websocket=_FakeSocket(),
            registration=provider_session_registration,
        )
    )

    response = client.get("/v1/providers/status", headers={"authorization": f"Bearer {token}"})

    assert response.status_code == 200
    providers = {item["provider_key"]: item for item in response.json()["data"]["providers"]}
    browser = providers["web.browser_extension"]
    assert browser["configured"] is True
    assert browser["runtime"]["state"] == "online"
    assert browser["runtime"]["connected_session_count"] == 1
    assert browser["permissions"][0]["state"] == "granted"
    assert browser["diagnostics"][0]["status"] == "passed"
    assert browser["sessions"] == []
    assert provider_session_registration.tab is not None
    assert provider_session_registration.tab.url not in response.text


def test_provider_diagnostics_unknown_provider_is_not_found(client: TestClient, token: str) -> None:
    response = client.post(
        "/v1/providers/missing.provider/diagnostics/run",
        headers={"authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_provider_status_requires_metadata_scope(client: TestClient) -> None:
    response = client.get("/v1/providers/status")

    assert response.status_code == 403


class _FakeSocket:
    async def send_text(self, data: str) -> None:
        del data
        return None
