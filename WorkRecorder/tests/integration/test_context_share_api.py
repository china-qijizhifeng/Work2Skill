from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.context_share.importers import FeishuDriveShareImporter, SharePackageParser
from packages.context_share.package import SharePackageBuilder
from packages.contracts import (
    AccessScope,
    ActorRef,
    Artifact,
    ArtifactIngestState,
    ArtifactRole,
    ArtifactType,
    ContextEventCreate,
    ContextShareCreateRequest,
    ContextShareStatus,
    EventStatus,
    EvidenceKind,
    RedactionState,
)
from packages.integrations.feishu import FeishuIntegrationError
from services.context_daemon.container import DaemonContainer

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00"
    b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)
TEST_SHARE_SECRET = "workrecorder-test-share-signature"


def _share_builder(clock) -> SharePackageBuilder:
    return SharePackageBuilder(clock=clock, signature_secret_provider=lambda: TEST_SHARE_SECRET)


def _share_parser() -> SharePackageParser:
    return SharePackageParser(signature_secret_provider=lambda: TEST_SHARE_SECRET)


def test_share_create_resolve_and_import_are_safe_and_audited(
    client: TestClient,
    event_create: ContextEventCreate,
) -> None:
    container = cast(DaemonContainer, cast(FastAPI, client.app).state.container)
    event = container.events.save(container.events.build(event_create))
    screenshot = _artifact(
        container,
        event.event_id,
        ArtifactType.SCREENSHOT,
        ArtifactRole.VISUAL_EVIDENCE,
        PNG_BYTES,
    )
    _artifact(
        container,
        event.event_id,
        ArtifactType.A11Y_SELECTION_TEXT,
        ArtifactRole.SELECTION_TEXT,
        "框内文本：默认分享摘要".encode("utf-8"),
        evidence_kind=EvidenceKind.SELECTION_TEXT,
        allowed_scopes=(AccessScope.READ_METADATA, AccessScope.READ_TEXT),
        ingest_state=ArtifactIngestState.DLP_PASSED,
    )
    full_dom = _artifact(
        container,
        event.event_id,
        ArtifactType.BROWSER_FULL_DOM,
        ArtifactRole.FULL_DOM,
        b"<html><input type=password value=secret></html>",
    )
    headers = {
        "authorization": f"Bearer {_token(client, ('create_share', 'read_text', 'read_share', 'import_share', 'revoke_share'))}"
    }

    create = client.post(
        "/v1/shares",
        headers=headers,
        json={"event_id": event.event_id, "purpose": "test_share"},
    )
    create_payload = create.json()
    assert create.status_code == 200
    assert create_payload["ok"] is True
    create_data = create_payload["data"]
    share_id = create_data["share"]["share_id"]
    assert create_data["share"]["status"] == "local_ready"
    assert create_data["external_url"] is None
    assert create_data["copyable_url"] is None
    assert create_data["screenshot_artifact_id"] == screenshot.artifact_id
    assert "screenshot_ref" in create_data["available_fields"]
    assert "screenshot_png" not in create_data["available_fields"]

    resolve = client.post(
        "/v1/shares/resolve",
        headers=headers,
        json={"source": f"workrecorder://share/{share_id}", "purpose": "user_shared_context"},
    )
    resolve_payload = resolve.json()
    assert resolve.status_code == 200
    assert resolve_payload["ok"] is True
    assert resolve_payload["retrieval_call_id"].startswith("ret_")
    run_id = resolve_payload["agent_run_id"]
    safe_context = resolve_payload["data"]["safe_context"]
    assert safe_context["summary_card"]["selection_text"] == "框内文本：默认分享摘要"
    serialized = json.dumps(safe_context, ensure_ascii=False)
    assert full_dom.artifact_id not in serialized
    assert "local-artifact://" not in serialized
    assert "value=secret" not in serialized
    assert "raw_artifact_refs" not in safe_context
    replay = client.get(f"/v1/agent-runs/{run_id}/replay", headers=headers).json()
    replay_text = json.dumps(replay["data"], ensure_ascii=False, sort_keys=True)
    assert replay["ok"] is True
    assert "share_resolve" in {call["kind"] for call in replay["data"]["retrieval_calls"]}
    assert "框内文本：默认分享摘要" in replay_text
    assert "value=secret" not in replay_text

    imported = client.post(
        "/v1/shares/import",
        headers=headers,
        json={"source": share_id, "purpose": "test_import"},
    )
    imported_payload = imported.json()
    assert imported.status_code == 200
    assert imported_payload["ok"] is True
    assert imported_payload["data"]["imported_event_id"] == event.event_id
    assert imported_payload["data"]["status"] == "linked_existing_event"

    sync = client.post(f"/v1/shares/{share_id}/sync", headers=headers)
    sync_payload = sync.json()
    assert sync.status_code == 200
    assert sync_payload["ok"] is True
    assert sync_payload["data"]["revision"]["revision"] == 2
    jobs = client.get(f"/v1/shares/{share_id}/jobs", headers=headers).json()
    assert jobs["ok"] is True
    assert len(jobs["data"]["jobs"]) >= 2

    listed = client.get("/v1/shares?user=Test%20User", headers=headers).json()
    assert listed["ok"] is True
    assert any(item["share_id"] == share_id for item in listed["data"]["shares"])

    revoked = client.post(f"/v1/shares/{share_id}/revoke", headers=headers).json()
    assert revoked["ok"] is True
    denied = client.post(
        "/v1/shares/resolve",
        headers=headers,
        json={"source": share_id, "purpose": "after_revoke"},
    )
    assert denied.status_code == 404


