from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast

from packages.capture.route_policy import ProviderRoutePolicy, ProviderRoutePolicyConfig
from packages.capture.routing import ProviderRoutingService
from packages.capture.surface import SurfaceDetectionService
from packages.contracts import (
    ActorRef,
    BoundingBox,
    BrowserTabRef,
    BrowserViewport,
    BrowserWindowRef,
    CaptureAttemptRequest,
    CaptureStrategy,
    CollectEvidenceCommand,
    CollectEvidenceResult,
    DetectedSurface,
    DisplayGeometry,
    EventType,
    EvidenceKind,
    FloatRect,
    ProviderCapability,
    ProviderCommandStatus,
    ProviderHeartbeat,
    ProviderKind,
    ProviderManifest,
    ProviderMode,
    ProviderSessionRegistration,
    SelectionGeometry,
    SourceBinding,
    SourceRef,
    SourceType,
    StagedArtifactRef,
    SurfaceKind,
    TriggerEnvelope,
    TriggerType,
    WindowHint,
)
from packages.contracts.enums import ArtifactType, CoordinateSpace
from packages.providers.base import SourceCaptureProvider
from packages.providers.registry import SourceProviderRegistry
from packages.providers.sessions import ProviderSessionService
from packages.providers.web import WebCaptureProvider
from packages.shared.config import WorkRecorderSettings
from packages.shared.ids import IdFactory
from packages.shared.time import Clock


def test_surface_detection_marks_chrome_as_web_provider_candidate():
    attempt = _attempt("Google Chrome")

    result = SurfaceDetectionService().detect(attempt)

    assert result.selected_surface_id == "surface_0"
    assert result.surfaces[0].kind == "web_browser"
    assert result.surfaces[0].app_name == "Google Chrome"


def test_surface_detection_creates_desktop_surface_without_window_hints():
    attempt = _attempt("Google Chrome").model_copy(update={"window_hints": ()})

    result = SurfaceDetectionService().detect(attempt)

    assert result.selected_surface_id == "surface_desktop"
    assert result.surfaces[0].app_name == "桌面"
    assert result.surfaces[0].title == "桌面区域"
    assert result.surfaces[0].overlap_ratio == 1.0


def test_source_provider_registry_requires_declared_capture_evidence_kind():
    class MissingEvidenceKindProvider:
        name = "test.missing_evidence_kind"
        event_type = EventType.SCREEN_REGION_CAPTURED
        capabilities: tuple[ProviderCapability, ...] = ()
        manifest = ProviderManifest(
            provider_key=name,
            display_name="Missing Evidence Kind",
            provider_kind=ProviderKind.SOURCE,
            modes=(ProviderMode.CAPTURE,),
        )

        def supports(self, surface):  # pragma: no cover - registry validation fails first
            del surface
            return False

        async def freshness_score(self, surface):  # pragma: no cover - registry validation fails first
            del surface
            return 0.0

        def collect_command(self, *, attempt, surface, route=None):  # pragma: no cover
            raise AssertionError("not reached")

        def bundle_from_result(self, *, attempt, surface, result, route=None):  # pragma: no cover
            raise AssertionError("not reached")

    registry = SourceProviderRegistry()

    try:
        registry.register(cast(SourceCaptureProvider, MissingEvidenceKindProvider()))
    except ValueError as exc:
        assert "capture_evidence_kind" in str(exc)
    else:
        raise AssertionError("registry accepted a source provider without capture_evidence_kind")


def test_provider_routing_records_no_app_route_for_non_web_surface():
    registry = SourceProviderRegistry()
    router = ProviderRoutingService(registry)
    detection = SurfaceDetectionService().detect(_attempt("Finder"))

    plan, reason = asyncio.run(router.route(detection))

    assert reason is None
    assert plan.primary_surface_id == "surface_0"
    assert plan.selected_provider_key is None
    assert plan.routes == ()


