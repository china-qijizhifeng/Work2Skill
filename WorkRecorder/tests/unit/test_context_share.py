from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.context_share.importers import ShareImportError, SharePackageParser, ShareSourceClassifier
from packages.context_share.package import SharePackageBuilder, sign_share_import_manifest
from packages.context_share.ports import SharePublisherRegistry
from packages.contracts import (
    AccessScope,
    ActorRef,
    Artifact,
    ArtifactIngestState,
    ArtifactRole,
    ArtifactType,
    ContextShareCreateRequest,
    ContextShareStatus,
    EvidenceKind,
    ExternalShareTarget,
    RedactionState,
    ShareImportSourceKind,
    SharePublishStatus,
    ShareRevision,
    ShareTargetKind,
)
from packages.shared.time import Clock
from services.context_daemon.container import DaemonContainer
from services.context_daemon.safe_metadata import safe_public_payload

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00"
    b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)
TEST_SHARE_SECRET = "workrecorder-test-share-signature"


def _signed_builder() -> SharePackageBuilder:
    return SharePackageBuilder(clock=Clock(), signature_secret_provider=lambda: TEST_SHARE_SECRET)


def _signed_parser() -> SharePackageParser:
    return SharePackageParser(signature_secret_provider=lambda: TEST_SHARE_SECRET)


