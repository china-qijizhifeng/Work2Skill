"""Browser-origin selection text validation helpers.

The capture pipeline receives browser DOM evidence and independent macOS a11y
evidence. This module owns the cross-checks needed before browser-selected text
is promoted into default selection text.
"""

from __future__ import annotations

import json
import logging

from packages.artifacts.vault import ArtifactVaultError, LocalArtifactVault
from packages.contracts import (
    A11ySnapshot,
    ArtifactType,
    BoundingBox,
    CaptureAttemptRequest,
    ContextEvent,
    EvidenceRecord,
    SourceType,
)
from packages.contracts.enums import ArtifactRole, ProviderKind
from packages.evidence.selection_text import SelectionTextProjectionService

logger = logging.getLogger(__name__)
TRUSTED_A11Y_PROVIDER_KEY = "system.macos_a11y"


class BrowserSelectionEvidenceValidator:
    """Validate browser selection text against source and system evidence."""

    def __init__(self, *, vault: LocalArtifactVault, projector: SelectionTextProjectionService) -> None:
        self.vault = vault
        self.projector = projector

    def selected_text(self, *, inputs: tuple[EvidenceRecord, ...], source_binding_id: str) -> EvidenceRecord | None:
        """Return the browser-selected-text evidence for a source command.

        Args:
            inputs: Evidence records captured during the run.
            source_binding_id: Source binding that must own the evidence.

        Returns:
            Browser selected-text evidence, or ``None`` when unavailable.
        """

        for evidence in inputs:
            if (
                evidence.artifact_type == ArtifactType.BROWSER_SELECTED_TEXT
                and evidence.role == ArtifactRole.SOURCE_TEXT
                and evidence.provenance.provider_kind == ProviderKind.SOURCE
                and evidence.provenance.source_binding_id == source_binding_id
                and evidence.payload.storage_uri is not None
                and evidence.metadata.get("selection_source") == "browser_dom_region"
            ):
                return evidence
        return None

    def selection_map(
        self,
        *,
        inputs: tuple[EvidenceRecord, ...],
        selected: EvidenceRecord,
        selected_text: str,
        attempt: CaptureAttemptRequest,
        source_binding_id: str,
    ) -> tuple[EvidenceRecord | None, float]:
        """Return a selection map only when it matches text and OS bbox.

        Args:
            inputs: Evidence records captured during the run.
            selected: Browser-selected-text evidence being validated.
            selected_text: Text payload read from ``selected``.
            attempt: Capture attempt containing the OS selection rectangle.
            source_binding_id: Source binding that must own the map.

        Returns:
            Matching selection-map evidence plus confidence, or ``None`` and
            the best failed confidence.
        """

        best_confidence = 0.0
        for evidence in inputs:
            if (
                evidence.artifact_type == ArtifactType.SELECTION_MAP
                and evidence.role == ArtifactRole.SELECTION_MAP
                and evidence.provenance.provider_kind == ProviderKind.SOURCE
                and evidence.provenance.source_binding_id == source_binding_id
                and evidence.payload.storage_uri is not None
                and evidence.provenance.command_id == selected.provenance.command_id
            ):
                confidence = self._selection_map_confidence(
                    evidence,
                    selected_text=selected_text,
                    attempt=attempt,
                )
                best_confidence = max(best_confidence, confidence)
                if confidence >= 0.62:
                    return evidence, confidence
        return None, best_confidence

    def page_support_count(
        self,
        *,
        inputs: tuple[EvidenceRecord, ...],
        selected: EvidenceRecord,
        selected_text: str,
        source_binding_id: str,
    ) -> int:
        """Count distinct page evidence families that contain selected text.

        Args:
            inputs: Evidence records captured during the run.
            selected: Browser-selected-text evidence being validated.
            selected_text: Text payload read from ``selected``.
            source_binding_id: Source binding that must own supporting page text.

        Returns:
            Number of distinct artifact families that support the selection.
        """

        if not _normalize_for_comparison(selected_text):
            return 0
        supported_types: set[ArtifactType] = set()
        for evidence in inputs:
            if evidence.evidence_id == selected.evidence_id:
                continue
            if evidence.provenance.provider_kind != ProviderKind.SOURCE:
                continue
            if evidence.provenance.source_binding_id != source_binding_id:
                continue
            if evidence.provenance.command_id != selected.provenance.command_id:
                continue
            if _text_supports_selection(evidence_text=self._page_support_text(evidence), selected_text=selected_text):
                supported_types.add(evidence.artifact_type)
        return len(supported_types)

    def supported_by_system_evidence(
        self,
        *,
        inputs: tuple[EvidenceRecord, ...],
        selected_text: str,
        attempt: CaptureAttemptRequest,
        event: ContextEvent,
    ) -> bool:
        """Return whether independent trusted a11y evidence supports selected text.

        Args:
            inputs: Evidence records captured during the run.
            selected_text: Browser-selected text to verify.
            attempt: Capture attempt containing the OS selection rectangle.
            event: Event receiving the derived selection text.

        Returns:
            ``True`` when trusted system evidence independently contains the
            selected text for the same region.
        """

        selected_normalized = _normalize_for_comparison(selected_text)
        if not selected_normalized:
            return False
        for a11y_tree in (evidence for evidence in inputs if self.is_trusted_a11y_tree(evidence)):
            assert a11y_tree.payload.storage_uri is not None
            try:
                snapshot = A11ySnapshot.model_validate_json(self.vault.read(a11y_tree.payload.storage_uri))
            except Exception:
                logger.exception(
                    "failed to parse trusted a11y snapshot for browser selection support event_id=%s evidence_id=%s",
                    event.event_id,
                    a11y_tree.evidence_id,
                    extra={"event_id": event.event_id, "evidence_id": a11y_tree.evidence_id},
                )
                continue
            if not _selection_matches(snapshot.selection, attempt.selection_geometry.selected_region):
                continue
            projection = self.projector.project(snapshot)
            if not projection.text.strip():
                continue
            if self.is_web_source(event) and self.looks_like_browser_ui_noise(projection.text):
                continue
            if selected_normalized in _normalize_for_comparison(projection.text):
                return True
        return False

    def read_text(self, evidence: EvidenceRecord) -> str:
        """Read UTF-8 text payload for a persisted evidence record.

        Args:
            evidence: Evidence record with vault-backed text payload.

        Returns:
            Decoded and stripped text, or an empty string when unreadable.
        """

        if evidence.payload.storage_uri is None:
            return ""
        try:
            return self.vault.read(evidence.payload.storage_uri).decode("utf-8").strip()
        except (ArtifactVaultError, UnicodeDecodeError):
            return ""

    def float_metadata(self, evidence: EvidenceRecord, key: str, *, default: float) -> float:
        """Read a clamped float metadata value.

        Args:
            evidence: Evidence record containing scalar metadata.
            key: Metadata key to read.
            default: Value returned when metadata is absent or non-numeric.

        Returns:
            Float clamped to the ``[0, 1]`` confidence interval.
        """

        value = evidence.metadata.get(key)
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
        return default

    def is_web_source(self, event: ContextEvent) -> bool:
        """Return whether an event source is browser-like web content.

        Args:
            event: Event whose source reference should be inspected.

        Returns:
            ``True`` when source type, URL, or origin indicates web content.
        """

        source_ref = event.source_binding.source_ref
        return source_ref.source_type == SourceType.WEB or bool(source_ref.url or source_ref.origin)

    def looks_like_browser_ui_noise(self, text: str) -> bool:
        """Return whether text looks like Chrome UI rather than page content.

        Args:
            text: Candidate text from a system accessibility projection.

        Returns:
            ``True`` when common browser chrome markers dominate the text.
        """

        normalized = " ".join(text.lower().split())
        if not normalized:
            return False
        markers = (
            "扩展程序",
            "地址和搜索栏",
            "新标签页",
            "键盘快捷键",
            "chrome 应用商店",
            "workrecorder web provider",
            "chrome web store",
            "omnibox",
            "extensions",
            "new tab",
        )
        hit_count = sum(1 for marker in markers if marker in normalized)
        if hit_count >= 2:
            return True
        chrome_ui_ratio = hit_count / max(len(normalized.split()), 1)
        return hit_count >= 1 and chrome_ui_ratio > 0.12

    def is_trusted_a11y_tree(self, evidence: EvidenceRecord) -> bool:
        """Return whether evidence is a trusted macOS a11y snapshot.

        Args:
            evidence: Evidence record to classify.

        Returns:
            ``True`` when the record is a daemon-owned macOS a11y snapshot.
        """

        return (
            evidence.artifact_type == ArtifactType.A11Y_TREE
            and evidence.role == ArtifactRole.UI_STRUCTURE
            and evidence.provenance.provider_key == TRUSTED_A11Y_PROVIDER_KEY
            and evidence.provenance.provider_kind == ProviderKind.SYSTEM_EVIDENCE
            and evidence.payload.payload_schema == "a11y_snapshot"
            and evidence.payload.storage_uri is not None
        )

    def _selection_map_confidence(
        self, evidence: EvidenceRecord, *, selected_text: str, attempt: CaptureAttemptRequest
    ) -> float:
        if evidence.payload.storage_uri is None:
            return 0.42
        try:
            payload = json.loads(self.vault.read(evidence.payload.storage_uri).decode("utf-8"))
        except (ArtifactVaultError, json.JSONDecodeError, UnicodeDecodeError):
            return 0.42
        if not isinstance(payload, dict):
            return 0.42
        viewport_region = payload.get("viewport_region")
        spans = payload.get("spans")
        if not isinstance(viewport_region, dict) or not isinstance(spans, list) or not spans:
            return 0.42
        if not _selection_map_text_matches(spans=spans, selected_text=selected_text):
            return 0.42
        if not _selection_map_region_matches(payload=payload, attempt=attempt):
            return 0.42
        value = payload.get("confidence")
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
        return 0.42

    def _page_support_text(self, evidence: EvidenceRecord) -> str:
        if evidence.payload.storage_uri is None:
            return ""
        if evidence.artifact_type in {
            ArtifactType.BROWSER_VISIBLE_TEXT,
            ArtifactType.BROWSER_READABILITY_MARKDOWN,
            ArtifactType.BROWSER_FULL_DOM,
            ArtifactType.BROWSER_DOM_SNAPSHOT,
        }:
            raw = self.read_text(evidence)
            if not raw:
                return ""
            if evidence.payload.content_type.startswith("application/json"):
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    return raw
                if not isinstance(payload, dict):
                    return raw
                parts: list[str] = []
                for key in ("plain_text", "markdown", "text_content", "visible_text"):
                    value = payload.get(key)
                    if isinstance(value, str):
                        parts.append(value)
                return "\n".join(parts) if parts else raw
            return raw
        return ""


