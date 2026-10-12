from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

import pytest
import uvicorn

from packages.shared.config import WorkRecorderSettings
from services.context_daemon.app import DaemonAppFactory

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WORKRECORDER_RUN_CHROME_E2E") != "1",
        reason="hidden Chrome extension E2E is opt-in; set WORKRECORDER_RUN_CHROME_E2E=1",
    ),
    pytest.mark.filterwarnings("ignore:websockets\\.legacy is deprecated:DeprecationWarning"),
    pytest.mark.filterwarnings("ignore:websockets\\.server\\.WebSocketServerProtocol is deprecated:DeprecationWarning"),
    pytest.mark.filterwarnings("ignore:remove second argument of ws_handler:DeprecationWarning"),
]

INSTALL_SECRET = "workrecorder_hidden_chrome_e2e_0123456789abcdef"
PROVIDER_REGISTRATION_SECRET = "workrecorder_provider_hidden_chrome_e2e_0123456789abcdef"
REPO_ROOT = Path(__file__).resolve().parents[2]
CHROME_BINARY_CANDIDATES = (
    Path.home()
    / "Library/Caches/ms-playwright/chromium-1208/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    Path("/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
)


def test_hidden_chrome_extension_bulk_pages(tmp_path: Path) -> None:
    chrome_binary = _chrome_binary()
    if chrome_binary is None:
        pytest.skip("No Chrome/Chrome for Testing binary available for hidden extension E2E")

    subprocess.run(["npm", "--prefix", "apps/browser_extension", "run", "build"], cwd=REPO_ROOT, check=True)

    fixture_dir = tmp_path / "site"
    fixture_dir.mkdir()
    pages = _write_fixture_pages(fixture_dir)
    with _HttpFixtureServer(fixture_dir) as site, _DaemonServer(tmp_path) as daemon:
        extension_dir = _prepared_extension_dir(tmp_path=tmp_path, daemon_port=daemon.port)
        token = daemon.issue_token()
        raw_token = daemon.issue_token(scopes=("read_raw_artifact",))
        for page in pages:
            with _HiddenChrome(
                page.url(site.base_url),
                tmp_path,
                extension_dir=extension_dir,
                chrome_binary=chrome_binary,
            ) as chrome:
                session = daemon.wait_for_session(page.url(site.base_url))
                assert session["provider_key"] == "web.browser_extension"
                assert session["tab"]["url"] == page.sanitized_url(site.base_url)

                saved = daemon.capture(
                    token=token,
                    slug=page.slug,
                    title=page.title,
                    session=session,
                    staging_dir=tmp_path / "staging",
                )
                assert saved["status"] == "accepted", saved
                event_id = saved["event"]["event_id"]
                artifact_types = {artifact["artifact_type"] for artifact in saved["artifacts"]}
                assert {
                    "screenshot",
                    "browser_full_dom",
                    "browser_readability_markdown",
                    "clean_page_text",
                    "canonical_text",
                }.issubset(artifact_types)

                inspect = daemon.get(
                    f"/v1/events/{event_id}?view=event_inspect&purpose=hidden_chrome_e2e"
                    "&inspect_views=canonical,clean_page_text",
                    token=token,
                )["data"]
                assert page.expected_text in inspect["clean_page_text"], page.slug
                assert page.expected_text in inspect["canonical_text"], page.slug
                for forbidden in page.forbidden_text:
                    assert forbidden not in inspect["clean_page_text"], page.slug
                    assert forbidden not in inspect["canonical_text"], page.slug

                search = daemon.get(
                    f"/v1/search?query={urllib.parse.quote(page.expected_text)}",
                    token=token,
                )["data"]
                assert search["events"] == []
                assert search["results"][0]["event_id"] == event_id
                assert page.expected_text not in search["results"][0]["selection_text"]
                assert "browser_full_dom" in search["results"][0]["hidden_artifacts"]

                full_dom = next(
                    artifact for artifact in saved["artifacts"] if artifact["artifact_type"] == "browser_full_dom"
                )
                denied = daemon.get(
                    f"/v1/artifacts/{full_dom['artifact_id']}/raw?" f"event_id={event_id}&purpose=hidden_chrome_e2e",
                    token=raw_token,
                    expect_ok=False,
                )
                assert denied["error"]["code"] == "policy.denied"

                chrome.assert_alive()


