"""Native capture routes for OS screenshot shells."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, BackgroundTasks, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from packages.artifacts.vault import ArtifactVaultError
from packages.capture.surface import SurfaceDetectionService
from packages.contracts import (
    AccessScope,
    AuditAction,
    CaptureAttemptRequest,
    CaptureAttemptStatus,
    CaptureSaveRequest,
    CaptureStrategy,
    ErrorCode,
    JobStatus,
    NativeCaptureTimingAuthority,
    WindowHint,
    WorkspaceSelection,
)
from packages.contracts.common import JsonScalar

from ..auth import DaemonAuth
from ..dependencies import route_support
from ..safe_metadata import safe_public_payload
from .validation_errors import safe_validation_error_details

if TYPE_CHECKING:
    from ..container import DaemonContainer

router = APIRouter(prefix="/v1/captures", tags=["captures"])
logger = logging.getLogger(__name__)


@router.get("/diagnose/{trigger_id}")
def _diagnose_capture(trigger_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="capture",
        reason="diagnose capture attempt",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    envelope_record = container.repositories.ledger.get_envelope_by_trigger_id(trigger_id)
    existing = container.repositories.captures.find_by_trigger_id(trigger_id)
    if envelope_record is None and existing is None:
        diagnostics = container.repositories.ledger.get_capture_diagnostics_by_trigger_id(trigger_id)
        if diagnostics is None:
            envelope = container.responses.error(
                ErrorCode.NOT_FOUND, "Capture trigger not found", request_id=request_id
            )
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
        response = container.responses.success(
            {"event": None, "first_artifact": None, "jobs": (), "diagnostics": safe_public_payload(diagnostics)},
            request_id=request_id,
        )
        return JSONResponse(content=response.model_dump(mode="json"))
    event, artifact = existing if existing is not None else (None, None)
    jobs = container.repositories.jobs.list_for_event(event.event_id) if event is not None else ()
    os_window_context = _is_os_window_context(event=event, envelope_record=envelope_record)
    envelope = container.responses.success(
        {
            "event": safe_public_payload(event, _os_window_context=os_window_context),
            "first_artifact": safe_public_payload(artifact, _os_window_context=os_window_context),
            "jobs": safe_public_payload(jobs, _os_window_context=os_window_context),
            "manifest": safe_public_payload(envelope_record, _os_window_context=os_window_context),
        },
        request_id=request_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.post("")
async def _save_capture(body: dict[str, object], request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.CREATE_EVENT,
        resource_type="capture",
        reason="save native screen capture",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    try:
        attempt = _parse_capture_attempt(body, container)
    except ValidationError as exc:
        envelope = container.responses.error(
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid capture payload",
            request_id=request_id,
            details=safe_validation_error_details(exc),
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=envelope.model_dump(mode="json"))
    if attempt.native_timing_receipt is not None and not DaemonAuth().native_capture_secret_matches(request, container):
        audit_id = route_support.audit_action(
            request=request,
            request_id=request_id,
            actor=actor,
            action=AuditAction.CAPTURE_ATTEMPTED,
            resource_type="capture",
            resource_id=None,
            policy_decision_id=decision_id,
            success=False,
            details={"reason": "native_timing_receipt_secret_missing"},
        )
        envelope = container.responses.error(
            code=ErrorCode.POLICY_DENIED,
            message="Native timing receipts require trusted local native authority",
            request_id=request_id,
            audit_id=audit_id,
        )
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=envelope.model_dump(mode="json"))
    os_window_denial = _os_window_native_authority_denial(attempt=attempt, request=request, container=container)
    if os_window_denial is not None:
        audit_id = route_support.audit_action(
            request=request,
            request_id=request_id,
            actor=actor,
            action=AuditAction.CAPTURE_ATTEMPTED,
            resource_type="capture",
            resource_id=None,
            policy_decision_id=decision_id,
            success=False,
            details={"reason": os_window_denial},
        )
        envelope = container.responses.error(
            code=ErrorCode.POLICY_DENIED,
            message="Current-window captures require trusted local native authority",
            request_id=request_id,
            audit_id=audit_id,
        )
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=envelope.model_dump(mode="json"))
    workspace_id = _workspace_id_from_request(request)
    if workspace_id is not None and attempt.workspace.workspace_id not in {
        workspace_id,
        WorkspaceSelection.AUTO_WORKSPACE_ID,
    }:
        envelope = container.responses.error(
            code=ErrorCode.VALIDATION_ERROR,
            message="Capture workspace must match the request workspace",
            request_id=request_id,
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=envelope.model_dump(mode="json"))
    workspace = _trusted_workspace_for_attempt(attempt=attempt, request_workspace_id=workspace_id)
    safe_attempt = attempt.model_copy(
        update={
            "actor": actor,
            "trigger": attempt.trigger.model_copy(update={"actor": actor}),
            "workspace": workspace,
        }
    )
    try:
        saved = await container.capture_attempts.submit(safe_attempt, policy_decision_id=decision_id)
    except ArtifactVaultError as exc:
        audit_id = route_support.audit_action(
            request=request,
            request_id=request_id,
            actor=actor,
            action=AuditAction.CAPTURE_ATTEMPTED,
            resource_type="capture",
            resource_id=None,
            policy_decision_id=decision_id,
            success=False,
        )
        envelope = container.responses.error(
            code=ErrorCode.VALIDATION_ERROR,
            message=str(exc),
            request_id=request_id,
            audit_id=audit_id,
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=envelope.model_dump(mode="json"))
    except Exception:
        logger.exception("failed to save native capture", extra={"request_id": request_id})
        audit_id = route_support.audit_action(
            request=request,
            request_id=request_id,
            actor=actor,
            action=AuditAction.CAPTURE_ATTEMPTED,
            resource_type="capture",
            resource_id=None,
            policy_decision_id=decision_id,
            success=False,
        )
        envelope = container.responses.error(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to save capture",
            request_id=request_id,
            audit_id=audit_id,
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=envelope.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.CAPTURE_ATTEMPTED,
        resource_type="capture",
        resource_id=saved.event.event_id if saved.event else None,
        policy_decision_id=decision_id,
        success=saved.status == CaptureAttemptStatus.ACCEPTED,
        details=_native_timing_audit_details(attempt),
    )
    if saved.event is not None:
        container.repositories.ledger.add_audit_ref(event_id=saved.event.event_id, audit_id=audit_id)
        background_tasks.add_task(container.capture_post_commit_outbox.drain_due_safe, saved.event.event_id)
        job = container.visual_ocr.maybe_schedule_for_capture(saved.event.event_id)
        if job is not None and job.status == JobStatus.PENDING:
            background_tasks.add_task(container.visual_ocr.run_for_event, saved.event.event_id)
    envelope = container.responses.success(
        safe_public_payload(
            saved,
            _os_window_context=attempt.trigger.capture_strategy == CaptureStrategy.OS_WINDOW,
        ),
        request_id=request_id,
        audit_id=audit_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


def _parse_capture_attempt(body: dict[str, object], container: "DaemonContainer") -> CaptureAttemptRequest:
    if "window_hints" in body or body.get("schema_version") == 1:
        return CaptureAttemptRequest.model_validate(body)
    legacy = CaptureSaveRequest.model_validate(body)
    return container.capture_attempts.from_legacy_save_request(legacy)


def _workspace_id_from_request(request: Request) -> str | None:
    workspace_id = request.headers.get("x-workrecorder-workspace-id")
    if workspace_id is None or not workspace_id.strip():
        return None
    return workspace_id.strip()


def _native_timing_audit_details(attempt: CaptureAttemptRequest) -> dict[str, JsonScalar]:
    if attempt.native_timing_receipt is None:
        return {}
    return {
        "native_timing_authority": attempt.native_timing_receipt.authority.value,
        "native_timing_source_clock": attempt.native_timing_receipt.source_clock.value,
    }


def _is_os_window_context(*, event: object | None, envelope_record: object | None) -> bool:
    for candidate in (event, envelope_record):
        if candidate is None:
            continue
        event_type = getattr(candidate, "event_type", None)
        if getattr(event_type, "value", event_type) == "screen.window.captured":
            return True
        trigger = getattr(candidate, "trigger", None)
        strategy = getattr(trigger, "capture_strategy", None)
        if getattr(strategy, "value", strategy) == "os_window":
            return True
    return False


def _os_window_native_authority_denial(
    *,
    attempt: CaptureAttemptRequest,
    request: Request,
    container: "DaemonContainer",
) -> str | None:
    if attempt.trigger.capture_strategy != CaptureStrategy.OS_WINDOW:
        return None
    receipt = attempt.native_timing_receipt
    if receipt is None or not DaemonAuth().native_capture_secret_matches(request, container):
        return "os_window_native_authority_missing"
    if receipt.authority != NativeCaptureTimingAuthority.MACOS_CAPTURE:
        return "os_window_native_authority_invalid"
    primary_hint = SurfaceDetectionService.primary_os_window_hint(tuple(attempt.window_hints))
    if primary_hint is None:
        return "os_window_primary_hint_missing"
    if not _receipt_matches_primary_window_hint(primary_hint, receipt.metadata):
        return "os_window_native_receipt_mismatch"
    return None


def _receipt_matches_primary_window_hint(hint: WindowHint, metadata: dict[str, JsonScalar]) -> bool:
    if (
        hint.process_id is None
        or hint.window_id is None
        or hint.bundle_id is None
        or hint.display_id is None
        or hint.frame is None
    ):
        return False
    if _metadata_int(metadata, "os_window_process_id") != hint.process_id:
        return False
    if _metadata_str(metadata, "os_window_window_id") != hint.window_id:
        return False
    if _metadata_str(metadata, "os_window_bundle_id") != hint.bundle_id:
        return False
    if _metadata_str(metadata, "os_window_display_id") != hint.display_id:
        return False
    return (
        _metadata_int(metadata, "os_window_frame_x") == hint.frame.x
        and _metadata_int(metadata, "os_window_frame_y") == hint.frame.y
        and _metadata_int(metadata, "os_window_frame_width") == hint.frame.width
        and _metadata_int(metadata, "os_window_frame_height") == hint.frame.height
        and _metadata_str(metadata, "os_window_frame_space") == hint.frame.coordinate_space.value
    )


def _metadata_int(metadata: dict[str, JsonScalar], key: str) -> int | None:
    value = metadata.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _metadata_str(metadata: dict[str, JsonScalar], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _trusted_workspace_for_attempt(
    *,
    attempt: CaptureAttemptRequest,
    request_workspace_id: str | None,
) -> WorkspaceSelection:
    if request_workspace_id is not None:
        return WorkspaceSelection(workspace_id=request_workspace_id, label=attempt.workspace.label, auto=False)
    if attempt.active_capture is not None:
        return WorkspaceSelection.auto_selection()
    return attempt.workspace