def test_provider_routing_selects_fresh_web_registration():
    clock = Clock()
    sessions = ProviderSessionService(clock=clock)
    provider = WebCaptureProvider(sessions=sessions, ids=IdFactory(), clock=clock)
    registry = SourceProviderRegistry()
    registry.register(provider)
    attempt = _attempt("Google Chrome")
    asyncio.run(sessions.register(websocket=_FakeSocket(), registration=_registration(clock.now())))
    detection = SurfaceDetectionService().detect(attempt)

    plan, reason = asyncio.run(ProviderRoutingService(registry).route(detection))

    assert reason is None
    assert plan.selected_provider_key == "web.browser_extension"


def test_provider_routing_accepts_chrome_for_testing_surface():
    clock = Clock()
    sessions = ProviderSessionService(clock=clock)
    provider = WebCaptureProvider(sessions=sessions, ids=IdFactory(), clock=clock)
    registry = SourceProviderRegistry()
    registry.register(provider)
    attempt = _attempt("Google Chrome for Testing")
    asyncio.run(sessions.register(websocket=_FakeSocket(), registration=_registration(clock.now())))
    detection = SurfaceDetectionService().detect(attempt)

    plan, reason = asyncio.run(ProviderRoutingService(registry).route(detection))

    assert reason is None
    assert plan.selected_provider_key == "web.browser_extension"


def test_provider_routing_falls_back_to_app_when_browser_window_ids_are_source_native():
    clock = Clock()
    sessions = ProviderSessionService(clock=clock)
    provider = WebCaptureProvider(sessions=sessions, ids=IdFactory(), clock=clock)
    registry = SourceProviderRegistry()
    registry.register(provider)
    attempt = _attempt("Google Chrome", window_id="macos-window-42")
    asyncio.run(sessions.register(websocket=_FakeSocket(), registration=_registration(clock.now())))
    detection = SurfaceDetectionService().detect(attempt)

    plan, reason = asyncio.run(ProviderRoutingService(registry).route(detection))

    assert reason is None
    assert plan.selected_provider_key == "web.browser_extension"


def test_provider_routing_rejects_stale_browser_tab_title_for_window_capture():
    clock = Clock()
    sessions = ProviderSessionService(clock=clock)
    provider = WebCaptureProvider(sessions=sessions, ids=IdFactory(), clock=clock)
    registry = SourceProviderRegistry()
    registry.register(provider)
    attempt = _attempt("Google Chrome")
    asyncio.run(
        sessions.register(websocket=_FakeSocket(), registration=_registration(clock.now(), title="LinkedIn Search"))
    )
    detection = SurfaceDetectionService().detect(attempt)

    plan, reason = asyncio.run(ProviderRoutingService(registry).route(detection))

    assert reason is None
    assert plan.selected_provider_key is None
    stale = next(decision for decision in plan.decisions if decision.provider_key == "web.browser_extension")
    assert stale.status.value == "stale"


def test_provider_routing_rejects_generated_browser_app_title_without_stronger_match():
    clock = Clock()
    sessions = ProviderSessionService(clock=clock)
    provider = WebCaptureProvider(sessions=sessions, ids=IdFactory(), clock=clock)
    registry = SourceProviderRegistry()
    registry.register(provider)
    attempt = _attempt("Google Chrome", title="Google Chrome")
    asyncio.run(
        sessions.register(
            websocket=_FakeSocket(), registration=_registration(clock.now(), title="ACME Pricing Dashboard")
        )
    )
    detection = SurfaceDetectionService().detect(attempt)

    plan, reason = asyncio.run(ProviderRoutingService(registry).route(detection))

    assert reason is None
    assert plan.selected_provider_key is None
    stale = next(decision for decision in plan.decisions if decision.provider_key == "web.browser_extension")
    assert stale.status.value == "stale"


def test_provider_routing_accepts_browser_window_title_with_app_suffix():
    clock = Clock()
    sessions = ProviderSessionService(clock=clock)
    provider = WebCaptureProvider(sessions=sessions, ids=IdFactory(), clock=clock)
    registry = SourceProviderRegistry()
    registry.register(provider)
    attempt = _attempt("Google Chrome", title="ACME Pricing Dashboard - Google Chrome")
    asyncio.run(
        sessions.register(
            websocket=_FakeSocket(), registration=_registration(clock.now(), title="ACME Pricing Dashboard")
        )
    )
    detection = SurfaceDetectionService().detect(attempt)

    plan, reason = asyncio.run(ProviderRoutingService(registry).route(detection))

    assert reason is None
    assert plan.selected_provider_key == "web.browser_extension"


