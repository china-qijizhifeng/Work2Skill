"""Typer entrypoint for the WorkRecorder `workrecorder` command."""

from __future__ import annotations

import base64
import binascii
import json
import os
import sys
from pathlib import Path
from typing import cast
from urllib.parse import urlencode, urlparse

import typer

from packages.contracts import (
    AccessScope,
    BundleRequest,
    RetrievalMode,
)

from .agent_commands import ClientFactory, PayloadWriter, RunResolver, build_agent_app
from .agent_session import DEFAULT_AGENT_SESSION_PATH, AgentSessionStore
from .client import DaemonClient
from .error_handling import run_cli_app
from .event_commands import build_events_app
from .output import OutputWriter
from .search_params import search_params as _search_params
from .share_commands import build_shares_app

DEFAULT_DAEMON_URL = "http://127.0.0.1:8765"
DEFAULT_INSTALL_SECRET = "dev-install-secret"
AGENT_SESSION_PATH = DEFAULT_AGENT_SESSION_PATH

app = typer.Typer(help="WorkRecorder local context CLI.")
daemon_app = typer.Typer(help="Daemon operations.")
events_app = build_events_app(
    client_factory=lambda: _client(),
    write_payload=cast(PayloadWriter, lambda payload: _write(payload)),
    resolve_agent_run_id=cast(RunResolver, lambda explicit=None: _resolved_agent_run_id(explicit)),
)
artifacts_app = typer.Typer(help="Artifact evidence access.")
evidence_app = typer.Typer(help="Evidence ledger access.")
bundle_app = typer.Typer(help="Context bundle operations.")
usage_app = typer.Typer(help="Usage audit operations.")
agent_app = build_agent_app(
    client_factory=lambda: _client(),
    write_payload=cast(PayloadWriter, lambda payload: _write(payload)),
    resolve_agent_run_id=cast(RunResolver, lambda explicit=None: _resolved_agent_run_id(explicit)),
)
citations_app = typer.Typer(help="Citation lookup operations.")
shares_app = build_shares_app(
    client_factory=lambda: _client(),
    write_payload=cast(PayloadWriter, lambda payload: _write(payload)),
    resolve_agent_run_id=cast(RunResolver, lambda explicit=None: _resolved_agent_run_id(explicit)),
)
providers_app = typer.Typer(help="Capture provider diagnostics.")
captures_app = typer.Typer(help="Capture attempt diagnostics.")
audit_app = typer.Typer(help="Audit trail export.")
disclosure_app = typer.Typer(help="Disclosure policy diagnostics.")
sources_app = typer.Typer(help="Safe source facet discovery.")
entities_app = typer.Typer(help="Safe entity facet discovery.")

app.add_typer(daemon_app, name="daemon")
app.add_typer(events_app, name="events")
app.add_typer(artifacts_app, name="artifacts")
app.add_typer(evidence_app, name="evidence")
app.add_typer(bundle_app, name="bundle")
app.add_typer(usage_app, name="usage")
app.add_typer(agent_app, name="agent")
app.add_typer(citations_app, name="citations")
app.add_typer(providers_app, name="providers")
app.add_typer(captures_app, name="captures")
app.add_typer(audit_app, name="audit")
app.add_typer(disclosure_app, name="disclosure")
app.add_typer(sources_app, name="sources")
app.add_typer(entities_app, name="entities")
app.add_typer(shares_app, name="shares")


