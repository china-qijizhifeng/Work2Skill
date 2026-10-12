"""Daemon orchestration for provider-backed system evidence services."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from packages.contracts import (
    AppshotComponentRef,
    AppshotPermissionReport,
    AppshotQualityReport,
    AppshotSurfaceSnapshot,
    AppshotWindowIdentity,
    ArtifactRole,
    ArtifactType,
    CaptureAttemptRequest,
    CollectEvidenceCommand,
    CollectEvidenceResult,
    DetectedSurface,
    EvidenceDraft,
    EvidenceKind,
    EvidenceLocator,
    EvidencePayloadRef,
    EvidencePhase,
    EvidenceProvenance,
    EvidenceSensitivity,
    EvidenceTrustState,
    ExtractorRef,
    ProviderCapability,
    ProviderCaptureOutcomeStatus,
    ProviderCommandStatus,
    ProviderEvidenceBundle,
    ProviderKind,
    ProviderManifest,
    ProviderMode,
    ProviderPermissionState,
    ProviderRoutePlan,
    ProviderRouteRole,
    RedactionState,
    SourceType,
    SystemAppshotSnapshot,
)
from packages.contracts.common import JsonScalar
from packages.providers.base import SystemEvidenceProvider
from packages.providers.registry import SystemEvidenceProviderRegistry
from packages.providers.sessions import ProviderSessionService
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

SCREENSHOT_PROVIDER_KEY = "system.screenshot"
A11Y_PROVIDER_KEY = "system.macos_a11y"
APPSHOT_PROVIDER_KEY = "system.appshot"
logger = logging.getLogger(__name__)


def register_default_system_evidence_providers(
    *,
    registry: SystemEvidenceProviderRegistry,
    sessions: ProviderSessionService,
    ids: IdFactory,
    clock: Clock,
    include_macos_a11y: bool = True,
) -> None:
    """Register built-in system evidence providers in capture order.

    Args:
        registry: System provider registry populated during daemon boot.
        sessions: Provider session service used by command-backed providers.
        ids: Id factory used for command and evidence provenance ids.
        clock: Runtime clock used for capture timestamps.
    """

    registry.register(SystemScreenshotProvider(ids=ids, clock=clock))
    if include_macos_a11y:
        registry.register(SystemMacOSA11yProvider(sessions=sessions, ids=ids, clock=clock))
    registry.register(SystemAppshotProvider(ids=ids, clock=clock))


class SystemEvidenceOrchestrator:
    """Collect common system evidence through a typed provider registry."""

    def __init__(self, *, registry: SystemEvidenceProviderRegistry, ids: IdFactory, clock: Clock) -> None:
        """Create the orchestrator."""

        self.registry = registry
        self.ids = ids
        self.clock = clock

    async def collect_for_attempt(
        self,
        *,
        attempt: CaptureAttemptRequest,
        primary_surface: DetectedSurface | None,
        detected_surfaces: tuple[DetectedSurface, ...],
        route_plan: ProviderRoutePlan,
    ) -> tuple[ProviderEvidenceBundle, ...]:
        """Collect all common evidence for a capture attempt.

        Args:
            attempt: User-triggered capture attempt and staged screenshot ref.
            primary_surface: Highest-ranked detected surface, if any.
            detected_surfaces: All surfaces overlapped by the selected bbox.
            route_plan: App provider route plan for the same capture.

        Returns:
            Provider evidence bundles for each registered system provider.
        """

        results: list[ProviderEvidenceBundle] = []
        for provider in self.registry.list():
            results.append(
                await self._collect_provider(
                    provider=provider,
                    attempt=attempt,
                    primary_surface=primary_surface,
                    detected_surfaces=detected_surfaces,
                    route_plan=route_plan,
                )
            )
        for bundle in results:
            logger.info(
                "system evidence provider completed trigger_id=%s provider_key=%s command_id=%s status=%s evidence=%s",
                attempt.trigger.trigger_id,
                bundle.provider_key,
                bundle.command_id,
                bundle.status,
                len(bundle.evidence),
                extra={
                    "trigger_id": attempt.trigger.trigger_id,
                    "provider_key": bundle.provider_key,
                    "command_id": bundle.command_id,
                    "status": bundle.status,
                    "evidence_count": len(bundle.evidence),
                },
            )
        return tuple(results)

    async def _collect_provider(
        self,
        *,
        provider: SystemEvidenceProvider,
        attempt: CaptureAttemptRequest,
        primary_surface: DetectedSurface | None,
        detected_surfaces: tuple[DetectedSurface, ...],
        route_plan: ProviderRoutePlan,
    ) -> ProviderEvidenceBundle:
        try:
            return await provider.collect(
                attempt=attempt,
                primary_surface=primary_surface,
                detected_surfaces=detected_surfaces,
                route_plan=route_plan,
            )
        except Exception as exc:
            provider_key = getattr(provider, "name", "system.unknown")
            evidence_kind = getattr(provider, "evidence_kind", EvidenceKind.PROVIDER_DIAGNOSTICS)
            logger.exception(
                "system evidence provider failed trigger_id=%s provider_key=%s",
                attempt.trigger.trigger_id,
                provider_key,
                extra={"trigger_id": attempt.trigger.trigger_id, "provider_key": provider_key},
            )
            return ProviderEvidenceBundle(
                provider_key=provider_key,
                provider_session_id=None,
                command_id=self.ids.new("cmd"),
                status=ProviderCommandStatus.FAILED,
                evidence_kind=evidence_kind,
                evidence=(),
                diagnostics={
                    "error_code": "system_provider_exception",
                    "error_message": str(exc),
                    "primary_surface_id": primary_surface.surface_id if primary_surface is not None else None,
                },
                completed_at=self.clock.now(),
            )


class SystemScreenshotProvider:
    """System provider that promotes the already staged OS screenshot."""

    name = SCREENSHOT_PROVIDER_KEY
    evidence_kind = EvidenceKind.SCREENSHOT
    capabilities: tuple[ProviderCapability, ...] = (ProviderCapability.COLLECT_SYSTEM_APPSHOT,)
    manifest = ProviderManifest(
        provider_key=SCREENSHOT_PROVIDER_KEY,
        display_name="系统截图",
        provider_kind=ProviderKind.SYSTEM_EVIDENCE,
        modes=(ProviderMode.SYSTEM, ProviderMode.CAPTURE),
        source_types=(SourceType.DESKTOP_WINDOW, SourceType.WEB, SourceType.DOCUMENT),
        capabilities=capabilities,
        evidence_kinds=(EvidenceKind.SCREENSHOT,),
        policy_tags=("system", "appshot", "raw_visual"),
        default_deadline_ms=1000,
    )

    def __init__(self, *, ids: IdFactory, clock: Clock) -> None:
        self.ids = ids
        self.clock = clock

    async def collect(
        self,
        *,
        attempt: CaptureAttemptRequest,
        primary_surface: DetectedSurface | None,
        detected_surfaces: tuple[DetectedSurface, ...],
        route_plan: ProviderRoutePlan,
    ) -> ProviderEvidenceBundle:
        """Return a screenshot evidence bundle for the staged OS screenshot.

        Args:
            attempt: Capture attempt containing the staged screenshot path.
            primary_surface: Main surface used only for diagnostics.
            detected_surfaces: All detected surfaces for diagnostics.
            route_plan: App provider route plan for diagnostics.

        Returns:
            A provider bundle containing one screenshot draft. The vault
            promotion still happens later in persistence.
        """

        now = self.clock.now()
        draft = _screenshot_draft(attempt=attempt, captured_at=now)
        return ProviderEvidenceBundle(
            provider_key=self.name,
            provider_session_id=None,
            command_id=self.ids.new("cmd"),
            status=ProviderCommandStatus.SUCCEEDED,
            evidence_kind=EvidenceKind.SCREENSHOT,
            evidence=(draft,),
            diagnostics={
                "primary_surface_id": primary_surface.surface_id if primary_surface is not None else None,
                "surface_count": len(detected_surfaces),
                "route_count": len(route_plan.routes),
            },
            completed_at=now,
        )


class SystemMacOSA11yProvider:
    """System provider that commands the native macOS a11y session."""

    name = A11Y_PROVIDER_KEY
    evidence_kind = EvidenceKind.A11Y
    capabilities: tuple[ProviderCapability, ...] = (ProviderCapability.READ_A11Y,)
    manifest = ProviderManifest(
        provider_key=A11Y_PROVIDER_KEY,
        display_name="macOS 辅助功能",
        provider_kind=ProviderKind.SYSTEM_EVIDENCE,
        modes=(ProviderMode.SYSTEM, ProviderMode.CAPTURE),
        source_types=(SourceType.DESKTOP_WINDOW, SourceType.WEB, SourceType.DOCUMENT),
        capabilities=capabilities,
        evidence_kinds=(EvidenceKind.A11Y,),
        policy_tags=("system", "appshot", "a11y"),
        default_deadline_ms=3000,
    )

    def __init__(self, *, sessions: ProviderSessionService, ids: IdFactory, clock: Clock) -> None:
        self.sessions = sessions
        self.ids = ids
        self.clock = clock

    async def collect(
        self,
        *,
        attempt: CaptureAttemptRequest,
        primary_surface: DetectedSurface | None,
        detected_surfaces: tuple[DetectedSurface, ...],
        route_plan: ProviderRoutePlan,
    ) -> ProviderEvidenceBundle:
        """Collect macOS accessibility evidence or a typed failure bundle.

        Args:
            attempt: Capture attempt sent to the native a11y provider.
            primary_surface: Surface used to scope AX extraction.
            detected_surfaces: All detected surfaces, currently diagnostic only.
            route_plan: App provider route plan, currently diagnostic only.

        Returns:
            The native provider evidence bundle, or a diagnostics bundle when
            permission/session/timeout prevents AX extraction.
        """

        result = await self._collect_a11y(attempt=attempt, surface=primary_surface)
        if result.evidence_bundle is not None:
            return result.evidence_bundle
        return self._a11y_failure_bundle(result, attempt=attempt)

    async def _collect_a11y(
        self, *, attempt: CaptureAttemptRequest, surface: DetectedSurface | None
    ) -> CollectEvidenceResult:
        command = CollectEvidenceCommand(
            command_id=self.ids.new("cmd"),
            provider_key=A11Y_PROVIDER_KEY,
            attempt=attempt,
            surface=surface,
            evidence_kinds=(EvidenceKind.A11Y,),
            required_capabilities=(ProviderCapability.READ_A11Y,),
            deadline_ms=3000,
            metadata={"provider_version": "macos_a11y_command_v1"},
        )
        return await self.sessions.collect(
            command=command,
            surface=None,
            evidence_kind=EvidenceKind.A11Y,
            timeout_seconds=3.5,
        )

    def _a11y_failure_bundle(
        self, result: CollectEvidenceResult, *, attempt: CaptureAttemptRequest
    ) -> ProviderEvidenceBundle:
        """Build a typed diagnostics bundle for a failed a11y command.

        Args:
            result: Failed provider command result.
            attempt: Capture attempt used for locator and trigger context.

        Returns:
            Provider evidence bundle containing a diagnostics artifact.
        """

        now = self.clock.now()
        error_message = _safe_diagnostic_text(result.error_message)
        diagnostics: dict[str, JsonScalar] = {
            **{key: _safe_diagnostic_text(str(value)) for key, value in result.diagnostics.items()},
            "error_code": result.status.value,
            "error_message": error_message,
        }
        payload = {
            "status": result.status.value,
            "provider_key": result.provider_key,
            "command_id": result.command_id,
            "error_message": error_message,
            "diagnostics": diagnostics,
        }
        draft = EvidenceDraft(
            phase=EvidencePhase.CAPTURED,
            kind=EvidenceKind.PROVIDER_DIAGNOSTICS,
            artifact_type=ArtifactType.A11Y_COVERAGE,
            role=ArtifactRole.PROVIDER_DIAGNOSTICS,
            payload=EvidencePayloadRef(
                content_type="application/json",
                inline_content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                payload_schema="a11y_failure_diagnostics",
            ),
            locator=EvidenceLocator(
                source_uri=f"macos://a11y/{attempt.trigger.trigger_id}",
                source_type=SourceType.DESKTOP_WINDOW,
                bbox=attempt.selection_geometry.selected_region,
                coordinate_space=attempt.selection_geometry.selected_region.coordinate_space.value,
            ),
            observed_at=now,
            captured_at=now,
            provenance=EvidenceProvenance(
                provider_key=A11Y_PROVIDER_KEY,
                provider_kind=ProviderKind.SYSTEM_EVIDENCE,
                provider_session_id=result.provider_session_id,
                command_id=result.command_id,
                extractor=ExtractorRef(name=A11Y_PROVIDER_KEY, version="p3_failure_v1"),
            ),
            sensitivity=EvidenceSensitivity.INTERNAL,
            trust_state_claim=EvidenceTrustState.UNTRUSTED,
            redaction_state_claim=RedactionState.NONE,
        )
        return ProviderEvidenceBundle(
            provider_key=A11Y_PROVIDER_KEY,
            provider_session_id=result.provider_session_id,
            command_id=result.command_id,
            status=result.status,
            evidence_kind=EvidenceKind.A11Y,
            evidence=(draft,),
            diagnostics=diagnostics,
            completed_at=now,
        )


class SystemAppshotProvider:
    """Composite system appshot provider that records safe refs and diagnostics."""

    name = APPSHOT_PROVIDER_KEY
    evidence_kind = EvidenceKind.SYSTEM_APPSHOT
    capabilities: tuple[ProviderCapability, ...] = (ProviderCapability.COLLECT_SYSTEM_APPSHOT,)
    manifest = ProviderManifest(
        provider_key=APPSHOT_PROVIDER_KEY,
        display_name="画面快照",
        provider_kind=ProviderKind.SYSTEM_EVIDENCE,
        modes=(ProviderMode.SYSTEM, ProviderMode.CAPTURE),
        source_types=(SourceType.DESKTOP_WINDOW, SourceType.WEB, SourceType.DOCUMENT),
        capabilities=capabilities,
        evidence_kinds=(EvidenceKind.SYSTEM_APPSHOT,),
        policy_tags=("system", "appshot", "metadata"),
        default_deadline_ms=1000,
    )

    def __init__(self, *, ids: IdFactory, clock: Clock) -> None:
        self.ids = ids
        self.clock = clock

    async def collect(
        self,
        *,
        attempt: CaptureAttemptRequest,
        primary_surface: DetectedSurface | None,
        detected_surfaces: tuple[DetectedSurface, ...],
        route_plan: ProviderRoutePlan,
    ) -> ProviderEvidenceBundle:
        """Build a read-only appshot bundle from system facts and refs.

        Args:
            attempt: Capture attempt with trigger and selection geometry.
            primary_surface: Surface that represents the primary App/window.
            detected_surfaces: All overlapped surfaces to include in the snapshot.
            route_plan: App route plan used to annotate primary/secondary roles.

        Returns:
            A metadata-only appshot bundle. Screenshot/a11y evidence ids are
            filled in after those drafts are persisted.
        """

        now = self.clock.now()
        snapshot = self._snapshot(
            attempt=attempt,
            primary_surface=primary_surface,
            detected_surfaces=detected_surfaces,
            route_plan=route_plan,
        )
        draft = EvidenceDraft(
            phase=EvidencePhase.CAPTURED,
            kind=EvidenceKind.SYSTEM_APPSHOT,
            artifact_type=ArtifactType.SYSTEM_APPSHOT,
            role=ArtifactRole.SYSTEM_APPSHOT,
            payload=EvidencePayloadRef(
                content_type="application/json",
                inline_content=snapshot.model_dump_json(),
                payload_schema="system_appshot_snapshot_v1",
            ),
            locator=EvidenceLocator(
                source_uri=f"workrecorder://appshots/{attempt.trigger.trigger_id}",
                source_type=SourceType.DESKTOP_WINDOW,
                bbox=attempt.selection_geometry.selected_region,
                coordinate_space=attempt.selection_geometry.selected_region.coordinate_space.value,
            ),
            observed_at=attempt.trigger.occurred_at,
            captured_at=now,
            provenance=EvidenceProvenance(
                provider_key=APPSHOT_PROVIDER_KEY,
                provider_kind=ProviderKind.SYSTEM_EVIDENCE,
                extractor=ExtractorRef(name=APPSHOT_PROVIDER_KEY, version="p5_appshot_v1"),
            ),
            sensitivity=EvidenceSensitivity.INTERNAL,
            trust_state_claim=EvidenceTrustState.PROVIDER_REDACTED,
            redaction_state_claim=RedactionState.NONE,
            metadata={
                "capture_revision": snapshot.capture_revision,
                "primary_surface_id": snapshot.primary_surface_id,
                "surface_count": len(snapshot.surfaces),
            },
        )
        return ProviderEvidenceBundle(
            provider_key=self.name,
            provider_session_id=None,
            command_id=self.ids.new("cmd"),
            status=ProviderCommandStatus.SUCCEEDED,
            evidence_kind=EvidenceKind.SYSTEM_APPSHOT,
            evidence=(draft,),
            diagnostics={
                "primary_surface_id": snapshot.primary_surface_id,
                "surface_count": len(snapshot.surfaces),
                "capture_revision": snapshot.capture_revision,
            },
            completed_at=now,
        )

    def _snapshot(
        self,
        *,
        attempt: CaptureAttemptRequest,
        primary_surface: DetectedSurface | None,
        detected_surfaces: tuple[DetectedSurface, ...],
        route_plan: ProviderRoutePlan,
    ) -> SystemAppshotSnapshot:
        primary_surface_id = (
            primary_surface.surface_id if primary_surface is not None else route_plan.primary_surface_id
        )
        route_roles = {route.surface_id: route.role for route in route_plan.routes if route.surface_id is not None}
        surfaces = tuple(
            AppshotSurfaceSnapshot(
                surface_id=surface.surface_id,
                kind=surface.kind,
                role=route_roles.get(
                    surface.surface_id,
                    (
                        ProviderRouteRole.PRIMARY_SOURCE
                        if surface.surface_id == primary_surface_id
                        else ProviderRouteRole.SECONDARY_SOURCE
                    ),
                ),
                identity=AppshotWindowIdentity(
                    app_name=surface.app_name,
                    title=surface.title,
                    bundle_id=surface.bundle_id,
                    bundle_url=None,
                    process_id=surface.process_id,
                    window_id=surface.window_id,
                    frame=surface.frame,
                    display_id=surface.display_id,
                    window_layer=surface.window_layer,
                    window_order=surface.window_order,
                    visible_area_ratio=surface.visible_area_ratio,
                    is_frontmost=surface.is_frontmost,
                    app_icon_ref=surface.app_icon_ref,
                ),
                overlap_ratio=surface.overlap_ratio,
                confidence=surface.confidence,
            )
            for surface in detected_surfaces
        )
        primary = primary_surface or (detected_surfaces[0] if detected_surfaces else None)
        quality = AppshotQualityReport(
            screenshot_present=True,
            a11y_supported=False,
            surface_count=len(detected_surfaces),
            primary_confidence=primary.confidence if primary is not None else 0.0,
            coverage_confidence=0.0,
            diagnostics=(),
        )
        permissions = AppshotPermissionReport(
            screen_recording=ProviderPermissionState.GRANTED,
            accessibility=ProviderPermissionState.UNKNOWN,
        )
        return SystemAppshotSnapshot(
            capture_revision=f"appshot:{attempt.trigger.trigger_id}",
            selected_region=attempt.selection_geometry.selected_region,
            primary_surface_id=primary_surface_id,
            primary_app_name=primary.app_name if primary is not None else None,
            primary_bundle_id=primary.bundle_id if primary is not None else None,
            primary_process_id=primary.process_id if primary is not None else None,
            primary_window_id=primary.window_id if primary is not None else None,
            surfaces=surfaces,
            quality=quality,
            permissions=permissions,
            components=(
                AppshotComponentRef(
                    provider_key=SCREENSHOT_PROVIDER_KEY,
                    evidence_kind=EvidenceKind.SCREENSHOT,
                    status=ProviderCaptureOutcomeStatus.SELECTED,
                ),
            ),
            metadata={"capture_strategy": attempt.trigger.capture_strategy.value},
        )


def _screenshot_draft(*, attempt: CaptureAttemptRequest, captured_at: datetime) -> EvidenceDraft:
    selection = attempt.selection_geometry.selected_region
    return EvidenceDraft(
        phase=EvidencePhase.CAPTURED,
        kind=EvidenceKind.SCREENSHOT,
        artifact_type=ArtifactType.SCREENSHOT,
        role=ArtifactRole.VISUAL_EVIDENCE,
        payload=EvidencePayloadRef(content_type=attempt.staged_artifact.content_type, payload_schema="png"),
        locator=EvidenceLocator(
            source_uri=f"macos://screenshot/{attempt.trigger.trigger_id}",
            source_type=SourceType.DESKTOP_WINDOW,
            coordinate_space=selection.coordinate_space.value,
            bbox=selection,
        ),
        observed_at=attempt.trigger.occurred_at,
        captured_at=captured_at,
        provenance=EvidenceProvenance(
            provider_key=SCREENSHOT_PROVIDER_KEY,
            provider_kind=ProviderKind.SYSTEM_EVIDENCE,
            extractor=ExtractorRef(name=SCREENSHOT_PROVIDER_KEY, version="p5_screenshot_v1"),
        ),
        sensitivity=EvidenceSensitivity.HIGH_SENSITIVITY,
        trust_state_claim=EvidenceTrustState.QUARANTINED,
        redaction_state_claim=RedactionState.QUARANTINED,
        metadata={
            "workspace_id": attempt.workspace.workspace_id,
            "workspace_auto": attempt.workspace.auto,
            "display_id": attempt.selection_geometry.display.display_id,
            "display_scale_factor": attempt.selection_geometry.display.scale_factor,
            "selection_x": selection.x,
            "selection_y": selection.y,
            "selection_width": selection.width,
            "selection_height": selection.height,
            "visual_ocr_upload_allowed": True,
        },
    )


def _safe_diagnostic_text(value: str | None) -> str | None:
    if value is None:
        return None
    redacted = value.replace("local-artifact://", "local-artifact:[redacted]")
    redacted = redacted.replace("file://", "file:[redacted]")
    redacted = " ".join("[path:redacted]" if _looks_like_local_path(part) else part for part in redacted.split())
    return redacted[:160]


def _looks_like_local_path(value: str) -> bool:
    return value.startswith(("/Users/", "/private/", "/tmp/", "/var/folders/"))
