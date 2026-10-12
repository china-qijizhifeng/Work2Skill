"""Evidence contracts for bundle citations and artifact-level references."""

from __future__ import annotations

from pydantic import Field

from .base import ContractModel
from .common import BoundingBox, TextRange
from .enums import ArtifactType, CoordinateSpace, RedactionState


class EvidenceElement(ContractModel):
    """Atomic evidence unit extracted from an artifact.

    Attributes:
        element_id: Stable element id inside an evidence layer.
        label: Human-readable label for UI and debug output.
        text: Optional text snippet carried by this element.
        bbox: Optional spatial location.
    """

    element_id: str
    label: str
    text: str | None = None
    bbox: BoundingBox | None = None


class EvidenceLayer(ContractModel):
    """Typed layer that groups elements from the same artifact.

    Attributes:
        layer_id: Stable layer id.
        event_id: Owning event id.
        artifact_id: Source artifact id.
        artifact_type: Artifact type that produced the layer.
        elements: Evidence elements in stable order.
    """

    layer_id: str
    event_id: str
    artifact_id: str
    artifact_type: ArtifactType
    elements: tuple[EvidenceElement, ...] = Field(default_factory=tuple)


class EvidenceRef(ContractModel):
    """Citation pointer included in context bundles and agent answers.

    Attributes:
        event_id: Owning event id.
        artifact_id: Source artifact id.
        evidence_ref: Stable selector within the artifact.
        text_range: Optional character range in canonical text.
        bbox: Optional spatial reference.
        coordinate_space: Coordinate system for bbox values.
        redaction_state: Redaction state visible to the caller.
        provenance_path: Ordered provenance labels for debugging.
    """

    event_id: str
    artifact_id: str
    evidence_ref: str
    text_range: TextRange | None = None
    bbox: BoundingBox | None = None
    coordinate_space: CoordinateSpace = CoordinateSpace.SCREEN_PX
    redaction_state: RedactionState = RedactionState.NONE
    provenance_path: tuple[str, ...] = Field(default_factory=tuple)
