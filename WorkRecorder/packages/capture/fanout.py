"""Fan out capture commands to all selected app/source providers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from packages.capture.commands import ProviderCommandService
from packages.contracts import (
    CaptureAttemptRequest,
    DetectedSurface,
    ProviderCaptureOutcome,
    ProviderCaptureOutcomeStatus,
    ProviderCommandRun,
    ProviderCommandStatus,
    ProviderEvidenceBundle,
    ProviderKind,
    ProviderRouteCandidate,
    ProviderRoutePlan,
    ProviderRouteRole,
    SurfaceDetectionResult,
)
from packages.providers.registry import SourceProviderRegistry
from packages.shared.time import Clock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppProviderFanoutResult:
    """Aggregated app-provider command result for one capture run.

    Attributes:
        app_bundles: Successful app/source bundles that should be persisted.
        command_runs: Durable command diagnostics for selected provider routes.
        outcomes: Selected, skipped, failed, and stale outcomes for routed app providers.
    """

    app_bundles: tuple[ProviderEvidenceBundle, ...]
    command_runs: tuple[ProviderCommandRun, ...]
    outcomes: tuple[ProviderCaptureOutcome, ...]


class AppProviderFanoutService:
    """Collect optional app/source evidence without gating event persistence."""

    def __init__(
        self,
        *,
        providers: SourceProviderRegistry,
        commands: ProviderCommandService,
        clock: Clock,
    ) -> None:
        self.providers = providers
        self.commands = commands
        self.clock = clock

    async def collect(
        self,
        *,
        attempt: CaptureAttemptRequest,
        detection: SurfaceDetectionResult,
        route_plan: ProviderRoutePlan,
    ) -> AppProviderFanoutResult:
        """Run selected app routes concurrently and keep all route outcomes.

        Args:
            attempt: Capture attempt being enriched by optional app providers.
            detection: Surface detection result used to resolve route targets.
            route_plan: Multi-route plan produced by provider routing.

        Returns:
            App evidence bundles, command runs, and auditable provider outcomes.
        """

        surfaces_by_id = {surface.surface_id: surface for surface in detection.surfaces}
        selected_tasks = [
            self._collect_route(attempt=attempt, route=route, surface=surfaces_by_id.get(route.surface_id or ""))
            for route in route_plan.routes
            if route.selected and route.provider_kind == ProviderKind.SOURCE
        ]
        completed = await asyncio.gather(*selected_tasks) if selected_tasks else ()
        bundles: list[ProviderEvidenceBundle] = []
        command_runs: list[ProviderCommandRun] = []
        outcomes: list[ProviderCaptureOutcome] = []
        for result in completed:
            if result.bundle is not None:
                bundles.append(result.bundle)
            if result.command_run is not None:
                command_runs.append(result.command_run)
            outcomes.append(result.outcome)
        selected_ids = {outcome.route_id for outcome in outcomes if outcome.route_id is not None}
        for route in route_plan.routes:
            if route.provider_kind != ProviderKind.SOURCE or route.route_id in selected_ids:
                continue
            outcomes.append(self._skipped_outcome(route))
        logger.info(
            "app provider fanout completed trigger_id=%s selected_routes=%s bundles=%s outcomes=%s",
            route_plan.trigger_id,
            len(selected_tasks),
            len(bundles),
            len(outcomes),
            extra={
                "trigger_id": route_plan.trigger_id,
                "selected_route_count": len(selected_tasks),
                "app_bundle_count": len(bundles),
                "provider_outcome_count": len(outcomes),
            },
        )
        return AppProviderFanoutResult(
            app_bundles=tuple(bundles),
            command_runs=tuple(command_runs),
            outcomes=tuple(outcomes),
        )

    async def _collect_route(
        self, *, attempt: CaptureAttemptRequest, route: ProviderRouteCandidate, surface: DetectedSurface | None
    ) -> "_RouteCollectResult":
        provider = self.providers.get(route.provider_key)
        if provider is None or surface is None:
            return _RouteCollectResult(
                bundle=None,
                command_run=None,
                outcome=ProviderCaptureOutcome(
                    route_id=route.route_id,
                    provider_key=route.provider_key,
                    provider_kind=route.provider_kind,
                    surface_id=route.surface_id,
                    role=route.role,
                    status=ProviderCaptureOutcomeStatus.SKIPPED,
                    reason_code="provider_or_surface_missing",
                    diagnostics={"surface_id": route.surface_id},
                ),
            )
        command = provider.collect_command(attempt=attempt, surface=surface, route=route)
        result = await self.commands.collect(
            command=command,
            surface=surface,
            evidence_kind=provider.capture_evidence_kind,
        )
        bundle = provider.bundle_from_result(attempt=attempt, surface=surface, result=result, route=route)
        outcome_status = self._outcome_status(result.status, bundle)
        reason_code = None
        if outcome_status != ProviderCaptureOutcomeStatus.SUCCEEDED:
            reason_code = result.error_message or result.status.value
        command_run = ProviderCommandRun(
            command_id=result.command_id,
            provider_key=result.provider_key,
            provider_session_id=result.provider_session_id,
            route_id=route.route_id,
            status=result.status,
            evidence_kind=result.evidence_kind,
            completed_at=result.completed_at,
            error_message=result.error_message,
            diagnostics=result.diagnostics,
        )
        outcome = ProviderCaptureOutcome(
            route_id=route.route_id,
            provider_key=route.provider_key,
            provider_kind=route.provider_kind,
            surface_id=route.surface_id,
            role=route.role,
            status=outcome_status,
            reason_code=reason_code,
            command_id=result.command_id,
            provider_session_id=result.provider_session_id,
            diagnostics=result.diagnostics,
        )
        return _RouteCollectResult(bundle=bundle, command_run=command_run, outcome=outcome)

    def _skipped_outcome(self, route: ProviderRouteCandidate) -> ProviderCaptureOutcome:
        status = (
            ProviderCaptureOutcomeStatus.STALE
            if route.reason == "stale_provider_context"
            else ProviderCaptureOutcomeStatus.SKIPPED
        )
        return ProviderCaptureOutcome(
            route_id=route.route_id,
            provider_key=route.provider_key,
            provider_kind=route.provider_kind,
            surface_id=route.surface_id,
            role=route.role,
            status=status,
            reason_code=route.reason,
            diagnostics={"confidence": route.confidence},
        )

    def _outcome_status(
        self, status: ProviderCommandStatus, bundle: ProviderEvidenceBundle | None
    ) -> ProviderCaptureOutcomeStatus:
        if status == ProviderCommandStatus.SUCCEEDED and bundle is not None:
            return ProviderCaptureOutcomeStatus.SUCCEEDED
        if status == ProviderCommandStatus.SUCCEEDED:
            return ProviderCaptureOutcomeStatus.FAILED
        if status == ProviderCommandStatus.TIMEOUT:
            return ProviderCaptureOutcomeStatus.TIMEOUT
        if status == ProviderCommandStatus.UNSUPPORTED:
            return ProviderCaptureOutcomeStatus.UNSUPPORTED
        if status == ProviderCommandStatus.SKIPPED:
            return ProviderCaptureOutcomeStatus.SKIPPED
        return ProviderCaptureOutcomeStatus.FAILED


@dataclass(frozen=True)
class _RouteCollectResult:
    bundle: ProviderEvidenceBundle | None
    command_run: ProviderCommandRun | None
    outcome: ProviderCaptureOutcome
