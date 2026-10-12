"""Agent-safe inspect service for active capture sessions."""

from __future__ import annotations

import logging

from packages.active_capture.repositories.protocol import ActiveCaptureRepository
from packages.contracts import (
    ActiveCaptureCitationKind,
    ActiveCaptureCitationRef,
    ActiveCaptureCitationTarget,
    ActiveCaptureInspectView,
    ActiveCaptureProjectionConfig,
    ActorRef,
    AgentVisibleField,
    ContextEvent,
    DisclosureClass,
    EventInspectSection,
    ProjectionTruncationSummary,
    RecordingAvailableField,
    RecordingHiddenMaterial,
    RecordingSafeTextBlock,
    RecordingTimelineInspectView,
    RecordingTimelineStepView,
    RecordingVideoInspectRef,
    SearchFieldKind,
    SkillReadinessState,
    SkillReadinessSummary,
    VideoArtifactState,
)
from packages.indexing.safety import IndexableTextSource, SafeIndexProjectionBatch, SafeIndexProjectionService
from packages.shared.time import Clock

from ..read_model import ActiveCaptureVisibilityProjector, RecordingSessionGraph, RecordingSessionGraphReader
from .ports import EventEvidenceInspectPort, EventLookupPort
from .text import RecordingSafeTextCollector
from .timeline import RecordingTimelineProjector

logger = logging.getLogger(__name__)