def test_feishu_share_url_import_creates_searchable_imported_event_without_duplicates(
    client: TestClient,
) -> None:
    class FakeDrive:
        def __init__(self, html: bytes) -> None:
            self.html = html
            self.tokens: list[str] = []

        def download_file(self, *, file_token: str) -> bytes:
            self.tokens.append(file_token)
            return self.html

    container = cast(DaemonContainer, cast(FastAPI, client.app).state.container)
    safe_context = {
        "share_id": "shr_external_import",
        "event_id": "evt_original_external",
        "captured_at": "2026-05-25T10:00:00+00:00",
        "summary_card": {
            "event_id": "evt_original_external",
            "event_type": "webpage.selection.captured",
            "captured_at": "2026-05-25T10:00:00+00:00",
            "source": {
                "title": "飞书导入网页",
                "app_name": "Google Chrome",
                "origin": "https://example.test",
                "sanitized_url": "https://example.test/imported?secret=1#frag",
            },
            "user_note": "同事分享的导入测试",
            "selection_text": "飞书链接导入后应该可以搜索",
            "selection_text_snippet": "飞书链接导入后应该可以搜索",
            "hidden_artifacts": ["screenshot"],
        },
        "clean_page_text": "这是从飞书分享包导入的网页正文。",
        "hidden_materials": ["screenshot"],
    }
    package = _share_builder(container.clock).build(
        share_id="shr_external_import",
        event_id="evt_original_external",
        revision=1,
        safe_context=safe_context,
        screenshot_png=PNG_BYTES,
    )
    fake_drive = FakeDrive(package.html)
    container.context_shares.feishu_importer = FeishuDriveShareImporter(
        drive=fake_drive,
        parser=_share_parser(),
    )
    headers = {"authorization": f"Bearer {_token(client, ('import_share', 'read_metadata', 'read_text'))}"}
    source = "https://example.feishu.cn/file/SyntheticFileToken00000001?from=copy"

    imported = client.post(
        "/v1/shares/import",
        headers=headers,
        json={"source": source, "purpose": "feishu_import_e2e"},
    )
    imported_payload = imported.json()

    assert imported.status_code == 200
    assert imported_payload["ok"] is True
    data = imported_payload["data"]
    assert data["status"] == "imported"
    assert data["source_kind"] == "feishu_drive_url"
    assert data["duplicate"] is False
    assert data["imported_event_id"].startswith("evt_")
    assert fake_drive.tokens == ["SyntheticFileToken00000001"]
    event = container.repositories.events.get(data["imported_event_id"])
    assert event is not None
    assert event.source_binding.source_ref.source_type.value == "imported_context"
    assert event.source_binding.source_ref.url == "https://example.test/imported"
    artifacts = container.repositories.artifacts.list_for_event(event.event_id)
    assert any(artifact.artifact_type == ArtifactType.SCREENSHOT for artifact in artifacts)
    assert any(artifact.artifact_type == ArtifactType.CLEAN_PAGE_TEXT for artifact in artifacts)

    search = client.get(
        "/v1/search?query=%E9%A3%9E%E4%B9%A6%E9%93%BE%E6%8E%A5%E5%AF%BC%E5%85%A5&limit=5",
        headers=headers,
    ).json()
    assert search["ok"] is True
    assert any(result["event_id"] == event.event_id for result in search["data"]["results"])
    inspect = client.get(
        f"/v1/events/{event.event_id}?view=event_inspect&purpose=agent_deep_read"
        "&inspect_views=selection_text,clean_page_text,screenshot_ref",
        headers=headers,
    ).json()
    assert inspect["ok"] is True
    assert "飞书链接导入后应该可以搜索" in str(inspect["data"])
    assert "这是从飞书分享包导入的网页正文" in str(inspect["data"])
    assert inspect["data"]["raw_artifacts"][0]["artifact_type"] == "screenshot"
    assert "secret=1" not in str(inspect["data"])

    event_count = len(container.repositories.events.list(limit=100))
    artifact_count = len(container.repositories.artifacts.list_for_event(event.event_id))
    index_count = _index_count(container, event.event_id)
    duplicate = client.post(
        "/v1/shares/import",
        headers=headers,
        json={"source": source, "purpose": "feishu_import_duplicate"},
    ).json()
    assert duplicate["ok"] is True
    assert duplicate["data"]["status"] == "linked_existing_event"
    assert duplicate["data"]["duplicate"] is True
    assert duplicate["data"]["imported_event_id"] == event.event_id
    assert len(container.repositories.events.list(limit=100)) == event_count
    assert len(container.repositories.artifacts.list_for_event(event.event_id)) == artifact_count
    assert _index_count(container, event.event_id) == index_count


