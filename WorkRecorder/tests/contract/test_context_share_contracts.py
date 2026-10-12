from __future__ import annotations

from datetime import UTC, datetime

from packages.context_share.package import SharePackageBuilder
from packages.contracts import (
    ActorRef,
    BoundingBox,
    CaptureStrategy,
    ContextEvent,
    ContextShare,
    ContextShareStatus,
    CoordinateSpace,
    EventStatus,
    EventType,
    ExternalShareTarget,
    IdentityProvider,
    SearchResultCard,
    SearchResultSource,
    ShareImportResponse,
    ShareImportStatus,
    SharePackageManifest,
    SharePublishStatus,
    ShareResolveResponse,
    ShareRevision,
    ShareScope,
    ShareSnapshot,
    ShareTargetKind,
    ShareVisibility,
    SourceBinding,
    SourceRef,
    SourceType,
    TriggerEnvelope,
    TriggerType,
    UserRef,
)
from packages.shared.time import Clock


def test_context_share_contracts_round_trip() -> None:
    now = datetime(2026, 5, 25, 8, 0, tzinfo=UTC)
    user = UserRef(
        user_id="user_local",
        display_name="Local User",
        identity_provider=IdentityProvider.LOCAL,
        tenant_key="tenant_hash",
    )
    share = ContextShare(
        share_id="shr_test",
        event_id="evt_test",
        created_by=user,
        user=user,
        status=ContextShareStatus.READY,
        scope=ShareScope.AGENT_CONTEXT_WITH_SCREENSHOT,
        target=ShareTargetKind.FEISHU_DRIVE,
        token_hash="a" * 64,
        created_at=now,
        updated_at=now,
    )
    snapshot = ShareSnapshot(
        snapshot_id="shr_snap_test",
        share_id=share.share_id,
        event_id=share.event_id,
        revision=1,
        payload_hash="b" * 64,
        payload_json={"summary_card": {"event_id": "evt_test"}},
        delivered_fields=("summary_card",),
        screenshot_artifact_id="art_screenshot",
        screenshot_sha256="c" * 64,
        created_at=now,
    )
    manifest = SharePackageManifest(
        share_id=share.share_id,
        event_id=share.event_id,
        revision=1,
        html_filename="workrecorder-share-shr_test-r1.html",
        json_filename="workrecorder-share-shr_test-r1.json",
        screenshot_filename="workrecorder-share-shr_test-r1.png",
        manifest_filename="workrecorder-share-shr_test-r1-manifest.json",
        html_sha256="d" * 64,
        json_sha256="e" * 64,
        manifest_sha256="f" * 64,
        screenshot_sha256="c" * 64,
        created_at=now,
    )
    revision = ShareRevision(
        revision_id="shr_rev_test",
        share_id=share.share_id,
        event_id=share.event_id,
        revision=1,
        snapshot_id=snapshot.snapshot_id,
        manifest=manifest,
        status=SharePublishStatus.PUBLISHED,
        created_at=now,
        published_at=now,
    )
    target = ExternalShareTarget(
        target_id="shr_tgt_test",
        share_id=share.share_id,
        revision_id=revision.revision_id,
        target=ShareTargetKind.FEISHU_DRIVE,
        status=SharePublishStatus.PUBLISHED,
        provider_file_token="file_token",
        provider_url="https://example.feishu.cn/file/boxcn",
        visibility=ShareVisibility.TENANT_READABLE,
        created_at=now,
        updated_at=now,
    )
    card = SearchResultCard(
        event_id=share.event_id,
        event_type=EventType.SCREEN_REGION_CAPTURED,
        captured_at=now,
        source=SearchResultSource(app_name="Preview", title="Contract.pdf"),
        selection_bbox=BoundingBox(x=0, y=0, width=100, height=80, coordinate_space=CoordinateSpace.SCREEN_PX),
        user_note="合同风险",
        selection_text_snippet="续费条款",
    )
    resolved = ShareResolveResponse(
        share=share,
        revision=revision,
        card=card,
        safe_context={"summary_card": card.model_dump(mode="json")},
        available_fields=("event_id", "selection_text", "screenshot_ref"),
        hidden_materials=("raw_dom",),
        screenshot_artifact_id="art_screenshot",
        external_url=target.provider_url,
        copyable_url=target.provider_url,
    )

    assert ContextShare.model_validate_json(share.model_dump_json()).user.user_id == "user_local"
    assert ShareSnapshot.model_validate_json(snapshot.model_dump_json()).screenshot_artifact_id == "art_screenshot"
    assert ShareRevision.model_validate_json(revision.model_dump_json()).status == SharePublishStatus.PUBLISHED
    assert (
        ExternalShareTarget.model_validate_json(target.model_dump_json()).visibility == ShareVisibility.TENANT_READABLE
    )
    assert ShareResolveResponse.model_validate_json(resolved.model_dump_json()).copyable_url == target.provider_url
    import_response = ShareImportResponse(status=ShareImportStatus.LINKED_EXISTING_EVENT, message="ok")
    assert (
        ShareImportResponse.model_validate_json(import_response.model_dump_json()).status
        == ShareImportStatus.LINKED_EXISTING_EVENT
    )


