"""Visual OCR enrichment orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from packages.artifacts.vault import LocalArtifactVault
from packages.contracts import (
    Artifact,
    ArtifactRole,
    ArtifactType,
    ContextEvent,
    EnrichmentRecord,
    EvidenceDraft,
    EvidenceKind,
    EvidenceLocator,
    EvidencePayloadRef,
    EvidencePhase,
    EvidenceProvenance,
    EvidenceSensitivity,
    EvidenceTrustState,
    ExtractorRef,
    ProviderKind,
    RedactionState,
    SourceType,
    VisualOCRPublicSettings,
    VisualOCRRequest,
    VisualOCRResult,
    VisualOCRSettings,
)
from packages.contracts.common import JsonScalar
from packages.evidence.redaction import SensitiveTextRedactor
from packages.settings.visual_ocr import VisualOCRSettingsService
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

from .image_preparer import VisualOCRImagePreparationError, VisualOCRImagePreparer
from .prompt import VisualOCRPromptBuilder
from .providers import VisualOCRProviderFactory


class VisualOCRServiceError(Exception):
    """Raised when visual OCR orchestration cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class VisualOCRDerivation:
    """Visual OCR output prepared for derived evidence persistence.

    Attributes:
        draft: Redacted markdown evidence that can be disclosed as selection text.
        sidecar_draft: Locked structured OCR JSON for diagnostics and replay.
        result: Parsed provider result used by Workbench status surfaces.
        extractor: Stable extractor identity for provenance and audit rows.
        input_evidence_ids: Evidence ids consumed by this derivation.
        input_artifact_ids: Screenshot artifact ids uploaded to the provider.
        metadata: Stable non-secret metadata copied into enrichment records.
    """

    draft: EvidenceDraft
    sidecar_draft: EvidenceDraft | None
    result: VisualOCRResult
    extractor: ExtractorRef
    input_evidence_ids: tuple[str, ...]
    input_artifact_ids: tuple[str, ...]
    metadata: dict[str, JsonScalar]

    def enrichment_record(
        self,
        *,
        ids: IdFactory,
        event_id: str,
        capture_run_id: str,
        output_evidence_id: str,
    ) -> EnrichmentRecord:
        """Create the enrichment ledger row after persistence assigns evidence id.

        Args:
            ids: Id generator used for enrichment run identity.
            event_id: Context event that owns this derived OCR evidence.
            capture_run_id: Capture run ledger id associated with the event.
            output_evidence_id: Persisted evidence id assigned to ``draft``.

        Returns:
            A completed enrichment record ready for ledger persistence.
        """

        return EnrichmentRecord(
            enrichment_id=ids.new("enr"),
            event_id=event_id,
            capture_run_id=capture_run_id,
            kind=EvidenceKind.VISUAL_OCR_TEXT,
            extractor=self.extractor,
            input_evidence_ids=self.input_evidence_ids,
            output_evidence_ids=(output_evidence_id,),
            status="completed",
            created_at=self.draft.observed_at,
            metadata=self.metadata,
        )