def test_provider_routing_rejects_low_confidence_surface():
    registry = SourceProviderRegistry()
    router = ProviderRoutingService(registry)
    detection = SurfaceDetectionService().detect(_attempt("Google Chrome", confidence=0.2, overlap_ratio=0.2))

    plan, reason = asyncio.run(router.route(detection))

    assert reason is None
    assert plan.decisions[0].reason == "low_confidence"
    assert plan.selected_provider_key is None


def test_provider_routing_records_ambiguous_surfaces_without_global_reject():
    registry = SourceProviderRegistry()
    router = ProviderRoutingService(registry)
    attempt = _attempt("Google Chrome")
    second_hint = WindowHint(
        app_name="Microsoft Edge",
        title="ACME Copy",
        frame=attempt.selection_geometry.selected_region,
        overlap_ratio=0.98,
        confidence=0.9,
    )
    detection = SurfaceDetectionService().detect(
        attempt.model_copy(update={"window_hints": (*attempt.window_hints, second_hint)})
    )

    plan, reason = asyncio.run(router.route(detection))

    assert reason is None
    assert plan.selected_provider_key is None
    assert plan.primary_surface_id in {"surface_0", "surface_1"}
    assert len(detection.surfaces) == 2


def test_primary_source_policy_prefers_largest_bbox_overlap():
    registry = SourceProviderRegistry()
    attempt = _attempt("Google Chrome", confidence=0.95, overlap_ratio=0.40)
    second_hint = WindowHint(
        app_name="Preview",
        title="Invoice PDF",
        frame=attempt.selection_geometry.selected_region,
        overlap_ratio=1.0,
        confidence=0.72,
    )
    detection = SurfaceDetectionService().detect(
        attempt.model_copy(update={"window_hints": (*attempt.window_hints, second_hint)})
    )

    plan, reason = asyncio.run(ProviderRoutingService(registry).route(detection))

    assert reason is None
    primary = next(surface for surface in detection.surfaces if surface.surface_id == plan.primary_surface_id)
    assert primary.app_name == "Preview"


def test_surface_detection_prefers_topmost_window_when_overlap_ties():
    attempt = _attempt("飞书", confidence=0.92, overlap_ratio=1.0)
    feishu_hint = attempt.window_hints[0].model_copy(
        update={
            "window_order": 41,
            "visible_area_ratio": 0.24,
            "bundle_id": "com.bytedance.macos.feishu",
        }
    )
    codex_hint = WindowHint(
        app_name="Codex",
        title="Codex",
        frame=attempt.selection_geometry.selected_region,
        overlap_ratio=1.0,
        confidence=0.92,
        window_order=37,
        visible_area_ratio=0.21,
        bundle_id="com.openai.codex",
    )

    detection = SurfaceDetectionService().detect(attempt.model_copy(update={"window_hints": (feishu_hint, codex_hint)}))

    assert detection.surfaces[0].app_name == "Codex"
    assert detection.selected_surface_id == detection.surfaces[0].surface_id


def test_surface_detection_os_window_uses_declared_frontmost_hint_only():
    attempt = _attempt("Finder", confidence=0.91, overlap_ratio=1.0)
    frontmost = attempt.window_hints[0].model_copy(
        update={
            "is_frontmost": True,
            "window_order": 4,
            "bundle_id": "com.apple.finder",
            "process_id": 101,
            "window_id": "finder-window-1",
            "display_id": "display_main",
        }
    )
    background = WindowHint(
        app_name="Google Chrome",
        title="Background",
        frame=attempt.selection_geometry.selected_region,
        overlap_ratio=1.0,
        confidence=0.99,
        window_order=1,
        visible_area_ratio=1.0,
        bundle_id="com.google.Chrome",
        is_frontmost=False,
    )
    os_window_attempt = attempt.model_copy(
        update={
            "trigger": attempt.trigger.model_copy(
                update={
                    "trigger_type": TriggerType.MANUAL_OS_FRONTMOST_WINDOW_HOTKEY,
                    "capture_strategy": CaptureStrategy.OS_WINDOW,
                }
            ),
            "window_hints": (frontmost, background),
        }
    )

    detection = SurfaceDetectionService().detect(os_window_attempt)

    assert len(detection.surfaces) == 1
    assert detection.surfaces[0].app_name == "Finder"
    assert detection.selected_surface_id == "surface_0"