class PageCase:
    def __init__(
        self,
        *,
        slug: str,
        filename: str,
        title: str,
        expected_text: str,
        html: str,
        forbidden_text: tuple[str, ...] = (),
    ) -> None:
        self.slug = slug
        self.filename = filename
        self.title = title
        self.expected_text = expected_text
        self.html = html
        self.forbidden_text = forbidden_text

    def url(self, base_url: str) -> str:
        return f"{base_url}/{self.filename}"

    def sanitized_url(self, base_url: str) -> str:
        return self.url(base_url)


def _write_fixture_pages(root: Path) -> tuple[PageCase, ...]:
    frame = PageCase(
        slug="frame",
        filename="frame.html",
        title="Embedded Frame",
        expected_text="IFRAME_INCLUDED_UNIQUE",
        html=_html("Embedded Frame", "<main><p>IFRAME_INCLUDED_UNIQUE from same-origin frame.</p></main>"),
    )
    pages = (
        PageCase(
            slug="ordinary",
            filename="ordinary.html",
            title="Ordinary Context Page",
            expected_text="ORDINARY_UNIQUE_CONTEXT",
            html=_html(
                "Ordinary Context Page",
                "<main><h1>Ordinary Context Page</h1><p>ORDINARY_UNIQUE_CONTEXT is visible body text.</p></main>",
            ),
        ),
        PageCase(
            slug="news",
            filename="news.html",
            title="WorkRecorder News Story",
            expected_text="NEWS_UNIQUE_CONTEXT",
            html=_html(
                "WorkRecorder News Story",
                "<article><h1>Market note</h1><p>NEWS_UNIQUE_CONTEXT appears in a blog-style paragraph.</p></article>",
            ),
        ),
        PageCase(
            slug="long",
            filename="long.html",
            title="Long Document",
            expected_text="LONG_CONTEXT_BEYOND_VIEW",
            html=_html(
                "Long Document",
                "<main>"
                + "".join(f"<p>Long paragraph {index}</p>" for index in range(120))
                + "<p>LONG_CONTEXT_BEYOND_VIEW proves capture is not viewport-only.</p></main>",
            ),
        ),
        PageCase(
            slug="table",
            filename="table.html",
            title="Table Context",
            expected_text="TABLE_RENEWAL_BLOCKER_UNIQUE",
            html=_html(
                "Table Context",
                "<main><table><tr><th>Account</th><th>Status</th></tr>"
                "<tr><td>ACME</td><td>TABLE_RENEWAL_BLOCKER_UNIQUE</td></tr></table></main>",
            ),
        ),
        PageCase(
            slug="docs",
            filename="docs.html",
            title="Developer Docs",
            expected_text="workrecorderDocsUniqueMethod",
            html=_html(
                "Developer Docs",
                "<main><h2>SDK Call</h2><pre><code>workrecorderDocsUniqueMethod()</code></pre>"
                "<ul><li>Install provider manifest</li><li>Register disclosure profile</li></ul></main>",
            ),
        ),
        PageCase(
            slug="saas",
            filename="saas.html",
            title="SaaS Workspace",
            expected_text="SAAS_PIPELINE_UNIQUE",
            forbidden_text=("SHOULD_NOT_LEAK_NAV",),
            html=_html(
                "SaaS Workspace",
                "<nav><p>SHOULD_NOT_LEAK_NAV</p></nav>"
                "<main><h1>Pipeline</h1><p>SAAS_PIPELINE_UNIQUE is the selected account note.</p></main>",
            ),
        ),
        PageCase(
            slug="spa_token_class",
            filename="spa-token-class.html",
            title="SPA Token Class Page",
            expected_text="SPA_TOKEN_CLASS_UNIQUE_CONTEXT",
            html=_html(
                "SPA Token Class Page",
                "<main><section class='text-token-text-primary'>"
                "<div>SPA_TOKEN_CLASS_UNIQUE_CONTEXT is app-rendered text inside a token-named CSS class.</div>"
                "</section></main>",
            ),
        ),
        PageCase(
            slug="div_only_spa",
            filename="div-only-spa.html",
            title="Div-only SPA",
            expected_text="DIV_ONLY_SPA_UNIQUE_CONTEXT",
            html=_html(
                "Div-only SPA",
                "<main role='main'><div><div>DIV_ONLY_SPA_UNIQUE_CONTEXT is rendered without semantic p/li tags.</div></div></main>",
            ),
        ),
        PageCase(
            slug="sensitive_data_zone",
            filename="sensitive-data-zone.html",
            title="Sensitive Data Zone",
            expected_text="SAFE_CONTEXT_OUTSIDE_AUTH_ZONE",
            forbidden_text=("SHOULD_NOT_LEAK_AUTH_ZONE",),
            html=_html(
                "Sensitive Data Zone",
                "<main><section data-auth-token='SHOULD_NOT_LEAK_AUTH_ZONE'>"
                "<p>SHOULD_NOT_LEAK_AUTH_ZONE appears inside a sensitive data-auth-token subtree.</p>"
                "</section><p>SAFE_CONTEXT_OUTSIDE_AUTH_ZONE remains readable.</p></main>",
            ),
        ),
        PageCase(
            slug="aria_grid_dashboard",
            filename="aria-grid-dashboard.html",
            title="ARIA Grid Dashboard",
            expected_text="ARIA_GRID_RENEWAL_RISK_UNIQUE",
            html=_html(
                "ARIA Grid Dashboard",
                "<main><div role='grid' aria-label='Renewal risk grid'>"
                "<div role='row'><span role='columnheader'>Account</span><span role='columnheader'>Risk</span></div>"
                "<div role='row'><span role='gridcell'>ACME</span><span role='gridcell'>ARIA_GRID_RENEWAL_RISK_UNIQUE</span></div>"
                "</div></main>",
            ),
        ),
        PageCase(
            slug="hidden_noise_fallback",
            filename="hidden-noise-fallback.html",
            title="Hidden Noise Fallback",
            expected_text="VISIBLE_FALLBACK_CONTEXT_UNIQUE",
            forbidden_text=("SHOULD_NOT_LEAK_HIDDEN_FALLBACK", "SHOULD_NOT_LEAK_NAV_FALLBACK"),
            html=_html(
                "Hidden Noise Fallback",
                "<nav><div>SHOULD_NOT_LEAK_NAV_FALLBACK</div></nav><main>"
                "<div hidden>SHOULD_NOT_LEAK_HIDDEN_FALLBACK</div>"
                "<div style='display:none'>SHOULD_NOT_LEAK_HIDDEN_FALLBACK</div>"
                "<div>VISIBLE_FALLBACK_CONTEXT_UNIQUE is the only div-only app text to keep.</div>"
                "</main>",
            ),
        ),
        PageCase(
            slug="iframe",
            filename="iframe.html",
            title="Iframe Page",
            expected_text="IFRAME_INCLUDED_UNIQUE",
            html=_html("Iframe Page", '<main><iframe src="/frame.html"></iframe></main>'),
        ),
        PageCase(
            slug="shadow",
            filename="shadow.html",
            title="Shadow DOM Page",
            expected_text="SHADOW_ROOT_UNIQUE",
            html=_html(
                "Shadow DOM Page",
                "<main><div id='host'></div><script>"
                "const root=document.querySelector('#host').attachShadow({mode:'open'});"
                "root.innerHTML='<p>SHADOW_ROOT_UNIQUE from open shadow root.</p>';"
                "</script></main>",
            ),
        ),
        PageCase(
            slug="pdf_like",
            filename="paper.pdf",
            title="PDF-like Paper",
            expected_text="PDF_TEXT_LAYER_UNIQUE",
            html=_html("PDF-like Paper", "<main><p>PDF_TEXT_LAYER_UNIQUE from a text-layer style fixture.</p></main>"),
        ),
    )
    for page in (frame, *pages):
        (root / page.filename).write_text(page.html, encoding="utf-8")
    return pages