def test_context_share_freezes_agent_context_and_screenshot_without_raw_leaks(
    client: TestClient,
    event_create,
) -> None:
    container = cast(DaemonContainer, cast(FastAPI, client.app).state.container)
    event = container.events.save(container.events.build(event_create))
    screenshot = _artifact(container, event.event_id, ArtifactType.SCREENSHOT, ArtifactRole.VISUAL_EVIDENCE, PNG_BYTES)
    selection = _artifact(
        container,
        event.event_id,
        ArtifactType.A11Y_SELECTION_TEXT,
        ArtifactRole.SELECTION_TEXT,
        "框内文本：合同续费风险".encode("utf-8"),
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

    result = container.context_shares.create(
        request=ContextShareCreateRequest(event_id=event.event_id),
        actor=ActorRef(actor_id="test-cli", display_name="Test CLI"),
    )
    snapshot = container.repositories.shares.latest_snapshot(result.share.share_id)

    assert result.share.status == ContextShareStatus.LOCAL_READY
    assert result.external_url is None
    assert snapshot is not None
    assert snapshot.screenshot_artifact_id == screenshot.artifact_id
    available = snapshot.payload_json["available_fields"]
    summary_card = snapshot.payload_json["summary_card"]
    assert isinstance(available, list)
    assert isinstance(summary_card, dict)
    assert "selection_text" in available
    assert summary_card["selection_text"] == "框内文本：合同续费风险"
    serialized = json.dumps(snapshot.payload_json, ensure_ascii=False)
    assert selection.artifact_id in serialized
    assert full_dom.artifact_id not in serialized
    assert "local-artifact://" not in serialized
    assert "value=secret" not in serialized
    public = json.dumps(safe_public_payload(result), ensure_ascii=False)
    assert result.share.token_hash not in public
    assert "token_hash" not in public


def test_share_package_embeds_screenshot_but_not_raw_secrets() -> None:
    package = _signed_builder().build(
        share_id="shr_pkg",
        event_id="evt_pkg",
        revision=1,
        safe_context={
            "summary_card": {
                "event_id": "evt_pkg",
                "source": {"title": "Example", "app_name": "Chrome", "sanitized_url": "https://example.test/path"},
                "selection_text": "框内文本",
                "user_note": "用户备注",
            },
            "clean_page_text": "Agent 可读正文",
            "hidden_materials": ["full_dom"],
            "policy": {"raw_dom_uploaded": False},
        },
        screenshot_png=PNG_BYTES,
    )

    html = package.html.decode("utf-8")

    assert "data:image/png;base64," in html
    assert "框内文本" in html
    assert "Agent 可读正文" in html
    assert "value=secret" not in html
    assert "local-artifact://" not in html
    assert package.manifest.screenshot_sha256 is not None


def test_share_package_is_self_contained_for_import() -> None:
    package = _signed_builder().build(
        share_id="shr_import_pkg",
        event_id="evt_import_pkg",
        revision=3,
        safe_context={
            "share_id": "shr_import_pkg",
            "event_id": "evt_import_pkg",
            "summary_card": {
                "event_id": "evt_import_pkg",
                "captured_at": "2026-05-25T10:00:00+00:00",
                "source": {"title": "Imported Context", "app_name": "Chrome"},
                "selection_text": "可导入框内文本",
                "user_note": "导入测试",
            },
        },
        screenshot_png=PNG_BYTES,
    )

    parsed = _signed_parser().parse_html(
        html_bytes=package.html,
        source_kind=ShareImportSourceKind.FEISHU_DRIVE_URL,
    )

    assert parsed.share_id == "shr_import_pkg"
    assert parsed.original_event_id == "evt_import_pkg"
    assert parsed.revision == 3
    summary_card = parsed.safe_context["summary_card"]
    assert isinstance(summary_card, dict)
    assert summary_card["selection_text"] == "可导入框内文本"
    assert parsed.screenshot_png == PNG_BYTES


def test_share_package_parser_rejects_unsigned_feishu_package() -> None:
    package = SharePackageBuilder(clock=Clock()).build(
        share_id="shr_unsigned",
        event_id="evt_unsigned",
        revision=1,
        safe_context={
            "share_id": "shr_unsigned",
            "event_id": "evt_unsigned",
            "summary_card": {"event_id": "evt_unsigned", "source": {"title": "Unsigned"}},
        },
        screenshot_png=None,
    )

    try:
        _signed_parser().parse_html(
            html_bytes=package.html,
            source_kind=ShareImportSourceKind.FEISHU_DRIVE_URL,
        )
    except ShareImportError as exc:
        assert exc.code == "signature_missing"
    else:  # pragma: no cover
        raise AssertionError("expected unsigned Feishu package to be rejected")


def test_share_package_parser_rejects_readable_evidence_raw_container() -> None:
    package = _signed_builder().build(
        share_id="shr_raw_readable",
        event_id="evt_raw_readable",
        revision=1,
        safe_context={
            "share_id": "shr_raw_readable",
            "event_id": "evt_raw_readable",
            "summary_card": {"event_id": "evt_raw_readable", "source": {"title": "Raw readable"}},
            "readable_evidence": [{"text": "raw tree", "nodes": [{"role": "AXWebArea"}]}],
        },
        screenshot_png=None,
    )

    try:
        _signed_parser().parse_html(
            html_bytes=package.html,
            source_kind=ShareImportSourceKind.FEISHU_DRIVE_URL,
        )
    except ShareImportError as exc:
        assert exc.code == "readable_evidence_invalid"
    else:  # pragma: no cover
        raise AssertionError("expected untyped readable evidence containers to be rejected")


def test_feishu_classifier_rejects_non_https_and_invalid_tokens() -> None:
    classifier = ShareSourceClassifier()

    assert (
        classifier.classify("https://example.feishu.cn/file/SyntheticFileToken00000001")
        == ShareImportSourceKind.FEISHU_DRIVE_URL
    )
    assert (
        classifier.classify("https://secret@example.feishu.cn/file/SyntheticFileToken00000001")
        == ShareImportSourceKind.FEISHU_DRIVE_URL
    )
    assert (
        classifier.classify("javascript://example.feishu.cn/file/SyntheticFileToken00000001")
        == ShareImportSourceKind.UNKNOWN
    )
    assert classifier.classify("https://evil.example/file/SyntheticFileToken00000001") == ShareImportSourceKind.UNKNOWN
    assert classifier.classify("https://example.feishu.cn/file/../../secret") == ShareImportSourceKind.UNKNOWN


def test_share_package_parser_rejects_tampered_safe_context() -> None:
    package = _signed_builder().build(
        share_id="shr_tamper",
        event_id="evt_tamper",
        revision=1,
        safe_context={
            "share_id": "shr_tamper",
            "event_id": "evt_tamper",
            "summary_card": {"event_id": "evt_tamper", "source": {"title": "Original"}},
        },
        screenshot_png=PNG_BYTES,
    )
    tampered = package.html.replace(b"Original", b"Modified")

    try:
        _signed_parser().parse_html(html_bytes=tampered, source_kind=ShareImportSourceKind.FEISHU_DRIVE_URL)
    except ShareImportError as exc:
        assert exc.code == "json_hash_mismatch"
    else:  # pragma: no cover
        raise AssertionError("expected tampered package to be rejected")


def test_share_package_parser_rejects_forbidden_raw_fields() -> None:
    safe_context = {
        "share_id": "shr_raw",
        "event_id": "evt_raw",
        "summary_card": {"event_id": "evt_raw", "source": {"title": "Unsafe"}},
        "raw_artifact_refs": ["local-artifact://secret"],
    }
    safe_json = json.dumps(safe_context, ensure_ascii=False, sort_keys=True, indent=2)
    html = f"""
    <html><body>
      <script type="application/json" id="workrecorder-safe-context">{safe_json}</script>
      <script type="application/json" id="workrecorder-import-manifest">{{"share_id":"shr_raw","event_id":"evt_raw","revision":1}}</script>
    </body></html>
    """.encode("utf-8")

    try:
        _signed_parser().parse_html(
            html_bytes=html,
            source_kind=ShareImportSourceKind.FEISHU_DRIVE_URL,
        )
    except ShareImportError as exc:
        assert exc.code == "safe_context_unexpected_fields"
    else:  # pragma: no cover
        raise AssertionError("expected raw fields to be rejected")


def test_share_package_parser_rejects_nested_case_insensitive_raw_keys() -> None:
    safe_context = {
        "share_id": "shr_raw_key",
        "event_id": "evt_raw_key",
        "summary_card": {
            "event_id": "evt_raw_key",
            "source": {"title": "Unsafe", "Storage_Path": "opaque-vault-handle"},
        },
    }
    html = _share_html(safe_context=safe_context)

    try:
        _signed_parser().parse_html(
            html_bytes=html,
            source_kind=ShareImportSourceKind.FEISHU_DRIVE_URL,
        )
    except ShareImportError as exc:
        assert exc.code == "safe_context_forbidden_raw"
    else:  # pragma: no cover
        raise AssertionError("expected nested raw-ish keys to be rejected")


def test_share_package_parser_rejects_missing_feishu_json_hash() -> None:
    safe_context = {
        "share_id": "shr_missing_hash",
        "event_id": "evt_missing_hash",
        "summary_card": {"event_id": "evt_missing_hash", "source": {"title": "Missing hash"}},
    }
    safe_json = json.dumps(safe_context, ensure_ascii=False, sort_keys=True, indent=2)
    manifest = {
        "schema_version": "workrecorder_share_html_v1",
        "share_id": "shr_missing_hash",
        "event_id": "evt_missing_hash",
        "revision": 1,
    }
    html = _share_html(safe_json=safe_json, manifest=manifest, include_hash=False)

    try:
        _signed_parser().parse_html(
            html_bytes=html,
            source_kind=ShareImportSourceKind.FEISHU_DRIVE_URL,
        )
    except ShareImportError as exc:
        assert exc.code == "json_hash_missing"
    else:  # pragma: no cover
        raise AssertionError("expected Feishu packages without json_sha256 to be rejected")


def test_share_package_parser_rejects_manifest_identity_mismatch() -> None:
    safe_context = {
        "share_id": "shr_identity",
        "event_id": "evt_identity",
        "summary_card": {"event_id": "evt_identity", "source": {"title": "Identity"}},
    }
    manifest = {
        "schema_version": "workrecorder_share_html_v1",
        "share_id": "shr_other",
        "event_id": "evt_identity",
        "revision": 1,
    }
    html = _share_html(safe_context=safe_context, manifest=manifest)

    try:
        _signed_parser().parse_html(
            html_bytes=html,
            source_kind=ShareImportSourceKind.FEISHU_DRIVE_URL,
        )
    except ShareImportError as exc:
        assert exc.code == "identity_mismatch"
    else:  # pragma: no cover
        raise AssertionError("expected manifest/safe-context identity mismatch to be rejected")


def test_share_package_parser_rejects_screenshot_hash_missing_when_image_present() -> None:
    safe_context = {
        "share_id": "shr_image_hash",
        "event_id": "evt_image_hash",
        "summary_card": {"event_id": "evt_image_hash", "source": {"title": "Image hash"}},
    }
    package = _signed_builder().build(
        share_id="shr_image_hash",
        event_id="evt_image_hash",
        revision=1,
        safe_context=safe_context,
        screenshot_png=PNG_BYTES,
    )
    html = package.html.replace(f', "screenshot_sha256": "{package.manifest.screenshot_sha256}"'.encode(), b"")

    try:
        _signed_parser().parse_html(
            html_bytes=html,
            source_kind=ShareImportSourceKind.FEISHU_DRIVE_URL,
        )
    except ShareImportError as exc:
        assert exc.code == "screenshot_hash_missing"
    else:  # pragma: no cover
        raise AssertionError("expected imported screenshot without hash to be rejected")


def test_share_package_parser_rejects_manifest_screenshot_without_image() -> None:
    safe_context = {
        "share_id": "shr_missing_image",
        "event_id": "evt_missing_image",
        "summary_card": {"event_id": "evt_missing_image", "source": {"title": "Missing image"}},
    }
    html = _share_html(
        safe_context=safe_context,
        manifest={"screenshot_sha256": "a" * 64},
    )

    try:
        _signed_parser().parse_html(
            html_bytes=html,
            source_kind=ShareImportSourceKind.FEISHU_DRIVE_URL,
        )
    except ShareImportError as exc:
        assert exc.code == "screenshot_missing"
    else:  # pragma: no cover
        raise AssertionError("expected manifest screenshot hash without image to be rejected")


def test_share_package_parser_sanitizes_bad_port_without_server_error() -> None:
    safe_context = {
        "share_id": "shr_bad_port",
        "event_id": "evt_bad_port",
        "summary_card": {
            "event_id": "evt_bad_port",
            "source": {
                "title": "Bad port",
                "sanitized_url": "https://example.test:bad/path?secret=1#frag",
                "origin": "https://example.test:bad",
            },
        },
    }
    parsed = _signed_parser().parse_html(
        html_bytes=_share_html(safe_context=safe_context),
        source_kind=ShareImportSourceKind.FEISHU_DRIVE_URL,
    )

    summary_card = parsed.safe_context["summary_card"]
    assert isinstance(summary_card, dict)
    source = summary_card["source"]
    assert isinstance(source, dict)
    assert source["sanitized_url"] == "https://example.test/path"
    assert source["origin"] == "https://example.test"


def test_share_package_parser_rejects_case_variant_local_paths() -> None:
    package = _signed_builder().build(
        share_id="shr_case_path",
        event_id="evt_case_path",
        revision=1,
        safe_context={
            "share_id": "shr_case_path",
            "event_id": "evt_case_path",
            "summary_card": {"event_id": "evt_case_path", "source": {"title": "Case path", "app_name": "Preview"}},
            "system_appshot": {"Local_Path": "/users/example/Desktop/private.png"},
        },
        screenshot_png=None,
    )

    try:
        _signed_parser().parse_html(
            html_bytes=package.html,
            source_kind=ShareImportSourceKind.FEISHU_DRIVE_URL,
        )
    except ShareImportError as exc:
        assert exc.code == "safe_context_forbidden_raw"
    else:  # pragma: no cover
        raise AssertionError("expected case-insensitive raw path rejection")


def test_share_sync_creates_new_revision_without_overwriting_old_snapshot(
    client: TestClient,
    event_create,
) -> None:
    container = cast(DaemonContainer, cast(FastAPI, client.app).state.container)
    event = container.events.save(container.events.build(event_create))
    _artifact(container, event.event_id, ArtifactType.SCREENSHOT, ArtifactRole.VISUAL_EVIDENCE, PNG_BYTES)
    first = container.context_shares.create(
        request=ContextShareCreateRequest(event_id=event.event_id, target=ShareTargetKind.FEISHU_DRIVE),
        actor=ActorRef(actor_id="test-cli", display_name="Test CLI"),
    )
    first_snapshot = container.repositories.shares.latest_snapshot(first.share.share_id)

    second = container.context_shares.sync(
        share_id=first.share.share_id,
        actor=ActorRef(actor_id="test-cli", display_name="Test CLI"),
    )
    second_snapshot = container.repositories.shares.latest_snapshot(first.share.share_id)

    assert first_snapshot is not None
    assert second_snapshot is not None
    assert second.revision is not None
    assert first.revision is not None
    assert second.revision.revision == first.revision.revision + 1
    assert second_snapshot.snapshot_id != first_snapshot.snapshot_id
    assert container.repositories.shares.get_snapshot(first_snapshot.snapshot_id) == first_snapshot


def test_share_can_resolve_stored_external_url_without_query_hash(
    client: TestClient,
    event_create,
) -> None:
    class FakePublisher:
        target = ShareTargetKind.FEISHU_DRIVE

        def publish(self, *, share_id: str, revision: ShareRevision, html: bytes) -> ExternalShareTarget:
            del html
            return ExternalShareTarget(
                target_id="shr_tgt_fake",
                share_id=share_id,
                revision_id=revision.revision_id,
                target=ShareTargetKind.FEISHU_DRIVE,
                status=SharePublishStatus.PUBLISHED,
                provider_file_token="file_token",
                provider_url="https://tenant.feishu.cn/file/boxcn",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

        def revoke(self, *, target: ExternalShareTarget) -> ExternalShareTarget:
            return target.model_copy(update={"status": SharePublishStatus.REVOKED})

    container = cast(DaemonContainer, cast(FastAPI, client.app).state.container)
    container.context_shares.publishers = SharePublisherRegistry((FakePublisher(),))
    event = container.events.save(container.events.build(event_create))
    _artifact(container, event.event_id, ArtifactType.SCREENSHOT, ArtifactRole.VISUAL_EVIDENCE, PNG_BYTES)
    result = container.context_shares.create(
        request=ContextShareCreateRequest(event_id=event.event_id),
        actor=ActorRef(actor_id="test-cli", display_name="Test CLI"),
    )

    resolved = container.context_shares.resolve(
        link_or_share_id="https://tenant.feishu.cn/file/boxcn?from=copy#hash",
        actor=ActorRef(actor_id="test-cli", display_name="Test CLI"),
    )

    assert result.external_url == "https://tenant.feishu.cn/file/boxcn"
    assert result.copyable_url == "https://tenant.feishu.cn/file/boxcn"
    assert resolved.share.share_id == result.share.share_id


def _share_html(
    *,
    safe_context: dict[str, object] | None = None,
    safe_json: str | None = None,
    manifest: dict[str, object] | None = None,
    include_hash: bool = True,
) -> bytes:
    context_json = safe_json or json.dumps(safe_context or {}, ensure_ascii=False, sort_keys=True, indent=2)
    import_manifest = {
        "schema_version": "workrecorder_share_html_v1",
        "share_id": (safe_context or {}).get("share_id"),
        "event_id": (safe_context or {}).get("event_id"),
        "revision": 1,
        **(manifest or {}),
    }
    if include_hash:
        import_manifest["json_sha256"] = hashlib.sha256(context_json.encode("utf-8")).hexdigest()
        signature = sign_share_import_manifest(import_manifest, secret=TEST_SHARE_SECRET)
        assert signature is not None
        import_manifest["signature_alg"] = "hmac_sha256_v1"
        import_manifest["package_signature"] = signature
    manifest_json = json.dumps(import_manifest, ensure_ascii=False, sort_keys=True)
    return f"""
    <html><body>
      <script type="application/json" id="workrecorder-safe-context">{context_json}</script>
      <script type="application/json" id="workrecorder-import-manifest">{manifest_json}</script>
    </body></html>
    """.encode("utf-8")


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