def test_surface_detection_os_window_without_valid_frontmost_hint_fails_closed_to_desktop():
    attempt = _attempt("Finder", confidence=0.91, overlap_ratio=1.0)
    invalid = attempt.window_hints[0].model_copy(update={"is_frontmost": False, "process_id": 101})
    os_window_attempt = attempt.model_copy(
        update={
            "trigger": attempt.trigger.model_copy(
                update={
                    "trigger_type": TriggerType.MANUAL_OS_FRONTMOST_WINDOW_HOTKEY,
                    "capture_strategy": CaptureStrategy.OS_WINDOW,
                }
            ),
            "window_hints": (invalid,),
        }
    )

    detection = SurfaceDetectionService().detect(os_window_attempt)

    assert detection.surfaces[0].surface_id == "surface_desktop"
    assert detection.surfaces[0].app_name == "桌面"


def test_provider_route_policy_prefers_topmost_window_when_overlap_ties():
    attempt = _attempt("飞书", confidence=0.92, overlap_ratio=1.0)
    feishu_hint = attempt.window_hints[0].model_copy(
        update={
            "window_order": 41,
            "visible_area_ratio": 0.24,
            "bundle_id": "com.bytedance.macos.feishu",
        }
    )
    codex_hint = WindowHint(
        app_name="Codex",
        title="Codex",
        frame=attempt.selection_geometry.selected_region,
        overlap_ratio=1.0,
        confidence=0.92,
        window_order=37,
        visible_area_ratio=0.21,
        bundle_id="com.openai.codex",
    )
    detection = SurfaceDetectionService().detect(attempt.model_copy(update={"window_hints": (feishu_hint, codex_hint)}))

    assignment = ProviderRoutePolicy().assign_surfaces(detection.surfaces)
    primary = next(surface for surface in detection.surfaces if surface.surface_id == assignment.primary_surface_id)

    assert primary.app_name == "Codex"


def test_provider_routing_primary_uses_overlap_first_policy_not_confidence_only():
    registry = SourceProviderRegistry()
    attempt = _attempt("Google Chrome", confidence=0.95, overlap_ratio=0.40)
    second_hint = WindowHint(
        app_name="TextEdit",
        title="Draft",
        frame=attempt.selection_geometry.selected_region,
        overlap_ratio=0.70,
        confidence=0.50,
    )
    detection = SurfaceDetectionService().detect(
        attempt.model_copy(update={"window_hints": (*attempt.window_hints, second_hint)})
    )

    plan, reason = asyncio.run(ProviderRoutingService(registry).route(detection))

    assert reason is None
    primary = next(surface for surface in detection.surfaces if surface.surface_id == plan.primary_surface_id)
    assert primary.app_name == "TextEdit"


def test_default_route_settings_keep_overlap_weight_above_confidence_weight():
    settings = WorkRecorderSettings(disclosure_policy_path=None)
    policy = ProviderRoutePolicy(
        ProviderRoutePolicyConfig(
            overlap_weight=settings.capture_route_overlap_weight,
            confidence_weight=settings.capture_route_confidence_weight,
            visible_area_weight=settings.capture_route_visible_area_weight,
            frontmost_bonus=settings.capture_route_frontmost_bonus,
            z_order_base_bonus=settings.capture_route_z_order_base_bonus,
            z_order_decay=settings.capture_route_z_order_decay,
        )
    )
    selection = _attempt("Google Chrome").selection_geometry.selected_region
    high_confidence_sliver = DetectedSurface(
        surface_id="surface_browser",
        kind=SurfaceKind.WEB_BROWSER.value,
        app_name="Google Chrome",
        title="Frontmost tab",
        frame=selection,
        overlap_ratio=0.40,
        confidence=0.95,
    )
    lower_confidence_owner = DetectedSurface(
        surface_id="surface_editor",
        kind=SurfaceKind.DESKTOP_WINDOW.value,
        app_name="TextEdit",
        title="Draft",
        frame=selection,
        overlap_ratio=0.70,
        confidence=0.50,
    )

    assert settings.capture_route_overlap_weight > settings.capture_route_confidence_weight
    assert policy.surface_score(lower_confidence_owner) > policy.surface_score(high_confidence_sliver)


