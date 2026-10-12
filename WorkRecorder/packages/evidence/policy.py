"""Daemon-owned evidence policy stamping."""

from __future__ import annotations

from packages.contracts import (
    AccessScope,
    ArtifactIngestState,
    ArtifactRole,
    ArtifactType,
    EvidenceDraft,
    EvidenceSensitivity,
    EvidenceTrustState,
    ProviderKind,
    RedactionState,
)


class EvidencePolicyDecision:
    """Effective policy for one evidence draft."""

    def __init__(
        self,
        *,
        ingest_state: ArtifactIngestState,
        redaction_state: RedactionState,
        trust_state: EvidenceTrustState,
        allowed_scopes: tuple[AccessScope, ...],
        indexable: bool,
    ) -> None:
        self.ingest_state = ingest_state
        self.redaction_state = redaction_state
        self.trust_state = trust_state
        self.allowed_scopes = allowed_scopes
        self.indexable = indexable


class EvidencePolicyService:
    """Apply daemon-owned ACL, DLP, and indexing rules to evidence drafts."""

    def decide(self, draft: EvidenceDraft) -> EvidencePolicyDecision:
        """Return effective policy for one evidence draft.

        Args:
            draft: Provider-produced evidence claim.

        Returns:
            Daemon-owned policy decision. Provider redaction claims are treated
            as hints; final artifact access is stamped here.
        """

        if draft.artifact_type in {
            ArtifactType.SCREENSHOT,
            ArtifactType.OS_REGION_SCREENSHOT,
            ArtifactType.OS_REGION_CROP,
        }:
            return EvidencePolicyDecision(
                ingest_state=ArtifactIngestState.QUARANTINED,
                redaction_state=RedactionState.QUARANTINED,
                trust_state=EvidenceTrustState.QUARANTINED,
                allowed_scopes=(AccessScope.READ_METADATA, AccessScope.READ_THUMBNAIL, AccessScope.READ_RAW_ARTIFACT),
                indexable=False,
            )
        if draft.artifact_type in {ArtifactType.BROWSER_FULL_DOM, ArtifactType.A11Y_TREE}:
            return EvidencePolicyDecision(
                ingest_state=ArtifactIngestState.QUARANTINED,
                redaction_state=RedactionState.QUARANTINED,
                trust_state=EvidenceTrustState.QUARANTINED,
                allowed_scopes=(AccessScope.READ_METADATA,),
                indexable=False,
            )
        if draft.artifact_type in {
            ArtifactType.PAGE_METADATA,
            ArtifactType.SELECTION_MAP,
            ArtifactType.A11Y_COVERAGE,
            ArtifactType.SYSTEM_APPSHOT,
        }:
            return EvidencePolicyDecision(
                ingest_state=ArtifactIngestState.DLP_PASSED,
                redaction_state=RedactionState.NONE,
                trust_state=EvidenceTrustState.DLP_PASSED,
                allowed_scopes=(AccessScope.READ_METADATA,),
                indexable=False,
            )
        if draft.role == ArtifactRole.SELECTION_TEXT and draft.provenance.provider_kind == ProviderKind.ENRICHMENT:
            return EvidencePolicyDecision(
                ingest_state=ArtifactIngestState.DLP_PASSED,
                redaction_state=RedactionState.REDACTED,
                trust_state=EvidenceTrustState.DLP_PASSED,
                allowed_scopes=(AccessScope.READ_METADATA, AccessScope.READ_TEXT),
                indexable=True,
            )
        if draft.role == ArtifactRole.VISUAL_OCR_TEXT and draft.provenance.provider_kind == ProviderKind.ENRICHMENT:
            return EvidencePolicyDecision(
                ingest_state=ArtifactIngestState.DLP_PASSED,
                redaction_state=RedactionState.REDACTED,
                trust_state=EvidenceTrustState.DLP_PASSED,
                allowed_scopes=(AccessScope.READ_METADATA, AccessScope.READ_TEXT),
                indexable=True,
            )
        if draft.role == ArtifactRole.SOURCE_TEXT:
            return EvidencePolicyDecision(
                ingest_state=ArtifactIngestState.QUARANTINED,
                redaction_state=RedactionState.QUARANTINED,
                trust_state=EvidenceTrustState.QUARANTINED,
                allowed_scopes=(AccessScope.READ_METADATA,),
                indexable=False,
            )
        if draft.role == ArtifactRole.CLEAN_PAGE_TEXT and draft.provenance.provider_kind == ProviderKind.ENRICHMENT:
            return EvidencePolicyDecision(
                ingest_state=ArtifactIngestState.DLP_PASSED,
                redaction_state=RedactionState.REDACTED,
                trust_state=EvidenceTrustState.DLP_PASSED,
                allowed_scopes=(AccessScope.READ_METADATA, AccessScope.READ_TEXT),
                indexable=True,
            )
        if draft.role == ArtifactRole.CANONICAL_TEXT and draft.provenance.provider_kind == ProviderKind.ENRICHMENT:
            return EvidencePolicyDecision(
                ingest_state=ArtifactIngestState.DLP_PASSED,
                redaction_state=RedactionState.REDACTED,
                trust_state=EvidenceTrustState.DLP_PASSED,
                allowed_scopes=(AccessScope.READ_METADATA, AccessScope.READ_TEXT),
                indexable=True,
            )
        if draft.sensitivity == EvidenceSensitivity.HIGH_SENSITIVITY:
            return EvidencePolicyDecision(
                ingest_state=ArtifactIngestState.QUARANTINED,
                redaction_state=RedactionState.QUARANTINED,
                trust_state=EvidenceTrustState.QUARANTINED,
                allowed_scopes=(AccessScope.READ_METADATA,),
                indexable=False,
            )
        return EvidencePolicyDecision(
            ingest_state=ArtifactIngestState.QUARANTINED,
            redaction_state=RedactionState.QUARANTINED,
            trust_state=EvidenceTrustState.QUARANTINED,
            allowed_scopes=(AccessScope.READ_METADATA,),
            indexable=False,
        )
