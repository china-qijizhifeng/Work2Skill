"""Read-time disclosure decisions and view builders."""

from __future__ import annotations

import logging

from packages.artifacts.vault import ArtifactVaultError, LocalArtifactVault
from packages.contracts import (
    AccessScope,
    ActorRef,
    Artifact,
    ArtifactType,
    BoundingBox,
    CaptureStrategy,
    ContextEvent,
    DisclosureClass,
    DisclosureDecision,
    DisclosureDecisionStatus,
    DisclosureField,
    DisclosureProfile,
    DisclosureView,
    EventCaptureEnvelope,
    EventInspectSection,
    EventInspectView,
    HiddenArtifactSummary,
    KeyframeInspectSummary,
    ProviderCaptureOutcomeStatus,
    ProviderKind,
    ReadableEvidenceView,
    SearchResultCard,
    SystemAppshotSnapshot,
)
from packages.shared.ids import IdFactory
from packages.storage.artifact_repository import ArtifactRepository
from packages.storage.event_repository import ContextEventRepository
from packages.storage.ledger_repository import CaptureLedgerRepository

from .registry import DisclosurePolicyRegistry
from .service_internals import _DisclosurePolicyInternals
from .source_contributions import EventSourceContributionBuilder
from .views import bounded_text, match_reason, snippet, source_for_event

logger = logging.getLogger(__name__)
SYSTEM_APPSHOT_PROVIDER_KEY = "system.appshot"