def _html(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{title}</title><style>body{{font-family:sans-serif}} iframe{{width:800px;height:160px}}</style>"
        "</head><body>"
        f"{body}"
        "</body></html>"
    )


class _HttpFixtureServer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.base_url = ""

    def __enter__(self) -> "_HttpFixtureServer":
        root = self.root

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, directory=str(root), **kwargs)

            def guess_type(self, path: str | os.PathLike[str]) -> str:
                path_string = os.fspath(path)
                if path_string.endswith(".pdf"):
                    return "text/html"
                return super().guess_type(path_string)

            def log_message(self, format: str, *args: Any) -> None:
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
        if self.thread is not None:
            self.thread.join(timeout=5)


class _NoSignalUvicornServer(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        return None


class _DaemonServer:
    def __init__(self, tmp_path: Path) -> None:
        self.port = _free_tcp_port()
        self.settings = WorkRecorderSettings(
            database_path=tmp_path / "chrome_e2e.sqlite",
            artifact_staging_dir=tmp_path / "staging",
            artifact_vault_dir=tmp_path / "artifacts",
            install_secret=INSTALL_SECRET,
            provider_registration_secret=PROVIDER_REGISTRATION_SECRET,
            disclosure_policy_path=None,
        )
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> "_DaemonServer":
        app = DaemonAppFactory(self.settings).create()
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning", log_config=None)
        server = _NoSignalUvicornServer(config)
        self.server = server
        self.thread = threading.Thread(target=server.run, daemon=True)
        self.thread.start()
        self._wait_for_health()
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None:
            self.thread.join(timeout=10)

    def issue_token(self, *, scopes: tuple[str, ...] | None = None) -> str:
        body: dict[str, object] = {"actor_id": "test-cli", "display_name": "Hidden Chrome E2E"}
        if scopes is not None:
            body["scopes"] = list(scopes)
        data = cast(dict[str, Any], self.post("/v1/auth/tokens", body=body, install_secret=True)["data"])
        return str(data["access_token"])

    def wait_for_session(self, url: str) -> dict[str, Any]:
        sanitized = url.split("?", 1)[0].split("#", 1)[0]
        token = self.issue_token()
        deadline = time.monotonic() + 20
        last_sessions: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            payload = self.get("/v1/providers/sessions", token=token)
            sessions = payload["data"]["sessions"]
            last_sessions = sessions
            for session in sessions:
                tab = session.get("tab")
                if session.get("provider_key") == "web.browser_extension" and tab and tab.get("url") == sanitized:
                    return cast(dict[str, Any], session)
            time.sleep(0.5)
        raise AssertionError(f"timed out waiting for Web provider session for {url}; sessions={last_sessions!r}")

    def capture(
        self,
        *,
        token: str,
        slug: str,
        title: str,
        session: dict[str, Any],
        staging_dir: Path,
    ) -> dict[str, Any]:
        staging_dir.mkdir(parents=True, exist_ok=True)
        staged = staging_dir / f"{slug}.png"
        staged.write_bytes(b"\x89PNG\r\n\x1a\nworkrecorder-hidden-chrome-e2e")
        now = datetime.now(UTC).isoformat()
        frame = session.get("window", {}).get("screen_rect") or {
            "x": 0,
            "y": 0,
            "width": 1280,
            "height": 900,
            "coordinate_space": "macos_global",
        }
        selection = {
            "x": frame["x"] + 80,
            "y": frame["y"] + 120,
            "width": min(900, max(300, frame["width"] - 160)),
            "height": 320,
            "coordinate_space": "macos_global",
        }
        payload = {
            "schema_version": 1,
            "trigger": {
                "trigger_id": f"trg_hidden_chrome_{slug}",
                "trigger_type": "manual_os_region_hotkey",
                "capture_strategy": "os_region",
                "actor": {"actor_id": "test-cli", "display_name": "Hidden Chrome E2E"},
                "occurred_at": now,
                "selection": selection,
                "intent_text": f"hidden Chrome E2E {slug}",
            },
            "selection_geometry": {
                "selected_region": selection,
                "display": {"display_id": "headless", "frame": frame, "scale_factor": 1.0},
            },
            "window_hints": [
                {
                    "app_name": session.get("app_name", "Google Chrome"),
                    "title": title,
                    "window_id": session.get("window_id"),
                    "frame": frame,
                    "overlap_ratio": 0.92,
                    "confidence": 0.95,
                }
            ],
            "workspace": {"workspace_id": "chrome-e2e", "label": "Chrome E2E", "auto": False},
            "actor": {"actor_id": "test-cli", "display_name": "Hidden Chrome E2E"},
            "staged_artifact": {
                "local_path": str(staged),
                "artifact_type": "screenshot",
                "content_type": "image/png",
                "filename": staged.name,
            },
            "intent_text": f"hidden Chrome E2E {slug}",
        }
        return cast(dict[str, Any], self.post("/v1/captures", token=token, body=payload)["data"])

    def get(self, path: str, *, token: str, expect_ok: bool = True) -> dict[str, Any]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            headers={"authorization": f"Bearer {token}"},
        )
        return self._request_json(request, expect_ok=expect_ok)

    def post(
        self,
        path: str,
        *,
        body: dict[str, object],
        token: str | None = None,
        install_secret: bool = False,
    ) -> dict[str, Any]:
        headers = {"content-type": "application/json"}
        if token is not None:
            headers["authorization"] = f"Bearer {token}"
        if install_secret:
            headers["x-workrecorder-install-secret"] = INSTALL_SECRET
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        return self._request_json(request, expect_ok=True)

    def _request_json(self, request: urllib.request.Request, *, expect_ok: bool) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = cast(dict[str, Any], json.loads(response.read().decode("utf-8")))
        except urllib.error.HTTPError as exc:
            payload = cast(dict[str, Any], json.loads(exc.read().decode("utf-8")))
        if expect_ok and not payload.get("ok"):
            raise AssertionError(payload)
        return payload

    def _wait_for_health(self) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1) as response:
                    if json.loads(response.read().decode("utf-8")).get("ok"):
                        return
            except OSError:
                time.sleep(0.1)
        raise AssertionError("daemon did not start")