def test_provider_routing_demotes_low_overlap_secondary_surface():
    clock = Clock()
    sessions = ProviderSessionService(clock=clock)
    provider = WebCaptureProvider(sessions=sessions, ids=IdFactory(), clock=clock)
    registry = SourceProviderRegistry()
    registry.register(provider)
    attempt = _attempt("Google Chrome")
    second_hint = WindowHint(
        app_name="Google Chrome",
        title="Tiny sliver",
        frame=attempt.selection_geometry.selected_region,
        overlap_ratio=0.03,
        confidence=0.95,
    )
    asyncio.run(sessions.register(websocket=_FakeSocket(), registration=_registration(clock.now())))
    detection = SurfaceDetectionService().detect(
        attempt.model_copy(update={"window_hints": (*attempt.window_hints, second_hint)})
    )

    plan, reason = asyncio.run(ProviderRoutingService(registry).route(detection))

    assert reason is None
    assert len(plan.selected_route_ids) == 1
    assert any(decision.reason == "outside_route_policy" for decision in plan.decisions)


def test_route_policy_config_raises_secondary_overlap_threshold():
    clock = Clock()
    sessions = ProviderSessionService(clock=clock)
    provider = WebCaptureProvider(sessions=sessions, ids=IdFactory(), clock=clock)
    registry = SourceProviderRegistry()
    registry.register(provider)
    attempt = _attempt("Google Chrome")
    second_hint = WindowHint(
        app_name="Google Chrome",
        title="Secondary under custom threshold",
        frame=attempt.selection_geometry.selected_region,
        overlap_ratio=0.42,
        confidence=0.95,
    )
    asyncio.run(sessions.register(websocket=_FakeSocket(), registration=_registration(clock.now())))
    detection = SurfaceDetectionService().detect(
        attempt.model_copy(update={"window_hints": (*attempt.window_hints, second_hint)})
    )
    router = ProviderRoutingService(
        registry,
        policy=ProviderRoutePolicy(ProviderRoutePolicyConfig(min_secondary_overlap_ratio=0.5)),
    )

    plan, reason = asyncio.run(router.route(detection))

    assert reason is None
    assert len(plan.selected_route_ids) == 1
    assert any(decision.reason == "outside_route_policy" for decision in plan.decisions)


def test_route_policy_config_limits_selected_app_routes():
    clock = Clock()
    sessions = ProviderSessionService(clock=clock)
    provider = WebCaptureProvider(sessions=sessions, ids=IdFactory(), clock=clock)
    registry = SourceProviderRegistry()
    registry.register(provider)
    attempt = _attempt("Google Chrome")
    hints = [
        WindowHint(
            app_name="Google Chrome",
            title=f"ACME window {index}",
            frame=attempt.selection_geometry.selected_region,
            overlap_ratio=0.9 - (index * 0.1),
            confidence=0.9,
        )
        for index in range(1, 4)
    ]
    asyncio.run(sessions.register(websocket=_FakeSocket(), registration=_registration(clock.now())))
    detection = SurfaceDetectionService().detect(
        attempt.model_copy(update={"window_hints": (*attempt.window_hints, *hints)})
    )
    router = ProviderRoutingService(
        registry,
        policy=ProviderRoutePolicy(ProviderRoutePolicyConfig(max_app_routes=2)),
    )

    plan, reason = asyncio.run(router.route(detection))

    assert reason is None
    assert len(plan.selected_route_ids) == 2
    assert sum(decision.reason == "outside_route_policy" for decision in plan.decisions) >= 1


