from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from packages.context_share.package import SharePackageBuilder
from packages.contracts import ExternalShareTarget, SharePackageManifest, SharePublishStatus, ShareRevision
from packages.integrations.feishu import FeishuDriveClient, FeishuSharePublisher, FeishuTokenClient
from packages.settings.secret_store import EnvSecretStore
from packages.shared.config import WorkRecorderSettings
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from services.context_daemon.app import DaemonAppFactory

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\xf8\xff"
    b"\xff?\x00\x05\xfe\x02\xfeA\xd8\xf9\x0b\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.skipif(os.getenv("WORKRECORDER_RUN_FEISHU_E2E") != "1", reason="Feishu live E2E is opt-in")
def test_feishu_live_publish_permission_url_and_revoke() -> None:
    app_id = os.getenv("WORKRECORDER_FEISHU_APP_ID")
    folder_token = os.getenv("WORKRECORDER_FEISHU_FOLDER_TOKEN")
    assert app_id, "WORKRECORDER_FEISHU_APP_ID is required"
    assert folder_token, "WORKRECORDER_FEISHU_FOLDER_TOKEN is required"
    token_client = FeishuTokenClient(
        app_id=app_id,
        secret_store=EnvSecretStore(),
        api_base_url=os.getenv("WORKRECORDER_FEISHU_API_BASE_URL", "https://open.feishu.cn"),
        clock=Clock(),
    )
    drive = FeishuDriveClient(
        token_client=token_client,
        folder_token=folder_token,
        api_base_url=os.getenv("WORKRECORDER_FEISHU_API_BASE_URL", "https://open.feishu.cn"),
    )
    now = datetime.now(UTC)
    share_id = f"shr_live_{now.strftime('%Y%m%d%H%M%S')}"
    manifest = SharePackageManifest(
        share_id=share_id,
        event_id="evt_live_feishu",
        revision=1,
        html_filename=f"workrecorder-share-{share_id}-r1.html",
        json_filename=f"workrecorder-share-{share_id}-r1.json",
        manifest_filename=f"workrecorder-share-{share_id}-r1-manifest.json",
        html_sha256="a" * 64,
        json_sha256="b" * 64,
        manifest_sha256="c" * 64,
        created_at=now,
    )
    revision = ShareRevision(
        revision_id=f"shr_rev_{share_id}",
        share_id=share_id,
        event_id="evt_live_feishu",
        revision=1,
        snapshot_id=f"shr_snap_{share_id}",
        manifest=manifest,
        status=SharePublishStatus.PENDING,
        created_at=now,
    )

    publisher = FeishuSharePublisher(drive=drive, ids=IdFactory(), clock=Clock())
    published: ExternalShareTarget | None = None
    try:
        published = publisher.publish(
            share_id=share_id,
            revision=revision,
            html=b"<html><body>WorkRecorder Feishu E2E</body></html>",
        )

        assert (
            published.status == SharePublishStatus.PUBLISHED
        ), f"{published.last_error_code}: {published.last_error_message}"
        assert published.provider_file_token
        assert published.provider_url
        assert "?" not in published.provider_url
        assert "#" not in published.provider_url

        revoked = publisher.revoke(target=published)

        assert revoked.status == SharePublishStatus.REVOKED
        published = revoked
    finally:
        if published is not None and published.status == SharePublishStatus.PUBLISHED:
            publisher.revoke(target=published)


