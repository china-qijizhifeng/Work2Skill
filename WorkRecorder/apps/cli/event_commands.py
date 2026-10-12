"""Typer command group for agent-facing context event reads."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import typer

from packages.contracts import AccessScope, EventInspectSection, RetrievalMode, SearchSort

from .agent_commands import ClientFactory, PayloadWriter, RunResolver
from .search_output import SearchOutputCompactor
from .search_params import search_params as _search_params


@dataclass(frozen=True)
class _EventCommandContext:
    client_factory: ClientFactory
    write_payload: PayloadWriter
    resolve_agent_run_id: RunResolver
    search_output: SearchOutputCompactor


def build_events_app(
    *,
    client_factory: ClientFactory,
    write_payload: PayloadWriter,
    resolve_agent_run_id: RunResolver,
) -> typer.Typer:
    """Build the event CLI group without bloating the root entrypoint.

    Args:
        client_factory: Factory returning the configured daemon client.
        write_payload: JSON writer that also updates local agent session state.
        resolve_agent_run_id: Resolver for explicit or active agent run ids.

    Returns:
        Typer application containing event list, search, inspect, and manifest
        commands.
    """

    events_app = typer.Typer(help="Context event discovery.")
    ctx = _EventCommandContext(
        client_factory=client_factory,
        write_payload=write_payload,
        resolve_agent_run_id=resolve_agent_run_id,
        search_output=SearchOutputCompactor(),
    )
    _register_ls(events_app, ctx)
    _register_get(events_app, ctx)
    _register_inspect(events_app, ctx)
    _register_manifest(events_app, ctx)
    _register_grep(events_app, ctx)
    _register_search(events_app, ctx)
    return events_app


def _register_ls(events_app: typer.Typer, ctx: _EventCommandContext) -> None:
    @events_app.command("ls")
    def _events_ls(
        json_output: bool = typer.Option(True, "--json/--no-json"),
        limit: int = typer.Option(50, "--limit"),
        since: str | None = typer.Option(None, "--since"),
        until: str | None = typer.Option(None, "--until"),
        workspace: str | None = typer.Option(None, "--workspace"),
        app_name: str | None = typer.Option(None, "--app"),
        domain: str | None = typer.Option(None, "--domain"),
        origin: str | None = typer.Option(None, "--origin"),
        source: str | None = typer.Option(None, "--source"),
        provider: str | None = typer.Option(None, "--provider"),
        event_type: str | None = typer.Option(None, "--event-type"),
        status: str | None = typer.Option(None, "--status"),
        sensitivity: str | None = typer.Option(None, "--sensitivity"),
        user: str | None = typer.Option(None, "--user"),
        sort: SearchSort = typer.Option(SearchSort.CAPTURED_AT, "--sort"),
        explain: bool = typer.Option(False, "--explain"),
        agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
    ) -> None:
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
            event_type=event_type,
            status=status,
            sensitivity=sensitivity,
            user=user,
            sort=sort,
            explain=explain,
        )
        ctx.write_payload(
            dict(
                ctx.client_factory().get(
                    f"/v1/search?{params}",
                    scopes=(AccessScope.READ_TEXT,),
                    agent_run_id=ctx.resolve_agent_run_id(agent_run_id),
                )
            )
        )


def _register_get(events_app: typer.Typer, ctx: _EventCommandContext) -> None:
    @events_app.command("get")
    def _events_get(
        event_id: str,
        include: str = typer.Option("", "--include"),
        agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
        json_output: bool = typer.Option(True, "--json/--no-json"),
    ) -> None:
        suffix = f"?{urlencode({'include': include})}" if include else ""
        requested_includes = {item.strip() for item in include.split(",") if item.strip()}
        scopes = (
            (AccessScope.READ_METADATA, AccessScope.READ_TEXT)
            if requested_includes.intersection({"evidence", "preview"})
            else (AccessScope.READ_METADATA,)
        )
        ctx.write_payload(
            dict(
                ctx.client_factory().get(
                    f"/v1/events/{event_id}{suffix}",
                    scopes=scopes,
                    agent_run_id=ctx.resolve_agent_run_id(agent_run_id),
                )
            )
        )


def _register_inspect(events_app: typer.Typer, ctx: _EventCommandContext) -> None:
    @events_app.command("inspect")
    def _events_inspect(
        event_id: str,
        purpose: str = typer.Option("event_inspect", "--purpose"),
        view: list[EventInspectSection] | None = typer.Option(None, "--view"),
        agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
        json_output: bool = typer.Option(True, "--json/--no-json"),
    ) -> None:
        params = {"view": "event_inspect", "purpose": purpose}
        if view:
            params["inspect_views"] = ",".join(item.value for item in view)
        ctx.write_payload(
            dict(
                ctx.client_factory().get(
                    f"/v1/events/{event_id}?{urlencode(params)}",
                    scopes=(AccessScope.READ_METADATA, AccessScope.READ_TEXT),
                    agent_run_id=ctx.resolve_agent_run_id(agent_run_id),
                )
            )
        )


def _register_manifest(events_app: typer.Typer, ctx: _EventCommandContext) -> None:
    @events_app.command("manifest")
    def _events_manifest(
        event_id: str,
        agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
        json_output: bool = typer.Option(True, "--json/--no-json"),
    ) -> None:
        ctx.write_payload(
            dict(
                ctx.client_factory().get(
                    f"/v1/events/{event_id}/manifest",
                    scopes=(AccessScope.READ_METADATA,),
                    agent_run_id=ctx.resolve_agent_run_id(agent_run_id),
                )
            )
        )


def _register_grep(events_app: typer.Typer, ctx: _EventCommandContext) -> None:
    @events_app.command("grep")
    def _events_grep(
        query: str,
        json_output: bool = typer.Option(True, "--json/--no-json"),
        limit: int = typer.Option(20, "--limit"),
        since: str | None = typer.Option(None, "--since"),
        until: str | None = typer.Option(None, "--until"),
        workspace: str | None = typer.Option(None, "--workspace"),
        app_name: str | None = typer.Option(None, "--app"),
        domain: str | None = typer.Option(None, "--domain"),
        source: str | None = typer.Option(None, "--source"),
        provider: str | None = typer.Option(None, "--provider"),
        status: str | None = typer.Option(None, "--status"),
        user: str | None = typer.Option(None, "--user"),
        explain: bool = typer.Option(False, "--explain"),
        agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
    ) -> None:
        params = _search_params(
            query=query,
            mode=RetrievalMode.KEYWORD,
            limit=limit,
            since=since,
            until=until,
            workspace=workspace,
            app_name=app_name,
            domain=domain,
            source=source,
            provider=provider,
            status=status,
            user=user,
            sort=SearchSort.SCORE,
            explain=explain,
        )
        payload = dict(
            ctx.client_factory().get(
                f"/v1/search?{params}",
                scopes=(AccessScope.READ_TEXT,),
                agent_run_id=ctx.resolve_agent_run_id(agent_run_id),
            )
        )
        ctx.write_payload(ctx.search_output.compact_envelope(payload))


def _register_search(events_app: typer.Typer, ctx: _EventCommandContext) -> None:
    @events_app.command("search")
    def _events_search(
        query: str,
        mode: RetrievalMode = typer.Option(RetrievalMode.KEYWORD, "--mode"),
        json_output: bool = typer.Option(True, "--json/--no-json"),
        limit: int = typer.Option(20, "--limit"),
        since: str | None = typer.Option(None, "--since"),
        until: str | None = typer.Option(None, "--until"),
        workspace: str | None = typer.Option(None, "--workspace"),
        app_name: str | None = typer.Option(None, "--app"),
        domain: str | None = typer.Option(None, "--domain"),
        origin: str | None = typer.Option(None, "--origin"),
        source: str | None = typer.Option(None, "--source"),
        provider: str | None = typer.Option(None, "--provider"),
        event_type: str | None = typer.Option(None, "--event-type"),
        evidence_kind: str | None = typer.Option(None, "--evidence-kind"),
        status: str | None = typer.Option(None, "--status"),
        sensitivity: str | None = typer.Option(None, "--sensitivity"),
        entity: str | None = typer.Option(None, "--entity"),
        project: str | None = typer.Option(None, "--project"),
        user: str | None = typer.Option(None, "--user"),
        cursor: str | None = typer.Option(None, "--cursor"),
        sort: SearchSort = typer.Option(SearchSort.SCORE, "--sort"),
        explain: bool = typer.Option(False, "--explain"),
        agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
    ) -> None:
        params = _search_params(
            query=query,
            mode=mode,
            limit=limit,
            since=since,
            until=until,
            workspace=workspace,
            app_name=app_name,
            domain=domain,
            origin=origin,
            source=source,
            provider=provider,
            event_type=event_type,
            evidence_kind=evidence_kind,
            status=status,
            sensitivity=sensitivity,
            entity=entity,
            project=project,
            user=user,
            cursor=cursor,
            sort=sort,
            explain=explain,
        )
        payload = dict(
            ctx.client_factory().get(
                f"/v1/search?{params}",
                scopes=(AccessScope.READ_TEXT,),
                agent_run_id=ctx.resolve_agent_run_id(agent_run_id),
            )
        )
        ctx.write_payload(ctx.search_output.compact_envelope(payload))
