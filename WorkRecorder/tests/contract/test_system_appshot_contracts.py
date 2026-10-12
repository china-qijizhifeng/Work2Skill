from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from packages.agent_runs.snapshots import DeliveredSnapshotBuilder
from packages.contracts import (
    ActorRef,
    AppshotComponentRef,
    AppshotPermissionReport,
    AppshotQualityReport,
    AppshotSurfaceSnapshot,
    AppshotWindowIdentity,
    ArtifactRole,
    ArtifactType,
    BoundingBox,
    CaptureStrategy,
    ContextEvent,
    EventStatus,
    EvidenceKind,
    ProviderCaptureOutcomeStatus,
    ProviderPermissionState,
    ProviderRouteRole,
    SearchResponse,
    SearchResultCard,
    SearchResultSource,
    SourceBinding,
    SourceRef,
    SourceType,
    SystemAppshotSnapshot,
    TriggerEnvelope,
    TriggerType,
)
from packages.contracts.provider_enums import ProviderCapability
from packages.disclosure.views import source_for_event
from packages.shared.ids import IdFactory
from services.context_daemon.safe_metadata import safe_public_payload


def test_system_appshot_contract_round_trips_without_raw_payload_fields() -> None:
    selection = BoundingBox(x=-20, y=30, width=640, height=360)
    snapshot = SystemAppshotSnapshot(
        capture_revision="appshot:trg_contract",
        selected_region=selection,
        primary_surface_id="surface_0",
        primary_app_name="Google Chrome",
        primary_bundle_id="com.google.Chrome",
        primary_process_id=4242,
        primary_window_id="99",
        surfaces=(
            AppshotSurfaceSnapshot(
                surface_id="surface_0",
                kind="web_browser",
                role=ProviderRouteRole.PRIMARY_SOURCE,
                identity=AppshotWindowIdentity(
                    app_name="Google Chrome",
                    title="WorkRecorder RFC",
                    bundle_id="com.google.Chrome",
                    process_id=4242,
                    window_id="99",
                    frame=selection,
                    display_id="1",
                    visible_area_ratio=0.76,
                    is_frontmost=True,
                ),
                overlap_ratio=0.92,
                confidence=0.88,
            ),
        ),
        screenshot_evidence_id="evd_screen",
        a11y_evidence_ids=("evd_a11y",),
        quality=AppshotQualityReport(
            screenshot_present=True,
            a11y_supported=True,
            surface_count=1,
            primary_confidence=0.88,
            coverage_confidence=0.82,
        ),
        permissions=AppshotPermissionReport(
            screen_recording=ProviderPermissionState.GRANTED,
            accessibility=ProviderPermissionState.GRANTED,
        ),
        components=(
            AppshotComponentRef(
                provider_key="system.screenshot",
                evidence_kind=EvidenceKind.SCREENSHOT,
                status=ProviderCaptureOutcomeStatus.SUCCEEDED,
                role=ProviderRouteRole.SYSTEM_EVIDENCE,
                evidence_ids=("evd_screen",),
                artifact_ids=("art_screen",),
            ),
        ),
    )

    payload = snapshot.model_dump(mode="json")
    assert payload["selected_region"]["x"] == -20
    assert payload["surfaces"][0]["identity"]["bundle_id"] == "com.google.Chrome"
    assert "storage_uri" not in str(payload)
    assert "raw" not in str(payload).lower()
    assert ArtifactType.SYSTEM_APPSHOT.value == "system_appshot"
    assert ArtifactRole.SYSTEM_APPSHOT.value == "system_appshot"
    assert EvidenceKind.SYSTEM_APPSHOT.value == "system_appshot"
    assert ProviderCapability.COLLECT_SYSTEM_APPSHOT.value == "collect_system_appshot"
    assert SourceType.DESKTOP_WINDOW.value == "desktop_window"


def test_system_appshot_contract_rejects_raw_or_vault_metadata() -> None:
    selection = BoundingBox(x=0, y=0, width=100, height=80)

    try:
        SystemAppshotSnapshot(
            capture_revision="appshot:leaky",
            selected_region=selection,
            quality=AppshotQualityReport(screenshot_present=True),
            permissions=AppshotPermissionReport(screen_recording=ProviderPermissionState.GRANTED),
            metadata={"storage_uri": "local-artifact://aa/bb/raw.png"},
        )
    except ValueError as exc:
        assert "raw or vault" in str(exc)
    else:
        raise AssertionError("system appshot accepted raw/vault metadata")


