"""Safe active-capture citation resolution."""

from __future__ import annotations

import logging

from packages.active_capture.application.read_model import (
    ActiveCaptureVisibilityProjector,
    RecordingSessionGraph,
    RecordingSessionGraphReader,
)
from packages.active_capture.repositories.protocol import ActiveCaptureProjectionReadRepository
from packages.artifacts.service import ArtifactAccessService
from packages.contracts import (
    AccessScope,
    ActiveCaptureSession,
    ActorRef,
    AgentRun,
    CitationRecord,
    CitationResolveResponse,
    EventStatus,
    WorkspaceSelection,
)
from packages.contracts.api import ApiError
from packages.storage.event_repository import ContextEventRepository

logger = logging.getLogger(__name__)


class ActiveCaptureCitationResolver:
    """Resolve active-capture citations only after visible graph validation."""

    def __init__(
        self,
        *,
        repository: ActiveCaptureProjectionReadRepository,
        events: ContextEventRepository,
        artifact_access: ArtifactAccessService,
    ) -> None:
        self.graph_reader = RecordingSessionGraphReader(repository=repository)
        self.visibility = ActiveCaptureVisibilityProjector()
        self.events = events
        self.artifact_access = artifact_access

    def resolve(self, *, citation: CitationRecord, actor: ActorRef, run: AgentRun) -> CitationResolveResponse | None:
        """Return safe citation payload or None when the target is no longer visible."""

        target = citation.active_capture_target
        if target is None:
            return None
        graph = self.graph_reader.load_for_session(target.session_id)
        if graph is None:
            return None
        if not self._session_read_allowed(graph.session, actor=actor, run=run):
            return None
        visible_event_ids = {
            keyframe.event_id
            for keyframe in graph.keyframes
            if (event := self.events.get(keyframe.event_id)) is not None
            and event.status not in {EventStatus.DELETED, EventStatus.RESTRICTED}
        }
        if graph.session.primary_event_id is not None:
            event = self.events.get(graph.session.primary_event_id)
            if event is not None and event.status not in {EventStatus.DELETED, EventStatus.RESTRICTED}:
                visible_event_ids.add(event.event_id)
        visible = self.visibility.project(graph=graph, visible_event_ids=visible_event_ids)
        if not self._target_is_visible(citation=citation, graph=visible):
            logger.info(
                "active capture citation denied by visible graph",
                extra={"session_id": target.session_id, "citation_id": citation.citation_id},
            )
            return None
        text = self._safe_text(citation=citation, actor=actor)
        return CitationResolveResponse(citation=citation, text=text, text_truncated=False)

    def _session_read_allowed(self, session: ActiveCaptureSession, *, actor: ActorRef, run: AgentRun) -> bool:
        session_actor = session.actor
        if session_actor is not None and session_actor.actor_id != actor.actor_id:
            return False
        session_workspace_id = session.workspace_id
        if run.workspace_id is not None and session_workspace_id not in {None, WorkspaceSelection.AUTO_WORKSPACE_ID}:
            return session_workspace_id == run.workspace_id
        if run.workspace_id is None and session_workspace_id not in {None, WorkspaceSelection.AUTO_WORKSPACE_ID}:
            return False
        return True

    def _target_is_visible(self, *, citation: CitationRecord, graph: RecordingSessionGraph) -> bool:
        target = citation.active_capture_target
        if target is None:
            return False
        keyframe_ids = {keyframe.keyframe_id for keyframe in graph.keyframes}
        action_ids = {action.action_id for action in graph.actions}
        event_ids = {keyframe.event_id for keyframe in graph.keyframes}
        if graph.session.primary_event_id is not None:
            event_ids.add(graph.session.primary_event_id)
        evidence_ids: set[str] = set()
        artifact_ids: set[str] = set()
        for keyframe_link in graph.keyframe_links:
            if keyframe_link.evidence_id is not None:
                evidence_ids.add(keyframe_link.evidence_id)
            if keyframe_link.artifact_id is not None:
                artifact_ids.add(keyframe_link.artifact_id)
        for action_link in graph.action_links:
            if action_link.evidence_id is not None:
                evidence_ids.add(action_link.evidence_id)
            if action_link.artifact_id is not None:
                artifact_ids.add(action_link.artifact_id)
        artifact_ids.update(
            keyframe.screenshot_artifact_id
            for keyframe in graph.keyframes
            if keyframe.screenshot_artifact_id is not None
        )
        if graph.timeline is not None and graph.timeline.video.artifact_id is not None:
            artifact_ids.add(graph.timeline.video.artifact_id)
        timeline_step_ids = {f"kf:{keyframe.keyframe_id}" for keyframe in graph.keyframes}
        timeline_step_ids.update(f"act:{action.action_id}" for action in graph.actions)
        timeline_step_ids.update(f"ctl:{control.control_id}" for control in graph.controls)
        if target.keyframe_id is not None and target.keyframe_id not in keyframe_ids:
            return False
        if target.action_id is not None and target.action_id not in action_ids:
            return False
        if target.timeline_step_id is not None and target.timeline_step_id not in timeline_step_ids:
            return False
        if target.evidence_id is not None and target.evidence_id not in evidence_ids:
            return False
        if target.artifact_id is not None and target.artifact_id not in artifact_ids:
            return False
        if target.event_id is not None:
            if target.event_id not in event_ids:
                return False
            event = self.events.get(target.event_id)
            if event is None or event.status in {EventStatus.DELETED, EventStatus.RESTRICTED}:
                return False
        return True

    def _safe_text(self, *, citation: CitationRecord, actor: ActorRef) -> str:
        if citation.artifact_id is None:
            return ""
        artifact = self.artifact_access.get_metadata(citation.artifact_id)
        if artifact is None or AccessScope.READ_TEXT not in artifact.allowed_scopes:
            return ""
        content = self.artifact_access.read_text_content(artifact=artifact, actor=actor, scope=AccessScope.READ_TEXT)
        if isinstance(content, ApiError):
            return ""
        if citation.text_range is None:
            return content[:4000]
        return content[citation.text_range.start : citation.text_range.end]
