"""Service container for the FastAPI local daemon."""

from __future__ import annotations

import logging
from pathlib import Path

from packages.active_capture.adapters.vault_video_artifact import VaultVideoArtifactAdapter
from packages.active_capture.application.citations import ActiveCaptureCitationResolver
from packages.active_capture.application.export import RecordingExporter
from packages.active_capture.application.inspect import RecordingInspectService
from packages.active_capture.application.read_model import RecordingSessionGraphReader
from packages.active_capture.application.service import ActiveCaptureService
from packages.active_capture.application.vm_a11y_probe import VMAccessibilityProbeConfig, VMAccessibilityProbeService
from packages.active_capture.application.vm_coordinate_mapping import VMDisplayGeometry
from packages.agent_runs import AgentRunLedgerService
from packages.artifacts.service import ArtifactAccessService
from packages.artifacts.vault import LocalArtifactVault
from packages.audit.writer import AuditWriter
from packages.capture.commands import ProviderCommandService
from packages.capture.derived_persistence import DerivedEvidencePersistenceService
from packages.capture.fanout import AppProviderFanoutService
from packages.capture.persistence import CapturePersistenceService
from packages.capture.post_commit import CapturePostCommitHandler, CapturePostCommitOutboxDispatcher
from packages.capture.route_policy import ProviderRoutePolicy, ProviderRoutePolicyConfig
from packages.capture.routing import ProviderRoutingService
from packages.capture.service import CaptureAttemptService, CaptureIngestService
from packages.capture.surface import SurfaceDetectionService
from packages.capture.system_evidence import SystemEvidenceOrchestrator, register_default_system_evidence_providers
from packages.context_share.importers import SharePackageParser
from packages.context_share.package import SharePackageBuilder
from packages.context_share.ports import SharePublisherRegistry
from packages.context_share.service import ContextShareService
from packages.contracts import (
    ActiveCaptureMode,
    ActiveCapturePolicyConfig,
    ActiveCaptureProjectionConfig,
    ActorRef,
    CapturePostCommitOutboxConfig,
    CapturePostCommitTaskKind,
    EventInspectSection,
)
from packages.disclosure import DisclosurePolicyRegistry, DisclosurePolicyService
from packages.enrichment.visual_ocr import VisualOCRJobRunner, VisualOCRPromptBuilder, VisualOCRService
from packages.events.service import ContextEventIngestService
from packages.evidence.policy import EvidencePolicyService
from packages.evidence.redaction import SensitiveTextRedactor
from packages.indexing import ContextBundleBuilder, IndexBackendRegistry, IndexingService, SearchService
from packages.indexing.backends import SQLiteKeywordIndexBackend
from packages.indexing.safety import SafeIndexPolicyConfig, SafeIndexProjectionService
from packages.indexing.search import SearchCardOverlay
from packages.integrations.feishu import FeishuDriveClient, FeishuSharePublisher, FeishuTokenClient
from packages.integrations.feishu.client import FEISHU_SECRET_ACCOUNT, FEISHU_SECRET_SERVICE
from packages.policy.evaluator import PolicyEvaluator
from packages.policy.service import AuthorizationService
from packages.policy.tokens import LocalTokenService
from packages.providers.lifecycle import (
    ProviderLifecycleRegistry,
    ProviderLifecycleService,
    register_default_lifecycle_definitions,
)
from packages.providers.registry import SourceProviderRegistry, SystemEvidenceProviderRegistry
from packages.providers.sessions import ProviderSessionService
from packages.providers.web import WebCaptureProvider
from packages.settings.secret_store import ChainedSecretStore, EnvSecretStore, MacOSKeychainSecretStore
from packages.settings.shortcuts import ShortcutSettingsService
from packages.settings.visual_ocr import VisualOCRSettingsService
from packages.settings.vm_a11y import VMA11yProbeSettingsService
from packages.shared.config import WorkRecorderSettings
from packages.shared.ids import IdFactory
from packages.shared.responses import ResponseFactory
from packages.shared.time import Clock
from packages.storage.container import RepositoryContainer
from packages.storage.database import SQLiteDatabase

from .active_capture_inspect import DisclosureEventEvidenceInspectAdapter, RepositoryEventLookupAdapter

logger = logging.getLogger(__name__)


