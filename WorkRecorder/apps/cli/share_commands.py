"""Context-share Typer commands for the WorkRecorder CLI."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from urllib.parse import urlencode

import typer

from packages.contracts import AccessScope, ContextShareCreateRequest, ShareImportRequest, ShareTargetKind

from .client import DaemonClient

ClientFactory = Callable[[], DaemonClient]
PayloadWriter = Callable[[dict[str, object]], None]
RunResolver = Callable[[str | None], str | None]


def build_shares_app(
    *,
    client_factory: ClientFactory,
    write_payload: PayloadWriter,
    resolve_agent_run_id: RunResolver,
) -> typer.Typer:
    """Build the `workrecorder shares` command group.

    Args:
        client_factory: Late-bound daemon client factory.
        write_payload: JSON output function that also tracks active runs.
        resolve_agent_run_id: Resolver for explicit/env/current run ids.

    Returns:
        A configured Typer application for share operations.
    """

    shares_app = typer.Typer(help="Context share link operations.")
    _register_share_commands(
        shares_app,
        client_factory=client_factory,
        write_payload=write_payload,
        resolve_agent_run_id=resolve_agent_run_id,
    )
    return shares_app


def _register_share_commands(
    shares_app: typer.Typer,
    *,
    client_factory: ClientFactory,
    write_payload: PayloadWriter,
    resolve_agent_run_id: RunResolver,
) -> None:
    @shares_app.command("create")
    def _shares_create(
        event_id: str = typer.Option(..., "--event"),
        target: ShareTargetKind = typer.Option(ShareTargetKind.FEISHU_DRIVE, "--target"),
        purpose: str = typer.Option("context_share", "--purpose"),
        copy_link: bool = typer.Option(False, "--copy-link"),
        agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
        json_output: bool = typer.Option(True, "--json/--no-json"),
    ) -> None:
        request = ContextShareCreateRequest(event_id=event_id, target=target, purpose=purpose)
        payload = _as_dict(
            client_factory().post(
                "/v1/shares",
                body=request.model_dump(mode="json"),
                scopes=(AccessScope.CREATE_SHARE, AccessScope.READ_TEXT),
                agent_run_id=resolve_agent_run_id(agent_run_id),
            )
        )
        if copy_link:
            _copy_share_link(payload)
        write_payload(payload)

    @shares_app.command("resolve")
    def _shares_resolve(
        link_or_share_id: str,
        purpose: str = typer.Option("user_shared_context", "--purpose"),
        agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
        json_output: bool = typer.Option(True, "--json/--no-json"),
    ) -> None:
        request = ShareImportRequest(source=link_or_share_id, purpose=purpose)
        write_payload(
            _as_dict(
                client_factory().post(
                    "/v1/shares/resolve",
                    body=request.model_dump(mode="json"),
                    scopes=(AccessScope.READ_SHARE,),
                    agent_run_id=resolve_agent_run_id(agent_run_id),
                )
            )
        )

    @shares_app.command("import")
    def _shares_import(
        link_or_file: str,
        purpose: str = typer.Option("share_import", "--purpose"),
        json_output: bool = typer.Option(True, "--json/--no-json"),
    ) -> None:
        request = ShareImportRequest(source=link_or_file, purpose=purpose)
        write_payload(
            _as_dict(
                client_factory().post(
                    "/v1/shares/import",
                    body=request.model_dump(mode="json"),
                    scopes=_import_scopes(link_or_file),
                )
            )
        )

    @shares_app.command("revoke")
    def _shares_revoke(share_id: str, json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
        write_payload(
            _as_dict(
                client_factory().post(f"/v1/shares/{share_id}/revoke", body={}, scopes=(AccessScope.REVOKE_SHARE,))
            )
        )

    @shares_app.command("sync")
    def _shares_sync(share_id: str, json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
        write_payload(
            _as_dict(
                client_factory().post(
                    f"/v1/shares/{share_id}/sync",
                    body={},
                    scopes=(AccessScope.CREATE_SHARE, AccessScope.READ_TEXT),
                )
            )
        )

    @shares_app.command("ls")
    def _shares_ls(
        user: str | None = typer.Option(None, "--user"),
        limit: int = typer.Option(50, "--limit"),
        json_output: bool = typer.Option(True, "--json/--no-json"),
    ) -> None:
        params = urlencode({key: value for key, value in {"user": user, "limit": limit}.items() if value is not None})
        write_payload(_as_dict(client_factory().get(f"/v1/shares?{params}", scopes=(AccessScope.READ_SHARE,))))

    @shares_app.command("jobs")
    def _shares_jobs(share_id: str, json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
        write_payload(_as_dict(client_factory().get(f"/v1/shares/{share_id}/jobs", scopes=(AccessScope.READ_SHARE,))))


def _copy_share_link(payload: dict[str, object]) -> None:
    data = payload.get("data")
    if not isinstance(data, dict):
        return
    link = data.get("copyable_url")
    if not isinstance(link, str) or not link:
        link = data.get("external_url")
    if not isinstance(link, str) or not link:
        return
    if not link:
        return
    try:
        subprocess.run(["pbcopy"], input=link.encode("utf-8"), check=True, timeout=2)
        data["copied_link"] = link
        data["clipboard"] = "copied"
    except (OSError, subprocess.SubprocessError):
        data["copied_link"] = link
        data["clipboard"] = "failed"


def _import_scopes(source: str) -> tuple[AccessScope, ...]:
    text = source.strip()
    if text.startswith(("workrecorder://share/", "shr_")):
        return (AccessScope.IMPORT_SHARE, AccessScope.READ_SHARE)
    return (AccessScope.IMPORT_SHARE,)


def _as_dict(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise TypeError("Daemon client returned a non-object payload.")
    return payload
