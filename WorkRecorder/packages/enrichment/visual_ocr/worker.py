"""Durable visual OCR job runner."""

from __future__ import annotations

import logging
from collections.abc import Callable

from packages.capture.derived_persistence import DerivedEvidencePersistenceService
from packages.contracts import (
    Artifact,
    ArtifactType,
    CaptureJob,
    ContextEvent,
    EnrichmentRecord,
    EventChangeType,
    EvidenceKind,
    JobStatus,
    JobType,
    VisualOCRStatus,
)
from packages.contracts.common import JsonScalar
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from packages.storage.container import RepositoryContainer

from .service import VisualOCRDerivation, VisualOCRService, VisualOCRServiceError

logger = logging.getLogger(__name__)

_DEFAULT_VISUAL_OCR_MAX_ATTEMPTS = 3


class VisualOCRJobRunner:
    """Schedule and execute visual OCR jobs outside capture hot path."""

    def __init__(
        self,
        *,
        repositories: RepositoryContainer,
        service: VisualOCRService,
        persistence: DerivedEvidencePersistenceService,
        ids: IdFactory,
        clock: Clock,
        max_attempts: int = _DEFAULT_VISUAL_OCR_MAX_ATTEMPTS,
        after_completed: Callable[[str], None] | None = None,
    ) -> None:
        self.repositories = repositories
        self.service = service
        self.persistence = persistence
        self.ids = ids
        self.clock = clock
        self.max_attempts = max(1, max_attempts)
        self.after_completed = after_completed

    def schedule_for_event(self, event_id: str, *, reason: str = "manual") -> CaptureJob:
        """Create or return a queued OCR job for one event.

        Args:
            event_id: Event that should receive visual OCR.
            reason: Stable reason recorded in job payload.

        Returns:
            Existing pending/running/completed job or a newly queued job.
        """

        existing = self.repositories.jobs.get_for_event_type(event_id=event_id, job_type=JobType.VISUAL_OCR_V0)
        if existing is not None:
            if existing.status in {JobStatus.PENDING, JobStatus.RUNNING}:
                return existing
            if existing.status == JobStatus.COMPLETED:
                return existing
        now = self.clock.now()
        job = CaptureJob(
            job_id=self.ids.new("job"),
            event_id=event_id,
            job_type=JobType.VISUAL_OCR_V0,
            status=JobStatus.PENDING,
            payload={"reason": reason, "visual_ocr_status": VisualOCRStatus.PENDING.value},
            created_at=now,
            updated_at=now,
        )
        saved = self.repositories.jobs.save(job)
        self._notify(event_id, VisualOCRStatus.PENDING, job=saved)
        return saved

    def maybe_schedule_for_capture(self, event_id: str) -> CaptureJob | None:
        """Schedule OCR after capture if enabled for new screenshots.

        Args:
            event_id: Newly saved event id.

        Returns:
            Queued/skipped job when settings require a decision, otherwise
            ``None`` when visual OCR auto-run is disabled.
        """

        readiness = self._readiness(event_id)
        if not readiness.allowed:
            return self._skip(event_id, reason=readiness.reason, job_reason="auto_run_on_capture")
        settings = self.service.settings.runtime_flags()
        if not settings.enabled:
            return self._skip(event_id, reason="config_required", job_reason="auto_run_on_capture")
        if not settings.auto_run_on_capture:
            return self._skip(event_id, reason="auto_run_disabled", job_reason="auto_run_on_capture")
        provider_unavailable = self.service.provider_unavailable_reason()
        if provider_unavailable is not None:
            return self._skip(event_id, reason=provider_unavailable, job_reason="auto_run_on_capture")
        return self.schedule_for_event(event_id, reason="auto_run_on_capture")

    async def run_for_event(self, event_id: str) -> CaptureJob:
        """Run the OCR job for one event and persist derived evidence.

        Args:
            event_id: Event whose queued visual OCR job should execute.

        Returns:
            Final or current job state. Concurrent callers that fail to claim
            the job return the current running/completed state without a second
            provider call.
        """

        job = self.repositories.jobs.get_for_event_type(event_id=event_id, job_type=JobType.VISUAL_OCR_V0)
        if job is None:
            job = self.schedule_for_event(event_id, reason="manual")
        if job.status == JobStatus.COMPLETED:
            self._notify(event_id, VisualOCRStatus.COMPLETED, job=job)
            return job
        readiness = self._readiness(event_id)
        if not readiness.allowed:
            skipped = self._skip(
                event_id, reason=readiness.reason, job_reason=str(job.payload.get("reason") or "manual")
            )
            return skipped
        provider_unavailable = self.service.provider_unavailable_reason()
        if provider_unavailable is not None:
            return self._skip(
                event_id, reason=provider_unavailable, job_reason=str(job.payload.get("reason") or "manual")
            )
        claimed = self.repositories.jobs.claim_for_run(
            event_id=event_id,
            job_type=JobType.VISUAL_OCR_V0,
            now=self.clock.now(),
            payload_updates={"visual_ocr_status": VisualOCRStatus.RUNNING.value},
        )
        if claimed is None:
            return self.schedule_for_event(event_id, reason="manual")
        job = claimed
        if job.status != JobStatus.RUNNING:
            self._notify(event_id, _status_from_job(job), job=job)
            return job
        self._notify(event_id, VisualOCRStatus.RUNNING, job=job)
        try:
            event, screenshot, capture_run_id, parent_evidence_ids = self._load_inputs(event_id)
            attempt_result = await self._run_service_with_retries(
                event_id=event_id,
                job=job,
                event=event,
                screenshot=screenshot,
                capture_run_id=capture_run_id,
                parent_evidence_ids=parent_evidence_ids,
            )
            job = attempt_result.job
            output = self._persist_derivation(
                event=event,
                capture_run_id=capture_run_id,
                derivation=attempt_result.derivation,
            )
            completed = self._set_status(
                job,
                JobStatus.COMPLETED,
                {
                    "visual_ocr_status": VisualOCRStatus.COMPLETED.value,
                    "output_evidence_id": output.output_evidence_id,
                    "output_artifact_id": output.output_artifact_id,
                    "text_length": output.text_length,
                    "attempt_count": attempt_result.attempt_count,
                    "max_attempts": self.max_attempts,
                },
            )
            self._notify(
                event_id,
                VisualOCRStatus.COMPLETED,
                job=completed,
                payload={
                    "output_evidence_id": output.output_evidence_id,
                    "output_artifact_id": output.output_artifact_id,
                    "text_length": output.text_length,
                    "attempt_count": attempt_result.attempt_count,
                    "max_attempts": self.max_attempts,
                },
            )
            self._after_completed(event_id)
            return completed
        except Exception as exc:
            logger.warning(
                "visual OCR job failed: %s",
                exc.__class__.__name__,
                extra={"event_id": event_id, "job_id": job.job_id},
            )
            retry_failure = exc if isinstance(exc, _VisualOCRRetriesExhausted) else None
            safe_error = _safe_error(retry_failure.original if retry_failure else exc)
            attempt_count = retry_failure.attempt_count if retry_failure else 0
            failed = self._set_status(
                job,
                JobStatus.FAILED,
                {
                    "visual_ocr_status": VisualOCRStatus.FAILED.value,
                    "error": safe_error,
                    "attempt_count": attempt_count,
                    "max_attempts": self.max_attempts,
                },
            )
            self._notify(
                event_id,
                VisualOCRStatus.FAILED,
                job=failed,
                payload={"error": safe_error, "attempt_count": attempt_count, "max_attempts": self.max_attempts},
            )
            return failed

    async def _run_service_with_retries(
        self,
        *,
        event_id: str,
        job: CaptureJob,
        event: ContextEvent,
        screenshot: Artifact,
        capture_run_id: str,
        parent_evidence_ids: tuple[str, ...],
    ) -> "_VisualOCRAttemptResult":
        """Run the visual OCR service with bounded retries.

        Args:
            event_id: Event being enriched.
            job: Claimed running job. Retry metadata is persisted on this job.
            event: Context event source record.
            screenshot: Screenshot artifact selected for OCR.
            capture_run_id: Capture run associated with the event.
            parent_evidence_ids: Parent evidence refs for provenance.

        Raises:
            _VisualOCRRetriesExhausted: When all configured attempts fail.
        """

        last_retry_error = ""
        for attempt in range(1, self.max_attempts + 1):
            if attempt > 1:
                job = self._set_status(
                    job,
                    JobStatus.RUNNING,
                    {
                        "visual_ocr_status": VisualOCRStatus.RUNNING.value,
                        "attempt_count": attempt,
                        "max_attempts": self.max_attempts,
                        "last_retry_error": last_retry_error,
                    },
                )
                self._notify(
                    event_id,
                    VisualOCRStatus.RUNNING,
                    job=job,
                    payload={"attempt_count": attempt, "max_attempts": self.max_attempts, "retrying": True},
                )
            try:
                derivation = await self.service.run(
                    event=event,
                    screenshot=screenshot,
                    capture_run_id=capture_run_id,
                    source_binding_id=event.source_binding.binding_id,
                    parent_evidence_ids=parent_evidence_ids,
                )
                return _VisualOCRAttemptResult(derivation=derivation, job=job, attempt_count=attempt)
            except Exception as exc:
                last_retry_error = _safe_error(exc)
                if attempt >= self.max_attempts:
                    raise _VisualOCRRetriesExhausted(original=exc, attempt_count=attempt) from exc
                logger.warning(
                    "visual OCR attempt failed; retrying: %s",
                    exc.__class__.__name__,
                    extra={
                        "event_id": event_id,
                        "job_id": job.job_id,
                        "attempt": attempt,
                        "max_attempts": self.max_attempts,
                    },
                )
        raise _VisualOCRRetriesExhausted(
            original=VisualOCRServiceError("visual OCR produced no result"),
            attempt_count=self.max_attempts,
        )

    def state_for_event(self, event_id: str) -> dict[str, JsonScalar]:
        """Return a scalar Workbench-friendly OCR status payload.

        Args:
            event_id: Event whose OCR state should be summarized.

        Returns:
            Scalar payload consumed by Workbench and event changes.
        """

        settings = self.service.settings.public()
        job = self.repositories.jobs.get_for_event_type(event_id=event_id, job_type=JobType.VISUAL_OCR_V0)
        if not settings.enabled:
            return {"status": VisualOCRStatus.DISABLED.value, "enabled": False}
        if job is None:
            return {
                "status": VisualOCRStatus.SKIPPED.value,
                "enabled": True,
                "auto_run_on_capture": settings.auto_run_on_capture,
            }
        return {
            "status": str(job.payload.get("visual_ocr_status") or _status_from_job(job).value),
            "enabled": True,
            "job_id": job.job_id,
            "updated_at": job.updated_at.isoformat(),
            **{key: value for key, value in job.payload.items() if isinstance(value, (str, int, float, bool))},
        }

    def _load_inputs(self, event_id: str) -> tuple[ContextEvent, Artifact, str, tuple[str, ...]]:
        event = self.repositories.events.get(event_id)
        envelope = self.repositories.ledger.get_envelope_by_event_id(event_id)
        if event is None or envelope is None:
            raise VisualOCRServiceError("event capture envelope was not found")
        artifacts = self.repositories.artifacts.list_for_event(event_id)
        screenshot = _select_screenshot(artifacts)
        if screenshot is None:
            raise VisualOCRServiceError("event has no screenshot artifact for visual OCR")
        parent_ids = tuple(
            evidence.evidence_id
            for evidence in envelope.evidence_records
            if evidence.artifact_id == screenshot.artifact_id
        )
        return event, screenshot, envelope.capture_run_id, parent_ids

    def _persist_derivation(
        self,
        *,
        event: ContextEvent,
        capture_run_id: str,
        derivation: VisualOCRDerivation,
    ) -> "_PersistedVisualOCR":
        drafts = (
            (derivation.draft,) if derivation.sidecar_draft is None else (derivation.draft, derivation.sidecar_draft)
        )
        persisted, _ = self.persistence.append_many(
            event=event,
            capture_run_id=capture_run_id,
            source_binding_id=event.source_binding.binding_id,
            drafts=drafts,
            enrichment=EnrichmentRecord(
                enrichment_id=self.ids.new("enr"),
                event_id=event.event_id,
                capture_run_id=capture_run_id,
                kind=EvidenceKind.VISUAL_OCR_TEXT,
                extractor=derivation.extractor,
                input_evidence_ids=derivation.input_evidence_ids,
                output_evidence_ids=(),
                status="completed",
                created_at=derivation.draft.observed_at,
                metadata=derivation.metadata,
            ),
        )
        artifact, evidence = persisted[0]
        return _PersistedVisualOCR(
            output_evidence_id=evidence.evidence_id,
            output_artifact_id=artifact.artifact_id if artifact else None,
            text_length=int(evidence.metadata.get("text_length") or 0),
        )

    def _set_status(self, job: CaptureJob, status: JobStatus, payload: dict[str, JsonScalar]) -> CaptureJob:
        next_payload = {**job.payload, **payload}
        updated = job.model_copy(update={"status": status, "payload": next_payload, "updated_at": self.clock.now()})
        return self.repositories.jobs.save(updated)

    def _notify(
        self,
        event_id: str,
        status: VisualOCRStatus,
        *,
        job: CaptureJob,
        payload: dict[str, JsonScalar] | None = None,
    ) -> None:
        body: dict[str, JsonScalar] = {
            "status": status.value,
            "job_id": job.job_id,
            "updated_at": job.updated_at.isoformat(),
        }
        if payload:
            body.update(payload)
        self.repositories.event_changes.append(
            event_id=event_id,
            change_type=EventChangeType.VISUAL_OCR,
            payload=body,
        )

    def _after_completed(self, event_id: str) -> None:
        if self.after_completed is None:
            return
        try:
            self.after_completed(event_id)
        except Exception:
            logger.warning(
                "visual OCR completion callback failed",
                extra={"event_id": event_id},
                exc_info=True,
            )

    def _skip(self, event_id: str, *, reason: str, job_reason: str) -> CaptureJob:
        now = self.clock.now()
        existing = self.repositories.jobs.get_for_event_type(event_id=event_id, job_type=JobType.VISUAL_OCR_V0)
        job = existing or CaptureJob(
            job_id=self.ids.new("job"),
            event_id=event_id,
            job_type=JobType.VISUAL_OCR_V0,
            status=JobStatus.SKIPPED,
            payload={},
            created_at=now,
            updated_at=now,
        )
        skipped = job.model_copy(
            update={
                "status": JobStatus.SKIPPED,
                "updated_at": now,
                "payload": {
                    **job.payload,
                    "reason": job_reason,
                    "visual_ocr_status": VisualOCRStatus.SKIPPED.value,
                    "skip_reason": reason,
                },
            }
        )
        saved = self.repositories.jobs.save(skipped)
        self._notify(event_id, VisualOCRStatus.SKIPPED, job=saved, payload={"skip_reason": reason})
        return saved

    def _readiness(self, event_id: str) -> "_OCRReadiness":
        event = self.repositories.events.get(event_id)
        envelope = self.repositories.ledger.get_envelope_by_event_id(event_id)
        if event is None or envelope is None:
            return _OCRReadiness(False, "event_not_found")
        source = event.source_binding.source_ref
        source_text = " ".join(
            item for item in (source.app_name, source.title, source.url, source.origin, source.connector_name) if item
        ).casefold()
        if any(marker in source_text for marker in _SENSITIVE_SOURCE_MARKERS):
            return _OCRReadiness(False, "sensitive_app_blocked")
        screenshot = _select_screenshot(self.repositories.artifacts.list_for_event(event_id))
        if screenshot is None:
            return _OCRReadiness(False, "no_selected_region_screenshot")
        return _OCRReadiness(True, "ready")


