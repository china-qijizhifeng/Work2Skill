"""Evidence-backed click target candidate providers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Protocol, cast

from pydantic import ValidationError

from packages.active_capture.click_targets.domain.geometry import ClickGeometry
from packages.active_capture.click_targets.domain.label_policy import ClickTargetLabelPolicy
from packages.contracts import (
    A11yNode,
    A11ySnapshot,
    ActionPoint,
    BoundingBox,
    ClickTargetCandidate,
    ClickTargetConfidenceBand,
    ClickTargetEvidenceAnchor,
    ClickTargetSemanticKind,
    ClickTargetSourceKind,
    ContextKeyframe,
    CoordinateSpace,
    EvidenceKind,
    EvidenceRecord,
    HumanActionEvent,
    SelectionMap,
    VisualOCRElement,
    VisualOCRElementRole,
    VisualOCRResult,
)

logger = logging.getLogger(__name__)


class _VaultReader(Protocol):
    def read(self, storage_uri: str) -> bytes: ...


@dataclass(frozen=True)
class _CandidateDraft:
    source_kind: ClickTargetSourceKind
    semantic_kind: ClickTargetSemanticKind
    raw_label: str | None
    confidence: float
    evidence: EvidenceRecord | None
    bbox: BoundingBox | None
    locator_seed: str | None = None


class EvidencePayloadReader:
    """Load small JSON evidence payloads without exposing storage URIs."""

    def __init__(self, *, vault: _VaultReader | None = None, max_payload_bytes: int = 2_000_000) -> None:
        self.vault = vault
        self.max_payload_bytes = max_payload_bytes

    def text_for(self, evidence: EvidenceRecord) -> str | None:
        if evidence.payload.byte_size is not None and evidence.payload.byte_size > self.max_payload_bytes:
            return None
        if evidence.payload.inline_content:
            if len(evidence.payload.inline_content.encode("utf-8")) > self.max_payload_bytes:
                return None
            return evidence.payload.inline_content
        if evidence.payload.storage_uri is None or self.vault is None:
            return None
        try:
            payload = self.vault.read(evidence.payload.storage_uri)
            if len(payload) > self.max_payload_bytes:
                return None
            return payload.decode("utf-8")
        except Exception as exc:
            logger.debug(
                "click target evidence payload read failed evidence_id=%s kind=%s error=%s",
                evidence.evidence_id,
                evidence.kind.value,
                exc.__class__.__name__,
            )
            return None

    def json_for(self, evidence: EvidenceRecord) -> object | None:
        text = self.text_for(evidence)
        if text is None:
            return None
        try:
            return cast(object, json.loads(text))
        except json.JSONDecodeError:
            return None


class _BaseCandidateProvider:
    def __init__(
        self,
        *,
        label_policy: ClickTargetLabelPolicy,
        payload_reader: EvidencePayloadReader,
        confidence_bands: dict[str, float],
    ) -> None:
        self.label_policy = label_policy
        self.payload_reader = payload_reader
        self.confidence_bands = confidence_bands

    def _point(self, action: HumanActionEvent) -> ActionPoint | None:
        if action.coordinates is None:
            return None
        return action.coordinates.screen_abs or action.coordinates.scope_rel or action.coordinates.screenshot_rel

    def _candidate(
        self,
        *,
        draft: _CandidateDraft,
        action: HumanActionEvent,
        keyframe: ContextKeyframe,
        resolution_id: str,
        now_id_prefix: str,
        created_at: datetime,
        index: int,
    ) -> ClickTargetCandidate:
        safe_label = self.label_policy.safe_label(draft.raw_label, semantic_kind=draft.semantic_kind)
        confidence = max(0.0, min(1.0, draft.confidence))
        evidence_anchor = (
            ClickTargetEvidenceAnchor(
                keyframe_id=keyframe.keyframe_id,
                event_id=draft.evidence.event_id,
                evidence_id=draft.evidence.evidence_id,
                artifact_id=draft.evidence.artifact_id,
                provider_key=draft.evidence.provenance.provider_key,
                bbox=draft.bbox,
            )
            if draft.evidence is not None
            else ClickTargetEvidenceAnchor(keyframe_id=keyframe.keyframe_id, bbox=draft.bbox)
        )
        return ClickTargetCandidate(
            candidate_id=f"{now_id_prefix}:{draft.source_kind.value}:{index}",
            resolution_id=resolution_id,
            action_id=action.action_id,
            session_id=action.session_id,
            source_kind=draft.source_kind,
            semantic_kind=draft.semantic_kind,
            safe_label=safe_label,
            label_fingerprint=self.label_policy.label_fingerprint(safe_label),
            locator_fingerprint=self._fingerprint(draft.locator_seed),
            confidence=confidence,
            confidence_band=self._band(confidence),
            evidence_anchor=evidence_anchor,
            bbox=draft.bbox,
            created_at=created_at,
            policy_version="click_target_policy_v1",
        )

    def _band(self, confidence: float) -> ClickTargetConfidenceBand:
        high = self.confidence_bands.get("high", 0.78)
        review = self.confidence_bands.get("review", 0.55)
        if confidence >= high:
            return ClickTargetConfidenceBand.HIGH
        if confidence >= review:
            return ClickTargetConfidenceBand.MEDIUM
        if confidence > 0:
            return ClickTargetConfidenceBand.LOW
        return ClickTargetConfidenceBand.UNAVAILABLE

    def _fingerprint(self, value: str | None) -> str | None:
        if value is None:
            return None
        return sha256(value.encode("utf-8")).hexdigest()


class A11yTargetCandidateProvider(_BaseCandidateProvider):
    """Infer click targets from safe accessibility snapshot geometry."""

    source_kind = ClickTargetSourceKind.A11Y_SNAPSHOT
    max_nodes = 2_000

    def candidates_for(
        self,
        *,
        action: HumanActionEvent,
        keyframe: ContextKeyframe,
        evidence_records: tuple[EvidenceRecord, ...],
        resolution_id: str,
        now_id_prefix: str,
        created_at: datetime,
    ) -> tuple[ClickTargetCandidate, ...]:
        point = self._point(action)
        if point is None:
            return ()
        drafts: list[_CandidateDraft] = []
        for evidence in evidence_records:
            if evidence.kind != EvidenceKind.A11Y:
                continue
            snapshot = self._snapshot(evidence)
            if snapshot is None:
                continue
            for node in self._flatten_nodes(snapshot.root_nodes)[: self.max_nodes]:
                if node.frame is None or not ClickGeometry.contains(point, node.frame):
                    continue
                semantic = self._semantic(node.role, node.name)
                trust = self._role_trust(semantic)
                area_penalty = min(0.22, ClickGeometry.area(node.frame) / 500_000)
                confidence = min(0.96, max(node.confidence, 0.55) + trust - area_penalty)
                drafts.append(
                    _CandidateDraft(
                        source_kind=ClickTargetSourceKind.A11Y_SNAPSHOT,
                        semantic_kind=semantic,
                        raw_label=None,
                        confidence=confidence,
                        evidence=evidence,
                        bbox=node.frame,
                        locator_seed=node.element_id or node.role,
                    )
                )
        ranked = sorted(
            drafts,
            key=lambda item: (item.confidence, -(ClickGeometry.area(item.bbox) if item.bbox else 0)),
            reverse=True,
        )
        return tuple(
            self._candidate(
                draft=draft,
                action=action,
                keyframe=keyframe,
                resolution_id=resolution_id,
                now_id_prefix=now_id_prefix,
                created_at=created_at,
                index=index,
            )
            for index, draft in enumerate(ranked[:8])
        )

    def _snapshot(self, evidence: EvidenceRecord) -> A11ySnapshot | None:
        text = self.payload_reader.text_for(evidence)
        if text is None:
            return None
        try:
            return A11ySnapshot.model_validate_json(text)
        except ValidationError:
            return None

    def _flatten_nodes(self, nodes: tuple[A11yNode, ...]) -> tuple[A11yNode, ...]:
        flattened: list[A11yNode] = []
        stack = list(nodes)
        while stack:
            node = stack.pop(0)
            flattened.append(node)
            stack[0:0] = list(node.children)
        return tuple(flattened)

    def _semantic(self, role: str, label: str | None) -> ClickTargetSemanticKind:
        lowered = f"{role} {label or ''}".lower()
        if "search" in lowered or "搜索" in lowered:
            return ClickTargetSemanticKind.SEARCH_FIELD
        if "button" in lowered:
            return ClickTargetSemanticKind.BUTTON
        if "link" in lowered:
            return ClickTargetSemanticKind.LINK
        if "textfield" in lowered or "textarea" in lowered or "input" in lowered:
            return ClickTargetSemanticKind.INPUT
        if "menu" in lowered:
            return ClickTargetSemanticKind.MENU_ITEM
        if "tab" in lowered:
            return ClickTargetSemanticKind.TAB
        if "checkbox" in lowered or "check box" in lowered:
            return ClickTargetSemanticKind.CHECKBOX
        if "window" in lowered:
            return ClickTargetSemanticKind.WINDOW
        return ClickTargetSemanticKind.UNKNOWN

    def _role_trust(self, semantic: ClickTargetSemanticKind) -> float:
        if semantic in {
            ClickTargetSemanticKind.BUTTON,
            ClickTargetSemanticKind.LINK,
            ClickTargetSemanticKind.INPUT,
            ClickTargetSemanticKind.SEARCH_FIELD,
            ClickTargetSemanticKind.MENU_ITEM,
            ClickTargetSemanticKind.TAB,
            ClickTargetSemanticKind.CHECKBOX,
        }:
            return 0.22
        if semantic == ClickTargetSemanticKind.WINDOW:
            return 0.02
        return 0.08


class VisualOcrTargetCandidateProvider(_BaseCandidateProvider):
    """Infer targets from OCR GUI element boxes."""

    source_kind = ClickTargetSourceKind.OCR_BOX
    max_elements = 500

    def candidates_for(
        self,
        *,
        action: HumanActionEvent,
        keyframe: ContextKeyframe,
        evidence_records: tuple[EvidenceRecord, ...],
        resolution_id: str,
        now_id_prefix: str,
        created_at: datetime,
    ) -> tuple[ClickTargetCandidate, ...]:
        point = self._point(action)
        if point is None:
            return ()
        drafts: list[_CandidateDraft] = []
        for evidence in evidence_records:
            if evidence.kind != EvidenceKind.VISUAL_OCR_TEXT:
                continue
            result = self._result(evidence)
            if result is None:
                continue
            for element in result.ui_elements[: self.max_elements]:
                if element.bbox is None or not ClickGeometry.contains(point, element.bbox):
                    continue
                semantic = self._semantic(element)
                confidence = min(0.78, max(element.confidence, 0.35) + 0.12)
                drafts.append(
                    _CandidateDraft(
                        source_kind=ClickTargetSourceKind.OCR_BOX,
                        semantic_kind=semantic,
                        raw_label=None,
                        confidence=confidence,
                        evidence=evidence,
                        bbox=element.bbox,
                        locator_seed=f"{element.raw_role}:{element.bbox.model_dump_json()}",
                    )
                )
        return tuple(
            self._candidate(
                draft=draft,
                action=action,
                keyframe=keyframe,
                resolution_id=resolution_id,
                now_id_prefix=now_id_prefix,
                created_at=created_at,
                index=index,
            )
            for index, draft in enumerate(sorted(drafts, key=lambda item: item.confidence, reverse=True)[:8])
        )

    def _result(self, evidence: EvidenceRecord) -> VisualOCRResult | None:
        text = self.payload_reader.text_for(evidence)
        if text is None:
            return None
        try:
            return VisualOCRResult.model_validate_json(text)
        except ValidationError:
            return None

    def _semantic(self, element: VisualOCRElement) -> ClickTargetSemanticKind:
        if element.role == VisualOCRElementRole.BUTTON:
            return ClickTargetSemanticKind.BUTTON
        if element.role == VisualOCRElementRole.LINK:
            return ClickTargetSemanticKind.LINK
        if element.role == VisualOCRElementRole.INPUT:
            return ClickTargetSemanticKind.INPUT
        if element.role == VisualOCRElementRole.CHECKBOX:
            return ClickTargetSemanticKind.CHECKBOX
        if element.role == VisualOCRElementRole.TAB:
            return ClickTargetSemanticKind.TAB
        if "search" in element.label.lower() or "搜索" in element.label:
            return ClickTargetSemanticKind.SEARCH_FIELD
        return ClickTargetSemanticKind.UNKNOWN


class WebSelectionMapTargetCandidateProvider(_BaseCandidateProvider):
    """Infer coarse web targets from selection maps without exposing selectors."""

    source_kind = ClickTargetSourceKind.WEB_DOM

    def candidates_for(
        self,
        *,
        action: HumanActionEvent,
        keyframe: ContextKeyframe,
        evidence_records: tuple[EvidenceRecord, ...],
        resolution_id: str,
        now_id_prefix: str,
        created_at: datetime,
    ) -> tuple[ClickTargetCandidate, ...]:
        point = self._point(action)
        if point is None:
            return ()
        candidates: list[ClickTargetCandidate] = []
        for evidence in evidence_records:
            if evidence.kind != EvidenceKind.SELECTION_MAP:
                continue
            selection_map = self._selection_map(evidence)
            if selection_map is None or not ClickGeometry.contains(point, selection_map.screen_region):
                continue
            draft = _CandidateDraft(
                source_kind=ClickTargetSourceKind.WEB_DOM,
                semantic_kind=ClickTargetSemanticKind.UNKNOWN,
                raw_label=None,
                confidence=min(0.62, max(selection_map.confidence, 0.35) + 0.1),
                evidence=evidence,
                bbox=selection_map.screen_region,
                locator_seed=";".join(span.selector or "" for span in selection_map.spans),
            )
            candidates.append(
                self._candidate(
                    draft=draft,
                    action=action,
                    keyframe=keyframe,
                    resolution_id=resolution_id,
                    now_id_prefix=now_id_prefix,
                    created_at=created_at,
                    index=len(candidates),
                )
            )
        return tuple(candidates[:8])

    def _selection_map(self, evidence: EvidenceRecord) -> SelectionMap | None:
        text = self.payload_reader.text_for(evidence)
        if text is None:
            return None
        try:
            return SelectionMap.model_validate_json(text)
        except ValidationError:
            return None


class CoordinateFallbackProvider(_BaseCandidateProvider):
    """Always provide a reviewable coordinate fallback."""

    source_kind = ClickTargetSourceKind.COORDINATE_FALLBACK

    def candidates_for(
        self,
        *,
        action: HumanActionEvent,
        keyframe: ContextKeyframe,
        evidence_records: tuple[EvidenceRecord, ...],
        resolution_id: str,
        now_id_prefix: str,
        created_at: datetime,
    ) -> tuple[ClickTargetCandidate, ...]:
        del evidence_records
        point = self._point(action)
        bbox = None
        if point is not None:
            bbox = BoundingBox(
                x=max(int(point.x) - 8, 0),
                y=max(int(point.y) - 8, 0),
                width=16,
                height=16,
                coordinate_space=point.coordinate_space or CoordinateSpace.SCREEN_PX,
            )
        draft = _CandidateDraft(
            source_kind=ClickTargetSourceKind.COORDINATE_FALLBACK,
            semantic_kind=ClickTargetSemanticKind.UNKNOWN,
            raw_label=None,
            confidence=0.22 if point is not None else 0.0,
            evidence=None,
            bbox=bbox,
            locator_seed=f"{point.x}:{point.y}:{point.coordinate_space.value}" if point is not None else None,
        )
        return (
            self._candidate(
                draft=draft,
                action=action,
                keyframe=keyframe,
                resolution_id=resolution_id,
                now_id_prefix=now_id_prefix,
                created_at=created_at,
                index=0,
            ),
        )