def test_provider_routing_records_multiple_selected_routes_for_overlapping_web_surfaces():
    clock = Clock()
    sessions = ProviderSessionService(clock=clock)
    provider = WebCaptureProvider(sessions=sessions, ids=IdFactory(), clock=clock)
    registry = SourceProviderRegistry()
    registry.register(provider)
    attempt = _attempt("Google Chrome")
    second_hint = WindowHint(
        app_name="Google Chrome",
        title="ACME Secondary",
        frame=attempt.selection_geometry.selected_region,
        overlap_ratio=0.82,
        confidence=0.86,
    )
    asyncio.run(sessions.register(websocket=_FakeSocket(), registration=_registration(clock.now())))
    detection = SurfaceDetectionService().detect(
        attempt.model_copy(update={"window_hints": (*attempt.window_hints, second_hint)})
    )

    plan, reason = asyncio.run(ProviderRoutingService(registry).route(detection))

    assert reason is None
    assert len(plan.selected_route_ids) == 2
    assert plan.primary_route_id == plan.selected_route_ids[0]
    assert {route.role for route in plan.routes} >= {"primary_source", "secondary_source"}


def test_provider_command_result_must_come_from_commanded_session():
    clock = Clock()
    sessions = ProviderSessionService(clock=clock)
    registration = _registration(clock.now())
    asyncio.run(sessions.register(websocket=_WrongSessionResultSocket(sessions), registration=registration))
    attempt = _attempt("Google Chrome")
    surface = SurfaceDetectionService().detect(attempt).surfaces[0]
    command = CollectEvidenceCommand(
        command_id="cmd_test",
        provider_key="web.browser_extension",
        attempt=attempt,
        surface=surface,
        evidence_kinds=(EvidenceKind.WEB,),
        required_capabilities=(ProviderCapability.RESOLVE_SOURCE,),
        deadline_ms=100,
    )

    result = asyncio.run(
        sessions.collect(command=command, surface=surface, evidence_kind=EvidenceKind.WEB, timeout_seconds=0.01)
    )

    assert result.status == ProviderCommandStatus.TIMEOUT


def test_provider_command_result_must_match_routed_tab():
    clock = Clock()
    sessions = ProviderSessionService(clock=clock)
    registration = _registration(clock.now())
    asyncio.run(sessions.register(websocket=_WrongTargetResultSocket(sessions), registration=registration))
    attempt = _attempt("Google Chrome")
    surface = SurfaceDetectionService().detect(attempt).surfaces[0]
    command = CollectEvidenceCommand(
        command_id="cmd_test",
        provider_key="web.browser_extension",
        attempt=attempt,
        surface=surface,
        evidence_kinds=(EvidenceKind.WEB,),
        required_capabilities=(ProviderCapability.RESOLVE_SOURCE,),
        deadline_ms=100,
    )

    result = asyncio.run(
        sessions.collect(command=command, surface=surface, evidence_kind=EvidenceKind.WEB, timeout_seconds=0.01)
    )

    assert result.status == ProviderCommandStatus.TIMEOUT


def test_provider_command_includes_routed_tab_metadata():
    clock = Clock()
    socket = _MatchingTargetResultSocket()
    sessions = ProviderSessionService(clock=clock)
    registration = _registration(clock.now())
    socket.sessions = sessions
    asyncio.run(sessions.register(websocket=socket, registration=registration))
    attempt = _attempt("Google Chrome")
    surface = SurfaceDetectionService().detect(attempt).surfaces[0]
    command = CollectEvidenceCommand(
        command_id="cmd_test",
        provider_key="web.browser_extension",
        attempt=attempt,
        surface=surface,
        evidence_kinds=(EvidenceKind.WEB,),
        required_capabilities=(ProviderCapability.RESOLVE_SOURCE,),
        deadline_ms=100,
    )

    result = asyncio.run(
        sessions.collect(command=command, surface=surface, evidence_kind=EvidenceKind.WEB, timeout_seconds=0.1)
    )

    assert result.status == ProviderCommandStatus.SUCCEEDED
    assert socket.command_metadata["target_tab_id"] == "tab"
    assert socket.command_metadata["target_window_id"] == "win"