def test_feishu_share_url_import_updates_newer_revision_without_duplicate_event(client: TestClient) -> None:
    class MutableDrive:
        def __init__(self, html: bytes) -> None:
            self.html = html

        def download_file(self, *, file_token: str) -> bytes:
            del file_token
            return self.html

    container = cast(DaemonContainer, cast(FastAPI, client.app).state.container)
    safe_context_v1 = {
        "share_id": "shr_external_revision",
        "event_id": "evt_original_revision",
        "captured_at": "2026-05-25T10:00:00+00:00",
        "summary_card": {
            "event_id": "evt_original_revision",
            "captured_at": "2026-05-25T10:00:00+00:00",
            "source": {"title": "Revision test", "app_name": "Google Chrome"},
            "selection_text": "旧版独有旧词",
        },
        "clean_page_text": "旧版页面旧词",
    }
    builder = _share_builder(container.clock)
    package_v1 = builder.build(
        share_id="shr_external_revision",
        event_id="evt_original_revision",
        revision=1,
        safe_context=safe_context_v1,
        screenshot_png=PNG_BYTES,
    )
    drive = MutableDrive(package_v1.html)
    container.context_shares.feishu_importer = FeishuDriveShareImporter(drive=drive, parser=_share_parser())
    headers = {"authorization": f"Bearer {_token(client, ('import_share', 'read_metadata', 'read_text'))}"}
    source_v1 = "https://example.feishu.cn/file/SyntheticFileToken00000001"
    source_v2 = "https://example.feishu.cn/file/SyntheticFileToken00000002"

    first = client.post("/v1/shares/import", headers=headers, json={"source": source_v1}).json()
    event_id = first["data"]["imported_event_id"]
    event_count = len(container.repositories.events.list(limit=100))

    safe_context_v2 = {
        **safe_context_v1,
        "summary_card": {
            **safe_context_v1["summary_card"],
            "selection_text": "新版独有新词",
        },
        "clean_page_text": "新版页面新词可以搜索",
    }
    drive.html = builder.build(
        share_id="shr_external_revision",
        event_id="evt_original_revision",
        revision=2,
        safe_context=safe_context_v2,
        screenshot_png=PNG_BYTES,
    ).html

    second = client.post("/v1/shares/import", headers=headers, json={"source": source_v2}).json()

    assert second["ok"] is True
    assert second["data"]["status"] == "updated_existing_event"
    assert second["data"]["imported_event_id"] == event_id
    assert second["data"]["revision"] == 2
    assert len(container.repositories.events.list(limit=100)) == event_count
    share = container.repositories.shares.get_share("shr_external_revision")
    assert share is not None
    latest = container.repositories.shares.latest_revision(share.share_id)
    assert latest is not None
    assert latest.revision == 2
    search = client.get(
        "/v1/search?query=%E6%96%B0%E8%AF%8D&limit=5",
        headers=headers,
    ).json()
    assert any(result["event_id"] == event_id for result in search["data"]["results"])
    stale_search = client.get(
        "/v1/search?query=%E6%97%A7%E8%AF%8D&limit=5",
        headers=headers,
    ).json()
    assert not any(result["event_id"] == event_id for result in stale_search["data"]["results"])
    inspect = client.get(
        f"/v1/events/{event_id}?view=event_inspect&purpose=agent_deep_read"
        "&inspect_views=selection_text,clean_page_text,screenshot_ref",
        headers=headers,
    ).json()
    inspect_text = json.dumps(inspect["data"], ensure_ascii=False)
    assert inspect["ok"] is True
    assert "新版独有新词" in inspect_text
    assert "新版页面新词可以搜索" in inspect_text
    assert "旧版独有旧词" not in inspect_text
    assert "旧版页面旧词" not in inspect_text
    artifacts = container.repositories.artifacts.list_for_event(event_id)
    assert {artifact.metadata.get("revision") for artifact in artifacts} == {2}


