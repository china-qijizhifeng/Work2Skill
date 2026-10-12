"""Safe text collection for active-capture inspect."""

from __future__ import annotations

from packages.contracts import (
    ActiveCaptureCitationKind,
    ActiveCaptureCitationRef,
    ActiveCaptureCitationTarget,
    ActorRef,
    AgentVisibleField,
    ContextEvent,
    DisclosureClass,
    EventInspectSection,
    EventInspectView,
    RecordingSafeTextBlock,
    RedactionState,
    TextRange,
)

from .batch_loader import RecordingInspectGraph
from .ports import EventEvidenceInspectPort

TEXT_INSPECT_SECTIONS = (
    EventInspectSection.SELECTION_TEXT,
    EventInspectSection.VISUAL_OCR_TEXT,
    EventInspectSection.CANONICAL,
    EventInspectSection.CLEAN_PAGE_TEXT,
    EventInspectSection.EVIDENCE_REFS,
)


class RecordingSafeTextCollector:
    """Collect bounded redacted text blocks through the existing disclosure layer."""

    def __init__(self, *, event_inspector: EventEvidenceInspectPort) -> None:
        self.event_inspector = event_inspector

    def collect(
        self,
        *,
        graph: RecordingInspectGraph,
        events_by_id: dict[str, ContextEvent],
        actor: ActorRef,
        purpose: str,
        requested_sections: tuple[EventInspectSection, ...],
    ) -> tuple[RecordingSafeTextBlock, ...]:
        """Return safe text blocks for requested active-capture events."""

        text_sections = self._text_sections(requested_sections)
        if not text_sections:
            return ()
        blocks: list[RecordingSafeTextBlock] = []
        for event_id in dict.fromkeys(keyframe.event_id for keyframe in graph.keyframes):
            event = events_by_id.get(event_id)
            if event is None:
                continue
            inspect = self.event_inspector.inspect_event(
                event=event,
                actor=actor,
                purpose=purpose,
                requested_sections=text_sections,
            )
            blocks.extend(self._blocks_from_inspect(graph=graph, inspect=inspect))
        return tuple(blocks)

    def _text_sections(self, requested_sections: tuple[EventInspectSection, ...]) -> tuple[EventInspectSection, ...]:
        requested = set(requested_sections)
        sections = tuple(section for section in TEXT_INSPECT_SECTIONS if section in requested)
        return sections

    def _blocks_from_inspect(
        self,
        *,
        graph: RecordingInspectGraph,
        inspect: EventInspectView,
    ) -> tuple[RecordingSafeTextBlock, ...]:
        blocks: list[RecordingSafeTextBlock] = []
        for index, item in enumerate(inspect.readable_evidence):
            if not item.text.strip():
                continue
            keyframe_id = self._keyframe_id_for_evidence(graph, event_id=inspect.event_id, evidence_id=item.evidence_id)
            source_field = self._source_field(item.disclosure_class)
            citation = ActiveCaptureCitationRef(
                target=ActiveCaptureCitationTarget(
                    kind=ActiveCaptureCitationKind.TEXT_RANGE,
                    session_id=graph.session.session_id,
                    event_id=inspect.event_id,
                    keyframe_id=keyframe_id,
                    evidence_id=item.evidence_id,
                    artifact_id=item.artifact_id,
                    text_range=TextRange(start=0, end=len(item.text)),
                    field_path=f"active_capture.safe_text_blocks.{index}",
                )
            )
            blocks.append(
                RecordingSafeTextBlock(
                    block_id=f"actxt_{inspect.event_id}_{index}",
                    source_field=source_field,
                    event_id=inspect.event_id,
                    keyframe_id=keyframe_id,
                    evidence_id=item.evidence_id,
                    artifact_id=item.artifact_id,
                    artifact_type=item.artifact_type,
                    disclosure_class=item.disclosure_class,
                    text=item.text,
                    text_truncated=item.text_truncated,
                    confidence=item.confidence,
                    redaction_state=RedactionState.REDACTED,
                    citations=(citation,),
                )
            )
        return tuple(blocks)

    def _keyframe_id_for_evidence(
        self,
        graph: RecordingInspectGraph,
        *,
        event_id: str,
        evidence_id: str | None,
    ) -> str | None:
        if evidence_id is not None:
            for link in graph.keyframe_links:
                if link.event_id == event_id and link.evidence_id == evidence_id:
                    return link.keyframe_id
        matches = tuple(keyframe.keyframe_id for keyframe in graph.keyframes if keyframe.event_id == event_id)
        return matches[0] if len(matches) == 1 else None

    def _source_field(self, disclosure_class: DisclosureClass) -> AgentVisibleField:
        if disclosure_class == DisclosureClass.VISUAL_OCR_TEXT:
            return AgentVisibleField.VISUAL_OCR_TEXT
        if disclosure_class == DisclosureClass.CLEAN_PAGE_TEXT:
            return AgentVisibleField.CLEAN_PAGE_TEXT
        if disclosure_class == DisclosureClass.REDACTED_CANONICAL:
            return AgentVisibleField.CANONICAL_TEXT
        return AgentVisibleField.SELECTION_TEXT
