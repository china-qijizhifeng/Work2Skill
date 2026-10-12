from __future__ import annotations

from fastapi.testclient import TestClient


def test_browser_extension_can_preflight_token_exchange(client: TestClient) -> None:
    response = client.options(
        "/v1/auth/tokens",
        headers={
            "origin": "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type,x-workrecorder-provider-secret",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert "x-workrecorder-provider-secret" in response.headers["access-control-allow-headers"].lower()


def test_non_extension_origin_cannot_preflight_token_exchange(client: TestClient) -> None:
    response = client.options(
        "/v1/auth/tokens",
        headers={
            "origin": "https://example.test",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type,x-workrecorder-provider-secret",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_browser_extension_token_response_includes_cors_header(client: TestClient) -> None:
    response = client.post(
        "/v1/auth/tokens",
        headers={
            "origin": "chrome-extension://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "x-workrecorder-provider-secret": "test-provider-secret",
        },
        json={
            "actor_id": "browser-extension",
            "display_name": "WorkRecorder Browser Extension",
            "scopes": ["register_provider_context"],
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "chrome-extension://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