@daemon_app.command("health")
def _daemon_health(json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
    client = _client()
    _writer().write_json(client.health())


@artifacts_app.command("cat")
def _artifacts_cat(
    artifact_id: str,
    event_id: str = typer.Option(..., "--event"),
    purpose: str = typer.Option("artifact_preview", "--purpose"),
    agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
    redacted: bool = typer.Option(True, "--redacted/--raw"),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    client = _client()
    if redacted:
        run_id = _resolved_agent_run_id(agent_run_id)
        params = urlencode({"event_id": event_id, "purpose": purpose})
        _write(
            dict(
                client.get(
                    f"/v1/artifacts/{artifact_id}/content?{params}",
                    scopes=(AccessScope.READ_TEXT,),
                    agent_run_id=run_id,
                )
            )
        )
        return
    raise typer.BadParameter("Use `workrecorder artifacts raw` for explicit raw artifact disclosure.")


@artifacts_app.command("raw")
def _artifacts_raw(
    artifact_id: str,
    event_id: str = typer.Option(..., "--event"),
    purpose: str = typer.Option(..., "--purpose"),
    agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        dir_okay=False,
        resolve_path=True,
        help="Write raw bytes to a local file and print only audit metadata.",
    ),
    inline: bool = typer.Option(
        False,
        "--inline/--metadata-only",
        help="Include raw base64 in stdout. Default omits raw content for agent safety.",
    ),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    client = _client()
    run_id = _resolved_agent_run_id(agent_run_id)
    params = urlencode({"event_id": event_id, "purpose": purpose})
    payload = dict(
        client.get(
            f"/v1/artifacts/{artifact_id}/raw?{params}",
            scopes=(AccessScope.READ_RAW_ARTIFACT,),
            agent_run_id=run_id,
        )
    )
    _write(_prepare_raw_artifact_cli_payload(payload, output=output, inline=inline))


def _prepare_raw_artifact_cli_payload(
    payload: dict[str, object], *, output: Path | None, inline: bool
) -> dict[str, object]:
    """Keep raw artifact CLI output small unless explicitly requested.

    The daemon still performs the audited raw disclosure. The CLI simply avoids
    dumping large base64 blobs into agent stdout by default.
    """

    data = payload.get("data")
    if not isinstance(data, dict):
        return payload
    content_base64 = data.get("content_base64")
    if output is not None:
        if not isinstance(content_base64, str):
            raise typer.BadParameter("raw artifact response did not include content_base64")
        try:
            raw_bytes = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise typer.BadParameter("raw artifact response contained invalid base64") from exc
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(raw_bytes)
        data["output_path"] = str(output)
        data["wrote_bytes"] = len(raw_bytes)
    if not inline:
        omitted = "content_base64" in data
        data.pop("content_base64", None)
        data["content_base64_omitted"] = omitted
        data["raw_content_hint"] = "Use --output <file> to write bytes, or --inline to print base64."
    return payload


@artifacts_app.command("verify")
def _artifacts_verify(artifact_id: str, json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
    client = _client()
    _writer().write_json(client.get(f"/v1/artifacts/{artifact_id}/verify", scopes=(AccessScope.READ_METADATA,)))


@evidence_app.command("ls")
def _evidence_ls(
    event: str = typer.Option(..., "--event"),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    client = _client()
    _writer().write_json(client.get(f"/v1/evidence?{urlencode({'event': event})}", scopes=(AccessScope.READ_METADATA,)))


@evidence_app.command("show")
def _evidence_show(evidence_id: str, json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
    client = _client()
    _writer().write_json(client.get(f"/v1/evidence/{evidence_id}", scopes=(AccessScope.READ_METADATA,)))


@bundle_app.command("create")
def _bundle_create(
    query: str = typer.Option(..., "--query"),
    purpose: str = typer.Option(..., "--purpose"),
    entity: str | None = typer.Option(None, "--entity"),
    max_tokens: int = typer.Option(8000, "--max-tokens"),
    agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    request = BundleRequest(query=query, purpose=purpose, entity=entity, max_tokens=max_tokens)
    client = _client()
    _write(
        dict(
            client.post(
                "/v1/context-bundles",
                body=request.model_dump(mode="json"),
                scopes=(AccessScope.CREATE_BUNDLE, AccessScope.READ_TEXT),
                agent_run_id=_resolved_agent_run_id(agent_run_id),
            )
        )
    )


@bundle_app.command("show")
def _bundle_show(
    bundle_id: str,
    agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    client = _client()
    _write(
        dict(
            client.get(
                f"/v1/context-bundles/{bundle_id}",
                scopes=(AccessScope.READ_TEXT,),
                agent_run_id=_resolved_agent_run_id(agent_run_id),
            )
        )
    )


@bundle_app.command("export")
def _bundle_export(
    bundle_id: str,
    format: str = typer.Option("markdown", "--format"),
    agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    client = _client()
    params = urlencode({"format": format})
    _write(
        dict(
            client.get(
                f"/v1/context-bundles/{bundle_id}/export?{params}",
                scopes=(AccessScope.READ_TEXT,),
                agent_run_id=_resolved_agent_run_id(agent_run_id),
            )
        )
    )


@usage_app.command("record")
def _usage_record(
    bundle: str = typer.Option(..., "--bundle"),
    agent: str = typer.Option(..., "--agent"),
    purpose: str = typer.Option(..., "--purpose"),
    output_ref: str = typer.Option(..., "--output-ref"),
    used_citation: list[str] | None = typer.Option(None, "--used-citation"),
    risk_advisory: list[str] | None = typer.Option(None, "--risk-advisory"),
    answer_hash: str | None = typer.Option(None, "--answer-hash"),
    agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    client = _client()
    run_id = _resolved_agent_run_id(agent_run_id)
    _write(
        dict(
            client.post(
                "/v1/agent-usage-events",
                body={
                    "bundle_id": bundle,
                    "agent_run_id": run_id,
                    "agent": agent,
                    "purpose": purpose,
                    "output_ref": output_ref,
                    "citation_ids": tuple(used_citation or ()),
                    "risk_advisory_ids": tuple(risk_advisory or ()),
                    "answer_hash": answer_hash,
                },
                scopes=(AccessScope.RECORD_USAGE,),
                agent_run_id=run_id,
            )
        )
    )


@citations_app.command("resolve")
def _citations_resolve(
    citation_id: str,
    agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    _write(
        dict(
            _client().get(
                f"/v1/citations/{citation_id}",
                scopes=(AccessScope.READ_TEXT,),
                agent_run_id=_resolved_agent_run_id(agent_run_id),
            )
        )
    )


@providers_app.command("ls")
def _providers_ls(json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
    client = _client()
    _writer().write_json(client.get("/v1/providers", scopes=(AccessScope.READ_METADATA,)))


@providers_app.command("sessions")
def _providers_sessions(json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
    client = _client()
    _writer().write_json(client.get("/v1/providers/sessions", scopes=(AccessScope.READ_METADATA,)))


@providers_app.command("manifests")
def _providers_manifests(json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
    client = _client()
    _writer().write_json(client.get("/v1/providers/manifests", scopes=(AccessScope.READ_METADATA,)))


@disclosure_app.command("profiles")
def _disclosure_profiles(json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
    client = _client()
    _writer().write_json(client.get("/v1/disclosure/profiles", scopes=(AccessScope.READ_METADATA,)))


@captures_app.command("diagnose")
def _captures_diagnose(
    trigger: str = typer.Option(..., "--trigger"),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    client = _client()
    _writer().write_json(client.get(f"/v1/captures/diagnose/{trigger}", scopes=(AccessScope.READ_METADATA,)))


@audit_app.command("export")
def _audit_export(
    event: str = typer.Option(..., "--event"),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    client = _client()
    _writer().write_json(client.get(f"/v1/audit?{urlencode({'event': event})}", scopes=(AccessScope.READ_METADATA,)))


@sources_app.command("ls")
def _sources_ls(
    json_output: bool = typer.Option(True, "--json/--no-json"),
    limit: int = typer.Option(100, "--limit"),
    since: str | None = typer.Option(None, "--since"),
    until: str | None = typer.Option(None, "--until"),
    workspace: str | None = typer.Option(None, "--workspace"),
    app_name: str | None = typer.Option(None, "--app"),
    domain: str | None = typer.Option(None, "--domain"),
    origin: str | None = typer.Option(None, "--origin"),
    source: str | None = typer.Option(None, "--source"),
    provider: str | None = typer.Option(None, "--provider"),
    status: str | None = typer.Option(None, "--status"),
    user: str | None = typer.Option(None, "--user"),
) -> None:
    client = _client()
    params = _search_params(
        query="",
        mode=RetrievalMode.KEYWORD,
        limit=limit,
        since=since,
        until=until,
        workspace=workspace,
        app_name=app_name,
        domain=domain,
        origin=origin,
        source=source,
        provider=provider,
        status=status,
        user=user,
    )
    _writer().write_json(client.get(f"/v1/search/facets?{params}", scopes=(AccessScope.READ_METADATA,)))


@entities_app.command("ls")
def _entities_ls(
    query: str = typer.Option("", "--query"),
    json_output: bool = typer.Option(True, "--json/--no-json"),
    limit: int = typer.Option(100, "--limit"),
) -> None:
    client = _client()
    params = urlencode({"query": query, "limit": limit})
    _writer().write_json(client.get(f"/v1/search/entities?{params}", scopes=(AccessScope.READ_METADATA,)))


def main() -> int | None:
    """Run the WorkRecorder CLI.

    Returns:
        ``None`` on success, or ``1`` after an expected JSON error envelope.
    """

    return run_cli_app(app, writer=_writer())


def _client() -> DaemonClient:
    return DaemonClient(
        base_url=_daemon_url(),
        install_secret=_install_secret(),
    )


def _daemon_url() -> str:
    """Resolve the daemon URL shared by the App, browser extension, and CLI."""

    if daemon_url := os.environ.get("WORKRECORDER_DAEMON_URL"):
        _require_loopback_daemon_url(daemon_url)
        return daemon_url
    if endpoint := _selected_endpoint_payload():
        return endpoint.daemon_url
    return DEFAULT_DAEMON_URL


def _require_loopback_daemon_url(daemon_url: str) -> None:
    if not _is_loopback_daemon_url(daemon_url):
        raise typer.BadParameter("WorkRecorder daemon URL must use a loopback host.")


def _is_loopback_daemon_url(daemon_url: str) -> bool:
    parsed = urlparse(daemon_url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and host in {"127.0.0.1", "localhost", "::1"}


def _install_secret() -> str:
    """Resolve the local daemon install secret for CLI token exchange."""

    if secret := os.environ.get("WORKRECORDER_INSTALL_SECRET"):
        return secret
    if endpoint := _selected_endpoint_payload():
        return endpoint.install_secret
    return DEFAULT_INSTALL_SECRET


class _EndpointPayload:
    def __init__(self, daemon_url: str, install_secret: str) -> None:
        self.daemon_url = daemon_url
        self.install_secret = install_secret


def _selected_endpoint_payload() -> _EndpointPayload | None:
    """Return the first config whose URL and secret describe the same daemon."""

    for payload in _endpoint_payloads():
        daemon_url = payload.get("daemon_url")
        install_secret = payload.get("install_secret")
        if (
            isinstance(daemon_url, str)
            and _is_loopback_daemon_url(daemon_url)
            and isinstance(install_secret, str)
            and len(install_secret) >= 8
        ):
            return _EndpointPayload(daemon_url=daemon_url, install_secret=install_secret)
    return None


def _endpoint_payloads() -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    config_path = Path.home() / ".workrecorder/app-dev/daemon-endpoint.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return payloads
    if isinstance(payload, dict):
        payloads.append(payload)
    return payloads


def _writer() -> OutputWriter:
    return OutputWriter()


def _write(payload: dict[str, object]) -> None:
    AgentSessionStore(AGENT_SESSION_PATH).remember_from_payload(payload)
    _writer().write_json(payload)


def _resolved_agent_run_id(explicit: str | None = None) -> str | None:
    return AgentSessionStore(AGENT_SESSION_PATH).resolve(explicit)


if __name__ == "__main__":
    sys.exit(main())