class RecordingInspectService:
    """Build active-capture inspect projections and safe index inputs."""

    _available_fields = (
        RecordingAvailableField.ACTIVE_CAPTURE_SUMMARY,
        RecordingAvailableField.RECORDING_TIMELINE,
        RecordingAvailableField.KEYFRAME_REFS,
        RecordingAvailableField.VIDEO_REF,
        RecordingAvailableField.HUMAN_DEMO_SUMMARY,
    )
    _hidden_materials = (
        RecordingHiddenMaterial.RAW_KEYFRAME_IMAGES,
        RecordingHiddenMaterial.RECORDING_VIDEO,
        RecordingHiddenMaterial.RAW_DOM,
        RecordingHiddenMaterial.RAW_A11Y_TREE,
        RecordingHiddenMaterial.OCR_BOXES,
        RecordingHiddenMaterial.ACTION_RAW_METADATA,
    )

    def __init__(
        self,
        *,
        repository: ActiveCaptureRepository,
        clock: Clock,
        event_lookup: EventLookupPort,
        event_inspector: EventEvidenceInspectPort,
        safe_index: SafeIndexProjectionService,
        projection_config: ActiveCaptureProjectionConfig | None = None,
    ) -> None:
        self.repository = repository
        self.clock = clock
        self.event_lookup = event_lookup
        self.visibility = ActiveCaptureVisibilityProjector()
        self.timeline_projector = RecordingTimelineProjector()
        self.text_collector = RecordingSafeTextCollector(event_inspector=event_inspector)
        self.safe_index = safe_index
        self.projection_config = projection_config or ActiveCaptureProjectionConfig()
        self.graph_reader = RecordingSessionGraphReader(repository=repository, projection_config=self.projection_config)

    def build_for_event(
        self,
        *,
        event_id: str,
        actor: ActorRef,
        purpose: str,
        requested_sections: tuple[EventInspectSection, ...],
    ) -> ActiveCaptureInspectView | None:
        """Build an active-capture inspect view for an event if one exists."""

        graph = self.graph_reader.load_for_event(event_id)
        if graph is None:
            return None
        primary_event = self._primary_event(graph, actor=actor)
        if primary_event is None:
            logger.info(
                "active capture inspect denied because primary event is hidden",
                extra={"session_id": graph.session.session_id, "event_id": event_id},
            )
            return None
        events_by_id = self._events_by_id(graph, actor=actor, primary_event=primary_event)
        graph = self.visibility.project(graph=graph, visible_event_ids=set(events_by_id))
        graph, truncation = self._truncate_graph(graph)
        requested = set(requested_sections)
        timeline = self.timeline_projector.build(graph) if EventInspectSection.RECORDING_TIMELINE in requested else None
        timeline, timeline_truncation = self._truncate_timeline(timeline)
        safe_text_blocks = self.text_collector.collect(
            graph=graph,
            events_by_id=events_by_id,
            actor=actor,
            purpose=purpose,
            requested_sections=requested_sections,
        )
        safe_text_blocks, text_truncation = self._truncate_safe_text_blocks(safe_text_blocks)
        truncation = self._merge_truncation(truncation, timeline_truncation, text_truncation)
        video_ref = self._video_ref(graph) if EventInspectSection.VIDEO_REF in requested else None
        inspect = ActiveCaptureInspectView(
            session_id=graph.session.session_id,
            mode=graph.session.mode,
            primary_event_id=graph.session.primary_event_id,
            status=graph.session.status,
            started_at=graph.session.started_at,
            ended_at=graph.session.ended_at,
            user_note=graph.session.user_note,
            available_fields=self._available_fields,
            hidden_materials=self._hidden_materials,
            warnings=tuple(warning.message for warning in graph.session.warnings),
            timeline=timeline,
            safe_text_blocks=safe_text_blocks,
            video_ref=video_ref,
            citations=self._session_citations(graph, timeline),
            skill_readiness=self._skill_readiness(timeline),
            projection=truncation,
            generated_at=self.clock.now(),
            metadata={"workspace_id": graph.session.workspace_id, "active_capture_mode": graph.session.mode.value},
        )
        logger.info(
            "active capture inspect built",
            extra={
                "session_id": inspect.session_id,
                "event_id": event_id,
                "timeline_step_count": len(timeline.steps) if timeline is not None else 0,
                "safe_text_block_count": len(safe_text_blocks),
            },
        )
        return inspect

    def index_projection_for_inspect(
        self,
        inspect: ActiveCaptureInspectView,
        *,
        actor: ActorRef,
    ) -> SafeIndexProjectionBatch | None:
        """Build a non-replacing safe index batch for an active-capture inspect view."""

        if inspect.primary_event_id is None:
            return None
        workspace_id = inspect.metadata.get("workspace_id")
        scoped_workspace_id = workspace_id if isinstance(workspace_id, str) else None
        event = self.event_lookup.get_event(inspect.primary_event_id, actor=actor, workspace_id=scoped_workspace_id)
        if event is None:
            return None
        sources: list[IndexableTextSource] = []
        summary_text = f"active capture {inspect.session_id} {inspect.status.value}".strip()
        sources.append(
            IndexableTextSource(
                event=event,
                field_kind=SearchFieldKind.ACTIVE_CAPTURE_SUMMARY,
                text=summary_text,
                captured_at=event.trigger.occurred_at,
                disclosure_class=DisclosureClass.SAFE_METADATA,
                workspace_id=event.user.tenant_key if event.user is not None else None,
                agent_visible_fields=(AgentVisibleField.ACTIVE_CAPTURE_SUMMARY,),
                metadata={
                    "active_capture_session_id": inspect.session_id,
                    "active_capture_mode": inspect.mode.value,
                    "active_capture_primary_event_id": inspect.primary_event_id,
                    "index_document_key": f"active_capture:{inspect.session_id}:summary",
                },
            )
        )
        if inspect.user_note is not None and inspect.user_note.strip():
            sources.append(
                IndexableTextSource(
                    event=event,
                    field_kind=SearchFieldKind.USER_NOTE,
                    text=inspect.user_note.strip(),
                    captured_at=event.trigger.occurred_at,
                    disclosure_class=DisclosureClass.SAFE_METADATA,
                    workspace_id=event.user.tenant_key if event.user is not None else None,
                    agent_visible_fields=(AgentVisibleField.USER_NOTE,),
                    metadata={
                        "active_capture_session_id": inspect.session_id,
                        "active_capture_mode": inspect.mode.value,
                        "active_capture_primary_event_id": inspect.primary_event_id,
                        "active_capture_user_note": inspect.user_note.strip(),
                        "index_document_key": f"active_capture:{inspect.session_id}:user_note",
                    },
                )
            )
        if inspect.timeline is not None:
            timeline_text = "\n".join(step.safe_caption for step in inspect.timeline.steps)
            if timeline_text.strip():
                sources.append(
                    IndexableTextSource(
                        event=event,
                        field_kind=SearchFieldKind.RECORDING_TIMELINE,
                        text=timeline_text,
                        captured_at=event.trigger.occurred_at,
                        disclosure_class=DisclosureClass.SAFE_METADATA,
                        workspace_id=event.user.tenant_key if event.user is not None else None,
                        agent_visible_fields=(AgentVisibleField.RECORDING_TIMELINE,),
                        metadata={
                            "active_capture_session_id": inspect.session_id,
                            "active_capture_mode": inspect.mode.value,
                            "active_capture_primary_event_id": inspect.primary_event_id,
                            "index_document_key": f"active_capture:{inspect.session_id}:timeline",
                        },
                    )
                )
            action_text = "\n".join(step.safe_caption for step in inspect.timeline.steps if step.action_id is not None)
            if action_text.strip():
                sources.append(
                    IndexableTextSource(
                        event=event,
                        field_kind=SearchFieldKind.HUMAN_DEMO_SUMMARY,
                        text=action_text,
                        captured_at=event.trigger.occurred_at,
                        disclosure_class=DisclosureClass.SAFE_METADATA,
                        workspace_id=event.user.tenant_key if event.user is not None else None,
                        agent_visible_fields=(AgentVisibleField.HUMAN_DEMO_SUMMARY,),
                        metadata={
                            "active_capture_session_id": inspect.session_id,
                            "active_capture_mode": inspect.mode.value,
                            "active_capture_primary_event_id": inspect.primary_event_id,
                            "index_document_key": f"active_capture:{inspect.session_id}:human_demo",
                        },
                    )
                )
        if inspect.safe_text_blocks:
            for block in inspect.safe_text_blocks:
                block_event = self.event_lookup.get_event(block.event_id, actor=actor, workspace_id=scoped_workspace_id)
                if block_event is None:
                    continue
                sources.append(
                    IndexableTextSource(
                        event=event,
                        field_kind=self._search_field_for_visible_field(block.source_field),
                        text=block.text,
                        captured_at=block_event.trigger.occurred_at,
                        evidence_id=block.evidence_id,
                        artifact_id=block.artifact_id,
                        artifact_type=block.artifact_type,
                        disclosure_class=block.disclosure_class,
                        redaction_state=block.redaction_state,
                        workspace_id=block_event.user.tenant_key if block_event.user is not None else None,
                        agent_visible_fields=(block.source_field,),
                        metadata={
                            "active_capture_session_id": inspect.session_id,
                            "active_capture_mode": inspect.mode.value,
                            "active_capture_primary_event_id": inspect.primary_event_id,
                            "active_capture_text_event_id": block.event_id,
                            "active_capture_keyframe_id": block.keyframe_id,
                            "index_document_key": f"active_capture:{inspect.session_id}:text:{block.block_id}",
                        },
                    )
                )
        if not sources:
            return None
        batch = self.safe_index.project(
            event_id=inspect.primary_event_id,
            sources=tuple(sources),
            replace_event=False,
        )
        return batch.model_copy(
            update={
                "replace_chunk_prefixes": (f"idxchk_{inspect.primary_event_id}_active_capture:{inspect.session_id}:",)
            }
        )

    def _primary_event(self, graph: RecordingSessionGraph, *, actor: ActorRef) -> ContextEvent | None:
        if graph.session.primary_event_id is None:
            if not graph.keyframes:
                return None
            return self.event_lookup.get_event(
                graph.keyframes[0].event_id,
                actor=actor,
                workspace_id=graph.session.workspace_id,
            )
        return self.event_lookup.get_event(
            graph.session.primary_event_id,
            actor=actor,
            workspace_id=graph.session.workspace_id,
        )

    def _events_by_id(
        self,
        graph: RecordingSessionGraph,
        *,
        actor: ActorRef,
        primary_event: ContextEvent,
    ) -> dict[str, ContextEvent]:
        event_ids = tuple(dict.fromkeys(keyframe.event_id for keyframe in graph.keyframes))
        events_by_id = {
            event.event_id: event
            for event in self.event_lookup.get_events(
                event_ids,
                actor=actor,
                workspace_id=graph.session.workspace_id,
            )
        }
        events_by_id[primary_event.event_id] = primary_event
        return events_by_id

    def _video_ref(self, graph: RecordingSessionGraph) -> RecordingVideoInspectRef:
        if graph.timeline is None:
            return RecordingVideoInspectRef(state=VideoArtifactState.NOT_RECORDED)
        video = graph.timeline.video
        return RecordingVideoInspectRef(
            artifact_id=video.artifact_id,
            state=video.state,
            content_type=video.content_type.value if video.content_type is not None else None,
            duration_ms=video.duration_ms,
            byte_size=video.byte_size,
            alignment_error_ms=graph.timeline.alignment_error_ms,
        )

    def _session_citations(
        self,
        graph: RecordingSessionGraph,
        timeline: RecordingTimelineInspectView | None,
    ) -> tuple[ActiveCaptureCitationRef, ...]:
        event_id = graph.session.primary_event_id or (graph.keyframes[0].event_id if graph.keyframes else "")
        citations = [
            ActiveCaptureCitationRef(
                target=ActiveCaptureCitationTarget(
                    kind=ActiveCaptureCitationKind.SESSION,
                    session_id=graph.session.session_id,
                    event_id=event_id,
                    field_path="active_capture.summary",
                )
            )
        ]
        if timeline is not None and graph.timeline is not None and graph.timeline.video.artifact_id is not None:
            citations.append(
                ActiveCaptureCitationRef(
                    target=ActiveCaptureCitationTarget(
                        kind=ActiveCaptureCitationKind.VIDEO_TIME,
                        session_id=graph.session.session_id,
                        event_id=event_id,
                        artifact_id=graph.timeline.video.artifact_id,
                        media_time_ms=0,
                        field_path="active_capture.video_ref",
                    )
                )
            )
        return tuple(citations)

    def _truncate_graph(
        self, graph: RecordingSessionGraph
    ) -> tuple[RecordingSessionGraph, ProjectionTruncationSummary]:
        config = self.projection_config
        truncated_counts: dict[str, int] = {}
        if graph.total_keyframe_count > len(graph.keyframes):
            truncated_counts["keyframes"] = graph.total_keyframe_count - len(graph.keyframes)
        if graph.total_control_count > len(graph.controls):
            truncated_counts["controls"] = graph.total_control_count - len(graph.controls)
        actions = graph.actions[: config.max_actions]
        if len(actions) < graph.total_action_count:
            truncated_counts["actions"] = graph.total_action_count - len(actions)
        visible_action_ids = {action.action_id for action in actions}
        producer_decisions = tuple(
            decision
            for decision in graph.producer_decisions[: config.max_producer_diagnostics]
            if decision.action_id is None or decision.action_id in visible_action_ids
        )
        if len(producer_decisions) < graph.total_producer_event_count:
            truncated_counts["producer_decisions"] = graph.total_producer_event_count - len(producer_decisions)
        producer_event_ids = {decision.producer_event_id for decision in producer_decisions}
        bounded = RecordingSessionGraph(
            session=graph.session,
            keyframes=graph.keyframes,
            actions=actions,
            controls=graph.controls,
            timeline=graph.timeline,
            keyframe_links=graph.keyframe_links,
            action_links=tuple(link for link in graph.action_links if link.action_id in visible_action_ids),
            action_observations=tuple(
                observation for observation in graph.action_observations if observation.action_id in visible_action_ids
            ),
            target_resolutions=tuple(
                target for target in graph.target_resolutions if target.action_id in visible_action_ids
            ),
            producer_events=tuple(
                event for event in graph.producer_events if event.producer_event_id in producer_event_ids
            ),
            producer_decisions=producer_decisions,
            segments=graph.segments,
            total_keyframe_count=graph.total_keyframe_count,
            total_action_count=graph.total_action_count,
            total_control_count=graph.total_control_count,
            total_producer_event_count=graph.total_producer_event_count,
        )
        return bounded, ProjectionTruncationSummary(truncated=bool(truncated_counts), truncated_counts=truncated_counts)

    def _truncate_safe_text_blocks(
        self,
        blocks: tuple[RecordingSafeTextBlock, ...],
    ) -> tuple[tuple[RecordingSafeTextBlock, ...], ProjectionTruncationSummary]:
        config = self.projection_config
        truncated_counts: dict[str, int] = {}
        remaining_chars = config.max_safe_text_chars
        kept: list[RecordingSafeTextBlock] = []
        for block in blocks[: config.max_safe_text_blocks]:
            text = getattr(block, "text", "")
            if isinstance(text, str) and len(text) > remaining_chars:
                kept.append(block.model_copy(update={"text": text[:remaining_chars], "text_truncated": True}))
                truncated_counts["safe_text_chars"] = len(text) - remaining_chars
                remaining_chars = 0
                break
            kept.append(block)
            if isinstance(text, str):
                remaining_chars -= len(text)
            if remaining_chars <= 0:
                break
        if len(kept) < len(blocks):
            truncated_counts["safe_text_blocks"] = len(blocks) - len(kept)
        return tuple(kept), ProjectionTruncationSummary(
            truncated=bool(truncated_counts), truncated_counts=truncated_counts
        )

    def _truncate_timeline(
        self, timeline: RecordingTimelineInspectView | None
    ) -> tuple[RecordingTimelineInspectView | None, ProjectionTruncationSummary]:
        if timeline is None or len(timeline.steps) <= self.projection_config.max_timeline_steps:
            return timeline, ProjectionTruncationSummary()
        limit = self.projection_config.max_timeline_steps
        cursor = self._cursor_for_step(timeline.steps[limit - 1])
        truncated = timeline.model_copy(update={"steps": timeline.steps[:limit]})
        return truncated, ProjectionTruncationSummary(
            truncated=True,
            truncated_counts={"timeline_steps": len(timeline.steps) - limit},
            next_cursor=cursor,
        )

    def _merge_truncation(self, *summaries: ProjectionTruncationSummary) -> ProjectionTruncationSummary:
        counts: dict[str, int] = {}
        cursor = None
        for summary in summaries:
            cursor = cursor or summary.next_cursor
            for key, value in summary.truncated_counts.items():
                counts[key] = counts.get(key, 0) + value
        return ProjectionTruncationSummary(truncated=bool(counts), truncated_counts=counts, next_cursor=cursor)

    def _cursor_for_step(self, step: RecordingTimelineStepView) -> str:
        media_time = step.media_time_ms
        sequence = step.sequence_index
        return f"{media_time if isinstance(media_time, int) else -1}:{sequence if isinstance(sequence, int) else -1}"

    def _skill_readiness(self, timeline: RecordingTimelineInspectView | None) -> SkillReadinessSummary:
        if timeline is None:
            return SkillReadinessSummary(state=SkillReadinessState.NEEDS_REVIEW, reasons=("timeline not requested",))
        review_count = sum(1 for step in timeline.steps if step.needs_review)
        return SkillReadinessSummary(
            state=SkillReadinessState.NEEDS_REVIEW if review_count else SkillReadinessState.READY,
            review_item_count=review_count,
            reasons=("some timeline steps need review",) if review_count else (),
        )

    def _search_field_for_visible_field(self, field: AgentVisibleField) -> SearchFieldKind:
        mapping = {
            AgentVisibleField.SELECTION_TEXT: SearchFieldKind.SELECTION_TEXT,
            AgentVisibleField.VISUAL_OCR_TEXT: SearchFieldKind.VISUAL_OCR_TEXT,
            AgentVisibleField.CANONICAL_TEXT: SearchFieldKind.CANONICAL_TEXT,
            AgentVisibleField.CLEAN_PAGE_TEXT: SearchFieldKind.CLEAN_PAGE_TEXT,
        }
        return mapping.get(field, SearchFieldKind.KEYFRAME_CONTEXT_TEXT)
