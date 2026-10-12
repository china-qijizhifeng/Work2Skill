from __future__ import annotations

from datetime import UTC, datetime

import httpx

from packages.contracts import SharePackageManifest, SharePublishStatus, ShareRevision
from packages.integrations.feishu import (
    FeishuDriveClient,
    FeishuIntegrationError,
    FeishuSharePublisher,
    FeishuTokenClient,
)
from packages.shared.ids import IdFactory
from packages.shared.time import Clock


class _MemorySecrets:
    def get(self, *, service: str, account: str) -> str | None:
        del service, account
        return "secret"

    def set(self, *, service: str, account: str, value: str) -> None:
        del service, account, value

    def delete(self, *, service: str, account: str) -> None:
        del service, account


class _ResponseStream:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response

    def __enter__(self) -> httpx.Response:
        return self.response

    def __exit__(self, *args: object) -> None:
        del args


def test_feishu_token_client_requires_secret_without_leaking_values() -> None:
    class EmptySecrets:
        def get(self, *, service: str, account: str) -> str | None:
            del service, account
            return None

        def set(self, *, service: str, account: str, value: str) -> None:
            del service, account, value

        def delete(self, *, service: str, account: str) -> None:
            del service, account

    client = FeishuTokenClient(
        app_id="cli_test",
        secret_store=EmptySecrets(),
        api_base_url="https://open.feishu.cn",
        clock=Clock(),
    )

    try:
        client.tenant_access_token()
    except FeishuIntegrationError as exc:
        assert exc.code == "secret_missing"
        assert "secret" not in str(exc).lower() or "not configured" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("expected missing secret failure")


