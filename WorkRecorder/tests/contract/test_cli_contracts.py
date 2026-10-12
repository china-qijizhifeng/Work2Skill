from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import typer
from typer.testing import CliRunner

from apps.cli import main as cli_main
from apps.cli.client import DaemonClient, DaemonClientError
from packages.contracts import ErrorCode
from scripts.repair_uv_editable_install import repair_macos_hidden_pth_files


class FakeClient:
    def health(self):
        return {"status": "ok"}

    def get(self, path, *, scopes, agent_run_id=None, context_query_id=None):
        return {"ok": True, "data": {"path": path, "scope_count": len(scopes)}, "request_id": "req_test"}

    def post(self, path, *, body, scopes, agent_run_id=None, context_query_id=None):
        return {"ok": True, "data": {"path": path, "body": body, "scope_count": len(scopes)}, "request_id": "req_test"}


class ScopeCaptureClient(FakeClient):
    def __init__(self):
        self.posts = []

    def post(self, path, *, body, scopes, agent_run_id=None, context_query_id=None):
        self.posts.append((path, tuple(scope.value for scope in scopes)))
        return super().post(
            path,
            body=body,
            scopes=scopes,
            agent_run_id=agent_run_id,
            context_query_id=context_query_id,
        )


class RawArtifactFakeClient(FakeClient):
    def get(self, path, *, scopes, agent_run_id=None, context_query_id=None):
        return {
            "ok": True,
            "data": {
                "artifact_id": "art_screenshot_123",
                "content_base64": "AQIDBA==",
                "content_type": "image/png",
                "path": path,
                "scope_count": len(scopes),
            },
            "request_id": "req_test",
        }


class SearchPayloadFakeClient(FakeClient):
    def get(self, path, *, scopes, agent_run_id=None, context_query_id=None):
        return {
            "ok": True,
            "data": {
                "results": [
                    {
                        "event_id": "evt_123",
                        "event_type": "webpage.selection.captured",
                        "captured_at": "2026-05-22T13:40:28Z",
                        "source": {
                            "app_name": "Google Chrome",
                            "title": "网页内容抽取策略",
                            "origin": "https://chatgpt.com",
                            "sanitized_url": "https://chatgpt.com/c/abc",
                        },
                        "selection_bbox": {"x": 1, "y": 2, "width": 3, "height": 4},
                        "user_note": "测试",
                        "selection_text": "最小可行版本可以这样做",
                        "selection_text_snippet": "最小可行版本",
                        "selection_text_truncated": False,
                        "canonical_text_snippet": "SHOULD_NOT_BE_IN_ROUGH_SEARCH",
                        "preview_evidence_id": "evd_123",
                        "preview_citation_id": "cit_123",
                        "preview_confidence": 0.91,
                        "match_reason": "canonical_text",
                        "hidden_artifacts": ["screenshot", "browser_full_dom", "a11y_tree"],
                        "provider_contributions": ["web.browser_extension"],
                        "provider_diagnostics_count": 2,
                        "source_kind": "web",
                        "disclosure_view": "summary_card",
                        "disclosure_policy_version": "disclosure_policy_v1",
                    }
                ],
                "backend": "sqlite_keyword",
                "degraded": False,
            },
            "agent_run_id": agent_run_id or "arun_test",
            "retrieval_call_id": "rcall_123",
            "snapshot_id": "snap_123",
            "request_id": "req_test",
        }