def test_feishu_share_url_import_rejects_same_url_identity_rebind(client: TestClient) -> None:
    class MutableDrive:
        def __init__(self, html: bytes) -> None:
            self.html = html

        def download_file(self, *, file_token: str) -> bytes:
            del file_token
            return self.html

    container = cast(DaemonContainer, cast(FastAPI, client.app).state.container)
    builder = _share_builder(container.clock)
    source = "https://example.feishu.cn/file/SyntheticFileToken00000001"
    drive = MutableDrive(
        builder.build(
            share_id="shr_url_rebind",
            event_id="evt_url_rebind_original",
            revision=1,
            safe_context={
                "share_id": "shr_url_rebind",
                "event_id": "evt_url_rebind_original",
                "summary_card": {
                    "event_id": "evt_url_rebind_original",
                    "captured_at": "2026-05-25T10:00:00+00:00",
                    "source": {"title": "Original", "app_name": "Chrome"},
                    "selection_text": "original safe text",
                },
            },
            screenshot_png=PNG_BYTES,
        ).html
    )
    container.context_shares.feishu_importer = FeishuDriveShareImporter(drive=drive, parser=_share_parser())
    headers = {"authorization": f"Bearer {_token(client, ('import_share', 'read_metadata', 'read_text'))}"}
    first = client.post("/v1/shares/import", headers=headers, json={"source": source}).json()
    event_id = first["data"]["imported_event_id"]
    drive.html = builder.build(
        share_id="shr_url_rebind",
        event_id="evt_url_rebind_attacker",
        revision=2,
        safe_context={
            "share_id": "shr_url_rebind",
            "event_id": "evt_url_rebind_attacker",
            "summary_card": {
                "event_id": "evt_url_rebind_attacker",
                "captured_at": "2026-05-25T10:00:00+00:00",
                "source": {"title": "Attacker", "app_name": "Chrome"},
                "selection_text": "malicious replacement",
            },
        },
        screenshot_png=PNG_BYTES,
    ).html

    second = client.post("/v1/shares/import", headers=headers, json={"source": source})

    assert second.status_code == 422
    payload = second.json()
    assert payload["error"]["details"]["status"] == "invalid_package"
    search = client.get("/v1/search?query=malicious%20replacement&limit=5", headers=headers).json()
    assert all(result["event_id"] != event_id for result in search["data"]["results"])