class DisclosurePolicyService(_DisclosurePolicyInternals):
    """Build policy-aware read views from stored event evidence."""

    def __init__(
        self,
        *,
        registry: DisclosurePolicyRegistry,
        artifacts: ArtifactRepository,
        events: ContextEventRepository,
        ledger: CaptureLedgerRepository,
        vault: LocalArtifactVault,
        ids: IdFactory,
        summary_selection_max_chars: int = 4000,
        summary_note_max_chars: int = 1000,
        inspect_text_max_chars: int = 64000,
    ) -> None:
        self.registry = registry
        self.artifacts = artifacts
        self.events = events
        self.ledger = ledger
        self.vault = vault
        self.ids = ids
        self.summary_selection_max_chars = summary_selection_max_chars
        self.summary_note_max_chars = summary_note_max_chars
        self.inspect_text_max_chars = inspect_text_max_chars
        self.source_contributions = EventSourceContributionBuilder(ledger)

    def summary_card(self, *, event: ContextEvent, query: str = "") -> SearchResultCard:
        """Return the safe default summary card for one event.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        profile = self.registry.profile_for_source_binding(event.source_binding)
        artifacts = self.artifacts.list_for_event(event.event_id)
        selection_text, selection_artifact, confidence = self._first_text_for_rule(
            profile=profile,
            view=DisclosureView.SUMMARY_CARD,
            disclosure_class=DisclosureClass.SELECTION_BOUND_TEXT,
            artifacts=artifacts,
        )
        canonical_text, _, _ = self._first_text_for_rule(
            profile=profile,
            view=DisclosureView.ARTIFACT_PREVIEW,
            disclosure_class=DisclosureClass.REDACTED_CANONICAL,
            artifacts=artifacts,
        )
        snippet_source = selection_text.text or event.intent_text or event.source_binding.source_ref.title
        user_note = bounded_text(
            event.intent_text or event.trigger.intent_text or "", limit=self.summary_note_max_chars
        )
        hidden = self.hidden_artifacts(artifacts=artifacts)
        envelope = self.ledger.get_envelope_by_event_id(event.event_id)
        provider_contributions, provider_diagnostics_count = self._provider_contribution_summary(envelope)
        match_reason_value = match_reason(
            query=query, selection_text=selection_text.text, canonical_text=canonical_text.text, event=event
        )
        logger.info(
            "disclosure summary card built",
            extra={
                "event_id": event.event_id,
                "profile_key": profile.profile_key,
                "hidden_artifact_count": len(hidden),
                "user_note_truncated": user_note.truncated,
                "selection_text_truncated": selection_text.truncated,
                "match_reason": match_reason_value,
            },
        )
        hidden_markers = [summary.artifact_type.value for summary in hidden]
        if ArtifactType.RECORDING_VIDEO.value in hidden_markers:
            hidden_markers.append("active_capture_recording")
        return SearchResultCard(
            event_id=event.event_id,
            event_type=event.event_type,
            captured_at=event.trigger.occurred_at,
            source=source_for_event(event),
            selection_bbox=self._public_selection_bbox(event),
            user_note=user_note.text or None,
            user_note_truncated=user_note.truncated,
            selection_text=selection_text.text,
            selection_text_snippet=snippet(snippet_source, query=query),
            selection_text_truncated=selection_text.truncated,
            canonical_text_snippet=snippet(canonical_text.text, query=query),
            canonical_text_truncated=canonical_text.truncated,
            preview_evidence_id=selection_artifact.evidence_id if selection_artifact is not None else None,
            preview_confidence=confidence,
            match_reason=match_reason_value,
            hidden_artifacts=tuple(dict.fromkeys(hidden_markers)),
            provider_contributions=provider_contributions,
            provider_diagnostics_count=provider_diagnostics_count,
            source_kind=event.source_binding.source_ref.source_type.value,
            disclosure_view=DisclosureView.SUMMARY_CARD,
            disclosure_policy_version=profile.version,
        )

    def _provider_contribution_summary(self, envelope: EventCaptureEnvelope | None) -> tuple[tuple[str, ...], int]:
        if envelope is None:
            return (), 0
        contributions: list[str] = []
        diagnostics_count = 0
        for outcome in envelope.provider_outcomes:
            if (
                outcome.provider_kind == ProviderKind.SOURCE
                and outcome.status == ProviderCaptureOutcomeStatus.SUCCEEDED
            ):
                contributions.append(outcome.provider_key)
            elif outcome.provider_kind == ProviderKind.SOURCE and outcome.status not in {
                ProviderCaptureOutcomeStatus.SUCCEEDED,
                ProviderCaptureOutcomeStatus.SELECTED,
            }:
                diagnostics_count += 1
        return tuple(dict.fromkeys(contributions)), diagnostics_count

    def inspect_event(
        self,
        *,
        event: ContextEvent,
        actor: ActorRef,
        purpose: str,
        requested_sections: tuple[EventInspectSection, ...] = (),
    ) -> EventInspectView:
        """Return the explicit event_id inspection view.

        Args:
            event: Event being inspected by id.
            actor: Actor receiving the disclosed view.
            purpose: Human-readable reason for the read.

        Returns:
            Policy-built event inspection view with readable evidence and raw refs.
        """

        return self._inspect_event_impl(
            event=event,
            actor=actor,
            purpose=purpose,
            requested_sections=requested_sections,
        )

    def with_keyframe_summaries(
        self,
        *,
        inspect_view: EventInspectView,
        keyframes: tuple[KeyframeInspectSummary, ...],
    ) -> EventInspectView:
        """Attach safe keyframe summaries inside the disclosure boundary."""

        decision = inspect_view.disclosure_decision.model_copy(
            update={
                "delivered_fields": tuple(
                    dict.fromkeys((*inspect_view.disclosure_decision.delivered_fields, DisclosureField.KEYFRAMES))
                ),
                "details": {
                    **inspect_view.disclosure_decision.details,
                    "keyframe_count": len(keyframes),
                },
            }
        )
        return inspect_view.model_copy(update={"keyframes": keyframes, "disclosure_decision": decision})

    def _inspect_event_impl(
        self,
        *,
        event: ContextEvent,
        actor: ActorRef,
        purpose: str,
        requested_sections: tuple[EventInspectSection, ...],
    ) -> EventInspectView:
        """Return the explicit event_id inspection view."""

        profile = self.registry.profile_for_source_binding(event.source_binding)
        artifacts = self.artifacts.list_for_event(event.event_id)
        requested = set(requested_sections)
        empty_text = bounded_text("", limit=1)
        if EventInspectSection.SELECTION_TEXT in requested:
            selection_text, selection_artifact, selection_confidence = self._first_text_for_rule(
                profile=profile,
                view=DisclosureView.EVENT_INSPECT,
                disclosure_class=DisclosureClass.SELECTION_BOUND_TEXT,
                artifacts=artifacts,
            )
        else:
            selection_text, selection_artifact, selection_confidence = empty_text, None, 0.0
        if EventInspectSection.CANONICAL in requested:
            canonical_text, canonical_artifact, canonical_confidence = self._first_text_for_rule(
                profile=profile,
                view=DisclosureView.EVENT_INSPECT,
                disclosure_class=DisclosureClass.REDACTED_CANONICAL,
                artifacts=artifacts,
            )
        else:
            canonical_text, canonical_artifact, canonical_confidence = empty_text, None, 0.0
        if EventInspectSection.CLEAN_PAGE_TEXT in requested:
            clean_page_text, clean_artifact, clean_confidence = self._first_text_for_rule(
                profile=profile,
                view=DisclosureView.EVENT_INSPECT,
                disclosure_class=DisclosureClass.CLEAN_PAGE_TEXT,
                artifacts=artifacts,
            )
        else:
            clean_page_text, clean_artifact, clean_confidence = empty_text, None, 0.0
        if EventInspectSection.VISUAL_OCR_TEXT in requested:
            visual_ocr_text, visual_ocr_artifact, visual_ocr_confidence = self._first_text_for_rule(
                profile=profile,
                view=DisclosureView.EVENT_INSPECT,
                disclosure_class=DisclosureClass.VISUAL_OCR_TEXT,
                artifacts=artifacts,
            )
        else:
            visual_ocr_text, visual_ocr_artifact, visual_ocr_confidence = empty_text, None, 0.0
        system_appshot = (
            self._system_appshot_snapshot(event=event, artifacts=artifacts)
            if EventInspectSection.SYSTEM_APPSHOT in requested
            else None
        )
        readable: list[ReadableEvidenceView] = []
        if EventInspectSection.EVIDENCE_REFS in requested:
            readable.extend(
                self._readable_refs(
                    profile=profile,
                    artifacts=artifacts,
                    requested_sections=requested_sections,
                )
            )
        if selection_artifact is not None:
            readable.append(
                self._readable_view(
                    artifact=selection_artifact,
                    text=selection_text.text,
                    truncated=selection_text.truncated,
                    disclosure_class=DisclosureClass.SELECTION_BOUND_TEXT,
                    confidence=selection_confidence,
                )
            )
        if canonical_artifact is not None:
            readable.append(
                self._readable_view(
                    artifact=canonical_artifact,
                    text=canonical_text.text,
                    truncated=canonical_text.truncated,
                    disclosure_class=DisclosureClass.REDACTED_CANONICAL,
                    confidence=canonical_confidence,
                )
            )
        if clean_artifact is not None:
            readable.append(
                self._readable_view(
                    artifact=clean_artifact,
                    text=clean_page_text.text,
                    truncated=clean_page_text.truncated,
                    disclosure_class=DisclosureClass.CLEAN_PAGE_TEXT,
                    confidence=clean_confidence,
                )
            )
        if visual_ocr_artifact is not None:
            readable.append(
                self._readable_view(
                    artifact=visual_ocr_artifact,
                    text=visual_ocr_text.text,
                    truncated=visual_ocr_text.truncated,
                    disclosure_class=DisclosureClass.VISUAL_OCR_TEXT,
                    confidence=visual_ocr_confidence,
                )
            )
        raw_refs = tuple(
            self._raw_ref(artifact)
            for artifact in artifacts
            if self._rule_for_artifact(
                profile=profile,
                view=DisclosureView.RAW_ARTIFACT,
                disclosure_class=DisclosureClass.RAW_VISUAL,
                artifact=artifact,
            )
            is not None
        )
        hidden = self.hidden_artifacts(artifacts=artifacts)
        decision = DisclosureDecision(
            decision_id=self.ids.new("dsc"),
            status=DisclosureDecisionStatus.ALLOWED,
            view=DisclosureView.EVENT_INSPECT,
            profile_key=profile.profile_key,
            resource_type="event",
            resource_id=event.event_id,
            allowed_scopes=(AccessScope.READ_METADATA, AccessScope.READ_TEXT),
            delivered_fields=tuple(
                field
                for field in (
                    DisclosureField.EVENT_ID,
                    DisclosureField.CAPTURED_AT,
                    DisclosureField.SOURCE,
                    DisclosureField.SELECTION_BBOX,
                    DisclosureField.SYSTEM_APPSHOT if system_appshot is not None else None,
                    DisclosureField.CANONICAL_TEXT if EventInspectSection.CANONICAL in requested else None,
                    DisclosureField.CLEAN_PAGE_TEXT if EventInspectSection.CLEAN_PAGE_TEXT in requested else None,
                    DisclosureField.VISUAL_OCR_TEXT if EventInspectSection.VISUAL_OCR_TEXT in requested else None,
                    DisclosureField.KEYFRAMES if EventInspectSection.KEYFRAMES in requested else None,
                    DisclosureField.RAW_ARTIFACT_REFS,
                    DisclosureField.HIDDEN_ARTIFACTS,
                )
                if field is not None
            ),
            hidden_artifacts=hidden,
            reason=purpose,
            policy_version=profile.version,
            details={
                "actor_id": actor.actor_id,
                "canonical_text_chars": len(canonical_text.text),
                "clean_page_text_chars": len(clean_page_text.text),
                "visual_ocr_text_chars": len(visual_ocr_text.text),
                "system_appshot_delivered": system_appshot is not None,
                "raw_ref_count": len(raw_refs),
            },
        )
        logger.info(
            "disclosure event inspect built",
            extra={
                "event_id": event.event_id,
                "profile_key": profile.profile_key,
                "actor_id": actor.actor_id,
                "purpose": purpose,
                "readable_evidence_count": len(readable),
                "raw_ref_count": len(raw_refs),
            },
        )
        return EventInspectView(
            event_id=event.event_id,
            captured_at=event.trigger.occurred_at,
            source=source_for_event(event),
            selection_bbox=self._public_selection_bbox(event),
            system_appshot=system_appshot,
            canonical_text=canonical_text.text,
            canonical_text_truncated=canonical_text.truncated,
            clean_page_text=clean_page_text.text,
            clean_page_text_truncated=clean_page_text.truncated,
            source_contributions=self.source_contributions.build(event),
            readable_evidence=tuple(readable),
            raw_artifacts=raw_refs,
            hidden_artifacts=hidden,
            disclosure_decision=decision,
        )

    def _public_selection_bbox(self, event: ContextEvent) -> BoundingBox | None:
        """Hide exact frontmost-window frames from default public projections."""

        if event.trigger.capture_strategy == CaptureStrategy.OS_WINDOW:
            return None
        return event.trigger.selection

    def _system_appshot_snapshot(
        self,
        *,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
    ) -> SystemAppshotSnapshot | None:
        """Load the safe system appshot metadata snapshot for event inspection."""

        for artifact in artifacts:
            if artifact.artifact_type != ArtifactType.SYSTEM_APPSHOT:
                continue
            if artifact.provider_key != SYSTEM_APPSHOT_PROVIDER_KEY or artifact.storage_uri is None:
                continue
            try:
                snapshot = SystemAppshotSnapshot.model_validate_json(
                    self.vault.read(artifact.storage_uri).decode("utf-8")
                )
                return self._public_system_appshot_snapshot(
                    snapshot,
                    is_os_window=event.trigger.capture_strategy == CaptureStrategy.OS_WINDOW,
                )
            except (ArtifactVaultError, UnicodeDecodeError, ValueError) as exc:
                logger.warning(
                    "failed to load system appshot artifact",
                    extra={"artifact_id": artifact.artifact_id, "error": str(exc)},
                )
                return None
        return None

    def _public_system_appshot_snapshot(
        self,
        snapshot: SystemAppshotSnapshot,
        *,
        is_os_window: bool = False,
    ) -> SystemAppshotSnapshot:
        selected_region = snapshot.selected_region
        if is_os_window:
            selected_region = selected_region.model_copy(
                update={
                    "x": 0,
                    "y": 0,
                    "width": 1,
                    "height": 1,
                }
            )
        safe_surfaces = tuple(
            surface.model_copy(
                update={
                    "identity": surface.identity.model_copy(
                        update={
                            "bundle_id": None,
                            "bundle_url": None,
                            "app_icon_ref": None,
                            "process_id": None,
                            "window_id": None,
                            "frame": None,
                            "display_id": None,
                            "window_order": None,
                        }
                    )
                }
            )
            for surface in snapshot.surfaces
        )
        safe_components = tuple(
            component.model_copy(
                update={
                    "artifact_ids": (),
                    "command_id": None,
                    "provider_session_id": None,
                    "route_id": None,
                }
            )
            for component in snapshot.components
        )
        safe_metadata = {
            key: value
            for key, value in snapshot.metadata.items()
            if not any(marker in key.lower() for marker in ("path", "uri", "url", "vault", "storage"))
        }
        return snapshot.model_copy(
            update={
                "selected_region": selected_region,
                "surfaces": safe_surfaces,
                "primary_bundle_id": None,
                "primary_process_id": None,
                "primary_window_id": None,
                "components": safe_components,
                "metadata": safe_metadata,
            }
        )

    def _readable_refs(
        self,
        *,
        profile: DisclosureProfile,
        artifacts: tuple[Artifact, ...],
        requested_sections: tuple[EventInspectSection, ...],
    ) -> list[ReadableEvidenceView]:
        """Return metadata-only readable evidence refs without opening artifact content."""

        requested = set(requested_sections)
        text_requested_classes: set[DisclosureClass] = set()
        if EventInspectSection.SELECTION_TEXT in requested:
            text_requested_classes.add(DisclosureClass.SELECTION_BOUND_TEXT)
        if EventInspectSection.CANONICAL in requested:
            text_requested_classes.add(DisclosureClass.REDACTED_CANONICAL)
        if EventInspectSection.CLEAN_PAGE_TEXT in requested:
            text_requested_classes.add(DisclosureClass.CLEAN_PAGE_TEXT)
        if EventInspectSection.VISUAL_OCR_TEXT in requested:
            text_requested_classes.add(DisclosureClass.VISUAL_OCR_TEXT)

        refs: list[ReadableEvidenceView] = []
        for artifact in artifacts:
            disclosure_class = self._disclosure_class(artifact)
            if disclosure_class not in {
                DisclosureClass.SELECTION_BOUND_TEXT,
                DisclosureClass.VISUAL_OCR_TEXT,
                DisclosureClass.REDACTED_CANONICAL,
                DisclosureClass.CLEAN_PAGE_TEXT,
            }:
                continue
            if disclosure_class in text_requested_classes:
                continue
            if (
                self._rule_for_artifact(
                    profile=profile,
                    view=DisclosureView.EVENT_INSPECT,
                    disclosure_class=disclosure_class,
                    artifact=artifact,
                )
                is None
            ):
                continue
            refs.append(
                self._readable_view(
                    artifact=artifact,
                    text="",
                    truncated=False,
                    disclosure_class=disclosure_class,
                    confidence=float(artifact.metadata.get("confidence", 0.0) or 0.0),
                )
            )
        return refs
