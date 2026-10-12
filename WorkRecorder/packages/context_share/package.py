"""Build static share packages from safe disclosure snapshots."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
from dataclasses import dataclass
from typing import Callable

from packages.contracts import SharePackageManifest
from packages.shared.time import Clock

SHARE_PACKAGE_SIGNATURE_ALG = "hmac_sha256_v1"
ShareSignatureSecretProvider = Callable[[], str | None]


@dataclass(frozen=True)
class SharePackage:
    """Generated static files for one immutable share revision.

    Attributes:
        html: Human-readable HTML page uploaded to the share target.
        safe_context_json: Machine-readable safe context payload.
        screenshot: Optional PNG bytes embedded in the HTML package.
        manifest_json: Serialized package integrity manifest.
        manifest: Typed manifest with filenames and hashes.
    """

    html: bytes
    safe_context_json: bytes
    screenshot: bytes | None
    manifest_json: bytes
    manifest: SharePackageManifest


class SharePackageBuilder:
    """Render human-readable HTML plus machine-readable JSON for sharing."""

    def __init__(self, *, clock: Clock, signature_secret_provider: ShareSignatureSecretProvider | None = None) -> None:
        self.clock = clock
        self.signature_secret_provider = signature_secret_provider

    def build(
        self,
        *,
        share_id: str,
        event_id: str,
        revision: int,
        safe_context: dict[str, object],
        screenshot_png: bytes | None,
    ) -> SharePackage:
        """Return a self-contained share package.

        Args:
            share_id: Stable share identifier.
            event_id: Local event captured by WorkRecorder.
            revision: Immutable revision number for this package.
            safe_context: Disclosure-approved payload for agents and import.
            screenshot_png: Optional full screenshot bytes for the HTML page.

        Returns:
            Rendered package files and typed integrity manifest.
        """

        safe_context_json = json.dumps(safe_context, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        screenshot_filename = f"workrecorder-share-{share_id}-r{revision}.png" if screenshot_png else None
        html_filename = f"workrecorder-share-{share_id}-r{revision}.html"
        json_filename = f"workrecorder-share-{share_id}-r{revision}.json"
        manifest_filename = f"workrecorder-share-{share_id}-r{revision}-manifest.json"
        json_sha256 = hashlib.sha256(safe_context_json).hexdigest()
        screenshot_sha256 = hashlib.sha256(screenshot_png).hexdigest() if screenshot_png else None
        import_manifest = {
            "schema_version": "workrecorder_share_html_v1",
            "share_id": share_id,
            "event_id": event_id,
            "revision": revision,
            "json_sha256": json_sha256,
            "screenshot_sha256": screenshot_sha256,
            "created_at": self.clock.now().isoformat(),
        }
        secret = self.signature_secret_provider() if self.signature_secret_provider is not None else None
        signature = sign_share_import_manifest(import_manifest, secret=secret)
        if signature is not None:
            import_manifest["signature_alg"] = SHARE_PACKAGE_SIGNATURE_ALG
            import_manifest["package_signature"] = signature
        html_bytes = self._render_html(
            share_id=share_id,
            revision=revision,
            safe_context=safe_context,
            safe_context_json=safe_context_json,
            screenshot_png=screenshot_png,
            import_manifest=import_manifest,
        )
        html_sha256 = hashlib.sha256(html_bytes).hexdigest()
        manifest_payload = {
            "share_id": share_id,
            "event_id": event_id,
            "revision": revision,
            "html_filename": html_filename,
            "json_filename": json_filename,
            "screenshot_filename": screenshot_filename,
            "manifest_filename": manifest_filename,
            "html_sha256": html_sha256,
            "json_sha256": json_sha256,
            "screenshot_sha256": screenshot_sha256,
            "created_at": self.clock.now().isoformat(),
        }
        manifest_json = json.dumps(manifest_payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        manifest = SharePackageManifest(
            share_id=share_id,
            event_id=event_id,
            revision=revision,
            html_filename=html_filename,
            json_filename=json_filename,
            screenshot_filename=screenshot_filename,
            manifest_filename=manifest_filename,
            html_sha256=html_sha256,
            json_sha256=json_sha256,
            manifest_sha256=hashlib.sha256(manifest_json).hexdigest(),
            screenshot_sha256=screenshot_sha256,
            created_at=self.clock.now(),
        )
        return SharePackage(
            html=html_bytes,
            safe_context_json=safe_context_json,
            screenshot=screenshot_png,
            manifest_json=manifest_json,
            manifest=manifest,
        )

    def _render_html(
        self,
        *,
        share_id: str,
        revision: int,
        safe_context: dict[str, object],
        safe_context_json: bytes,
        screenshot_png: bytes | None,
        import_manifest: dict[str, object],
    ) -> bytes:
        card = safe_context.get("summary_card")
        card_payload = card if isinstance(card, dict) else {}
        source = card_payload.get("source") if isinstance(card_payload, dict) else {}
        source_payload = source if isinstance(source, dict) else {}
        title = self._text(source_payload.get("title") or "WorkRecorder Context")
        app_name = self._text(source_payload.get("app_name") or "Unknown App")
        url = self._text(source_payload.get("sanitized_url") or source_payload.get("origin") or "")
        captured_at = self._text(card_payload.get("captured_at") or safe_context.get("captured_at") or "")
        user_note = self._text(card_payload.get("user_note") or "")
        selection_text = self._text(
            card_payload.get("selection_text") or card_payload.get("selection_text_snippet") or ""
        )
        clean_page_text = self._text(safe_context.get("clean_page_text") or "")
        canonical_text = self._text(safe_context.get("canonical_text") or "")
        ocr_text = self._text(safe_context.get("visual_ocr_text") or "")
        hidden = safe_context.get("hidden_materials")
        hidden_items = hidden if isinstance(hidden, list) else []
        screenshot_html = ""
        if screenshot_png:
            encoded = base64.b64encode(screenshot_png).decode("ascii")
            screenshot_html = f'<img class="shot" src="data:image/png;base64,{encoded}" alt="WorkRecorder screenshot" />'
        else:
            screenshot_html = '<div class="empty-shot">这次分享没有可用截图。</div>'
        json_text = html.escape(safe_context_json.decode("utf-8"))
        safe_context_script = _json_script(safe_context_json)
        import_manifest_script = _json_script(
            json.dumps(import_manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
        )
        hidden_html = "\n".join(f"<li>{html.escape(str(item))}</li>" for item in hidden_items) or "<li>无</li>"
        body = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)} · WorkRecorder Context</title>
  <style>
    :root {{ color-scheme: light; --ink:#173136; --muted:#6c8186; --line:rgba(36,119,126,.18); --accent:#00a99d; }}
    body {{ margin:0; font:14px/1.6 -apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC",sans-serif; background:linear-gradient(135deg,#f8fcfb,#eef8f7 54%,#f9fbff); color:var(--ink); }}
    main {{ max-width:1040px; margin:40px auto; padding:0 24px 48px; }}
    .shell {{ border:1px solid var(--line); border-radius:28px; background:rgba(255,255,255,.78); box-shadow:0 26px 80px rgba(20,80,88,.12), inset 0 1px rgba(255,255,255,.9); overflow:hidden; }}
    header {{ padding:30px 34px 24px; border-bottom:1px solid var(--line); background:radial-gradient(circle at 90% 0%,rgba(137,198,255,.25),transparent 26%),radial-gradient(circle at 12% 8%,rgba(90,235,205,.25),transparent 24%); }}
    h1 {{ margin:0 0 8px; font-size:28px; letter-spacing:0; }}
    .meta {{ color:var(--muted); display:flex; flex-wrap:wrap; gap:10px 18px; }}
    section {{ padding:26px 34px; border-bottom:1px solid var(--line); }}
    section:last-child {{ border-bottom:0; }}
    h2 {{ margin:0 0 12px; font-size:16px; }}
    pre, .text {{ white-space:pre-wrap; word-break:break-word; background:rgba(248,252,252,.86); border:1px solid var(--line); border-radius:16px; padding:16px; margin:0; }}
    .shot {{ width:100%; display:block; border-radius:18px; border:1px solid var(--line); box-shadow:0 16px 48px rgba(20,80,88,.12); }}
    .empty-shot {{ border:1px dashed var(--line); border-radius:18px; padding:44px; color:var(--muted); text-align:center; }}
    .pill {{ display:inline-flex; align-items:center; border:1px solid rgba(0,169,157,.26); border-radius:999px; padding:5px 10px; background:rgba(227,250,246,.78); color:#078274; font-weight:650; }}
    .grid {{ display:grid; gap:18px; grid-template-columns:1fr 1fr; }}
    @media (max-width:760px) {{ main {{ margin:18px auto; padding:0 12px 32px; }} .grid {{ grid-template-columns:1fr; }} header,section {{ padding:22px; }} }}
  </style>
</head>
<body>
  <main>
    <div class="shell">
      <header>
        <span class="pill">WorkRecorder 安全上下文</span>
        <h1>{html.escape(title)}</h1>
        <div class="meta"><span>{html.escape(app_name)}</span><span>{html.escape(url)}</span><span>{html.escape(captured_at)}</span><span>share {html.escape(share_id)} · r{revision}</span></div>
      </header>
      <section>
        <h2>完整截图</h2>
        {screenshot_html}
      </section>
      <section class="grid">
        <div>
          <h2>用户备注</h2>
          <div class="text">{html.escape(user_note or "无备注")}</div>
        </div>
        <div>
          <h2>框内文本</h2>
          <div class="text">{html.escape(selection_text or "暂无可靠框内文本")}</div>
        </div>
      </section>
      <section>
        <h2>Agent 可读正文</h2>
        <div class="text">{html.escape(clean_page_text or canonical_text or ocr_text or "暂无正文投影")}</div>
      </section>
      <section>
        <h2>未默认分享的原始材料</h2>
        <ul>{hidden_html}</ul>
      </section>
      <section>
        <h2>机器可读 safe_context.json</h2>
        <pre>{json_text}</pre>
      </section>
    </div>
  </main>
  <script type="application/json" id="workrecorder-import-manifest">{import_manifest_script}</script>
  <script type="application/json" id="workrecorder-safe-context">{safe_context_script}</script>
</body>
</html>"""
        return body.encode("utf-8")

    def _text(self, value: object) -> str:
        return value if isinstance(value, str) else str(value or "")