@pytest.mark.skipif(os.getenv("WORKRECORDER_RUN_FEISHU_E2E") != "1", reason="Feishu live E2E is opt-in")
def test_feishu_live_publish_import_search_inspect_and_duplicate(tmp_path) -> None:
    app_id = os.getenv("WORKRECORDER_FEISHU_APP_ID")
    folder_token = os.getenv("WORKRECORDER_FEISHU_FOLDER_TOKEN")
    assert app_id, "WORKRECORDER_FEISHU_APP_ID is required"
    assert folder_token, "WORKRECORDER_FEISHU_FOLDER_TOKEN is required"
    api_base_url = os.getenv("WORKRECORDER_FEISHU_API_BASE_URL", "https://open.feishu.cn")
    clock = Clock()
    token_client = FeishuTokenClient(
        app_id=app_id,
        secret_store=EnvSecretStore(),
        api_base_url=api_base_url,
        clock=clock,
    )
    drive = FeishuDriveClient(token_client=token_client, folder_token=folder_token, api_base_url=api_base_url)
    now = datetime.now(UTC)
    share_id = f"shr_live_import_{now.strftime('%Y%m%d%H%M%S')}"
    package = SharePackageBuilder(
        clock=clock,
        signature_secret_provider=lambda: os.getenv("WORKRECORDER_FEISHU_APP_SECRET"),
    ).build(
        share_id=share_id,
        event_id="evt_live_import_original",
        revision=1,
        safe_context={
            "share_id": share_id,
            "event_id": "evt_live_import_original",
            "captured_at": now.isoformat(),
            "summary_card": {
                "event_id": "evt_live_import_original",
                "captured_at": now.isoformat(),
                "source": {
                    "title": "WorkRecorder 飞书导入 E2E",
                    "app_name": "Google Chrome",
                    "origin": "https://example.test",
                    "sanitized_url": "https://example.test/live-import?secret=hidden#hash",
                },
                "user_note": "live feishu import note",
                "selection_text": "live feishu import selection text",
                "selection_text_snippet": "live feishu import selection text",
                "hidden_artifacts": ["screenshot"],
            },
            "clean_page_text": "live feishu import clean page text",
            "hidden_materials": ["screenshot"],
        },
        screenshot_png=PNG_BYTES,
    )
    revision = ShareRevision(
        revision_id=f"shr_rev_{share_id}",
        share_id=share_id,
        event_id="evt_live_import_original",
        revision=1,
        snapshot_id=f"shr_snap_{share_id}",
        manifest=package.manifest,
        status=SharePublishStatus.PENDING,
        created_at=now,
    )
    publisher = FeishuSharePublisher(drive=drive, ids=IdFactory(), clock=clock)
    published: ExternalShareTarget | None = None
    try:
        published = publisher.publish(share_id=share_id, revision=revision, html=package.html)
        assert (
            published.status == SharePublishStatus.PUBLISHED
        ), f"{published.last_error_code}: {published.last_error_message}"
        assert published.provider_url

        settings = WorkRecorderSettings(
            database_path=tmp_path / "workrecorder.sqlite",
            artifact_staging_dir=tmp_path / "staging",
            artifact_vault_dir=tmp_path / "artifacts",
            install_secret="test-install-secret",
            disclosure_policy_path=None,
            feishu_app_id=app_id,
            feishu_folder_token=folder_token,
            feishu_api_base_url=api_base_url,
        )
        client = TestClient(DaemonAppFactory(settings).create())
        auth = client.post(
            "/v1/auth/tokens",
            headers={"x-workrecorder-install-secret": "test-install-secret"},
            json={
                "actor_id": "feishu-e2e",
                "display_name": "Feishu E2E",
                "scopes": ["import_share", "read_metadata", "read_text"],
            },
        ).json()
        headers = {"authorization": f"Bearer {auth['data']['access_token']}"}

        imported = client.post(
            "/v1/shares/import",
            headers=headers,
            json={"source": published.provider_url, "purpose": "feishu_live_import"},
        ).json()
        assert imported["ok"] is True, imported
        event_id = imported["data"]["imported_event_id"]
        assert event_id
        search = client.get("/v1/search?query=live%20feishu%20import&limit=5", headers=headers).json()
        assert search["ok"] is True
        assert any(item["event_id"] == event_id for item in search["data"]["results"])
        inspect = client.get(
            f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read"
            "&inspect_views=selection_text,clean_page_text,screenshot_ref",
            headers=headers,
        ).json()
        assert inspect["ok"] is True
        assert "secret=hidden" not in str(inspect["data"])
        duplicate = client.post(
            "/v1/shares/import",
            headers=headers,
            json={"source": published.provider_url, "purpose": "feishu_live_import_duplicate"},
        ).json()
        assert duplicate["ok"] is True
        assert duplicate["data"]["duplicate"] is True
        assert duplicate["data"]["imported_event_id"] == event_id

        revoked = publisher.revoke(target=published)
        assert revoked.status == SharePublishStatus.REVOKED
        published = revoked
    finally:
        if published is not None and published.status == SharePublishStatus.PUBLISHED:
            publisher.revoke(target=published)