def test_cli_skill_commands_parse(monkeypatch):
    monkeypatch.setattr(cli_main, "_client", lambda: FakeClient())
    runner = CliRunner()
    commands = (
        ["daemon", "health", "--json"],
        ["agent", "begin", "--purpose", "customer_brief", "--question", "ACME?", "--json"],
        ["agent", "current", "--json"],
        ["agent", "replay", "--agent-run-id", "arun_123", "--json"],
        ["agent", "export", "--agent-run-id", "arun_123", "--format", "json", "--json"],
        ["agent", "end", "--agent-run-id", "arun_123", "--json"],
        ["events", "ls", "--json"],
        ["events", "grep", "Budget variance", "--json"],
        ["events", "search", "ACME 续约风险", "--mode", "keyword", "--json"],
        ["events", "get", "evt_123", "--json"],
        ["events", "get", "evt_123", "--include", "artifacts,evidence", "--json"],
        ["events", "inspect", "evt_123", "--purpose", "agent_deep_read", "--json"],
        ["artifacts", "cat", "art_dom_123", "--event", "evt_123", "--redacted", "--json"],
        ["artifacts", "raw", "art_screenshot_123", "--event", "evt_123", "--purpose", "agent_deep_read", "--json"],
        ["bundle", "create", "--query", "生成 ACME brief", "--purpose", "customer_brief", "--json"],
        ["bundle", "show", "cb_123", "--json"],
        ["bundle", "export", "cb_123", "--format", "markdown", "--json"],
        ["citations", "resolve", "cit_123", "--agent-run-id", "arun_123", "--json"],
        ["shares", "create", "--event", "evt_123", "--purpose", "handoff", "--json"],
        ["shares", "resolve", "workrecorder://share/shr_123", "--purpose", "user_shared_context", "--json"],
        ["shares", "import", "workrecorder://share/shr_123", "--json"],
        ["shares", "revoke", "shr_123", "--json"],
        ["shares", "sync", "shr_123", "--json"],
        ["shares", "ls", "--user", "Test User", "--json"],
        ["shares", "jobs", "shr_123", "--json"],
        ["providers", "ls", "--json"],
        ["disclosure", "profiles", "--json"],
        ["sources", "ls", "--since", "2026-05-01T00:00:00Z", "--app", "Chrome", "--limit", "20", "--json"],
        ["entities", "ls", "--query", "ACME", "--json"],
        ["captures", "diagnose", "--trigger", "trg_123", "--json"],
        [
            "usage",
            "record",
            "--bundle",
            "cb_123",
            "--agent",
            "codex",
            "--purpose",
            "customer_brief",
            "--output-ref",
            "run_123",
            "--used-citation",
            "cit_123",
            "--json",
        ],
    )
    for command in commands:
        result = runner.invoke(cli_main.app, command)
        assert result.exit_code == 0, result.output


def test_cli_share_import_requests_import_and_read_share_scopes_for_local_refs(monkeypatch):
    fake = ScopeCaptureClient()
    monkeypatch.setattr(cli_main, "_client", lambda: fake)
    runner = CliRunner()

    result = runner.invoke(cli_main.app, ["shares", "import", "workrecorder://share/shr_123", "--json"])

    assert result.exit_code == 0, result.output
    assert fake.posts == [("/v1/shares/import", ("import_share", "read_share"))]


def test_cli_share_import_requests_only_import_scope_for_feishu_urls(monkeypatch):
    fake = ScopeCaptureClient()
    monkeypatch.setattr(cli_main, "_client", lambda: fake)
    runner = CliRunner()

    result = runner.invoke(
        cli_main.app,
        ["shares", "import", "https://tenant.feishu.cn/file/SyntheticFileToken00000001", "--json"],
    )

    assert result.exit_code == 0, result.output
    assert fake.posts == [("/v1/shares/import", ("import_share",))]


def test_cli_reads_daemon_url_from_local_endpoint_config(monkeypatch, tmp_path):
    monkeypatch.delenv("WORKRECORDER_DAEMON_URL", raising=False)
    monkeypatch.setattr(cli_main.Path, "home", lambda: tmp_path)
    config_path = tmp_path / ".workrecorder/app-dev/daemon-endpoint.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"daemon_url": "http://127.0.0.1:8771", "install_secret": "workrecorder_test_secret"}),
        encoding="utf-8",
    )

    assert cli_main._daemon_url() == "http://127.0.0.1:8771"
    assert cli_main._install_secret() == "workrecorder_test_secret"


def test_cli_ignores_provider_extension_config_for_install_secret(monkeypatch, tmp_path):
    monkeypatch.delenv("WORKRECORDER_DAEMON_URL", raising=False)
    monkeypatch.setattr(cli_main.Path, "home", lambda: tmp_path)
    config_path = tmp_path / ".workrecorder/app-dev/browser_extension/workrecorder-extension-config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {"daemon_url": "http://127.0.0.1:8772", "provider_registration_secret": "workrecorder_provider_secret"}
        ),
        encoding="utf-8",
    )

    assert cli_main._daemon_url() == cli_main.DEFAULT_DAEMON_URL
    assert cli_main._install_secret() == cli_main.DEFAULT_INSTALL_SECRET