def _json_script(value: bytes) -> str:
    """Return JSON bytes safe for embedding inside an inert script tag."""

    return value.decode("utf-8").replace("</", "<\\/")


def sign_share_import_manifest(manifest: dict[str, object], *, secret: str | None) -> str | None:
    """Sign the immutable import manifest with an installation/org secret.

    Args:
        manifest: Import manifest fields to sign.
        secret: Optional shared secret used for HMAC signing.

    Returns:
        Hex-encoded signature, or None when no secret is configured.
    """

    if not secret:
        return None
    return hmac.new(secret.encode("utf-8"), _signature_payload(manifest), hashlib.sha256).hexdigest()


def verify_share_import_manifest(manifest: dict[str, object], *, secret: str | None) -> bool:
    """Verify a share import manifest signature without leaking timing clues.

    Args:
        manifest: Import manifest containing signature fields.
        secret: Optional shared secret used to recompute the signature.

    Returns:
        True when the manifest signature is present and valid.
    """

    signature = manifest.get("package_signature")
    alg = manifest.get("signature_alg")
    if not isinstance(signature, str) or alg != SHARE_PACKAGE_SIGNATURE_ALG or not secret:
        return False
    expected = sign_share_import_manifest(manifest, secret=secret)
    return expected is not None and hmac.compare_digest(signature, expected)


def _signature_payload(manifest: dict[str, object]) -> bytes:
    signed = {
        "schema_version": manifest.get("schema_version"),
        "share_id": manifest.get("share_id"),
        "event_id": manifest.get("event_id"),
        "revision": manifest.get("revision"),
        "json_sha256": manifest.get("json_sha256"),
        "screenshot_sha256": manifest.get("screenshot_sha256"),
    }
    return json.dumps(signed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
