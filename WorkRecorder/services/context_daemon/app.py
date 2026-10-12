"""FastAPI application factory for the WorkRecorder local daemon."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from packages.agent_runs import AgentRunAccessError
from packages.contracts import ErrorCode
from packages.shared.config import WorkRecorderSettings, SettingsLoader

from .background import CapturePostCommitOutboxWorker
from .container import DaemonContainer
from .routers import (
    active_captures,
    agent_runs,
    artifacts,
    audit,
    auth,
    bundles,
    captures,
    citations,
    disclosure,
    enrichments,
    events,
    evidence,
    health,
    policy,
    providers,
    search,
    settings,
    shares,
    usage,
)


def _agent_run_access_error(request: Request, exc: Exception) -> JSONResponse:
    request_id = request.headers.get("x-request-id") or request.app.state.container.ids.new("req")
    envelope = request.app.state.container.responses.error(
        ErrorCode.NOT_FOUND,
        str(exc) or "Agent run not found",
        request_id=request_id,
    )
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))


class DaemonAppFactory:
    """Build a configured FastAPI daemon application."""

    def __init__(self, settings: WorkRecorderSettings | None = None) -> None:
        """Create an application factory.

        Args:
            settings: Optional settings override for tests.
        """

        self.settings = settings or SettingsLoader().load()

    def create(self) -> FastAPI:
        """Create a FastAPI application with all P0 routers.

        Returns:
            Configured FastAPI application.
        """

        container = DaemonContainer(self.settings)
        worker = CapturePostCommitOutboxWorker(container)
        app = FastAPI(title="WorkRecorder Local Context Daemon", version="0.1.0", lifespan=self._lifespan(worker))
        self._install_browser_extension_cors(app)
        app.state.container = container
        app.add_exception_handler(AgentRunAccessError, _agent_run_access_error)
        app.include_router(health.router)
        app.include_router(auth.router)
        app.include_router(active_captures.router)
        app.include_router(agent_runs.router)
        app.include_router(captures.router)
        app.include_router(citations.router)
        app.include_router(disclosure.router)
        app.include_router(enrichments.router)
        app.include_router(events.router)
        app.include_router(evidence.router)
        app.include_router(search.router)
        app.include_router(shares.router)
        app.include_router(bundles.router)
        app.include_router(artifacts.router)
        app.include_router(audit.router)
        app.include_router(usage.router)
        app.include_router(policy.router)
        app.include_router(providers.router)
        app.include_router(settings.router)
        return app

    def _lifespan(
        self,
        worker: CapturePostCommitOutboxWorker,
    ) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
        @asynccontextmanager
        async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
            worker.start()
            try:
                yield
            finally:
                await worker.stop()

        return lifespan

    def _install_browser_extension_cors(self, app: FastAPI) -> None:
        """Allow the bundled browser extension to call the local daemon.

        Browser extensions run under ``chrome-extension://<id>`` origins and
        perform a real CORS preflight when exchanging the provider-only secret
        for a short-lived provider token. CLI and native clients do not need
        CORS, but Chrome does, so the allow-list is intentionally narrow and
        local.
        """

        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r"^chrome-extension://[a-z]{32}$",
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=[
                "authorization",
                "content-type",
                "x-workrecorder-provider-secret",
                "x-request-id",
            ],
            expose_headers=["x-request-id"],
            allow_credentials=False,
            max_age=600,
        )


def create_app() -> FastAPI:
    """Create the default daemon app for ASGI servers.

    Returns:
        Configured FastAPI application.
    """

    return DaemonAppFactory().create()


app = create_app()