class VisualOCRService:
    """Run VLM OCR against a selected screenshot and produce typed evidence."""

    def __init__(
        self,
        *,
        vault: LocalArtifactVault,
        settings: VisualOCRSettingsService,
        clock: Clock,
        ids: IdFactory,
        redactor: SensitiveTextRedactor,
        prompt_builder: VisualOCRPromptBuilder | None = None,
        provider_factory: VisualOCRProviderFactory | None = None,
        image_preparer: VisualOCRImagePreparer | None = None,
    ) -> None:
        self.vault = vault
        self.settings = settings
        self.clock = clock
        self.ids = ids
        self.redactor = redactor
        self.prompt_builder = prompt_builder or VisualOCRPromptBuilder()
        self.provider_factory = provider_factory or VisualOCRProviderFactory(prompt_builder=self.prompt_builder)
        self.image_preparer = image_preparer or VisualOCRImagePreparer(vault=vault)

    async def run(
        self,
        *,
        event: ContextEvent,
        screenshot: Artifact,
        capture_run_id: str,
        source_binding_id: str,
        parent_evidence_ids: tuple[str, ...],
    ) -> VisualOCRDerivation:
        """Run configured OCR and return a derived evidence draft.

        Args:
            event: Context event whose screenshot should be read.
            screenshot: Quarantined screenshot artifact to send to the provider.
            capture_run_id: Ledger run id used for provenance rows.
            source_binding_id: Source binding id copied into evidence provenance.
            parent_evidence_ids: Existing evidence ids that led to this OCR pass.

        Returns:
            Redacted derived evidence plus locked OCR diagnostics.

        Raises:
            VisualOCRServiceError: If OCR is disabled, the screenshot cannot be
                read safely, the image is invalid, or the configured provider
                fails validation.
        """

        config = self.settings.get(include_secret=True)
        if not config.enabled:
            raise VisualOCRServiceError("visual OCR is disabled")
        if unavailable_reason := self.provider_factory.unavailable_reason(config):
            raise VisualOCRServiceError(unavailable_reason)
        try:
            prepared_image = self.image_preparer.prepare_artifact(storage_uri=screenshot.storage_uri, settings=config)
        except VisualOCRImagePreparationError as exc:
            raise VisualOCRServiceError(str(exc)) from exc
        request = VisualOCRRequest(
            request_id=self.ids.new("vocr_req"),
            event_id=event.event_id,
            artifact_id=screenshot.artifact_id,
            source=event.source_binding.source_ref,
            user_note=event.intent_text or event.trigger.intent_text,
            selection_bbox=event.trigger.selection,
            image_base64=prepared_image.image_base64,
            image_media_type=prepared_image.image_media_type,
            settings=self._public_settings(config),
        )
        provider = self.provider_factory.create(config)
        result = await provider.run(request)
        return self._derivation(
            event=event,
            screenshot=screenshot,
            source_binding_id=source_binding_id,
            parent_evidence_ids=parent_evidence_ids,
            result=result,
        )

    async def test_provider(self) -> None:
        """Validate that the configured provider can accept a tiny OCR request."""

        config = self.settings.get(include_secret=True)
        unavailable_reason = self.provider_unavailable_reason()
        if unavailable_reason is not None:
            raise VisualOCRServiceError(unavailable_reason)
        provider = self.provider_factory.create(config)
        probe = getattr(provider, "probe", None)
        if not callable(probe):
            raise VisualOCRServiceError("visual OCR provider does not expose a probe method")
        await cast(Callable[[], Awaitable[object]], probe)()

    def provider_unavailable_reason(self) -> str | None:
        """Return a stable reason when the configured provider cannot run locally.

        Returns:
            ``None`` when the configured OCR provider is enabled and runnable;
            otherwise a stable reason code for skipped jobs and diagnostics.
        """

        config = self.settings.get(include_secret=True)
        if not config.enabled:
            return "config_required"
        return self.provider_factory.unavailable_reason(config)

    def _derivation(
        self,
        *,
        event: ContextEvent,
        screenshot: Artifact,
        source_binding_id: str,
        parent_evidence_ids: tuple[str, ...],
        result: VisualOCRResult,
    ) -> VisualOCRDerivation:
        now = self.clock.now()
        extractor = ExtractorRef(name="visual_ocr_v0", version="p0_v1")
        safe_result = self._redacted_result(result)
        ocr_text = self._ocr_text(safe_result)
        redacted = self.redactor.redact(ocr_text)
        provider_source = str(safe_result.metadata.get("source") or "")
        ocr_provider = (
            "apple_vision"
            if safe_result.raw_model_name == "apple_vision" or provider_source == "apple_vision"
            else "openai_compatible"
        )
        metadata: dict[str, JsonScalar] = {
            "source_method": "ocr",
            "ocr_provider": ocr_provider,
            "provider_key": "system.enrichment.visual_ocr",
            "model": result.raw_model_name or "configured_model",
            "input_artifact_id": screenshot.artifact_id,
            "text_length": len(redacted),
            "line_count": len(result.lines),
            "ui_element_count": len(result.ui_elements),
            "confidence": result.quality.confidence,
            "truncated": result.quality.truncated,
            "payload_schema": "visual_ocr_markdown_v0",
        }
        sidecar = self._sidecar_draft(
            event=event,
            screenshot=screenshot,
            source_binding_id=source_binding_id,
            parent_evidence_ids=parent_evidence_ids,
            extractor=extractor,
            result=safe_result,
        )
        draft = EvidenceDraft(
            phase=EvidencePhase.ENRICHED,
            kind=EvidenceKind.VISUAL_OCR_TEXT,
            artifact_type=ArtifactType.VISUAL_OCR_TEXT,
            role=ArtifactRole.VISUAL_OCR_TEXT,
            payload=EvidencePayloadRef(
                content_type="text/markdown; charset=utf-8",
                inline_content=redacted,
                payload_schema="visual_ocr_markdown_v0",
            ),
            locator=EvidenceLocator(
                source_uri=f"workrecorder://events/{event.event_id}/visual_ocr",
                source_type=SourceType.DESKTOP_WINDOW,
                bbox=event.trigger.selection,
                metadata={
                    "input_artifact_id": screenshot.artifact_id,
                    "source_method": "ocr",
                },
            ),
            observed_at=now,
            captured_at=event.trigger.occurred_at,
            provenance=EvidenceProvenance(
                provider_key="system.enrichment.visual_ocr",
                provider_kind=ProviderKind.ENRICHMENT,
                source_binding_id=source_binding_id,
                parent_evidence_ids=parent_evidence_ids,
                input_artifact_ids=(screenshot.artifact_id,),
                extractor=extractor,
            ),
            sensitivity=EvidenceSensitivity.INTERNAL,
            trust_state_claim=EvidenceTrustState.DLP_PASSED,
            redaction_state_claim=RedactionState.REDACTED,
            metadata=metadata,
        )
        return VisualOCRDerivation(
            draft=draft,
            sidecar_draft=sidecar,
            result=result,
            extractor=extractor,
            input_evidence_ids=parent_evidence_ids,
            input_artifact_ids=(screenshot.artifact_id,),
            metadata=metadata,
        )

    def _ocr_text(self, result: VisualOCRResult) -> str:
        """Return user-visible OCR text without agent safety wrapper copy.

        Args:
            result: Provider OCR result after redaction has been applied.

        Returns:
            Plain OCR text. Agent-facing safety wording belongs in disclosure
            and bundle instructions, not inside the OCR evidence itself.
        """

        return (result.readable_markdown.strip() or result.plain_text.strip()).strip()

    def _sidecar_draft(
        self,
        *,
        event: ContextEvent,
        screenshot: Artifact,
        source_binding_id: str,
        parent_evidence_ids: tuple[str, ...],
        extractor: ExtractorRef,
        result: VisualOCRResult,
    ) -> EvidenceDraft:
        now = self.clock.now()
        return EvidenceDraft(
            phase=EvidencePhase.ENRICHED,
            kind=EvidenceKind.PROVIDER_DIAGNOSTICS,
            artifact_type=ArtifactType.VISUAL_OCR_RESULT,
            role=ArtifactRole.PROVIDER_DIAGNOSTICS,
            payload=EvidencePayloadRef(
                content_type="application/json; charset=utf-8",
                inline_content=result.model_dump_json(),
                payload_schema="visual_ocr_result_v0",
            ),
            locator=EvidenceLocator(
                source_uri=f"workrecorder://events/{event.event_id}/visual_ocr/result",
                source_type=SourceType.DESKTOP_WINDOW,
                bbox=event.trigger.selection,
                metadata={
                    "input_artifact_id": screenshot.artifact_id,
                    "source_method": "ocr",
                },
            ),
            observed_at=now,
            captured_at=event.trigger.occurred_at,
            provenance=EvidenceProvenance(
                provider_key="system.enrichment.visual_ocr",
                provider_kind=ProviderKind.ENRICHMENT,
                source_binding_id=source_binding_id,
                parent_evidence_ids=parent_evidence_ids,
                input_artifact_ids=(screenshot.artifact_id,),
                extractor=extractor,
            ),
            sensitivity=EvidenceSensitivity.SENSITIVE,
            trust_state_claim=EvidenceTrustState.QUARANTINED,
            redaction_state_claim=RedactionState.REDACTED,
            metadata={
                "input_artifact_id": screenshot.artifact_id,
                "payload_schema": "visual_ocr_result_v0",
                "default_agent_visible": False,
            },
        )

    def _redacted_result(self, result: VisualOCRResult) -> VisualOCRResult:
        return result.model_copy(
            update={
                "plain_text": self.redactor.redact(result.plain_text),
                "readable_markdown": self.redactor.redact(result.readable_markdown),
                "lines": tuple(
                    line.model_copy(update={"text": self.redactor.redact(line.text)}) for line in result.lines
                ),
                "ui_elements": tuple(
                    element.model_copy(
                        update={
                            "label": self.redactor.redact(element.label),
                            "nearby_context": (
                                self.redactor.redact(element.nearby_context)
                                if element.nearby_context is not None
                                else None
                            ),
                        }
                    )
                    for element in result.ui_elements
                ),
            }
        )

    def _public_settings(self, settings: VisualOCRSettings) -> VisualOCRPublicSettings:
        return VisualOCRPublicSettings(
            enabled=settings.enabled,
            auto_run_on_capture=settings.auto_run_on_capture,
            provider_kind=settings.provider_kind,
            api_style=settings.api_style,
            base_url=settings.base_url,
            allow_insecure_remote_base_url=settings.allow_insecure_remote_base_url,
            model=settings.model,
            timeout_seconds=settings.timeout_seconds,
            max_image_long_edge=settings.max_image_long_edge,
            api_key_configured=bool(settings.api_key),
        )