def test_provider_heartbeat_uses_daemon_clock_not_provider_timestamp():
    clock = _FixedClock(datetime(2026, 5, 14, 12, 0, tzinfo=UTC))
    sessions = ProviderSessionService(clock=clock)
    registration = _registration(clock.now())
    asyncio.run(sessions.register(websocket=_FakeSocket(), registration=registration))

    asyncio.run(
        sessions.heartbeat(
            ProviderHeartbeat(
                provider_key="web.browser_extension",
                provider_session_id=registration.provider_session_id,
                observed_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        )
    )
    ref = asyncio.run(sessions.list_sessions())[0]

    assert ref.last_seen_at == clock.now()


def test_provider_heartbeat_must_match_registered_socket_identity():
    clock = _FixedClock(datetime(2026, 5, 14, 12, 0, tzinfo=UTC))
    sessions = ProviderSessionService(clock=clock)
    registration = _registration(clock.now())
    asyncio.run(sessions.register(websocket=_FakeSocket(), registration=registration))

    result = asyncio.run(
        sessions.heartbeat(
            ProviderHeartbeat(
                provider_key="web.browser_extension",
                provider_session_id="ctx_wrong",
                observed_at=datetime(2099, 1, 1, tzinfo=UTC),
            ),
            provider_key="web.browser_extension",
            provider_session_id=registration.provider_session_id,
        )
    )

    assert result is None
    assert asyncio.run(sessions.list_sessions())[0].last_seen_at == clock.now()


def test_stale_socket_unregister_does_not_remove_reconnected_session():
    clock = Clock()
    sessions = ProviderSessionService(clock=clock)
    old_socket = _FakeSocket()
    new_socket = _FakeSocket()
    registration = _registration(clock.now())
    asyncio.run(sessions.register(websocket=old_socket, registration=registration))
    asyncio.run(sessions.register(websocket=new_socket, registration=registration))

    asyncio.run(sessions.unregister(registration.provider_session_id, websocket=old_socket))

    refs = asyncio.run(sessions.list_sessions())
    assert len(refs) == 1
    assert refs[0].provider_session_id == registration.provider_session_id


def _attempt(
    app_name: str,
    *,
    confidence: float = 0.9,
    overlap_ratio: float = 1.0,
    window_id: str | None = None,
    title: str = "ACME",
) -> CaptureAttemptRequest:
    occurred_at = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
    actor = ActorRef(actor_id="test", display_name="Test")
    selection = BoundingBox(x=-120, y=140, width=520, height=280, coordinate_space=CoordinateSpace.MACOS_GLOBAL)
    return CaptureAttemptRequest(
        trigger=TriggerEnvelope(
            trigger_id="trg_test",
            trigger_type=TriggerType.MANUAL_OS_REGION_HOTKEY,
            capture_strategy=CaptureStrategy.OS_REGION,
            actor=actor,
            occurred_at=occurred_at,
            selection=selection,
        ),
        selection_geometry=SelectionGeometry(
            selected_region=selection,
            display=DisplayGeometry(
                display_id="display",
                frame=BoundingBox(x=-500, y=0, width=1920, height=1080, coordinate_space=CoordinateSpace.MACOS_GLOBAL),
                scale_factor=2.0,
            ),
        ),
        window_hints=(
            WindowHint(
                app_name=app_name,
                title=title,
                window_id=window_id,
                frame=selection,
                overlap_ratio=overlap_ratio,
                confidence=confidence,
            ),
        ),
        actor=actor,
        staged_artifact=StagedArtifactRef(
            local_path="/tmp/staged.png",
            artifact_type=ArtifactType.SCREENSHOT,
            content_type="image/png",
        ),
    )


class _FakeSocket:
    async def send_text(self, data: str) -> None:
        return None


class _WrongSessionResultSocket:
    def __init__(self, sessions: ProviderSessionService) -> None:
        self.sessions = sessions

    async def send_text(self, data: str) -> None:
        import json

        command = json.loads(data)["command"]
        result = CollectEvidenceResult(
            command_id=command["command_id"],
            provider_key="web.browser_extension",
            provider_session_id="ctx_wrong",
            status=ProviderCommandStatus.SUCCEEDED,
            evidence_kind=EvidenceKind.WEB,
            diagnostics={},
            completed_at=datetime.now(UTC),
        )
        await self.sessions.handle_collect_result(result, provider_session_id="ctx_wrong")


class _WrongTargetResultSocket:
    def __init__(self, sessions: ProviderSessionService) -> None:
        self.sessions = sessions

    async def send_text(self, data: str) -> None:
        import json

        command = json.loads(data)["command"]
        result = CollectEvidenceResult(
            command_id=command["command_id"],
            provider_key="web.browser_extension",
            provider_session_id="ctx_test",
            status=ProviderCommandStatus.SUCCEEDED,
            evidence_kind=EvidenceKind.WEB,
            source_binding=_source_binding("other-tab"),
            diagnostics={"actual_window_id": "win"},
            completed_at=datetime.now(UTC),
        )
        await self.sessions.handle_collect_result(result, provider_session_id="ctx_test")


class _MatchingTargetResultSocket:
    def __init__(self) -> None:
        self.sessions: ProviderSessionService | None = None
        self.command_metadata: dict[str, object] = {}

    async def send_text(self, data: str) -> None:
        import json

        if self.sessions is None:
            raise AssertionError("sessions must be assigned")
        command = json.loads(data)["command"]
        self.command_metadata = command["metadata"]
        result = CollectEvidenceResult(
            command_id=command["command_id"],
            provider_key="web.browser_extension",
            provider_session_id="ctx_test",
            status=ProviderCommandStatus.SUCCEEDED,
            evidence_kind=EvidenceKind.WEB,
            source_binding=_source_binding("tab"),
            diagnostics={"actual_window_id": "win"},
            completed_at=datetime.now(UTC),
        )
        await self.sessions.handle_collect_result(result, provider_session_id="ctx_test")


def _source_binding(tab_id: str) -> SourceBinding:
    return SourceBinding(
        binding_id="src_test",
        source_ref=SourceRef(
            source_type=SourceType.WEB,
            title="ACME",
            app_name="Google Chrome",
            url="https://example.test/acme",
            origin="https://example.test",
            connector_name="web.browser_extension",
            external_id=tab_id,
        ),
        confidence=0.9,
        resolved_at=datetime.now(UTC),
        provider_key="web.browser_extension",
        provider_context_id="ctx_test",
    )


class _FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def _registration(now: datetime, *, title: str = "ACME") -> ProviderSessionRegistration:
    rect = BoundingBox(x=-120, y=140, width=520, height=280, coordinate_space=CoordinateSpace.MACOS_GLOBAL)
    return ProviderSessionRegistration(
        provider_key="web.browser_extension",
        provider_session_id="ctx_test",
        provider_kind=ProviderKind.SOURCE,
        display_name="Web",
        app_name="Google Chrome",
        window=BrowserWindowRef(window_id="win", screen_rect=rect),
        tab=BrowserTabRef(
            browser="chrome",
            tab_id="tab",
            window_id="win",
            url="https://example.test/acme",
            origin="https://example.test",
            title=title,
        ),
        viewport=BrowserViewport(
            rect=FloatRect(x=0, y=0, width=100, height=100, coordinate_space=CoordinateSpace.VIEWPORT_CSS_PX),
            device_pixel_ratio=2.0,
        ),
        capabilities=(
            ProviderCapability.RESOLVE_SOURCE,
            ProviderCapability.COLLECT_PAGE_METADATA,
            ProviderCapability.COLLECT_VISIBLE_TEXT,
            ProviderCapability.COLLECT_SELECTED_TEXT,
            ProviderCapability.COLLECT_PAGE_TEXT,
            ProviderCapability.COLLECT_READABILITY_TEXT,
            ProviderCapability.COLLECT_SANITIZED_DOM,
            ProviderCapability.COLLECT_FULL_DOM,
            ProviderCapability.MAP_SELECTION,
        ),
        registered_at=now,
    )
