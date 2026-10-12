"""Small pure helpers used by active capture application services."""

from __future__ import annotations

from packages.contracts import (
    ActiveCaptureStatus,
    Artifact,
    EvidenceKind,
    EvidenceRecord,
    KeyframeEvidenceRole,
)


def is_terminal_status(status: ActiveCaptureStatus) -> bool:
    """Return whether a status no longer accepts new keyframes.

    Args:
        status: Active-capture lifecycle state to classify.

    Returns:
        True when the session is in a terminal state.
    """

    return status in {
        ActiveCaptureStatus.COMPLETED,
        ActiveCaptureStatus.COMPLETED_WITH_WARNINGS,
        ActiveCaptureStatus.FAILED,
        ActiveCaptureStatus.CANCELLED,
    }


def first_evidence_of_kind(records: tuple[EvidenceRecord, ...], kind: EvidenceKind) -> EvidenceRecord | None:
    """Return the first evidence record with the requested typed kind.

    Args:
        records: Evidence rows attached to a capture event.
        kind: Typed evidence family to search for.

    Returns:
        The first matching evidence record, or None when absent.
    """

    return next((record for record in records if record.kind == kind), None)


def artifact_for_evidence(
    artifacts: tuple[Artifact, ...],
    evidence: EvidenceRecord | None,
) -> Artifact | None:
    """Resolve the artifact attached to an evidence record.

    Args:
        artifacts: Artifacts loaded with the capture envelope.
        evidence: Evidence row whose artifact link should be resolved.

    Returns:
        The matching artifact, or None when no artifact is linked.
    """

    if evidence is None or evidence.artifact_id is None:
        return None
    return next((artifact for artifact in artifacts if artifact.artifact_id == evidence.artifact_id), None)


def evidence_link_role(record: EvidenceRecord) -> KeyframeEvidenceRole:
    """Map evidence kinds into the compact role used by keyframe timelines.

    Args:
        record: Evidence row to translate into a keyframe role.

    Returns:
        The typed keyframe evidence role.

    Raises:
        ValueError: Raised when a new evidence kind has no active-capture role.
    """

    mapping = {
        EvidenceKind.SCREENSHOT: KeyframeEvidenceRole.SCREENSHOT,
        EvidenceKind.SYSTEM_APPSHOT: KeyframeEvidenceRole.SYSTEM_APPSHOT,
        EvidenceKind.A11Y: KeyframeEvidenceRole.A11Y,
        EvidenceKind.VISUAL_OCR_TEXT: KeyframeEvidenceRole.OCR,
        EvidenceKind.SELECTION_TEXT: KeyframeEvidenceRole.SELECTION_TEXT,
        EvidenceKind.CANONICAL_TEXT: KeyframeEvidenceRole.CANONICAL_TEXT,
        EvidenceKind.CLEAN_PAGE_TEXT: KeyframeEvidenceRole.CLEAN_TEXT,
        EvidenceKind.WEB: KeyframeEvidenceRole.WEB,
        EvidenceKind.PAGE_METADATA: KeyframeEvidenceRole.WEB,
        EvidenceKind.SELECTION_MAP: KeyframeEvidenceRole.WEB,
        EvidenceKind.FULL_DOM: KeyframeEvidenceRole.WEB,
        EvidenceKind.PAGE_TEXT: KeyframeEvidenceRole.WEB,
        EvidenceKind.VISIBLE_TEXT: KeyframeEvidenceRole.WEB,
        EvidenceKind.SELECTED_TEXT: KeyframeEvidenceRole.WEB,
        EvidenceKind.SYSTEM: KeyframeEvidenceRole.SUMMARY,
        EvidenceKind.PROVIDER_DIAGNOSTICS: KeyframeEvidenceRole.SUMMARY,
        EvidenceKind.KEYFRAME_CONTEXT_TEXT: KeyframeEvidenceRole.SUMMARY,
    }
    try:
        return mapping[record.kind]
    except KeyError as exc:
        raise ValueError(f"unmapped active capture evidence kind: {record.kind.value}") from exc
