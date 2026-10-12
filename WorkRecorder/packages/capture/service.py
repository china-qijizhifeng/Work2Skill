"""Service layer for native capture hot-path persistence."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from packages.artifacts.vault import ArtifactVaultError, LocalArtifactVault
from packages.capture.fanout import AppProviderFanoutService
from packages.capture.system_evidence import SystemEvidenceOrchestrator
from packages.contracts import (
    AccessScope,
    Artifact,
    ArtifactType,
    CaptureAttemptRequest,
    CaptureAttemptResponse,
    CaptureAttemptStatus,
    CaptureSaveRequest,
    CaptureSaveResponse,
    ContextEvent,
    EventStatus,
    ProviderCommandRun,
    ProviderEvidenceBundle,
    ProviderRoutePlan,
    RedactionState,
    SourceBinding,
    UnsupportedReason,
    UserRef,
    WindowHint,
    WorkspaceSelection,
)
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from packages.storage.capture_repository import CaptureRepository

from .persistence import CapturePersistenceService
from .routing import ProviderRoutingService
from .surface import SurfaceDetectionService

logger = logging.getLogger(__name__)


class CaptureIngestService:
    """Persist a native screenshot as a context event plus artifact."""

    def __init__(
        self,
        *,
        captures: CaptureRepository,
        vault: LocalArtifactVault,
        ids: IdFactory,
        clock: Clock,
    ) -> None:
        """Create a capture ingest service.

        Args:
            captures: Atomic capture repository.
            vault: Local artifact vault for staged screenshot files.
            ids: Identifier generator.
            clock: Shared clock.
        """

        self.captures = captures
        self.vault = vault
        self.ids = ids
        self.clock = clock

    def save(self, request: CaptureSaveRequest) -> CaptureSaveResponse:
        """Promote a staged screenshot and persist its event metadata.

        Args:
            request: Typed capture save request from a native shell.

        Returns:
            Persisted capture response with event and screenshot artifact.

        Raises:
            ArtifactVaultError: When staged screenshot type, MIME, path, or
                bytes are not valid for native capture ingestion.
        """

        if request.staged_artifact.artifact_type != ArtifactType.SCREENSHOT:
            raise ArtifactVaultError("native capture only accepts screenshot artifacts")
        if request.staged_artifact.content_type != "image/png":
            raise ArtifactVaultError("native capture only accepts image/png artifacts")
        existing = self.find_by_trigger_id(request.trigger.trigger_id)
        if existing is not None:
            return existing
        now = self.clock.now()
        event = ContextEvent(
            event_id=self.ids.new("evt"),
            event_type=request.event_type,
            trigger=request.trigger,
            source_binding=request.source_binding,
            status=EventStatus.PENDING_ENRICHMENT,
            intent_text=request.intent_text or request.trigger.intent_text,
            created_at=now,
            updated_at=now,
            user=UserRef.from_actor(request.trigger.actor),
        )
        artifact_id = self.ids.new("art")
        promoted = self.vault.promote(
            staged_path=Path(request.staged_artifact.local_path),
            artifact_id=artifact_id,
            created_at=now,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            event_id=event.event_id,
            artifact_type=request.staged_artifact.artifact_type,
            role="visual_evidence",
            storage_uri=promoted.storage_uri,
            redaction_state=RedactionState.QUARANTINED,
            allowed_scopes=(AccessScope.READ_METADATA, AccessScope.READ_THUMBNAIL),
            metadata={
                "content_type": request.staged_artifact.content_type,
                "sha256": promoted.sha256,
                "byte_size": promoted.byte_size,
                "workspace_id": request.workspace.workspace_id,
                "workspace_auto": request.workspace.auto,
                "display_id": request.selection_geometry.display.display_id,
                "display_scale_factor": request.selection_geometry.display.scale_factor,
                "selection_x": request.selection_geometry.selected_region.x,
                "selection_y": request.selection_geometry.selected_region.y,
                "selection_width": request.selection_geometry.selected_region.width,
                "selection_height": request.selection_geometry.selected_region.height,
                "visual_ocr_upload_allowed": True,
            },
            created_at=now,
        )
        try:
            saved_event, saved_artifact = self.captures.save_event_and_artifact(event=event, artifact=artifact)
        except Exception:
            logger.exception(
                "capture repository write failed after vault promotion", extra={"artifact_id": artifact_id}
            )
            raise
        return CaptureSaveResponse(
            event=saved_event,
            artifact=saved_artifact,
            workspace=request.workspace,
            pending_enrichment=True,
        )

    def find_by_trigger_id(self, trigger_id: str) -> CaptureSaveResponse | None:
        """Return a prior capture result for an idempotent trigger.

        Args:
            trigger_id: Stable trigger id created before the staged file was
                promoted.

        Returns:
            Existing save response if this trigger was already persisted.
        """

        existing = self.captures.find_by_trigger_id(trigger_id)
        if existing is None:
            return None
        event, artifact = existing
        return CaptureSaveResponse(
            event=event,
            artifact=artifact,
            workspace=WorkspaceSelection(
                workspace_id=str(artifact.metadata.get("workspace_id", "auto")),
                label=str(artifact.metadata.get("workspace_id", "Auto")),
                auto=bool(artifact.metadata.get("workspace_auto", True)),
            ),
            pending_enrichment=event.status == EventStatus.PENDING_ENRICHMENT,
        )

    def validate_staged_artifact(self, request: CaptureSaveRequest) -> None:
        """Validate staged screenshot path before action audit is written.

        Args:
            request: Capture save request to inspect.
        """

        self.vault.validate_staged_file(Path(request.staged_artifact.local_path))


class CaptureAttemptService:
    """Application service for capture SDK attempts and provider orchestration."""

    def __init__(
        self,
        *,
        surface_detection: SurfaceDetectionService,
        provider_routing: ProviderRoutingService,
        app_fanout: AppProviderFanoutService,
        system_evidence: SystemEvidenceOrchestrator,
        persistence: CapturePersistenceService,
    ) -> None:
        """Create the capture attempt orchestrator."""

        self.surface_detection = surface_detection
        self.provider_routing = provider_routing
        self.app_fanout = app_fanout
        self.system_evidence = system_evidence
        self.persistence = persistence
        self._trigger_locks: dict[str, asyncio.Lock] = {}

    async def submit(
        self,
        attempt: CaptureAttemptRequest,
        *,
        policy_decision_id: str | None = None,
    ) -> CaptureAttemptResponse:
        """Resolve, route, command providers, and persist one capture attempt.

        Args:
            attempt: Capture attempt submitted by the native shell.
            policy_decision_id: Optional policy decision id to attach to the envelope.

        Returns:
            Accepted response with event/artifacts, or unsupported response with route diagnostics.
        """

        lock = self._trigger_locks.setdefault(attempt.trigger.trigger_id, asyncio.Lock())
        async with lock:
            return await self._submit_impl(attempt, policy_decision_id=policy_decision_id)

    async def _submit_impl(
        self,
        attempt: CaptureAttemptRequest,
        *,
        policy_decision_id: str | None = None,
    ) -> CaptureAttemptResponse:
        """Resolve, route, and persist one capture attempt.

        Args:
            attempt: P1 capture attempt submitted by the native shell.

        Returns:
            Accepted response with event/artifacts or unsupported response with
            provider route diagnostics.
        """

        existing = self.persistence.find_by_trigger_id(attempt.trigger.trigger_id)
        if existing is not None:
            event, artifacts = existing
            return CaptureAttemptResponse(
                status=CaptureAttemptStatus.ACCEPTED,
                event=event,
                artifacts=artifacts,
                workspace=attempt.workspace,
                pending_enrichment=False,
            )
        self.persistence.validate_staged_artifact(attempt)
        logger.info(
            "capture attempt accepted for routing trigger_id=%s selection=%s window_hints=%s",
            attempt.trigger.trigger_id,
            attempt.selection_geometry.selected_region.model_dump(mode="json"),
            len(attempt.window_hints),
            extra={
                "trigger_id": attempt.trigger.trigger_id,
                "selection": attempt.selection_geometry.selected_region.model_dump(mode="json"),
                "window_hint_count": len(attempt.window_hints),
            },
        )
        detection = self.surface_detection.detect(attempt)
        route_plan, _unsupported_reason = await self.provider_routing.route(detection)
        logger.info(
            "capture route plan resolved trigger_id=%s selected_provider=%s selected_surface=%s routes=%s decisions=%s",
            attempt.trigger.trigger_id,
            route_plan.selected_provider_key,
            route_plan.selected_surface_id,
            len(route_plan.routes),
            len(route_plan.decisions),
            extra={
                "trigger_id": attempt.trigger.trigger_id,
                "selected_provider_key": route_plan.selected_provider_key,
                "selected_surface_id": route_plan.selected_surface_id,
                "route_count": len(route_plan.routes),
                "decision_count": len(route_plan.decisions),
            },
        )
        surface = self.provider_routing.selected_surface(detection, route_plan) or (
            detection.surfaces[0] if detection.surfaces else None
        )
        system_bundles = await self.system_evidence.collect_for_attempt(
            attempt=attempt,
            primary_surface=surface,
            detected_surfaces=detection.surfaces,
            route_plan=route_plan,
        )
        fanout_result = await self.app_fanout.collect(
            attempt=attempt,
            detection=detection,
            route_plan=route_plan,
        )
        command_runs = (
            *fanout_result.command_runs,
            *(
                ProviderCommandRun(
                    command_id=bundle.command_id,
                    provider_key=bundle.provider_key,
                    provider_session_id=bundle.provider_session_id,
                    status=bundle.status,
                    evidence_kind=bundle.evidence_kind,
                    completed_at=bundle.completed_at,
                    error_message=(
                        str(bundle.diagnostics.get("error_message"))
                        if bundle.diagnostics and bundle.diagnostics.get("error_message") is not None
                        else None
                    ),
                    diagnostics=bundle.diagnostics,
                )
                for bundle in system_bundles
            ),
        )
        primary_source_binding = self._primary_source_binding(
            app_bundles=fanout_result.app_bundles,
            route_plan=route_plan,
        )
        event, artifacts, envelope = self.persistence.save_accepted(
            attempt=attempt,
            app_bundles=fanout_result.app_bundles,
            system_bundles=system_bundles,
            provider_outcomes=fanout_result.outcomes,
            route_plan=route_plan,
            detected_surfaces=detection.surfaces,
            command_runs=command_runs,
            primary_source_binding=primary_source_binding,
            source_bindings=tuple(
                bundle.source_binding for bundle in fanout_result.app_bundles if bundle.source_binding is not None
            ),
            policy_decision_id=policy_decision_id,
        )
        logger.info(
            "capture attempt persisted trigger_id=%s event_id=%s run_id=%s artifacts=%s evidence=%s app_bundles=%s provider_outcomes=%s",
            attempt.trigger.trigger_id,
            event.event_id,
            envelope.capture_run_id,
            len(artifacts),
            len(envelope.evidence_records),
            len(fanout_result.app_bundles),
            len(envelope.provider_outcomes),
            extra={
                "trigger_id": attempt.trigger.trigger_id,
                "event_id": event.event_id,
                "capture_run_id": envelope.capture_run_id,
                "artifact_count": len(artifacts),
                "evidence_count": len(envelope.evidence_records),
                "app_bundle_count": len(fanout_result.app_bundles),
                "provider_outcome_count": len(envelope.provider_outcomes),
            },
        )
        return CaptureAttemptResponse(
            status=CaptureAttemptStatus.ACCEPTED,
            event=event,
            artifacts=artifacts,
            workspace=attempt.workspace,
            pending_enrichment=False,
            route_plan=route_plan,
        )

    def from_legacy_save_request(self, request: CaptureSaveRequest) -> CaptureAttemptRequest:
        """Convert the P0 native capture request into the P1 attempt shape.

        Args:
            request: Legacy screenshot save request.

        Returns:
            Equivalent P1 attempt with a single window hint derived from the
            old source binding.
        """

        external_id = request.source_binding.source_ref.external_id
        hint = WindowHint(
            app_name=request.source_binding.source_ref.app_name or request.source_binding.source_ref.title,
            title=request.source_binding.source_ref.title,
            process_id=int(external_id) if external_id is not None and external_id.isdigit() else None,
            frame=request.selection_geometry.selected_region,
            overlap_ratio=1.0,
            confidence=request.source_binding.confidence,
        )
        return CaptureAttemptRequest(
            trigger=request.trigger,
            selection_geometry=request.selection_geometry,
            window_hints=(hint,),
            workspace=request.workspace,
            actor=request.actor,
            staged_artifact=request.staged_artifact,
            intent_text=request.intent_text,
            metadata=request.metadata,
        )

    def _primary_source_binding(
        self,
        *,
        app_bundles: tuple[ProviderEvidenceBundle, ...],
        route_plan: ProviderRoutePlan,
    ) -> SourceBinding | None:
        if route_plan.primary_route_id is not None:
            for bundle in app_bundles:
                if (
                    bundle.diagnostics.get("route_id") == route_plan.primary_route_id
                    and bundle.source_binding is not None
                ):
                    return bundle.source_binding
        return None

    def _unsupported_message(self, reason: UnsupportedReason) -> str:
        if reason == UnsupportedReason.STALE_PROVIDER_CONTEXT:
            return "这次截图已进入系统保存链路，但 App 增强来源暂时不可用；请稍后再试或查看诊断。"
        if reason == UnsupportedReason.NO_PROVIDER:
            return "这次截图没有可用的 App 增强来源；系统截图仍应保存，请查看诊断确认失败原因。"
        if reason == UnsupportedReason.NON_WEB_SOURCE:
            return "这次框选没有命中可用的 App 增强来源；系统截图仍应保存，请查看诊断确认失败原因。"
        if reason == UnsupportedReason.AMBIGUOUS_SURFACE:
            return "截图区域同时压到多个窗口；WorkRecorder 会保存系统证据，并在诊断里标出主来源和附属来源。"
        if reason == UnsupportedReason.LOW_CONFIDENCE:
            return "WorkRecorder 没能稳定识别截图区域属于哪个窗口；请稍微扩大或移动框选区域后重试。"
        if reason == UnsupportedReason.PROVIDER_COMMAND_FAILED:
            return "App 增强采集失败；系统截图仍应保存，请查看诊断确认失败原因。"
        return "这次截图没有保存成功，请查看诊断确认失败原因。"
