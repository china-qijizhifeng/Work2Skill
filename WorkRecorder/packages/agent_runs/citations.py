"""Citation registration and safe resolution services."""

from __future__ import annotations

from packages.active_capture.application.citations import ActiveCaptureCitationResolver
from packages.artifacts.service import ArtifactAccessService
from packages.contracts import (
    AccessScope,
    ActorRef,
    AgentRun,
    ArtifactDisclosureRef,
    CitationRecord,
    CitationResolveResponse,
    CitationUseState,
    ContextBundle,
    ContextBundleItem,
    EventInspectView,
    EvidenceRef,
    ReadableEvidenceView,
    SearchResponse,
    SearchResultCard,
)
from packages.contracts.active_capture_inspect import (
    ActiveCaptureCitationRef,
    ActiveCaptureInspectView,
    RecordingSafeTextBlock,
    RecordingTimelineStepView,
)
from packages.contracts.api import ApiError
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from packages.storage.agent_run_repository import AgentRunLedgerRepository
from packages.storage.artifact_repository import ArtifactRepository


class CitationRegistryService:
    """Create and resolve citation ids tied to one agent run."""

    def __init__(
        self,
        *,
        repository: AgentRunLedgerRepository,
        artifacts: ArtifactRepository,
        artifact_access: ArtifactAccessService,
        ids: IdFactory,
        clock: Clock,
        active_capture_resolver: ActiveCaptureCitationResolver | None = None,
    ) -> None:
        self.repository = repository
        self.artifacts = artifacts
        self.artifact_access = artifact_access
        self.ids = ids
        self.clock = clock
        self.active_capture_resolver = active_capture_resolver

    def attach_search(self, *, run: AgentRun, response: SearchResponse) -> SearchResponse:
        """Attach preview citation ids to search result cards.

        Args:
            run: Agent run that owns the delivered search response.
            response: Policy-filtered search response to annotate.

        Returns:
            Search response with per-card preview citation ids where evidence is available.
        """

        cards: list[SearchResultCard] = []
        for card in response.results:
            citation_id = None
            if card.preview_evidence_id:
                citation_id = self._citation_for_event_evidence(
                    run=run,
                    event_id=card.event_id,
                    evidence_id=card.preview_evidence_id,
                    state=CitationUseState.DELIVERED,
                )
            cards.append(card.model_copy(update={"preview_citation_id": citation_id}))
        return response.model_copy(update={"results": tuple(cards)})

    def attach_inspect(self, *, run: AgentRun, view: EventInspectView) -> EventInspectView:
        """Attach citation ids to inspect evidence and screenshot refs.

        Args:
            run: Agent run that requested the inspect view.
            view: Disclosure-filtered event inspect view.

        Returns:
            Inspect view with citation ids on readable evidence and raw refs.
        """

        readable: list[ReadableEvidenceView] = []
        for item in view.readable_evidence:
            citation_id = self._citation_for_ref(
                run=run,
                event_id=view.event_id,
                artifact_id=item.artifact_id,
                evidence_id=item.evidence_id,
                state=CitationUseState.DELIVERED,
                metadata={"disclosure_class": item.disclosure_class.value},
            )
            readable.append(item.model_copy(update={"citation_id": citation_id}))
        raw_refs: list[ArtifactDisclosureRef] = []
        for ref in view.raw_artifacts:
            citation_id = self._citation_for_ref(
                run=run,
                event_id=view.event_id,
                artifact_id=ref.artifact_id,
                evidence_id=ref.evidence_id,
                state=CitationUseState.DELIVERED,
                metadata={"disclosure_class": ref.disclosure_class.value, "raw_ref_only": True},
            )
            raw_refs.append(ref.model_copy(update={"citation_id": citation_id}))
        active_capture = (
            self._attach_active_capture(run=run, view=view.active_capture) if view.active_capture is not None else None
        )
        return view.model_copy(
            update={
                "readable_evidence": tuple(readable),
                "raw_artifacts": tuple(raw_refs),
                "active_capture": active_capture,
            }
        )

    def attach_bundle(self, *, run: AgentRun, bundle: ContextBundle) -> ContextBundle:
        """Register bundle citation ids and attach them to bundle items.

        Args:
            run: Agent run that created the bundle.
            bundle: Context bundle whose item references should become citations.

        Returns:
            Bundle copy with citation ids attached to each item.
        """

        items: list[ContextBundleItem] = []
        for item in bundle.items:
            citation_ids = tuple(
                self._citation_from_evidence_ref(run=run, ref=ref, state=CitationUseState.INCLUDED_IN_BUNDLE)
                for ref in item.citations
            )
            items.append(item.model_copy(update={"citation_ids": citation_ids}))
        return bundle.model_copy(update={"items": tuple(items), "agent_run_id": run.agent_run_id})

    def resolve(self, *, citation_id: str, actor: ActorRef, run: AgentRun) -> CitationResolveResponse | None:
        """Resolve one citation to safe metadata and text when permitted.

        Args:
            citation_id: Citation id previously delivered during this run.
            actor: Actor requesting the citation resolution.
            run: Active agent run that must own the citation.

        Returns:
            Safe citation response, or ``None`` when the citation is missing or foreign.
        """

        citation = self.repository.get_citation(citation_id)
        if citation is None or citation.agent_run_id != run.agent_run_id or run.actor.actor_id != actor.actor_id:
            return None
        if citation.active_capture_target is not None and self.active_capture_resolver is not None:
            return self.active_capture_resolver.resolve(citation=citation, actor=actor, run=run)
        text = ""
        if citation.artifact_id:
            artifact = self.artifact_access.get_metadata(citation.artifact_id)
            if artifact is not None and AccessScope.READ_TEXT in artifact.allowed_scopes:
                content = self.artifact_access.read_text_content(
                    artifact=artifact, actor=actor, scope=AccessScope.READ_TEXT
                )
                if not isinstance(content, ApiError):
                    text = self._slice_text(content, citation)
        return CitationResolveResponse(citation=citation, text=text, text_truncated=False)

    def _citation_for_event_evidence(
        self, *, run: AgentRun, event_id: str, evidence_id: str, state: CitationUseState
    ) -> str:
        artifact_id = None
        for artifact in self.artifacts.list_for_event(event_id):
            if artifact.evidence_id == evidence_id:
                artifact_id = artifact.artifact_id
                break
        return self._citation_for_ref(
            run=run,
            event_id=event_id,
            artifact_id=artifact_id,
            evidence_id=evidence_id,
            state=state,
            metadata={},
        )

    def _citation_for_ref(
        self,
        *,
        run: AgentRun,
        event_id: str,
        artifact_id: str | None,
        evidence_id: str | None,
        state: CitationUseState,
        metadata: dict[str, object],
    ) -> str:
        citation = CitationRecord(
            citation_id=self.ids.new("cit"),
            agent_run_id=run.agent_run_id,
            event_id=event_id,
            evidence_id=evidence_id,
            artifact_id=artifact_id,
            evidence_ref=evidence_id,
            state=state,
            created_at=self.clock.now(),
            metadata=self._scalar_metadata(metadata),
        )
        return self.repository.save_citation(citation).citation_id

    def _citation_from_evidence_ref(self, *, run: AgentRun, ref: EvidenceRef, state: CitationUseState) -> str:
        citation = CitationRecord(
            citation_id=self.ids.new("cit"),
            agent_run_id=run.agent_run_id,
            event_id=ref.event_id,
            evidence_id=ref.evidence_ref,
            artifact_id=ref.artifact_id,
            evidence_ref=ref.evidence_ref,
            text_range=ref.text_range,
            bbox=ref.bbox,
            coordinate_space=ref.coordinate_space,
            state=state,
            created_at=self.clock.now(),
            metadata={"redaction_state": ref.redaction_state.value},
        )
        return self.repository.save_citation(citation).citation_id

    def _attach_active_capture(
        self,
        *,
        run: AgentRun,
        view: ActiveCaptureInspectView,
    ) -> ActiveCaptureInspectView:
        citations = tuple(self._attached_active_ref(run=run, ref=ref) for ref in view.citations)
        timeline = view.timeline
        if timeline is not None:
            timeline = timeline.model_copy(
                update={
                    "steps": tuple(self._attach_timeline_step(run=run, step=step) for step in timeline.steps),
                }
            )
        safe_text_blocks = tuple(self._attach_text_block(run=run, block=block) for block in view.safe_text_blocks)
        return view.model_copy(
            update={"citations": citations, "timeline": timeline, "safe_text_blocks": safe_text_blocks}
        )

    def _attach_timeline_step(self, *, run: AgentRun, step: RecordingTimelineStepView) -> RecordingTimelineStepView:
        return step.model_copy(
            update={"citations": tuple(self._attached_active_ref(run=run, ref=ref) for ref in step.citations)}
        )

    def _attach_text_block(self, *, run: AgentRun, block: RecordingSafeTextBlock) -> RecordingSafeTextBlock:
        return block.model_copy(
            update={"citations": tuple(self._attached_active_ref(run=run, ref=ref) for ref in block.citations)}
        )

    def _attached_active_ref(self, *, run: AgentRun, ref: ActiveCaptureCitationRef) -> ActiveCaptureCitationRef:
        if ref.citation_id is not None:
            return ref
        target = ref.target
        citation = CitationRecord(
            citation_id=self.ids.new("cit"),
            agent_run_id=run.agent_run_id,
            event_id=target.event_id,
            evidence_id=target.evidence_id,
            artifact_id=target.artifact_id,
            evidence_ref=target.evidence_id or target.keyframe_id or target.action_id or target.session_id,
            text_range=target.text_range,
            bbox=target.bbox,
            coordinate_space=target.coordinate_space,
            active_capture_target=target,
            state=CitationUseState.DELIVERED,
            created_at=self.clock.now(),
            metadata=self._scalar_metadata(
                {
                    **ref.metadata,
                    "active_capture_kind": target.kind.value,
                    "active_capture_session_id": target.session_id,
                    "active_capture_keyframe_id": target.keyframe_id,
                    "active_capture_action_id": target.action_id,
                    "active_capture_timeline_step_id": target.timeline_step_id,
                    "active_capture_media_time_ms": target.media_time_ms,
                    "field_path": target.field_path,
                }
            ),
        )
        return ref.model_copy(update={"citation_id": self.repository.save_citation(citation).citation_id})

    def _slice_text(self, text: str, citation: CitationRecord) -> str:
        if citation.text_range is None:
            return text[:4000]
        return text[citation.text_range.start : citation.text_range.end]

    def _scalar_metadata(self, metadata: dict[str, object]) -> dict[str, str | int | float | bool | None]:
        return {
            key: value for key, value in metadata.items() if isinstance(value, (str, int, float, bool)) or value is None
        }
