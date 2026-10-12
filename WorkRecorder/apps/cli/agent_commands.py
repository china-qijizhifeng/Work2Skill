"""Agent-run Typer commands for the WorkRecorder CLI."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from urllib.parse import urlencode

import typer

from packages.contracts import AccessScope, AgentRunBeginRequest, AgentRunOrigin

from .client import DaemonClient

ClientFactory = Callable[[], DaemonClient]
PayloadWriter = Callable[[dict[str, object]], None]
RunResolver = Callable[[str | None], str | None]


def build_agent_app(
    *,
    client_factory: ClientFactory,
    write_payload: PayloadWriter,
    resolve_agent_run_id: RunResolver,
) -> typer.Typer:
    """Build the `workrecorder agent` command group.

    Args:
        client_factory: Late-bound factory for the daemon client.
        write_payload: Output function that also remembers returned run ids.
        resolve_agent_run_id: Resolver for explicit, env, or stored run ids.

    Returns:
        A configured Typer application for agent-run commands.
    """

    agent_app = typer.Typer(help="Agent run ledger operations.")
    _register_run_start_commands(agent_app, client_factory=client_factory, write_payload=write_payload)
    _register_run_read_commands(
        agent_app,
        client_factory=client_factory,
        write_payload=write_payload,
        resolve_agent_run_id=resolve_agent_run_id,
    )
    return agent_app


def _register_run_start_commands(
    agent_app: typer.Typer,
    *,
    client_factory: ClientFactory,
    write_payload: PayloadWriter,
) -> None:
    @agent_app.command("begin")
    def _agent_begin(
        purpose: str = typer.Option("agent_context", "--purpose"),
        agent: str = typer.Option("codex", "--agent"),
        question: str | None = typer.Option(None, "--question"),
        workspace: str | None = typer.Option(None, "--workspace"),
        json_output: bool = typer.Option(True, "--json/--no-json"),
    ) -> None:
        request = AgentRunBeginRequest(
            agent=agent,
            purpose=purpose,
            user_question=question,
            workspace_id=workspace,
            origin=AgentRunOrigin.CLI_EXPLICIT,
        )
        write_payload(
            _as_dict(
                client_factory().post(
                    "/v1/agent-runs",
                    body=request.model_dump(mode="json"),
                    scopes=(AccessScope.READ_METADATA,),
                )
            )
        )


def _register_run_read_commands(
    agent_app: typer.Typer,
    *,
    client_factory: ClientFactory,
    write_payload: PayloadWriter,
    resolve_agent_run_id: RunResolver,
) -> None:
    @agent_app.command("current")
    def _agent_current(json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
        write_payload(
            _as_dict(
                client_factory().get(
                    "/v1/agent-runs/current",
                    scopes=(AccessScope.READ_METADATA,),
                    agent_run_id=resolve_agent_run_id(None),
                )
            )
        )

    @agent_app.command("end")
    def _agent_end(
        agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
        status: str = typer.Option("completed", "--status"),
        json_output: bool = typer.Option(True, "--json/--no-json"),
    ) -> None:
        run_id = resolve_agent_run_id(agent_run_id)
        if not run_id:
            raise typer.BadParameter("No active agent run. Use `workrecorder agent begin` first.")
        write_payload(
            _as_dict(
                client_factory().post(
                    f"/v1/agent-runs/{run_id}/end?{urlencode({'status': status})}",
                    body={},
                    scopes=(AccessScope.RECORD_USAGE,),
                    agent_run_id=run_id,
                )
            )
        )

    @agent_app.command("replay")
    def _agent_replay(
        agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
        json_output: bool = typer.Option(True, "--json/--no-json"),
    ) -> None:
        run_id = resolve_agent_run_id(agent_run_id)
        if not run_id:
            raise typer.BadParameter("No active agent run. Use `workrecorder agent begin` first.")
        write_payload(
            _as_dict(
                client_factory().get(
                    f"/v1/agent-runs/{run_id}/replay",
                    scopes=(AccessScope.READ_TEXT,),
                    agent_run_id=run_id,
                )
            )
        )

    @agent_app.command("export")
    def _agent_export(
        agent_run_id: str | None = typer.Option(None, "--agent-run-id"),
        format: str = typer.Option("json", "--format"),
        json_output: bool = typer.Option(True, "--json/--no-json"),
    ) -> None:
        run_id = resolve_agent_run_id(agent_run_id)
        if not run_id:
            raise typer.BadParameter("No active agent run. Use `workrecorder agent begin` first.")
        write_payload(
            _as_dict(
                client_factory().get(
                    f"/v1/agent-runs/{run_id}/replay?{urlencode({'format': format})}",
                    scopes=(AccessScope.READ_TEXT,),
                    agent_run_id=run_id,
                )
            )
        )


def _as_dict(payload: Mapping[str, object]) -> dict[str, object]:
    return dict(payload)