class DaemonContainer:
    """Wire daemon services while keeping routes thin.

    Attributes:
        settings: Loaded runtime settings.
        ids: Identifier generator.
        clock: Shared clock.
        repositories: SQLite repository container.
        tokens: Local token service.
        authorization: Policy and audit orchestration service.
        responses: API response factory.
        events: Event ingest service.
        captures: Native screenshot capture ingest service.
        search: Agent-facing search service.
        bundles: Context bundle builder.
        artifacts: Artifact access service.
    """

    def __init__(self, settings: WorkRecorderSettings) -> None:
        """Create all daemon dependencies.

        Args:
            settings: Runtime settings.
        """

        self.settings = settings
        self.ids = IdFactory()
        self.clock = Clock()
        self.repositories = RepositoryContainer(SQLiteDatabase(settings.database_path))
        audit_writer = AuditWriter(repository=self.repositories.audits, ids=self.ids, clock=self.clock)
        evaluator = PolicyEvaluator(ids=self.ids, clock=self.clock)
        self.tokens = LocalTokenService(
            secret=settings.install_secret,
            audience=settings.token_audience,
            ttl_seconds=settings.token_ttl_seconds,
            ids=self.ids,
            clock=self.clock,
        )
        self.authorization = AuthorizationService(
            evaluator=evaluator,
            decisions=self.repositories.policies,
            audits=audit_writer,
        )
        self.responses = ResponseFactory()
        vault = LocalArtifactVault(
            staging_dir=settings.artifact_staging_dir,
            vault_dir=settings.artifact_vault_dir,
        )
        self.vault = vault
        secret_store = ChainedSecretStore(MacOSKeychainSecretStore(), EnvSecretStore())
        self.visual_ocr_settings = VisualOCRSettingsService(
            repository=self.repositories.settings,
            secrets=secret_store,
        )
        self.shortcut_settings = ShortcutSettingsService(repository=self.repositories.settings)
        self.disclosure_registry = DisclosurePolicyRegistry()
        self.index_backends = IndexBackendRegistry()
        self.index_backends.register(SQLiteKeywordIndexBackend(self.repositories.database), default=True)
        self.safe_index_projection = SafeIndexProjectionService(
            ids=self.ids,
            config=SafeIndexPolicyConfig(
                policy_version=settings.safe_index_policy_version,
                max_text_chars=settings.safe_index_max_text_chars,
            ),
        )
        self.indexing = IndexingService(
            registry=self.index_backends,
            vault=vault,
            safe_projection=self.safe_index_projection,
            policy_audit=self.repositories.index_policy_decisions,
        )
        self.events = ContextEventIngestService(
            events=self.repositories.events,
            ids=self.ids,
            clock=self.clock,
        )
        self.captures = CaptureIngestService(
            captures=self.repositories.captures,
            vault=vault,
            ids=self.ids,
            clock=self.clock,
        )
        self.provider_sessions = ProviderSessionService(clock=self.clock)
        self.provider_commands = ProviderCommandService(sessions=self.provider_sessions)
        self.system_evidence_providers = SystemEvidenceProviderRegistry()
        register_default_system_evidence_providers(
            registry=self.system_evidence_providers,
            include_macos_a11y=settings.recording_target == "macos",
            sessions=self.provider_sessions,
            ids=self.ids,
            clock=self.clock,
        )
        self.provider_lifecycle_registry = ProviderLifecycleRegistry()
        register_default_lifecycle_definitions(self.provider_lifecycle_registry)
        self.provider_lifecycle = ProviderLifecycleService(
            registry=self.provider_lifecycle_registry,
            sessions=self.provider_sessions,
        )
        self.source_providers = SourceProviderRegistry()
        web_provider = WebCaptureProvider(sessions=self.provider_sessions, ids=self.ids, clock=self.clock)
        if settings.recording_target == "macos":
            self.source_providers.register(web_provider)
        self.disclosure_registry.register_provider_manifest(web_provider.manifest)
        self.disclosure_registry.load_workspace_overrides(settings.disclosure_policy_path)
        active_capture_config = ActiveCapturePolicyConfig(
            enabled=settings.active_capture_enabled,
            auto_anchor_screenshots=settings.active_capture_auto_anchor_screenshots,
            short_observation_window_ms=settings.active_capture_short_observation_window_ms,
            max_session_duration_ms=settings.active_capture_max_session_duration_ms,
            max_keyframes_per_session=settings.active_capture_max_keyframes_per_session,
            scope_lost_grace_ms=settings.active_capture_scope_lost_grace_ms,
            video_enabled=settings.active_capture_video_enabled,
            video_max_bytes=settings.active_capture_video_max_bytes,
            timeline_alignment_tolerance_ms=settings.active_capture_timeline_alignment_tolerance_ms,
            pause_resume_enabled=settings.active_capture_pause_resume_enabled,
            action_trace_enabled=settings.active_capture_action_trace_enabled,
            record_action_coordinates=settings.active_capture_record_action_coordinates,
            max_action_events_per_session=settings.active_capture_max_action_events_per_session,
            min_keyframe_gap_ms=settings.active_capture_min_keyframe_gap_ms,
            click_settle_delay_ms=settings.active_capture_click_settle_delay_ms,
            scroll_stop_delay_ms=settings.active_capture_scroll_stop_delay_ms,
            hotkey_settle_delay_ms=settings.active_capture_hotkey_settle_delay_ms,
            typing_pause_delay_ms=settings.active_capture_typing_pause_delay_ms,
            idle_anchor_interval_ms=settings.active_capture_idle_anchor_interval_ms,
            visual_diff_threshold=settings.active_capture_visual_diff_threshold,
            text_diff_threshold=settings.active_capture_text_diff_threshold,
            adaptive_settle_min_delay_ms=settings.active_capture_adaptive_settle_min_delay_ms,
            adaptive_settle_max_wait_ms=settings.active_capture_adaptive_settle_max_wait_ms,
            adaptive_settle_poll_interval_ms=settings.active_capture_adaptive_settle_poll_interval_ms,
            adaptive_settle_required_stable_samples=settings.active_capture_adaptive_settle_required_stable_samples,
            settle_live_polling_enabled=settings.active_capture_settle_live_polling_enabled,
            settle_probe_strategy=settings.active_capture_settle_probe_strategy,
            settle_sample_budget=settings.active_capture_settle_sample_budget,
            settle_visual_diff_enabled=settings.active_capture_settle_visual_diff_enabled,
            settle_text_diff_enabled=settings.active_capture_settle_text_diff_enabled,
            settle_provider_readiness_enabled=settings.active_capture_settle_provider_readiness_enabled,
            settle_timeout_capture_enabled=settings.active_capture_settle_timeout_capture_enabled,
            settle_capture_claim_lease_ms=settings.active_capture_settle_capture_claim_lease_ms,
            max_pending_trigger_candidates=settings.active_capture_max_pending_trigger_candidates,
            max_producer_events_per_session=settings.active_capture_max_producer_events_per_session,
            click_target_resolver_enabled=settings.active_capture_click_target_resolver_enabled,
            click_target_high_confidence_threshold=(settings.active_capture_click_target_high_confidence_threshold),
            click_target_review_confidence_threshold=(settings.active_capture_click_target_review_confidence_threshold),
            click_target_max_candidates=settings.active_capture_click_target_max_candidates,
            click_target_max_safe_label_chars=settings.active_capture_click_target_max_safe_label_chars,
        )
        active_capture_projection_config = ActiveCaptureProjectionConfig(
            max_timeline_steps=settings.active_capture_projection_max_timeline_steps,
            max_actions=settings.active_capture_projection_max_actions,
            max_safe_text_blocks=settings.active_capture_projection_max_safe_text_blocks,
            max_safe_text_chars=settings.active_capture_projection_max_safe_text_chars,
            max_producer_diagnostics=settings.active_capture_projection_max_producer_diagnostics,
        )
        self.vm_a11y_probe = VMAccessibilityProbeService(
            config=VMAccessibilityProbeConfig(
                enabled=settings.recording_target == "linux" and settings.active_capture_vm_a11y_probe_enabled,
                profile=settings.active_capture_vm_a11y_probe_profile,
                source=settings.active_capture_vm_a11y_probe_source,
                url=settings.active_capture_vm_a11y_probe_url,
                a11y_path=settings.active_capture_vm_a11y_probe_a11y_path,
                events_path=settings.active_capture_vm_a11y_probe_events_path,
                events_limit=settings.active_capture_vm_a11y_probe_events_limit,
                events_poll_attempts=settings.active_capture_vm_a11y_probe_events_poll_attempts,
                events_poll_interval_seconds=settings.active_capture_vm_a11y_probe_events_poll_interval_seconds,
                events_match_window_seconds=settings.active_capture_vm_a11y_probe_events_match_window_seconds,
                click_log_url=settings.active_capture_vm_a11y_probe_click_log_url,
                click_log_path=settings.active_capture_vm_a11y_probe_click_log_path,
                click_log_ssh_enabled=settings.active_capture_vm_a11y_probe_click_log_ssh_enabled,
                click_log_ssh_jump_host=settings.active_capture_vm_a11y_probe_click_log_ssh_jump_host,
                click_log_ssh_host=settings.active_capture_vm_a11y_probe_click_log_ssh_host,
                click_log_ssh_port=settings.active_capture_vm_a11y_probe_click_log_ssh_port,
                click_log_ssh_user=settings.active_capture_vm_a11y_probe_click_log_ssh_user,
                click_log_ssh_key_path=settings.active_capture_vm_a11y_probe_click_log_ssh_key_path,
                click_log_ssh_guest_path=settings.active_capture_vm_a11y_probe_click_log_ssh_guest_path,
                click_log_ssh_timeout_seconds=settings.active_capture_vm_a11y_probe_click_log_ssh_timeout_seconds,
                depth=settings.active_capture_vm_a11y_probe_depth,
                max_nodes=settings.active_capture_vm_a11y_probe_max_nodes,
                periodic_depth=settings.active_capture_vm_a11y_probe_periodic_depth,
                periodic_max_nodes=settings.active_capture_vm_a11y_probe_periodic_max_nodes,
                request_timeout_seconds=settings.active_capture_vm_a11y_probe_request_timeout_seconds,
                restart_backoff_seconds=settings.active_capture_vm_a11y_probe_restart_backoff_seconds,
                max_history_per_session=settings.active_capture_vm_a11y_probe_max_history_per_session,
                export_drain_timeout_seconds=settings.active_capture_vm_a11y_probe_export_drain_timeout_seconds,
                archive_dir=str(Path(settings.database_path).expanduser().parent / "recording_probe_logs"),
            )
        )
        self.vm_a11y_probe_settings = VMA11yProbeSettingsService(
            repository=self.repositories.settings,
            probe=self.vm_a11y_probe,
            allowed=settings.recording_target == "linux",
        )
        vm_display_geometry = (
            VMDisplayGeometry(
                vm_width=settings.active_capture_vm_a11y_probe_vm_screen_width,
                vm_height=settings.active_capture_vm_a11y_probe_vm_screen_height,
                title_bar_pt=settings.active_capture_vm_a11y_probe_title_bar_pt,
            )
            if settings.active_capture_vm_a11y_probe_vm_screen_width is not None
            and settings.active_capture_vm_a11y_probe_vm_screen_height is not None
            else None
        )
        self.active_capture = ActiveCaptureService(
            repository=self.repositories.active_capture,
            ids=self.ids,
            clock=self.clock,
            config=active_capture_config,
            projection_config=active_capture_projection_config,
            artifact_vault=vault,
            vm_a11y_probe=self.vm_a11y_probe,
            vm_display=vm_display_geometry,
            video_artifacts=VaultVideoArtifactAdapter(
                vault=vault,
                artifacts=self.repositories.artifacts,
                ids=self.ids,
                clock=self.clock,
                config=active_capture_config,
            ),
        )
        post_commit_outbox_config = CapturePostCommitOutboxConfig(
            enabled=settings.capture_post_commit_outbox_enabled,
            max_attempts=settings.capture_post_commit_outbox_max_attempts,
            claim_limit=settings.capture_post_commit_outbox_claim_limit,
            retry_backoff_ms=settings.capture_post_commit_outbox_retry_backoff_ms,
            max_retry_delay_ms=settings.capture_post_commit_outbox_max_retry_delay_ms,
            stale_running_after_ms=settings.capture_post_commit_outbox_stale_running_after_ms,
            worker_enabled=settings.capture_post_commit_outbox_worker_enabled,
            worker_poll_interval_ms=settings.capture_post_commit_outbox_worker_poll_interval_ms,
        )
        self.capture_post_commit_outbox = CapturePostCommitOutboxDispatcher(
            repository=self.repositories.capture_post_commit_outbox,
            context_resolver=self.repositories.capture_post_commit_context_resolver,
            handlers=(
                CapturePostCommitHandler(
                    kind=CapturePostCommitTaskKind.ACTIVE_CAPTURE_KEYFRAME,
                    handler_id="active_capture.keyframe.v1",
                    hook=self.active_capture,
                ),
            ),
            ids=self.ids,
            clock=self.clock,
            config=post_commit_outbox_config,
        )
        self.capture_attempts = CaptureAttemptService(
            surface_detection=SurfaceDetectionService(),
            provider_routing=ProviderRoutingService(
                self.source_providers,
                policy=ProviderRoutePolicy(
                    ProviderRoutePolicyConfig(
                        min_provider_confidence=settings.capture_route_min_provider_confidence,
                        min_secondary_overlap_ratio=settings.capture_route_min_secondary_overlap_ratio,
                        max_app_routes=settings.capture_route_max_app_routes,
                        overlap_weight=settings.capture_route_overlap_weight,
                        confidence_weight=settings.capture_route_confidence_weight,
                        visible_area_weight=settings.capture_route_visible_area_weight,
                        frontmost_bonus=settings.capture_route_frontmost_bonus,
                        z_order_base_bonus=settings.capture_route_z_order_base_bonus,
                        z_order_decay=settings.capture_route_z_order_decay,
                    )
                ),
            ),
            app_fanout=AppProviderFanoutService(
                providers=self.source_providers,
                commands=self.provider_commands,
                clock=self.clock,
            ),
            system_evidence=SystemEvidenceOrchestrator(
                registry=self.system_evidence_providers,
                ids=self.ids,
                clock=self.clock,
            ),
            persistence=CapturePersistenceService(
                captures=self.repositories.captures,
                jobs=self.repositories.jobs,
                ledger=self.repositories.ledger,
                vault=vault,
                ids=self.ids,
                clock=self.clock,
                indexing=self.indexing,
                post_commit_task_planner=self.capture_post_commit_outbox,
            ),
        )
        self.artifacts = ArtifactAccessService(
            self.repositories.artifacts, events=self.repositories.events, vault=vault
        )
        self.recording_exporter = RecordingExporter(
            graph_reader=RecordingSessionGraphReader(
                repository=self.repositories.active_capture,
                projection_config=active_capture_projection_config,
            ),
            artifacts=self.repositories.artifacts,
            content_source=vault,
            vm_a11y_probe=self.vm_a11y_probe,
            vm_display=vm_display_geometry,
        )
        self.derived_persistence = DerivedEvidencePersistenceService(
            ledger=self.repositories.ledger,
            artifacts=self.repositories.artifacts,
            vault=vault,
            ids=self.ids,
            clock=self.clock,
            evidence_policy=EvidencePolicyService(),
            indexing=self.indexing,
        )
        self.visual_ocr = VisualOCRJobRunner(
            repositories=self.repositories,
            service=VisualOCRService(
                vault=vault,
                settings=self.visual_ocr_settings,
                clock=self.clock,
                ids=self.ids,
                redactor=SensitiveTextRedactor(),
                prompt_builder=VisualOCRPromptBuilder(),
            ),
            persistence=self.derived_persistence,
            ids=self.ids,
            clock=self.clock,
            after_completed=self._refresh_active_capture_index_after_visual_ocr,
        )
        self.agent_runs = AgentRunLedgerService(
            repository=self.repositories.agent_run_ledger,
            traces=self.repositories.agent_run_traces,
            artifacts=self.repositories.artifacts,
            events=self.repositories.events,
            artifact_access=self.artifacts,
            ids=self.ids,
            clock=self.clock,
            active_capture_citations=ActiveCaptureCitationResolver(
                repository=self.repositories.active_capture,
                events=self.repositories.events,
                artifact_access=self.artifacts,
            ),
        )
        self.disclosure = DisclosurePolicyService(
            registry=self.disclosure_registry,
            artifacts=self.repositories.artifacts,
            events=self.repositories.events,
            ledger=self.repositories.ledger,
            vault=vault,
            ids=self.ids,
        )
        self.active_capture_inspect = RecordingInspectService(
            repository=self.repositories.active_capture,
            clock=self.clock,
            event_lookup=RepositoryEventLookupAdapter(self.repositories.events),
            event_inspector=DisclosureEventEvidenceInspectAdapter(self.disclosure),
            safe_index=self.safe_index_projection,
            projection_config=active_capture_projection_config,
        )
        feishu_token_client = FeishuTokenClient(
            app_id=settings.feishu_app_id,
            secret_store=secret_store,
            api_base_url=settings.feishu_api_base_url,
            clock=self.clock,
        )
        feishu_drive = FeishuDriveClient(
            token_client=feishu_token_client,
            folder_token=settings.feishu_folder_token,
            api_base_url=settings.feishu_api_base_url,
        )

        def feishu_share_signature_secret() -> str | None:
            return secret_store.get(service=FEISHU_SECRET_SERVICE, account=FEISHU_SECRET_ACCOUNT)

        self.context_shares = ContextShareService(
            shares=self.repositories.shares,
            events=self.repositories.events,
            artifacts=self.repositories.artifacts,
            disclosure=self.disclosure,
            vault=vault,
            ids=self.ids,
            clock=self.clock,
            package_builder=SharePackageBuilder(
                clock=self.clock,
                signature_secret_provider=feishu_share_signature_secret,
            ),
            package_parser=SharePackageParser(signature_secret_provider=feishu_share_signature_secret),
            publishers=SharePublisherRegistry(
                (FeishuSharePublisher(drive=feishu_drive, ids=self.ids, clock=self.clock),)
            ),
            feishu_drive=feishu_drive,
            indexing=self.indexing,
        )
        self.search = SearchService(
            events=self.repositories.events,
            disclosure=self.disclosure,
            index_registry=self.index_backends,
            card_overlay=self._active_capture_card_overlay,
        )
        self.bundles = ContextBundleBuilder(
            search=self.search,
            bundles=self.repositories.bundles,
            artifacts=self.repositories.artifacts,
            ids=self.ids,
            clock=self.clock,
        )
        self.audits = audit_writer

    def _active_capture_card_overlay(self, event_id: str) -> SearchCardOverlay | None:
        keyframes = self.repositories.active_capture.list_keyframes_for_event(event_id)
        if not keyframes:
            event = self.repositories.events.get(event_id)
            candidate_id = event.trigger.metadata.get("active_capture_candidate_id") if event is not None else None
            if not isinstance(candidate_id, str) or not candidate_id:
                return None
            candidate = self.repositories.active_capture.get_trigger_candidate(candidate_id)
            if candidate is None:
                return None
            session = self.repositories.active_capture.get_session(candidate.session_id)
            if session is None:
                return None
            if session.primary_event_id == event_id and session.mode == ActiveCaptureMode.RECORDING_SESSION:
                return SearchCardOverlay(
                    hidden_artifacts=("active_capture_raw_materials", "active_capture_recording"),
                    user_note=session.user_note,
                )
            return SearchCardOverlay(
                hidden_artifacts=("active_capture_raw_materials", "active_capture_keyframe_material")
            )
        session = self.repositories.active_capture.get_session(keyframes[0].session_id)
        if session is None:
            return None
        if session.primary_event_id == event_id:
            if session.mode == ActiveCaptureMode.RECORDING_SESSION:
                return SearchCardOverlay(
                    hidden_artifacts=("active_capture_raw_materials", "active_capture_recording"),
                    user_note=session.user_note,
                )
            return None
        hidden_artifacts = ["active_capture_raw_materials"]
        hidden_artifacts.append("active_capture_keyframe_material")
        return SearchCardOverlay(hidden_artifacts=tuple(hidden_artifacts))

    def _refresh_active_capture_index_after_visual_ocr(self, event_id: str) -> None:
        """Refresh active-capture safe index projections after late OCR evidence.

        Visual OCR evidence is appended after the original capture commit. When
        the event is part of a recording graph, rebuild only the safe
        active-capture projection so the recording card/search can see the new
        redacted text without exposing raw keyframe material.
        """

        keyframes = self.repositories.active_capture.list_keyframes_for_event(event_id)
        session = None
        if keyframes:
            session = self.repositories.active_capture.get_session(keyframes[0].session_id)
        else:
            bundle = self.repositories.active_capture.get_bundle_for_event(event_id)
            if bundle is not None:
                session = self.repositories.active_capture.get_session(bundle.session_id)
        if session is None or session.primary_event_id is None:
            return
        actor = session.actor or ActorRef(actor_id="system.visual_ocr", display_name="Visual OCR")
        try:
            inspect = self.active_capture_inspect.build_for_event(
                event_id=session.primary_event_id,
                actor=actor,
                purpose="active_capture_visual_ocr_refresh",
                requested_sections=(
                    EventInspectSection.ACTIVE_CAPTURE_SUMMARY,
                    EventInspectSection.RECORDING_TIMELINE,
                    EventInspectSection.SELECTION_TEXT,
                    EventInspectSection.VISUAL_OCR_TEXT,
                    EventInspectSection.CANONICAL,
                    EventInspectSection.CLEAN_PAGE_TEXT,
                    EventInspectSection.EVIDENCE_REFS,
                ),
            )
            if inspect is None:
                return
            batch = self.active_capture_inspect.index_projection_for_inspect(inspect, actor=actor)
            if batch is not None:
                self.indexing.index_safe_projection(batch)
        except Exception:
            logger.warning(
                "active capture visual OCR safe index refresh failed",
                extra={"event_id": event_id},
                exc_info=True,
            )