def test_context_event_old_payload_without_user_still_validates() -> None:
    now = datetime(2026, 5, 25, 8, 0, tzinfo=UTC)
    payload = {
        "event_id": "evt_legacy",
        "event_type": EventType.SCREEN_REGION_CAPTURED.value,
        "trigger": TriggerEnvelope(
            trigger_id="trg_legacy",
            trigger_type=TriggerType.MANUAL_OS_REGION_HOTKEY,
            capture_strategy=CaptureStrategy.OS_REGION,
            actor=ActorRef(actor_id="legacy_user", display_name="Legacy User"),
            occurred_at=now,
        ).model_dump(mode="json"),
        "source_binding": SourceBinding(
            binding_id="src_legacy",
            source_ref=SourceRef(source_type=SourceType.DESKTOP_WINDOW, title="Legacy Window", app_name="Finder"),
            confidence=0.8,
            resolved_at=now,
        ).model_dump(mode="json"),
        "status": EventStatus.AGENT_READY.value,
        "intent_text": None,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    event = ContextEvent.model_validate(payload)

    assert event.user is None
    assert event.trigger.actor.actor_id == "legacy_user"


def test_context_share_api_golden_shapes_are_stable() -> None:
    now = datetime(2026, 5, 25, 8, 0, tzinfo=UTC)
    import_response = ShareImportResponse(
        imported_event_id="evt_imported",
        share_id="shr_imported",
        status=ShareImportStatus.IMPORTED,
        message="上下文已导入本地，可以搜索和查看。",
        duplicate=False,
        revision=1,
    )
    resolve_response = ShareResolveResponse(
        share=ContextShare(
            share_id="shr_imported",
            event_id="evt_imported",
            created_by=UserRef(
                user_id="user_local", display_name="Local User", identity_provider=IdentityProvider.LOCAL
            ),
            user=UserRef(user_id="user_local", display_name="Local User", identity_provider=IdentityProvider.LOCAL),
            status=ContextShareStatus.READY,
            scope=ShareScope.AGENT_CONTEXT_WITH_SCREENSHOT,
            target=ShareTargetKind.FEISHU_DRIVE,
            token_hash="a" * 64,
            created_at=now,
            updated_at=now,
        ),
        card=SearchResultCard(
            event_id="evt_imported",
            event_type=EventType.IMPORTED_CONTEXT,
            captured_at=now,
            source=SearchResultSource(app_name="Chrome", title="Imported"),
        ),
        safe_context={"summary_card": {"event_id": "evt_imported", "selection_text": "框内文本"}},
        available_fields=("summary_card", "screenshot_ref"),
        hidden_materials=("raw_dom", "a11y_tree"),
        screenshot_artifact_id="art_screen",
        external_url="https://example.feishu.cn/file/SyntheticFileToken00000001",
        copyable_url="https://example.feishu.cn/file/SyntheticFileToken00000001",
    )

    assert import_response.model_dump(mode="json") == {
        "imported_event_id": "evt_imported",
        "share_id": "shr_imported",
        "status": "imported",
        "message": "上下文已导入本地，可以搜索和查看。",
        "duplicate": False,
        "revision": 1,
        "source_kind": "unknown",
    }
    resolve_payload = resolve_response.model_dump(mode="json")
    assert sorted(resolve_payload) == [
        "available_fields",
        "card",
        "copyable_url",
        "external_url",
        "hidden_materials",
        "revision",
        "safe_context",
        "screenshot_artifact_id",
        "share",
    ]
    assert resolve_payload["card"]["source"]["title"] == "Imported"


def test_share_package_html_embeds_import_manifest_and_safe_context() -> None:
    package = SharePackageBuilder(clock=Clock()).build(
        share_id="shr_contract_html",
        event_id="evt_contract_html",
        revision=7,
        safe_context={
            "share_id": "shr_contract_html",
            "event_id": "evt_contract_html",
            "summary_card": {
                "event_id": "evt_contract_html",
                "source": {"title": "Contract HTML", "app_name": "Chrome"},
                "selection_text": "可导入字段",
            },
        },
        screenshot_png=None,
    )
    html = package.html.decode("utf-8")

    assert 'id="workrecorder-import-manifest"' in html
    assert 'id="workrecorder-safe-context"' in html
    assert '"schema_version": "workrecorder_share_html_v1"' in html
    assert '"json_sha256"' in html
    assert "可导入字段" in html