def test_feishu_share_url_import_deduplicates_same_package_hash_across_urls(client: TestClient) -> None:
    class FakeDrive:
        def __init__(self, html: bytes) -> None:
            self.html = html

        def download_file(self, *, file_token: str) -> bytes:
            del file_token
            return self.html

    container = cast(DaemonContainer, cast(FastAPI, client.app).state.container)
    package = _share_builder(container.clock).build(
        share_id="shr_external_hash_dup",
        event_id="evt_original_hash_dup",
        revision=1,
        safe_context={
            "share_id": "shr_external_hash_dup",
            "event_id": "evt_original_hash_dup",
            "summary_card": {
                "event_id": "evt_original_hash_dup",
                "source": {"title": "Hash duplicate", "app_name": "Chrome"},
                "selection_text": "同一 HTML 不应重复导入",
            },
        },
        screenshot_png=PNG_BYTES,
    )
    container.context_shares.feishu_importer = FeishuDriveShareImporter(
        drive=FakeDrive(package.html),
        parser=_share_parser(),
    )
    headers = {"authorization": f"Bearer {_token(client, ('import_share',))}"}
    first = client.post(
        "/v1/shares/import",
        headers=headers,
        json={"source": "https://example.feishu.cn/file/SyntheticFileToken00000001"},
    ).json()
    event_count = len(container.repositories.events.list(limit=100))

    second = client.post(
        "/v1/shares/import",
        headers=headers,
        json={"source": "https://example.feishu.cn/file/SyntheticFileToken00000002"},
    ).json()

    assert second["ok"] is True
    assert second["data"]["duplicate"] is True
    assert second["data"]["imported_event_id"] == first["data"]["imported_event_id"]
    assert len(container.repositories.events.list(limit=100)) == event_count


def test_feishu_import_permission_error_maps_to_permission_required(client: TestClient) -> None:
    class ForbiddenDrive:
        def download_file(self, *, file_token: str) -> bytes:
            del file_token
            raise FeishuIntegrationError("forbidden", code="feishu_99991672")

    container = cast(DaemonContainer, cast(FastAPI, client.app).state.container)
    before = len(container.repositories.events.list(limit=100))
    container.context_shares.feishu_importer = FeishuDriveShareImporter(
        drive=ForbiddenDrive(),
        parser=_share_parser(),
    )
    headers = {"authorization": f"Bearer {_token(client, ('import_share',))}"}

    response = client.post(
        "/v1/shares/import",
        headers=headers,
        json={"source": "https://example.feishu.cn/file/SyntheticFileToken00000001"},
    )

    assert response.status_code == 403
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["details"]["status"] == "permission_required"
    assert len(container.repositories.events.list(limit=100)) == before