class _PersistedVisualOCR:
    """Small return value for a persisted OCR output."""

    def __init__(self, *, output_evidence_id: str, output_artifact_id: str | None, text_length: int) -> None:
        self.output_evidence_id = output_evidence_id
        self.output_artifact_id = output_artifact_id
        self.text_length = text_length


class _VisualOCRAttemptResult:
    """Result of a provider call after zero or more retries."""

    def __init__(self, *, derivation: VisualOCRDerivation, job: CaptureJob, attempt_count: int) -> None:
        self.derivation = derivation
        self.job = job
        self.attempt_count = attempt_count


class _VisualOCRRetriesExhausted(Exception):
    """Internal wrapper that preserves the final sanitized failure context."""

    def __init__(self, *, original: Exception, attempt_count: int) -> None:
        super().__init__(str(original))
        self.original = original
        self.attempt_count = attempt_count


class _OCRReadiness:
    """Local readiness decision for uploading a selected screenshot to a VLM."""

    def __init__(self, allowed: bool, reason: str) -> None:
        self.allowed = allowed
        self.reason = reason


def _select_screenshot(artifacts: tuple[Artifact, ...]) -> Artifact | None:
    for artifact in reversed(artifacts):
        if artifact.artifact_type == ArtifactType.OS_REGION_CROP:
            return artifact
        if (
            artifact.artifact_type == ArtifactType.SCREENSHOT
            and artifact.metadata.get("visual_ocr_upload_allowed") is True
        ):
            return artifact
    return None


def _status_from_job(job: CaptureJob) -> VisualOCRStatus:
    if job.status == JobStatus.PENDING:
        return VisualOCRStatus.PENDING
    if job.status == JobStatus.RUNNING:
        return VisualOCRStatus.RUNNING
    if job.status == JobStatus.COMPLETED:
        return VisualOCRStatus.COMPLETED
    if job.status == JobStatus.SKIPPED:
        return VisualOCRStatus.SKIPPED
    return VisualOCRStatus.FAILED


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, VisualOCRServiceError):
        return str(exc)[:160] or "visual_ocr_service_error"
    return exc.__class__.__name__


_SENSITIVE_SOURCE_MARKERS = (
    "1password",
    "keychain",
    "password",
    "bitwarden",
    "bank",
    "banking",
    "wallet",
    "paypal",
    "stripe",
    "tax",
    "irs",
    "health",
    "medical",
    "clinic",
    "hospital",
    "sso",
    "mfa",
    "otp",
    "authenticator",
    "银行",
    "钥匙串",
    "密码",
    "钱包",
    "税务",
    "医疗",
)