def test_feishu_drive_client_maps_upload_rejection(monkeypatch) -> None:
    token_client = FeishuTokenClient(
        app_id="cli_test",
        secret_store=_MemorySecrets(),
        api_base_url="https://open.feishu.cn",
        clock=Clock(),
    )
    monkeypatch.setattr(token_client, "tenant_access_token", lambda: "token")
    drive = FeishuDriveClient(token_client=token_client, folder_token="folder", api_base_url="https://open.feishu.cn")
    monkeypatch.setattr(drive, "root_folder_token", lambda: "folder")

    def fake_post(*args, **kwargs):
        del args, kwargs
        return httpx.Response(
            200,
            json={"code": 1061004, "msg": "forbidden"},
            request=httpx.Request("POST", "https://open.feishu.cn/open-apis/drive/v1/files/upload_all"),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    try:
        drive.upload_html(file_name="workrecorder-share.html", content=b"<html></html>")
    except FeishuIntegrationError as exc:
        assert exc.code == "feishu_1061004"
        assert "forbidden" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected Feishu upload failure")


def test_feishu_drive_client_redacts_urls_in_rejection_messages(monkeypatch) -> None:
    token_client = FeishuTokenClient(
        app_id="cli_test",
        secret_store=_MemorySecrets(),
        api_base_url="https://open.feishu.cn",
        clock=Clock(),
    )
    monkeypatch.setattr(token_client, "tenant_access_token", lambda: "token")
    drive = FeishuDriveClient(token_client=token_client, folder_token="folder", api_base_url="https://open.feishu.cn")

    def fake_post(*args, **kwargs):
        del args, kwargs
        return httpx.Response(
            200,
            json={
                "code": 1061004,
                "msg": "forbidden https://tenant.feishu.cn/file/boxcn?token=SHOULD_NOT_LEAK#frag",
            },
            request=httpx.Request("POST", "https://open.feishu.cn/open-apis/drive/v1/files/upload_all"),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    try:
        drive.upload_html(file_name="workrecorder-share.html", content=b"<html></html>")
    except FeishuIntegrationError as exc:
        message = str(exc)
        assert "[url:redacted]" in message
        assert "SHOULD_NOT_LEAK" not in message
        assert "token=" not in message
    else:  # pragma: no cover
        raise AssertionError("expected Feishu upload failure")


def test_feishu_drive_client_maps_json_error_even_on_http_forbidden(monkeypatch) -> None:
    token_client = FeishuTokenClient(
        app_id="cli_test",
        secret_store=_MemorySecrets(),
        api_base_url="https://open.feishu.cn",
        clock=Clock(),
    )
    monkeypatch.setattr(token_client, "tenant_access_token", lambda: "token")
    drive = FeishuDriveClient(token_client=token_client, folder_token="folder", api_base_url="https://open.feishu.cn")
    monkeypatch.setattr(drive, "root_folder_token", lambda: "folder")

    def fake_post(*args, **kwargs):
        del args, kwargs
        return httpx.Response(
            403,
            json={"code": 1061004, "msg": "forbidden."},
            request=httpx.Request("POST", "https://open.feishu.cn/open-apis/drive/v1/files/upload_all"),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    try:
        drive.upload_html(file_name="workrecorder-share.html", content=b"<html></html>")
    except FeishuIntegrationError as exc:
        assert exc.code == "feishu_1061004"
        assert exc.retryable is False
    else:  # pragma: no cover
        raise AssertionError("expected Feishu upload failure")


def test_feishu_success_path_sets_tenant_readable_and_reads_url(monkeypatch) -> None:
    token_client = FeishuTokenClient(
        app_id="cli_test",
        secret_store=_MemorySecrets(),
        api_base_url="https://open.feishu.cn",
        clock=Clock(),
    )
    monkeypatch.setattr(token_client, "tenant_access_token", lambda: "token")
    drive = FeishuDriveClient(token_client=token_client, folder_token="folder", api_base_url="https://open.feishu.cn")
    patch_payloads: list[dict[str, object]] = []

    def fake_post(url, **kwargs):
        if str(url).endswith("/upload_all"):
            return httpx.Response(
                200,
                json={"code": 0, "data": {"file_token": "file_token"}},
                request=httpx.Request("POST", str(url)),
            )
        return httpx.Response(
            200,
            json={"code": 0, "data": {"metas": [{"url": "https://example.feishu.cn/file/boxcn?from=copy"}]}},
            request=httpx.Request("POST", str(url)),
        )

    def fake_patch(url, **kwargs):
        patch_payloads.append(kwargs["json"])
        return httpx.Response(200, json={"code": 0}, request=httpx.Request("PATCH", str(url)))

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "patch", fake_patch)

    token = drive.upload_html(file_name="workrecorder.html", content=b"<html></html>")
    drive.set_tenant_readable(file_token=token)
    url = drive.file_url(file_token=token)

    assert token == "file_token"
    assert patch_payloads == [{"external_access": False, "link_share_entity": "tenant_readable"}]
    assert url == "https://example.feishu.cn/file/boxcn?from=copy"


def test_feishu_download_file_returns_bytes_and_rejects_oversized(monkeypatch) -> None:
    token_client = FeishuTokenClient(
        app_id="cli_test",
        secret_store=_MemorySecrets(),
        api_base_url="https://open.feishu.cn",
        clock=Clock(),
    )
    monkeypatch.setattr(token_client, "tenant_access_token", lambda: "token")
    drive = FeishuDriveClient(token_client=token_client, folder_token="folder", api_base_url="https://open.feishu.cn")

    def ok_stream(method, url, **kwargs):
        assert method == "GET"
        del kwargs
        return _ResponseStream(
            httpx.Response(
                200,
                content=b"<html>WorkRecorder</html>",
                headers={"content-type": "text/html", "content-length": "23"},
                request=httpx.Request("GET", str(url)),
            )
        )

    monkeypatch.setattr(httpx, "stream", ok_stream)
    assert drive.download_file(file_token="file_token") == b"<html>WorkRecorder</html>"

    def too_large_stream(method, url, **kwargs):
        assert method == "GET"
        del kwargs
        return _ResponseStream(
            httpx.Response(
                200,
                content=b"",
                headers={"content-type": "text/html", "content-length": str(16 * 1024 * 1024)},
                request=httpx.Request("GET", str(url)),
            )
        )

    monkeypatch.setattr(httpx, "stream", too_large_stream)
    try:
        drive.download_file(file_token="file_token")
    except FeishuIntegrationError as exc:
        assert exc.code == "download_too_large"
    else:  # pragma: no cover
        raise AssertionError("expected oversized download rejection")


def test_feishu_download_maps_forbidden_json(monkeypatch) -> None:
    token_client = FeishuTokenClient(
        app_id="cli_test",
        secret_store=_MemorySecrets(),
        api_base_url="https://open.feishu.cn",
        clock=Clock(),
    )
    monkeypatch.setattr(token_client, "tenant_access_token", lambda: "token")
    drive = FeishuDriveClient(token_client=token_client, folder_token="folder", api_base_url="https://open.feishu.cn")

    def fake_stream(method, url, **kwargs):
        assert method == "GET"
        del kwargs
        return _ResponseStream(
            httpx.Response(
                403,
                json={"code": 1061004, "msg": "forbidden"},
                request=httpx.Request("GET", str(url)),
            )
        )

    monkeypatch.setattr(httpx, "stream", fake_stream)
    try:
        drive.download_file(file_token="file_token")
    except FeishuIntegrationError as exc:
        assert exc.code == "feishu_1061004"
        assert exc.retryable is False
    else:  # pragma: no cover
        raise AssertionError("expected forbidden download rejection")


def test_feishu_upload_fails_closed_when_configured_folder_is_forbidden(monkeypatch) -> None:
    token_client = FeishuTokenClient(
        app_id="cli_test",
        secret_store=_MemorySecrets(),
        api_base_url="https://open.feishu.cn",
        clock=Clock(),
    )
    monkeypatch.setattr(token_client, "tenant_access_token", lambda: "token")
    drive = FeishuDriveClient(
        token_client=token_client,
        folder_token="user_folder_without_app_permission",
        api_base_url="https://open.feishu.cn",
    )
    posted_parent_nodes: list[str] = []

    def fake_post(url, **kwargs):
        posted_parent_nodes.append(kwargs["data"]["parent_node"])
        if kwargs["data"]["parent_node"] == "user_folder_without_app_permission":
            return httpx.Response(
                200,
                json={"code": 1061004, "msg": "forbidden"},
                request=httpx.Request("POST", str(url)),
            )
        return httpx.Response(
            200,
            json={"code": 0, "data": {"file_token": "file_from_app_root"}},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    root_called = False

    def root_folder_token() -> str:
        nonlocal root_called
        root_called = True
        return "app_root_folder"

    monkeypatch.setattr(drive, "root_folder_token", root_folder_token)

    try:
        drive.upload_html(file_name="workrecorder.html", content=b"<html></html>")
    except FeishuIntegrationError as exc:
        assert exc.code == "feishu_1061004"
    else:  # pragma: no cover
        raise AssertionError("expected configured folder upload to fail closed")

    assert posted_parent_nodes == ["user_folder_without_app_permission"]
    assert root_called is False


def test_feishu_publisher_retries_retryable_errors_and_sanitizes_url(monkeypatch) -> None:
    token_client = FeishuTokenClient(
        app_id="cli_test",
        secret_store=_MemorySecrets(),
        api_base_url="https://open.feishu.cn",
        clock=Clock(),
    )
    monkeypatch.setattr(token_client, "tenant_access_token", lambda: "token")
    drive = FeishuDriveClient(token_client=token_client, folder_token="folder", api_base_url="https://open.feishu.cn")
    attempts = {"upload": 0}

    def upload(file_name: str, content: bytes) -> str:
        del file_name, content
        attempts["upload"] += 1
        if attempts["upload"] < 3:
            raise FeishuIntegrationError("rate limited", code="upload_http", retryable=True)
        return "file_token"

    monkeypatch.setattr(drive, "upload_html", upload)
    monkeypatch.setattr(drive, "set_tenant_readable", lambda *, file_token: None)
    monkeypatch.setattr(drive, "file_url", lambda *, file_token: "https://tenant.feishu.cn/file/boxcn?from=copy#hash")
    now = datetime(2026, 5, 25, tzinfo=UTC)
    manifest = SharePackageManifest(
        share_id="shr_retry",
        event_id="evt_retry",
        revision=1,
        html_filename="workrecorder.html",
        json_filename="workrecorder.json",
        manifest_filename="workrecorder-manifest.json",
        html_sha256="a" * 64,
        json_sha256="b" * 64,
        manifest_sha256="c" * 64,
        created_at=now,
    )
    revision = ShareRevision(
        revision_id="shr_rev_retry",
        share_id="shr_retry",
        event_id="evt_retry",
        revision=1,
        snapshot_id="shr_snap_retry",
        manifest=manifest,
        status=SharePublishStatus.PENDING,
        created_at=now,
    )

    target = FeishuSharePublisher(drive=drive, ids=IdFactory(), clock=Clock()).publish(
        share_id="shr_retry",
        revision=revision,
        html=b"<html></html>",
    )

    assert attempts["upload"] == 3
    assert target.status == SharePublishStatus.PUBLISHED
    assert target.provider_url == "https://tenant.feishu.cn/file/boxcn"