class _HiddenChrome:
    def __init__(self, url: str, tmp_path: Path, *, extension_dir: Path, chrome_binary: Path) -> None:
        self.url = url
        self.user_data_dir = tmp_path / f"chrome-profile-{abs(hash(url))}"
        self.extension_dir = extension_dir
        self.chrome_binary = chrome_binary
        self.process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> "_HiddenChrome":
        command = [
            str(self.chrome_binary),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            f"--user-data-dir={self.user_data_dir}",
            f"--disable-extensions-except={self.extension_dir}",
            f"--load-extension={self.extension_dir}",
            "--window-size=1280,900",
            self.url,
        ]
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=8)
        shutil.rmtree(self.user_data_dir, ignore_errors=True)

    def assert_alive(self) -> None:
        assert self.process is not None
        assert self.process.poll() is None, "hidden Chrome exited before collection finished"


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _chrome_binary() -> Path | None:
    override = os.getenv("WORKRECORDER_CHROME_BINARY")
    if override:
        candidate = Path(override)
        return candidate if candidate.exists() else None
    for candidate in CHROME_BINARY_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def _prepared_extension_dir(*, tmp_path: Path, daemon_port: int) -> Path:
    source = REPO_ROOT / "apps" / "browser_extension"
    target = tmp_path / "browser_extension"
    ignore = shutil.ignore_patterns("node_modules", ".turbo", "*.tsbuildinfo", "workrecorder-extension-config.json")
    shutil.copytree(source, target, ignore=ignore)
    (target / "workrecorder-extension-config.json").write_text(
        json.dumps(
            {
                "daemon_url": f"http://127.0.0.1:{daemon_port}",
                "provider_registration_secret": PROVIDER_REGISTRATION_SECRET,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return target
