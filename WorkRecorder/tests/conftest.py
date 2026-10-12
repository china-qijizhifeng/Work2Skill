from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from packages.contracts import (
    ActorRef,
    BoundingBox,
    BrowserKind,
    BrowserTabRef,
    BrowserViewport,
    BrowserWindowRef,
    CaptureSaveRequest,
    CaptureStrategy,
    ContextEventCreate,
    DisplayGeometry,
    FloatRect,
    ProviderSessionRegistration,
    SelectionGeometry,
    SourceBinding,
    SourceRef,
    SourceType,
    StagedArtifactRef,
    TriggerEnvelope,
    TriggerType,
    WorkspaceSelection,
)
from packages.contracts.enums import ArtifactType, CoordinateSpace, ProviderCapability, ProviderKind
from packages.shared.config import WorkRecorderSettings
from scripts.repair_uv_editable_install import repair_macos_hidden_pth_files
from services.context_daemon.app import DaemonAppFactory

repair_macos_hidden_pth_files()


def _write_test_png(path: Path, *, size: tuple[int, int] = (640, 360)) -> None:
    image = Image.new("RGB", size, "#f7fbfc")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, size[0] - 40, size[1] - 40), outline="#81d8d0", width=3)
    draw.text((64, 68), "WorkRecorder test screenshot", fill="#245b62")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())


@pytest.fixture()
def settings(tmp_path: Path) -> WorkRecorderSettings:
    return WorkRecorderSettings(
        database_path=tmp_path / "workrecorder.sqlite",
        artifact_staging_dir=tmp_path / "staging",
        artifact_vault_dir=tmp_path / "artifacts",
        install_secret="test-install-secret",
        provider_registration_secret="test-provider-secret",
        native_capture_secret="test-native-secret",
        disclosure_policy_path=None,
        capture_post_commit_outbox_worker_enabled=False,
    )


@pytest.fixture()
def client(settings: WorkRecorderSettings) -> TestClient:
    app = DaemonAppFactory(settings).create()
    return TestClient(app)


@pytest.fixture()
def token(client: TestClient) -> str:
    response = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "test-cli", "display_name": "Test CLI"},
    )
    payload = response.json()
    return cast(str, payload["data"]["access_token"])


@pytest.fixture()
def event_create() -> ContextEventCreate:
    occurred_at = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
    trigger = TriggerEnvelope(
        trigger_id="trg_test",
        trigger_type=TriggerType.MANUAL_OS_REGION_HOTKEY,
        capture_strategy=CaptureStrategy.OS_REGION,
        actor=ActorRef(actor_id="user_test", display_name="Test User"),
        occurred_at=occurred_at,
        selection=BoundingBox(x=10, y=20, width=300, height=160),
        intent_text="用于 ACME 续约 brief",
    )
    source = SourceBinding(
        binding_id="src_test",
        source_ref=SourceRef(
            source_type=SourceType.WEB,
            title="ACME Pricing Dashboard",
            app_name="Chrome",
            url="https://example.test/acme",
            origin="https://example.test",
        ),
        confidence=0.98,
        resolved_at=occurred_at,
    )
    return ContextEventCreate(trigger=trigger, source_binding=source, intent_text="用于 ACME 续约 brief")


@pytest.fixture()
def capture_save_request(settings: WorkRecorderSettings, event_create: ContextEventCreate) -> CaptureSaveRequest:
    settings.artifact_staging_dir.mkdir(parents=True, exist_ok=True)
    staged_file = settings.artifact_staging_dir / "capture.png"
    _write_test_png(staged_file)
    selected_region = BoundingBox(
        x=120,
        y=140,
        width=520,
        height=280,
        coordinate_space=CoordinateSpace.MACOS_GLOBAL,
    )
    display = DisplayGeometry(
        display_id="display_main",
        frame=BoundingBox(x=0, y=0, width=1440, height=900, coordinate_space=CoordinateSpace.MACOS_GLOBAL),
        scale_factor=2.0,
    )
    return CaptureSaveRequest(
        trigger=event_create.trigger.model_copy(
            update={
                "selection": selected_region,
                "capture_strategy": CaptureStrategy.OS_REGION,
            }
        ),
        selection_geometry=SelectionGeometry(selected_region=selected_region, display=display),
        source_binding=event_create.source_binding,
        workspace=WorkspaceSelection(),
        actor=ActorRef(actor_id="test-cli", display_name="Test CLI"),
        staged_artifact=StagedArtifactRef(
            local_path=str(staged_file),
            artifact_type=ArtifactType.SCREENSHOT,
            content_type="image/png",
            filename="capture.png",
        ),
        intent_text="用于 ACME 续约 brief",
    )


@pytest.fixture()
def provider_session_registration(capture_save_request: CaptureSaveRequest) -> ProviderSessionRegistration:
    selected = capture_save_request.selection_geometry.selected_region
    return ProviderSessionRegistration(
        provider_key="web.browser_extension",
        provider_session_id="ctx_ext_test_win_test_tab_acme",
        provider_kind=ProviderKind.SOURCE,
        display_name="WorkRecorder Web Provider",
        app_name="Google Chrome",
        window_id="win_test",
        window=BrowserWindowRef(window_id="win_test", screen_rect=selected),
        tab=BrowserTabRef(
            browser=BrowserKind.CHROME.value,
            tab_id="tab_acme",
            window_id="win_test",
            url="https://example.test/acme",
            origin="https://example.test",
            title="ACME Pricing Dashboard",
        ),
        viewport=BrowserViewport(
            rect=FloatRect(x=0, y=0, width=1440, height=900, coordinate_space=CoordinateSpace.VIEWPORT_CSS_PX),
            device_pixel_ratio=2.0,
        ),
        capabilities=(
            ProviderCapability.RESOLVE_SOURCE,
            ProviderCapability.COLLECT_PAGE_METADATA,
            ProviderCapability.COLLECT_VISIBLE_TEXT,
            ProviderCapability.COLLECT_SELECTED_TEXT,
            ProviderCapability.COLLECT_PAGE_TEXT,
            ProviderCapability.COLLECT_READABILITY_TEXT,
            ProviderCapability.COLLECT_SANITIZED_DOM,
            ProviderCapability.COLLECT_FULL_DOM,
            ProviderCapability.MAP_SELECTION,
        ),
        registered_at=datetime.now(UTC),
        ttl_ms=60000,
    )