def test_system_appshot_contract_rejects_file_locator_metadata_values() -> None:
    selection = BoundingBox(x=0, y=0, width=100, height=80)

    try:
        SystemAppshotSnapshot(
            capture_revision="appshot:leaky",
            selected_region=selection,
            quality=AppshotQualityReport(screenshot_present=True),
            permissions=AppshotPermissionReport(screen_recording=ProviderPermissionState.GRANTED),
            metadata={"diagnostic": "failed at file:///Users/example/raw.png"},
        )
    except ValueError as exc:
        assert "raw or vault" in str(exc)
    else:
        raise AssertionError("system appshot accepted file locator metadata")


def test_system_appshot_contract_rejects_local_icon_refs() -> None:
    selection = BoundingBox(x=0, y=0, width=100, height=80)

    try:
        SystemAppshotSnapshot(
            capture_revision="appshot:leaky",
            selected_region=selection,
            surfaces=(
                AppshotSurfaceSnapshot(
                    surface_id="surface_0",
                    kind="desktop_window",
                    role=ProviderRouteRole.PRIMARY_SOURCE,
                    identity=AppshotWindowIdentity(
                        app_name="Preview",
                        app_icon_ref="local-artifact://icons/preview.png",
                    ),
                    overlap_ratio=1.0,
                    confidence=0.9,
                ),
            ),
            quality=AppshotQualityReport(screenshot_present=True),
            permissions=AppshotPermissionReport(screen_recording=ProviderPermissionState.GRANTED),
        )
    except ValueError as exc:
        assert "raw or vault" in str(exc)
    else:
        raise AssertionError("system appshot accepted local app icon ref")


def test_safe_metadata_redacts_local_diagnostic_values() -> None:
    payload = {
        "diagnostics": {
            "error_message": "failed at /Users/example/.workrecorder/vault/raw.png local-artifact://abc/raw.png file:///tmp/raw.png",
            "local_path": "/private/tmp/workrecorder/capture.png",
            "messages": ["see file:///Users/example/raw.png", "/var/folders/example/raw.png"],
        }
    }

    safe = cast(dict[str, Any], safe_public_payload(payload))
    safe_text = str(safe)

    assert "/Users/example" not in safe_text
    assert "/private/tmp" not in safe_text
    assert "local-artifact://abc" not in safe_text
    assert "file:///tmp" not in safe_text
    assert "/var/folders/example" not in safe_text
    assert safe["diagnostics"]["local_path"] is None