def _selection_map_text_matches(*, spans: list[object], selected_text: str) -> bool:
    span_text = "\n".join(str(span.get("text") or "") for span in spans if isinstance(span, dict) and span.get("text"))
    selected = _normalize_for_comparison(selected_text)
    mapped = _normalize_for_comparison(span_text)
    return bool(selected and mapped and selected == mapped)


def _selection_map_region_matches(*, payload: dict[str, object], attempt: CaptureAttemptRequest) -> bool:
    screen_region = payload.get("screen_region")
    if not isinstance(screen_region, dict):
        return False
    space = str(screen_region.get("coordinate_space") or "")
    pixel_region = attempt.selection_geometry.pixel_region
    if pixel_region is not None and space == pixel_region.coordinate_space.value:
        reference = pixel_region
    elif space == attempt.selection_geometry.selected_region.coordinate_space.value:
        reference = attempt.selection_geometry.selected_region
    else:
        return False
    candidate = _rect_from_mapping(screen_region)
    if candidate is None:
        return False
    return _rect_iou(candidate, (reference.x, reference.y, reference.width, reference.height)) >= 0.72


def _text_supports_selection(*, evidence_text: str, selected_text: str) -> bool:
    evidence_normalized = _normalize_for_comparison(evidence_text)
    selected_normalized = _normalize_for_comparison(selected_text)
    if not evidence_normalized or not selected_normalized:
        return False
    if selected_normalized in evidence_normalized or evidence_normalized in selected_normalized:
        return True
    fragments = _support_fragments(selected_text)
    if not fragments:
        return False
    matches = sum(1 for fragment in fragments if fragment in evidence_normalized)
    if len(fragments) == 1:
        return matches == 1
    return matches >= min(2, len(fragments))