def test_import_cannot_rebind_existing_share_with_higher_revision(
    client: TestClient,
    event_create: ContextEventCreate,
) -> None:
    class FakeDrive:
        def __init__(self, html: bytes) -> None:
            self.html = html

        def download_file(self, *, file_token: str) -> bytes:
            del file_token
            return self.html

    container = cast(DaemonContainer, cast(FastAPI, client.app).state.container)
    event = container.events.save(container.events.build(event_create))
    _artifact(container, event.event_id, ArtifactType.SCREENSHOT, ArtifactRole.VISUAL_EVIDENCE, PNG_BYTES)
    created = container.context_shares.create(
        request=ContextShareCreateRequest(event_id=event.event_id),
        actor=ActorRef(actor_id="test-cli", display_name="Test CLI"),
    )
    safe_context = {
        "share_id": created.share.share_id,
        "event_id": "evt_attacker_original",
        "captured_at": "2026-05-25T10:00:00+00:00",
        "summary_card": {
            "event_id": "evt_attacker_original",
            "captured_at": "2026-05-25T10:00:00+00:00",
            "source": {"title": "Attacker", "app_name": "Chrome"},
            "selection_text": "malicious import",
        },
    }
    package = _share_builder(container.clock).build(
        share_id=created.share.share_id,
        event_id="evt_attacker_original",
        revision=99,
        safe_context=safe_context,
        screenshot_png=PNG_BYTES,
    )
    container.context_shares.feishu_importer = FeishuDriveShareImporter(
        drive=FakeDrive(package.html),
        parser=_share_parser(),
    )
    headers = {"authorization": f"Bearer {_token(client, ('import_share',))}"}

    response = client.post(
        "/v1/shares/import",
        headers=headers,
        json={"source": "https://example.feishu.cn/file/SyntheticFileToken00000001"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["details"]["status"] == "invalid_package"
    share_after = container.repositories.shares.get_share(created.share.share_id)
    assert share_after is not None
    assert share_after.event_id == created.share.event_id


def test_invalid_feishu_import_returns_error_and_does_not_create_event(client: TestClient) -> None:
    class FakeDrive:
        def download_file(self, *, file_token: str) -> bytes:
            del file_token
            return b"<html><body>not a WorkRecorder share</body></html>"

    container = cast(DaemonContainer, cast(FastAPI, client.app).state.container)
    before = len(container.repositories.events.list(limit=100))
    container.context_shares.feishu_importer = FeishuDriveShareImporter(
        drive=FakeDrive(),
        parser=_share_parser(),
    )
    headers = {"authorization": f"Bearer {_token(client, ('import_share',))}"}

    response = client.post(
        "/v1/shares/import",
        headers=headers,
        json={"source": "https://example.feishu.cn/file/SyntheticFileToken00000001"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["details"]["status"] == "invalid_package"
    assert len(container.repositories.events.list(limit=100)) == before


def test_share_rejects_deleted_and_expired_events(
    client: TestClient,
    event_create: ContextEventCreate,
) -> None:
    container = cast(DaemonContainer, cast(FastAPI, client.app).state.container)
    event = container.events.save(container.events.build(event_create))
    deleted = event.model_copy(update={"status": EventStatus.DELETED, "updated_at": datetime.now(UTC)})
    container.repositories.events.mark_deleted(event.event_id, deleted_payload=deleted)
    headers = {"authorization": f"Bearer {_token(client, ('create_share', 'read_text', 'read_share'))}"}

    create = client.post(
        "/v1/shares",
        headers=headers,
        json={"event_id": event.event_id, "purpose": "deleted_event"},
    )

    assert create.status_code == 404

    event2 = container.events.save(
        container.events.build(event_create.model_copy(update={"intent_text": "not expired"}))
    )
    _artifact(container, event2.event_id, ArtifactType.SCREENSHOT, ArtifactRole.VISUAL_EVIDENCE, PNG_BYTES)
    created = client.post(
        "/v1/shares",
        headers=headers,
        json={"event_id": event2.event_id, "purpose": "expire_me"},
    ).json()
    share_id = created["data"]["share"]["share_id"]
    share = container.repositories.shares.get_share(share_id)
    assert share is not None
    expired = share.model_copy(
        update={"status": ContextShareStatus.READY, "expires_at": datetime(2000, 1, 1, tzinfo=UTC)}
    )
    container.repositories.shares.save_share(expired)

    resolve = client.post(
        "/v1/shares/resolve",
        headers=headers,
        json={"source": share_id, "purpose": "after_expire"},
    )

    assert resolve.status_code == 404


def test_revoked_local_share_import_returns_stable_json_error(
    client: TestClient,
    event_create: ContextEventCreate,
) -> None:
    container = cast(DaemonContainer, cast(FastAPI, client.app).state.container)
    event = container.events.save(container.events.build(event_create))
    _artifact(container, event.event_id, ArtifactType.SCREENSHOT, ArtifactRole.VISUAL_EVIDENCE, PNG_BYTES)
    headers = {
        "authorization": f"Bearer {_token(client, ('create_share', 'read_text', 'read_share', 'import_share', 'revoke_share'))}"
    }
    created = client.post(
        "/v1/shares",
        headers=headers,
        json={"event_id": event.event_id, "purpose": "revoked_local_import"},
    ).json()
    share_id = created["data"]["share"]["share_id"]
    revoked = client.post(f"/v1/shares/{share_id}/revoke", headers=headers)
    assert revoked.status_code == 200

    imported = client.post(
        "/v1/shares/import",
        headers=headers,
        json={"source": share_id, "purpose": "after_revoke_import"},
    )

    assert imported.status_code == 422
    payload = imported.json()
    assert payload["ok"] is False
    assert payload["error"]["details"]["status"] == "unsupported_source"


def test_share_create_and_sync_require_read_text_scope(
    client: TestClient,
    event_create: ContextEventCreate,
) -> None:
    container = cast(DaemonContainer, cast(FastAPI, client.app).state.container)
    event = container.events.save(container.events.build(event_create))
    _artifact(container, event.event_id, ArtifactType.SCREENSHOT, ArtifactRole.VISUAL_EVIDENCE, PNG_BYTES)
    create_only_headers = {"authorization": f"Bearer {_token(client, ('create_share',))}"}

    denied_create = client.post(
        "/v1/shares",
        headers=create_only_headers,
        json={"event_id": event.event_id, "purpose": "missing_read_text"},
    )

    assert denied_create.status_code == 403

    allowed_headers = {"authorization": f"Bearer {_token(client, ('create_share', 'read_text'))}"}
    created = client.post(
        "/v1/shares",
        headers=allowed_headers,
        json={"event_id": event.event_id, "purpose": "allowed"},
    ).json()
    share_id = created["data"]["share"]["share_id"]

    denied_sync = client.post(f"/v1/shares/{share_id}/sync", headers=create_only_headers)

    assert denied_sync.status_code == 403


def _token(client: TestClient, scopes: tuple[str, ...]) -> str:
    response = client.post(
        "/v1/auth/tokens",
        headers={"x-workrecorder-install-secret": "test-install-secret"},
        json={"actor_id": "test-cli", "display_name": "Test CLI", "scopes": list(scopes)},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    return str(payload["data"]["access_token"])


def _index_count(container: DaemonContainer, event_id: str) -> int:
    with container.repositories.shares.database.transaction() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM keyword_index_documents WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    return int(row["count"]) if row is not None else 0


def _artifact(
    container: DaemonContainer,
    event_id: str,
    artifact_type: ArtifactType,
    role: ArtifactRole,
    content: bytes,
    *,
    evidence_kind: EvidenceKind | None = None,
    allowed_scopes: tuple[AccessScope, ...] = (AccessScope.READ_METADATA,),
    ingest_state: ArtifactIngestState = ArtifactIngestState.QUARANTINED,
) -> Artifact:
    artifact_id = container.ids.new("art")
    promoted = container.vault.write_generated(
        artifact_id=artifact_id,
        created_at=datetime.now(UTC),
        content=content,
        suffix=".png" if artifact_type == ArtifactType.SCREENSHOT else ".txt",
    )
    artifact = Artifact(
        artifact_id=artifact_id,
        event_id=event_id,
        artifact_type=artifact_type,
        role=role,
        storage_uri=promoted.storage_uri,
        redaction_state=RedactionState.REDACTED,
        allowed_scopes=allowed_scopes,
        content_type="image/png" if artifact_type == ArtifactType.SCREENSHOT else "text/plain",
        byte_size=promoted.byte_size,
        sha256=promoted.sha256,
        ingest_state=ingest_state,
        metadata={"confidence": 0.92},
        created_at=datetime.now(UTC),
        evidence_id=container.ids.new("evd"),
        provider_key="system.test",
        evidence_kind=evidence_kind,
    )
    return container.repositories.artifacts.save(artifact)