def test_safe_metadata_redacts_os_window_private_identity_recursively() -> None:
    payload = {
        "event_type": "screen.window.captured",
        "capture_strategy": "os_window",
        "trigger": {
            "capture_strategy": "os_window",
            "selection": {"x": 10, "y": 20, "width": 300, "height": 200},
            "metadata": {"os_window_bundle_id": "com.apple.finder"},
        },
        "source_binding": {
            "binding_id": "src-secret",
            "provider_context_id": "ctx-secret",
            "provider_session_id": "provider-session-secret",
            "matched_region": {"x": 10, "y": 20, "width": 300, "height": 200},
            "source_ref": {
                "app_name": "Finder",
                "title": "Downloads",
                "external_id": "external-secret",
            },
        },
        "selection_geometry": {"selected_region": {"x": 10, "y": 20, "width": 300, "height": 200}},
        "artifact": {
            "source_uri": "macos://a11y/123/win-1",
            "metadata": {
                "selection_x": 10,
                "selection_y": 20,
                "selection_width": 300,
                "selection_height": 200,
                "target_tab_id": "tab-secret",
                "target_window_id": "win-secret",
                "target_provider_session_id": "provider-secret",
                "command_id": "cmd-secret",
                "source_binding_id": "src-secret",
            },
        },
        "system_appshot": {
            "primary_process_id": 123,
            "primary_window_id": "win-1",
            "primary_bundle_id": "com.apple.finder",
            "surfaces": [
                {
                    "identity": {
                        "process_id": 123,
                        "window_id": "win-1",
                        "bundle_id": "com.apple.finder",
                        "display_id": "display-secret",
                        "frame": {"x": 10, "y": 20, "width": 300, "height": 200},
                    }
                }
            ],
        },
        "manifest": {
            "evidence_records": [{"locator": {"source_uri": "macos://a11y/123/win-1"}}],
            "detected_surfaces": [{"process_id": 123, "window_id": "win-1"}],
            "provider_routes": [{"window_id": "win-1"}],
            "provider_outcomes": [{"command_id": "cmd-secret"}],
            "source_bindings": [{"external_id": "external-secret"}],
        },
        "provider_session": {
            "window": {"native_window_id": "native-window-secret", "screen_rect": {"x": 1, "y": 2}},
            "viewport": {"rect": {"x": 1, "y": 2, "width": 300, "height": 200}},
        },
    }

    safe = cast(dict[str, Any], safe_public_payload(payload))
    safe_text = str(safe)

    assert "win-1" not in safe_text
    assert "tab-secret" not in safe_text
    assert "provider-secret" not in safe_text
    assert "provider-session-secret" not in safe_text
    assert "external-secret" not in safe_text
    assert "cmd-secret" not in safe_text
    assert "src-secret" not in safe_text
    assert "native-window-secret" not in safe_text
    assert "display-secret" not in safe_text
    assert "com.apple.finder" not in safe_text
    assert "'process_id': 123" not in safe_text
    assert "'selection_x': 10" not in safe_text
    assert safe["trigger"]["selection"] is None
    assert safe["source_binding"]["matched_region"] is None
    assert safe["artifact"]["metadata"]["selection_x"] is None
    assert safe["artifact"]["metadata"]["target_window_id"] is None
    assert safe["artifact"]["metadata"]["command_id"] is None
    assert safe["artifact"]["source_uri"] == "macos://a11y/[redacted]"
    assert safe["source_binding"]["binding_id"] is None
    assert safe["source_binding"]["source_ref"]["external_id"] is None
    assert safe["selection_geometry"] is None
    assert safe["system_appshot"]["primary_process_id"] is None
    assert safe["system_appshot"]["primary_window_id"] is None
    assert safe["system_appshot"]["primary_bundle_id"] is None
    assert safe["system_appshot"]["surfaces"][0]["identity"]["frame"] is None
    assert safe["system_appshot"]["surfaces"][0]["identity"]["bundle_id"] is None
    assert safe["system_appshot"]["surfaces"][0]["identity"]["display_id"] is None
    assert safe["manifest"]["evidence_records"][0]["locator"]["source_uri"] == "macos://a11y/[redacted]"
    assert safe["manifest"]["detected_surfaces"] is None
    assert safe["manifest"]["provider_routes"] is None
    assert safe["manifest"]["provider_outcomes"] is None
    assert safe["manifest"]["source_bindings"] is None
    assert safe["provider_session"]["window"] is None
    assert safe["provider_session"]["viewport"] is None


def test_safe_metadata_redacts_camel_case_identity_and_secret_keys() -> None:
    payload = {
        "processId": 1234,
        "windowId": "win-secret",
        "providerSessionId": "provider-secret",
        "nativeWindowId": "native-window-secret",
        "screenRect": {"x": 1, "y": 2, "width": 300, "height": 200},
        "localPath": "/Users/example/private.txt",
        "accessToken": "token-secret",
        "title": "/Users/example/private token=SHOULD_NOT_LEAK",
    }

    safe = cast(dict[str, Any], safe_public_payload(payload))
    safe_text = str(safe)

    assert safe["processId"] is None
    assert safe["windowId"] is None
    assert safe["providerSessionId"] is None
    assert safe["nativeWindowId"] is None
    assert safe["screenRect"] is None
    assert safe["localPath"] is None
    assert safe["accessToken"] is None
    assert "/Users/example" not in safe_text
    assert "SHOULD_NOT_LEAK" not in safe_text


def test_safe_metadata_redacts_secret_key_variants_and_bearer_strings() -> None:
    payload = {
        "apiKey": "SHOULD_NOT_LEAK_API_KEY",
        "bearerToken": "SHOULD_NOT_LEAK_BEARER_TOKEN",
        "authToken": "SHOULD_NOT_LEAK_AUTH_TOKEN",
        "clientSecret": "SHOULD_NOT_LEAK_CLIENT_SECRET",
        "Authorization": "Bearer SHOULD_NOT_LEAK_AUTHORIZATION_HEADER",
        "title": "Authorization: Bearer SHOULD_NOT_LEAK_TITLE",
        "other": "Bearer SHOULD_NOT_LEAK_BARE",
        "query": "api_key=SHOULD_NOT_LEAK_QUERY",
        "label": "api key: SHOULD_NOT_LEAK_LABEL",
        "client_secret": "SHOULD_NOT_LEAK_CLIENT_SECRET_SNAKE",
    }

    safe = cast(dict[str, Any], safe_public_payload(payload))
    safe_text = str(safe)

    assert "SHOULD_NOT_LEAK" not in safe_text
    assert safe["apiKey"] is None
    assert safe["bearerToken"] is None
    assert safe["authToken"] is None
    assert safe["clientSecret"] is None
    assert safe["Authorization"] is None
    assert safe["client_secret"] is None
    assert safe["title"] == "[secret:redacted]"
    assert safe["other"] == "[secret:redacted]"
    assert safe["query"] == "[secret:redacted]"
    assert safe["label"] == "[secret:redacted]"