def test_cli_ignores_non_loopback_daemon_url_from_local_config(monkeypatch, tmp_path):
    monkeypatch.delenv("WORKRECORDER_DAEMON_URL", raising=False)
    monkeypatch.setattr(cli_main.Path, "home", lambda: tmp_path)
    config_path = tmp_path / ".workrecorder/app-dev/daemon-endpoint.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"daemon_url": "https://example.invalid:8772", "install_secret": "workrecorder_test_secret"}),
        encoding="utf-8",
    )

    assert cli_main._daemon_url() == cli_main.DEFAULT_DAEMON_URL
    assert cli_main._install_secret() == cli_main.DEFAULT_INSTALL_SECRET


def test_cli_uses_secret_from_same_valid_endpoint_config(monkeypatch, tmp_path):
    monkeypatch.delenv("WORKRECORDER_DAEMON_URL", raising=False)
    monkeypatch.delenv("WORKRECORDER_INSTALL_SECRET", raising=False)
    monkeypatch.setattr(cli_main.Path, "home", lambda: tmp_path)
    app_config = tmp_path / ".workrecorder/app-dev/daemon-endpoint.json"
    app_config.parent.mkdir(parents=True)
    app_config.write_text(
        json.dumps({"daemon_url": "http://127.0.0.1:8773", "install_secret": "workrecorder_right_secret"}),
        encoding="utf-8",
    )

    assert cli_main._daemon_url() == "http://127.0.0.1:8773"
    assert cli_main._install_secret() == "workrecorder_right_secret"


def test_cli_rejects_non_loopback_daemon_url_from_env(monkeypatch):
    monkeypatch.setenv("WORKRECORDER_DAEMON_URL", "https://example.invalid:8772")

    with pytest.raises(typer.BadParameter):
        cli_main._daemon_url()


def test_cli_daemon_error_exits_nonzero(monkeypatch):
    class ErrorClient(FakeClient):
        def get(self, path, *, scopes, agent_run_id=None, context_query_id=None):
            raise DaemonClientError("Capture trigger not found")

    monkeypatch.setattr(cli_main, "_client", lambda: ErrorClient())
    runner = CliRunner()

    result = runner.invoke(cli_main.app, ["captures", "diagnose", "--trigger", "missing", "--json"])

    assert result.exit_code != 0
    assert isinstance(result.exception, DaemonClientError)
    assert "Capture trigger not found" in str(result.exception)


def test_daemon_client_preserves_error_code_details_and_request_id() -> None:
    client = DaemonClient(base_url="http://127.0.0.1:8765", install_secret="secret")
    response = httpx.Response(
        404,
        json={
            "ok": False,
            "data": None,
            "error": {
                "code": "not_found",
                "message": "Capture trigger not found",
                "details": {"trigger_id": "missing"},
            },
            "request_id": "req_not_found",
        },
    )

    try:
        client._json_payload(response)  # noqa: SLF001 - CLI error-envelope contract test.
    except DaemonClientError as exc:
        assert exc.code == ErrorCode.NOT_FOUND
        assert exc.details == {"trigger_id": "missing"}
        assert exc.request_id == "req_not_found"
        assert str(exc) == "Capture trigger not found"
    else:
        raise AssertionError("daemon error envelope was not raised")


