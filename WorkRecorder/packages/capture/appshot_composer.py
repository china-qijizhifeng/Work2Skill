"""Post-persistence composer for safe system appshot references."""

from __future__ import annotations

import logging

from packages.artifacts.vault import LocalArtifactVault
from packages.contracts import (
    A11yPermissionState,
    A11ySnapshot,
    AppshotComponentRef,
    Artifact,
    ArtifactType,
    EvidenceDraft,
    EvidenceKind,
    EvidenceRecord,
    ProviderCaptureOutcomeStatus,
    ProviderCommandStatus,
    ProviderEvidenceBundle,
    ProviderPermissionState,
    ProviderRouteRole,
    SystemAppshotSnapshot,
)

logger = logging.getLogger(__name__)

SYSTEM_SCREENSHOT_PROVIDER_KEY = "system.screenshot"
SYSTEM_A11Y_PROVIDER_KEY = "system.macos_a11y"


class SystemAppshotComposer:
    """Fill a metadata-only appshot draft with trusted persisted refs."""

    def __init__(self, *, vault: LocalArtifactVault) -> None:
        self.vault = vault

    def enrich(
        self,
        *,
        draft: EvidenceDraft,
        evidence_records: tuple[EvidenceRecord, ...],
        artifacts: tuple[Artifact, ...],
        system_bundles: tuple[ProviderEvidenceBundle, ...],
    ) -> EvidenceDraft:
        """Return an appshot draft with screenshot/a11y refs and quality filled.

        Args:
            draft: Metadata-only appshot draft emitted before persistence.
            evidence_records: Evidence already persisted for the capture run.
            artifacts: Artifacts already persisted for the capture run.
            system_bundles: System provider bundles that produced the inputs.

        Returns:
            Updated appshot draft with safe parent refs and quality diagnostics.
        """

        if draft.payload.inline_content is None:
            return draft
        try:
            snapshot = SystemAppshotSnapshot.model_validate_json(draft.payload.inline_content)
        except ValueError:
            logger.warning("system appshot payload validation failed", exc_info=True)
            return draft
        artifact_ids_by_evidence = {
            artifact.evidence_id: artifact.artifact_id for artifact in artifacts if artifact.evidence_id is not None
        }
        evidence_by_command = self._evidence_ids_by_command(evidence_records)
        screenshot_ids = tuple(
            evidence.evidence_id
            for evidence in evidence_records
            if evidence.kind == EvidenceKind.SCREENSHOT
            and evidence.provenance.provider_key == SYSTEM_SCREENSHOT_PROVIDER_KEY
        )
        a11y_ids = tuple(
            evidence.evidence_id
            for evidence in evidence_records
            if evidence.kind == EvidenceKind.A11Y and evidence.provenance.provider_key == SYSTEM_A11Y_PROVIDER_KEY
        )
        components = self._components(
            system_bundles=system_bundles,
            evidence_by_command=evidence_by_command,
            artifact_ids_by_evidence=artifact_ids_by_evidence,
        )
        a11y_snapshot = self._a11y_snapshot(evidence_records=evidence_records)
        a11y_succeeded = a11y_snapshot is not None and a11y_snapshot.permission_state == A11yPermissionState.GRANTED
        updated_snapshot = snapshot.model_copy(
            update={
                "screenshot_evidence_id": screenshot_ids[0] if screenshot_ids else None,
                "a11y_evidence_ids": a11y_ids,
                "components": tuple(components),
                "quality": snapshot.quality.model_copy(
                    update={
                        "screenshot_present": bool(screenshot_ids),
                        "a11y_supported": a11y_succeeded,
                        "a11y_permission_state": (
                            a11y_snapshot.permission_state if a11y_snapshot is not None else None
                        ),
                        "text_block_count": (
                            a11y_snapshot.coverage.text_block_count if a11y_snapshot is not None else 0
                        ),
                        "coverage_confidence": (
                            a11y_snapshot.coverage.confidence if a11y_snapshot is not None else 0.0
                        ),
                        "diagnostics": (
                            *snapshot.quality.diagnostics,
                            *self._appshot_a11y_diagnostics(
                                a11y_snapshot=a11y_snapshot,
                                a11y_evidence_ids=a11y_ids,
                            ),
                        ),
                    }
                ),
                "permissions": snapshot.permissions.model_copy(
                    update={"accessibility": self._accessibility_state(a11y_snapshot)}
                ),
            }
        )
        payload = draft.payload.model_copy(update={"inline_content": updated_snapshot.model_dump_json()})
        provenance = draft.provenance.model_copy(
            update={
                "parent_evidence_ids": tuple(dict.fromkeys((*screenshot_ids, *a11y_ids))),
                "input_artifact_ids": tuple(
                    artifact_ids_by_evidence[evidence_id]
                    for evidence_id in (*screenshot_ids, *a11y_ids)
                    if evidence_id in artifact_ids_by_evidence
                ),
            }
        )
        return draft.model_copy(update={"payload": payload, "provenance": provenance})

    def _components(
        self,
        *,
        system_bundles: tuple[ProviderEvidenceBundle, ...],
        evidence_by_command: dict[str, tuple[str, ...]],
        artifact_ids_by_evidence: dict[str, str],
    ) -> list[AppshotComponentRef]:
        components: list[AppshotComponentRef] = []
        for bundle in system_bundles:
            if bundle.evidence_kind == EvidenceKind.SYSTEM_APPSHOT:
                continue
            evidence_ids = evidence_by_command.get(bundle.command_id, ())
            components.append(
                AppshotComponentRef(
                    provider_key=bundle.provider_key,
                    evidence_kind=bundle.evidence_kind,
                    status=self._outcome_status_for_command(bundle.status),
                    role=ProviderRouteRole.SYSTEM_EVIDENCE,
                    command_id=bundle.command_id,
                    provider_session_id=bundle.provider_session_id,
                    evidence_ids=evidence_ids,
                    artifact_ids=tuple(
                        artifact_ids_by_evidence[evidence_id]
                        for evidence_id in evidence_ids
                        if evidence_id in artifact_ids_by_evidence
                    ),
                    reason_code=(
                        str(bundle.diagnostics.get("error_code"))
                        if bundle.diagnostics and bundle.diagnostics.get("error_code") is not None
                        else None
                    ),
                )
            )
        return components

    def _a11y_snapshot(self, *, evidence_records: tuple[EvidenceRecord, ...]) -> A11ySnapshot | None:
        for evidence in evidence_records:
            if (
                evidence.kind != EvidenceKind.A11Y
                or evidence.artifact_type != ArtifactType.A11Y_TREE
                or evidence.provenance.provider_key != SYSTEM_A11Y_PROVIDER_KEY
            ):
                continue
            if evidence.payload.storage_uri is None:
                continue
            try:
                raw = self.vault.read(evidence.payload.storage_uri).decode("utf-8")
                return A11ySnapshot.model_validate_json(raw)
            except (OSError, UnicodeDecodeError, ValueError):
                logger.warning(
                    "failed to read a11y snapshot for system appshot quality",
                    extra={"evidence_id": evidence.evidence_id},
                    exc_info=True,
                )
        return None

    def _accessibility_state(self, snapshot: A11ySnapshot | None) -> ProviderPermissionState:
        if snapshot is None:
            return ProviderPermissionState.UNKNOWN
        if snapshot.permission_state == A11yPermissionState.GRANTED:
            return ProviderPermissionState.GRANTED
        if snapshot.permission_state == A11yPermissionState.DENIED:
            return ProviderPermissionState.NEEDS_USER_ACTION
        return ProviderPermissionState.UNKNOWN

    def _appshot_a11y_diagnostics(
        self, *, a11y_snapshot: A11ySnapshot | None, a11y_evidence_ids: tuple[str, ...]
    ) -> tuple[str, ...]:
        if a11y_snapshot is None:
            return ("a11y_snapshot_unavailable",)
        diagnostics: list[str] = []
        if not a11y_evidence_ids:
            diagnostics.append("a11y_evidence_unavailable")
        if a11y_snapshot.permission_state != A11yPermissionState.GRANTED:
            diagnostics.append(f"a11y_permission_{a11y_snapshot.permission_state.value}")
        if a11y_snapshot.truncated:
            diagnostics.append("a11y_truncated")
        if a11y_snapshot.coverage.error_message:
            diagnostics.append("a11y_coverage_error")
        return tuple(diagnostics)

    def _evidence_ids_by_command(self, evidence_records: tuple[EvidenceRecord, ...]) -> dict[str, tuple[str, ...]]:
        grouped: dict[str, list[str]] = {}
        for evidence in evidence_records:
            command_id = evidence.provenance.command_id
            if command_id is None:
                continue
            grouped.setdefault(command_id, []).append(evidence.evidence_id)
        return {command_id: tuple(ids) for command_id, ids in grouped.items()}

    def _outcome_status_for_command(self, status: ProviderCommandStatus) -> ProviderCaptureOutcomeStatus:
        if status == ProviderCommandStatus.SUCCEEDED:
            return ProviderCaptureOutcomeStatus.SUCCEEDED
        if status == ProviderCommandStatus.TIMEOUT:
            return ProviderCaptureOutcomeStatus.TIMEOUT
        if status == ProviderCommandStatus.UNSUPPORTED:
            return ProviderCaptureOutcomeStatus.UNSUPPORTED
        if status == ProviderCommandStatus.SKIPPED:
            return ProviderCaptureOutcomeStatus.SKIPPED
        return ProviderCaptureOutcomeStatus.FAILED