def test_safe_metadata_redacts_unsafe_keys_and_generic_url_queries() -> None:
    payload = {
        "/Users/example/token.txt": "safe value",
        "Authorization: Bearer SHOULD_NOT_LEAK_KEY": "safe value",
        "windowId_123": "safe value",
        "nested": {
            "https://example.test/path?token=SHOULD_NOT_LEAK_KEY_URL#frag": "safe value",
        },
        "message": "open https://example.test/path?token=SHOULD_NOT_LEAK_VALUE_URL#frag now",
    }

    safe = cast(dict[str, Any], safe_public_payload(payload))
    safe_text = str(safe)

    assert "SHOULD_NOT_LEAK" not in safe_text
    assert "/Users/example" not in safe_text
    assert "windowId_123" not in safe_text
    assert "frag" not in safe_text
    assert "redacted_key_1" in safe
    assert "redacted_key_2" in safe
    assert "redacted_key_3" in safe
    assert "https://example.test/path" in safe["message"]


def test_safe_metadata_handles_malformed_embedded_http_urls_without_crashing() -> None:
    payload = {
        "message": "open https://[broken/path?token=SHOULD_NOT_LEAK_VALUE and continue",
        "origin": "https://[broken/path?token=SHOULD_NOT_LEAK_ORIGIN",
        "closed_bracket": "open https://[broken]/path?token=SHOULD_NOT_LEAK_CLOSED now",
        "closed_bracket_no_slash": "open https://[broken]path?token=SHOULD_NOT_LEAK_NO_SLASH now",
    }

    safe = cast(dict[str, Any], safe_public_payload(payload))
    safe_text = str(safe)

    assert "SHOULD_NOT_LEAK" not in safe_text
    assert safe["message"] == "open [url:redacted] and continue"
    assert safe["origin"] == "[url:redacted]"
    assert safe["closed_bracket"] == "open [url:redacted] now"
    assert safe["closed_bracket_no_slash"] == "open [url:redacted] now"


def test_delivered_search_snapshot_redacts_malformed_url_queries_without_crashing() -> None:
    response = SearchResponse(
        events=(),
        degraded=False,
        backend="keyword",
        results=(
            SearchResultCard(
                event_id="evt_bad_url",
                event_type="screen.region.captured",
                captured_at=datetime.now(UTC),
                source=SearchResultSource(title="Bad URL", origin=None),
                selection_text_snippet="open https://[broken]/path?token=SHOULD_NOT_LEAK_QUERY now",
            ),
        ),
    )

    safe = DeliveredSnapshotBuilder(IdFactory()).safe_payload(response)
    safe_text = str(safe)

    assert "SHOULD_NOT_LEAK" not in safe_text
    assert "[url:redacted]" in safe_text


def test_source_for_event_redacts_local_paths_and_token_like_text() -> None:
    now = datetime.now(UTC)
    event = ContextEvent(
        event_id="evt_source_safe",
        event_type="screen.region.captured",
        trigger=TriggerEnvelope(
            trigger_id="trg_source_safe",
            trigger_type=TriggerType.MANUAL_OS_REGION_HOTKEY,
            capture_strategy=CaptureStrategy.OS_REGION,
            actor=ActorRef(actor_id="test", display_name="Test"),
            occurred_at=now,
            selection=BoundingBox(x=0, y=0, width=100, height=100),
        ),
        source_binding=SourceBinding(
            binding_id="src_source_safe",
            source_ref=SourceRef(
                source_type=SourceType.DESKTOP_WINDOW,
                app_name="/Users/example/App token=SHOULD_NOT_LEAK_APP",
                title="/Users/example/Secret.pdf token=SHOULD_NOT_LEAK_TITLE",
                url="file:///Users/example/Secret.pdf?token=SHOULD_NOT_LEAK_URL",
                origin="file:///Users/example?token=SHOULD_NOT_LEAK_ORIGIN",
            ),
            confidence=1.0,
            resolved_at=now,
        ),
        status=EventStatus.AGENT_READY,
        intent_text=None,
        created_at=now,
        updated_at=now,
    )

    source = source_for_event(event)
    safe_text = str(source.model_dump(mode="json"))

    assert "/Users/example" not in safe_text
    assert "SHOULD_NOT_LEAK" not in safe_text
    assert source.origin == "[uri:redacted]"
    assert source.sanitized_url == "[uri:redacted]"