def test_cli_search_filters_map_to_api_params(monkeypatch):
    monkeypatch.setattr(cli_main, "_client", lambda: FakeClient())
    runner = CliRunner()

    result = runner.invoke(
        cli_main.app,
        [
            "events",
            "search",
            "ACME",
            "--mode",
            "keyword",
            "--since",
            "2026-05-01T00:00:00Z",
            "--until",
            "2026-05-18T00:00:00Z",
            "--workspace",
            "ws_acme",
            "--app",
            "Chrome",
            "--domain",
            "example.test",
            "--source",
            "web",
            "--provider",
            "web.browser_extension",
            "--event-type",
            "webpage.selection.captured",
            "--evidence-kind",
            "canonical_text",
            "--status",
            "agent_ready",
            "--sensitivity",
            "internal",
            "--entity",
            "ACME",
            "--project",
            "Renewal",
            "--user",
            "Test User",
            "--cursor",
            "cur_1",
            "--sort",
            "score",
            "--explain",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    params = parse_qs(urlsplit(payload["data"]["path"]).query)
    assert params["query"] == ["ACME"]
    assert params["workspace"] == ["ws_acme"]
    assert params["app"] == ["Chrome"]
    assert params["domain"] == ["example.test"]
    assert params["source"] == ["web"]
    assert params["provider"] == ["web.browser_extension"]
    assert params["event_type"] == ["webpage.selection.captured"]
    assert params["evidence_kind"] == ["canonical_text"]
    assert params["status"] == ["agent_ready"]
    assert params["sensitivity"] == ["internal"]
    assert params["entity"] == ["ACME"]
    assert params["project"] == ["Renewal"]
    assert params["user"] == ["Test User"]
    assert params["cursor"] == ["cur_1"]
    assert params["explain"] == ["true"]


def test_cli_events_search_compacts_agent_facing_card(monkeypatch):
    monkeypatch.setattr(cli_main, "_client", lambda: SearchPayloadFakeClient())
    runner = CliRunner()

    result = runner.invoke(cli_main.app, ["events", "search", "网页内容", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    card = payload["data"]["results"][0]
    assert card == {
        "app": "Google Chrome",
        "available_fields": [
            "selection_text",
            "canonical",
            "clean_page_text",
            "system_appshot",
            "screenshot_ref",
            "evidence_refs",
            "artifact_metadata",
        ],
        "captured_at": "2026-05-22T13:40:28Z",
        "event_id": "evt_123",
        "selection_text": "最小可行版本可以这样做",
        "selection_text_truncated": False,
        "title": "网页内容抽取策略",
        "url": "https://chatgpt.com/c/abc",
        "user_note": "测试",
    }
    assert "canonical_text_snippet" not in json.dumps(payload, ensure_ascii=False)
    assert "browser_full_dom" not in json.dumps(payload, ensure_ascii=False)
    assert "backend" not in payload["data"]
    assert payload["retrieval_call_id"] == "rcall_123"


def test_cli_bundle_create_requests_create_and_read_text_scopes(monkeypatch):
    monkeypatch.setattr(cli_main, "_client", lambda: FakeClient())
    runner = CliRunner()

    result = runner.invoke(
        cli_main.app,
        ["bundle", "create", "--query", "生成 ACME brief", "--purpose", "customer_brief", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data"]["scope_count"] == 2


def test_cli_entities_uses_daemon_api(monkeypatch):
    monkeypatch.setattr(cli_main, "_client", lambda: FakeClient())
    runner = CliRunner()

    result = runner.invoke(cli_main.app, ["entities", "ls", "--query", "ACME", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data"]["path"].startswith("/v1/search/entities?")


def test_cli_sources_filters_map_to_api_params(monkeypatch):
    monkeypatch.setattr(cli_main, "_client", lambda: FakeClient())
    runner = CliRunner()

    result = runner.invoke(
        cli_main.app,
        [
            "sources",
            "ls",
            "--since",
            "2026-05-01T00:00:00Z",
            "--until",
            "2026-05-18T00:00:00Z",
            "--workspace",
            "ws_acme",
            "--app",
            "Chrome",
            "--domain",
            "example.test",
            "--origin",
            "https://example.test",
            "--source",
            "web",
            "--provider",
            "web.browser_extension",
            "--status",
            "agent_ready",
            "--limit",
            "20",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    params = parse_qs(urlsplit(payload["data"]["path"]).query)
    assert params["limit"] == ["20"]
    assert params["workspace"] == ["ws_acme"]
    assert params["app"] == ["Chrome"]
    assert params["domain"] == ["example.test"]
    assert params["origin"] == ["https://example.test"]
    assert params["source"] == ["web"]
    assert params["provider"] == ["web.browser_extension"]
    assert params["status"] == ["agent_ready"]


def test_cli_raw_artifact_omits_base64_by_default(monkeypatch):
    monkeypatch.setattr(cli_main, "_client", lambda: RawArtifactFakeClient())
    runner = CliRunner()

    result = runner.invoke(
        cli_main.app,
        [
            "artifacts",
            "raw",
            "art_screenshot_123",
            "--event",
            "evt_123",
            "--purpose",
            "visual_check",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "content_base64" not in payload["data"]
    assert payload["data"]["content_base64_omitted"] is True
    assert payload["data"]["raw_content_hint"].startswith("Use --output")


def test_cli_raw_artifact_writes_output_file(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cli_main, "_client", lambda: RawArtifactFakeClient())
    output_path = tmp_path / "shot.png"
    runner = CliRunner()

    result = runner.invoke(
        cli_main.app,
        [
            "artifacts",
            "raw",
            "art_screenshot_123",
            "--event",
            "evt_123",
            "--purpose",
            "visual_check",
            "--output",
            str(output_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "content_base64" not in payload["data"]
    assert payload["data"]["output_path"] == str(output_path.resolve())
    assert payload["data"]["wrote_bytes"] == 4
    assert output_path.read_bytes() == b"\x01\x02\x03\x04"


def test_cli_raw_artifact_inline_prints_base64(monkeypatch):
    monkeypatch.setattr(cli_main, "_client", lambda: RawArtifactFakeClient())
    runner = CliRunner()

    result = runner.invoke(
        cli_main.app,
        [
            "artifacts",
            "raw",
            "art_screenshot_123",
            "--event",
            "evt_123",
            "--purpose",
            "visual_check",
            "--inline",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data"]["content_base64"] == "AQIDBA=="
    assert "content_base64_omitted" not in payload["data"]


def test_cli_agent_run_session_is_reused(monkeypatch, tmp_path: Path):
    seen: list[str | None] = []

    class TraceClient(FakeClient):
        def post(self, path, *, body, scopes, agent_run_id=None, context_query_id=None):
            return {
                "ok": True,
                "agent_run_id": "arun_cli_test",
                "data": {"agent_run_id": "arun_cli_test", "path": path, "body": body},
                "request_id": "req_test",
            }

        def get(self, path, *, scopes, agent_run_id=None, context_query_id=None):
            seen.append(agent_run_id)
            return {"ok": True, "data": {"path": path}, "agent_run_id": agent_run_id, "request_id": "req_test"}

    monkeypatch.setattr(cli_main, "_client", lambda: TraceClient())
    monkeypatch.setattr(cli_main, "AGENT_SESSION_PATH", tmp_path / "agent_session.json")
    runner = CliRunner()

    begin = runner.invoke(cli_main.app, ["agent", "begin", "--purpose", "test", "--json"])
    search = runner.invoke(cli_main.app, ["events", "search", "ACME", "--json"])

    assert begin.exit_code == 0, begin.output
    assert search.exit_code == 0, search.output
    assert seen == ["arun_cli_test"]


def test_cli_console_script_imports_without_pythonpath() -> None:
    repair_macos_hidden_pth_files()
    script = Path(sys.executable).with_name("workrecorder")

    result = subprocess.run(
        [str(script), "--help"],
        check=False,
        capture_output=True,
        env={},
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "WorkRecorder local context CLI" in result.stdout


def test_cli_json_error_is_parseable_without_traceback() -> None:
    repair_macos_hidden_pth_files()
    script = Path(sys.executable).with_name("workrecorder")

    result = subprocess.run(
        [str(script), "events", "inspect", "evt_missing", "--view", "summary", "--json"],
        check=False,
        capture_output=True,
        env={},
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert json.loads(result.stderr)["ok"] is False


def test_cli_module_execution_preserves_error_exit_code() -> None:
    result = subprocess.run(
        [
            str(Path(sys.executable)),
            "-m",
            "apps.cli.main",
            "events",
            "inspect",
            "evt_missing",
            "--view",
            "summary",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert json.loads(result.stderr)["ok"] is False