def _support_fragments(selected_text: str) -> tuple[str, ...]:
    fragments: list[str] = []
    for line in selected_text.replace("\r", "\n").split("\n"):
        normalized = _normalize_for_comparison(line)
        if len(normalized) >= 24:
            fragments.append(normalized)
    if fragments:
        return tuple(fragments[:8])
    normalized = _normalize_for_comparison(selected_text)
    if len(normalized) >= 24:
        return (normalized[:160],)
    return ()


def _rect_from_mapping(value: dict[str, object]) -> tuple[float, float, float, float] | None:
    x = _number_from_mapping(value, "x")
    y = _number_from_mapping(value, "y")
    width = _number_from_mapping(value, "width")
    height = _number_from_mapping(value, "height")
    if x is None or y is None or width is None or height is None:
        return None
    if width <= 0 or height <= 0:
        return None
    return (x, y, width, height)


def _number_from_mapping(value: dict[str, object], key: str) -> float | None:
    raw = value.get(key)
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float, str)):
        try:
            return float(raw)
        except ValueError:
            return None
    return None


def _rect_iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    intersection_width = max(0.0, min(lx + lw, rx + rw) - max(lx, rx))
    intersection_height = max(0.0, min(ly + lh, ry + rh) - max(ly, ry))
    intersection = intersection_width * intersection_height
    if intersection <= 0:
        return 0.0
    union = (lw * lh) + (rw * rh) - intersection
    return intersection / union if union > 0 else 0.0


def _normalize_for_comparison(value: str) -> str:
    return " ".join(value.split()).strip()


def _selection_matches(left: BoundingBox, right: BoundingBox) -> bool:
    return all(
        getattr(left, field) == getattr(right, field) for field in ("x", "y", "width", "height", "coordinate_space")
    )
