"""Event routes for the local context daemon."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

from packages.artifacts.public_projection import ArtifactPublicProjector
from packages.contracts import (
    AccessScope,
    AuditAction,
    CaptureStrategy,
    ContextEventCreate,
    DisclosureClass,
    DisclosureDecision,
    DisclosureField,
    DisclosureView,
    ErrorCode,
    EventInspectSection,
    EventInspectView,
    EventStatus,
    EventType,
    RetrievalCallKind,
    SnapshotKind,
    VisualOCRStatus,
)

from ..dependencies import route_support
from ..safe_metadata import safe_public_payload

router = APIRouter(prefix="/v1/events", tags=["events"])
logger = logging.getLogger(__name__)
_artifact_projector = ArtifactPublicProjector()


@router.post("")
def _create_event(body: ContextEventCreate, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.CREATE_EVENT,
        resource_type="event",
        reason="create context event",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    if _is_reserved_os_window_create(body):
        envelope = container.responses.error(
            ErrorCode.POLICY_DENIED,
            "Current-window captures must be created through the native capture endpoint.",
            request_id=request_id,
        )
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=envelope.model_dump(mode="json"))
    event = container.events.build(body)
    try:
        saved = container.events.save(event)
    except Exception:
        logger.exception("failed to create context event", extra={"request_id": request_id})
        audit_id = route_support.audit_action(
            request=request,
            request_id=request_id,
            actor=actor,
            action=AuditAction.EVENT_CREATED,
            resource_type="event",
            resource_id=event.event_id,
            policy_decision_id=decision_id,
            success=False,
        )
        envelope = container.responses.error(
            ErrorCode.INTERNAL_ERROR,
            "Failed to create event",
            request_id=request_id,
            audit_id=audit_id,
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=envelope.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_CREATED,
        resource_type="event",
        resource_id=event.event_id,
        policy_decision_id=decision_id,
        success=True,
    )
    envelope = container.responses.success(
        safe_public_payload(saved, _os_window_context=_is_os_window_event(saved)),
        request_id=request_id,
        audit_id=audit_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("")
def _list_events(request: Request, limit: int = Query(50, ge=1, le=100)) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="event",
        reason="list context events",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    events = container.repositories.events.list(limit=limit)
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_LISTED,
        resource_type="event",
        resource_id=None,
        policy_decision_id=decision_id,
        success=True,
    )
    envelope = container.responses.success(
        {"events": safe_public_payload(events)}, request_id=request_id, audit_id=audit_id
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/{event_id}/manifest")
def _get_event_manifest(event_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="event_manifest",
        resource_id=event_id,
        reason="read event capture manifest",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    event = container.repositories.events.get(event_id)
    envelope = container.repositories.ledger.get_envelope_by_event_id(event_id)
    if event is None or event.status in {EventStatus.DELETED, EventStatus.RESTRICTED} or envelope is None:
        response = container.responses.error(ErrorCode.NOT_FOUND, "Event manifest not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=response.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_READ,
        resource_type="event_manifest",
        resource_id=event_id,
        policy_decision_id=decision_id,
        success=True,
    )
    response = container.responses.success(safe_public_payload(envelope), request_id=request_id, audit_id=audit_id)
    return JSONResponse(content=response.model_dump(mode="json"))


@router.get("/{event_id}/changes")
async def _get_event_changes(
    event_id: str,
    request: Request,
    since: int = Query(0, ge=0),
    timeout_ms: int = Query(0, ge=0, le=30000),
) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="event_changes",
        resource_id=event_id,
        reason="watch event changes",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    event = container.repositories.events.get(event_id)
    if event is None or event.status in {EventStatus.DELETED, EventStatus.RESTRICTED}:
        response = container.responses.error(ErrorCode.NOT_FOUND, "Event not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=response.model_dump(mode="json"))
    deadline = timeout_ms / 1000.0
    elapsed = 0.0
    changes = container.repositories.event_changes.list_since(event_id=event_id, since=since)
    while not changes and elapsed < deadline:
        await asyncio.sleep(0.25)
        elapsed += 0.25
        changes = container.repositories.event_changes.list_since(event_id=event_id, since=since)
    response = container.responses.success(
        safe_public_payload(
            {
                "changes": changes,
                "latest": container.repositories.event_changes.latest_id(event_id),
                "visual_ocr": container.visual_ocr.state_for_event(event_id),
            }
        ),
        request_id=request_id,
    )
    return JSONResponse(content=response.model_dump(mode="json"))


@router.get("/{event_id}")
def _get_event(
    event_id: str,
    request: Request,
    include: str = Query("", max_length=120),
    view: DisclosureView | None = Query(default=None),
    purpose: str = Query("event_inspect", max_length=160),
    inspect_views: str = Query("", max_length=240),
) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="event",
        resource_id=event_id,
        reason="read context event",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    event = container.repositories.events.get(event_id)
    if event is None or event.status in {EventStatus.DELETED, EventStatus.RESTRICTED}:
        envelope = container.responses.error(ErrorCode.NOT_FOUND, "Event not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    if view == DisclosureView.EVENT_INSPECT:
        unknown_views = _unknown_inspect_views(inspect_views)
        if unknown_views:
            envelope = container.responses.error(
                ErrorCode.VALIDATION_ERROR,
                "Unknown event inspect view.",
                request_id=request_id,
                details={"unknown_views": ",".join(sorted(unknown_views))},
            )
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=envelope.model_dump(mode="json")
            )
        text_auth = route_support.authorize(
            request=request,
            request_id=request_id,
            action=AccessScope.READ_TEXT,
            resource_type="event_inspect",
            resource_id=event_id,
            reason=purpose,
        )
        if not isinstance(text_auth, tuple):
            return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=text_auth.model_dump(mode="json"))
        inspect_actor, inspect_decision_id = text_auth
        requested_sections = _parse_inspect_sections(inspect_views)
        run = container.agent_runs.ensure_run(
            actor=inspect_actor,
            requested_run_id=request.headers.get("x-workrecorder-agent-run-id"),
            purpose=purpose,
        )
        context_query = container.agent_runs.context_query(
            run=run,
            query_text=f"inspect {event_id}: {','.join(section.value for section in requested_sections)}",
            purpose=purpose,
            requested_query_id=request.headers.get("x-workrecorder-context-query-id"),
        )
        inspect_view = _trim_inspect_view(
            container.disclosure.inspect_event(
                event=event,
                actor=inspect_actor,
                purpose=purpose,
                requested_sections=requested_sections,
            ),
            inspect_sections=requested_sections,
        )
        inspect_view = _with_runtime_appshot_status(
            inspect_view,
            visual_ocr_status=str(container.visual_ocr.state_for_event(event_id).get("status") or ""),
        )
        if EventInspectSection.KEYFRAMES in requested_sections:
            inspect_view = container.disclosure.with_keyframe_summaries(
                inspect_view=inspect_view,
                keyframes=container.active_capture.inspect_summaries_for_event(event_id),
            )
        if _active_capture_sections_requested(requested_sections):
            active_capture_view = container.active_capture_inspect.build_for_event(
                event_id=event_id,
                actor=inspect_actor,
                purpose=purpose,
                requested_sections=requested_sections,
            )
            if active_capture_view is not None:
                decision = inspect_view.disclosure_decision.model_copy(
                    update={
                        "delivered_fields": tuple(
                            dict.fromkeys(
                                (*inspect_view.disclosure_decision.delivered_fields, DisclosureField.ACTIVE_CAPTURE)
                            )
                        ),
                        "details": {
                            **inspect_view.disclosure_decision.details,
                            "active_capture_session_id": active_capture_view.session_id,
                            "active_capture_safe_text_block_count": len(active_capture_view.safe_text_blocks),
                        },
                    }
                )
                inspect_view = inspect_view.model_copy(
                    update={"active_capture": active_capture_view, "disclosure_decision": decision}
                )
        inspect_view = container.agent_runs.attach_inspect_citations(run=run, view=inspect_view)
        audit_id = route_support.audit_action(
            request=request,
            request_id=request_id,
            actor=inspect_actor,
            action=AuditAction.DISCLOSURE_EVALUATED,
            resource_type="event",
            resource_id=event_id,
            policy_decision_id=inspect_decision_id,
            success=True,
            details=container.disclosure.decision_audit_details(inspect_view.disclosure_decision),
        )
        call, snapshot = container.agent_runs.trace_delivery(
            run=run,
            context_query=context_query,
            request_id=request_id,
            kind=RetrievalCallKind.EVENT_INSPECT,
            resource_type="event",
            resource_id=event_id,
            purpose=purpose,
            request_payload={"event_id": event_id, "views": [section.value for section in requested_sections]},
            response_payload=inspect_view,
            snapshot_kind=SnapshotKind.EVENT_INSPECT,
            metadata={"audit_id": audit_id},
        )
        response = container.responses.success(
            inspect_view,
            request_id=request_id,
            audit_id=audit_id,
            agent_run_id=run.agent_run_id,
            context_query_id=context_query.context_query_id,
            retrieval_call_id=call.retrieval_call_id,
            snapshot_id=snapshot.snapshot_id,
        )
        return JSONResponse(content=response.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_READ,
        resource_type="event",
        resource_id=event_id,
        policy_decision_id=decision_id,
        success=True,
    )
    if include:
        included = {item.strip() for item in include.split(",") if item.strip()}
        if included.intersection({"evidence", "preview"}):
            envelope = container.responses.error(
                ErrorCode.VALIDATION_ERROR,
                "Text-bearing event reads must use /v1/events/{event_id}?view=event_inspect.",
                request_id=request_id,
                audit_id=audit_id,
            )
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=envelope.model_dump(mode="json")
            )
        artifacts = container.repositories.artifacts.list_for_event(event.event_id)
        os_window_context = _is_os_window_event(event)
        data: dict[str, object] = {"event": safe_public_payload(event, _os_window_context=os_window_context)}
        if "artifacts" in included:
            data["artifacts"] = safe_public_payload(
                tuple(_artifact_projector.project(item) for item in artifacts),
                _os_window_context=os_window_context,
            )
        if "manifest" in included:
            data["manifest"] = safe_public_payload(
                container.repositories.ledger.get_envelope_by_event_id(event.event_id),
                _os_window_context=os_window_context,
            )
        response_data: object = data
    else:
        response_data = safe_public_payload(event, _os_window_context=_is_os_window_event(event))
    envelope = container.responses.success(response_data, request_id=request_id, audit_id=audit_id)
    return JSONResponse(content=envelope.model_dump(mode="json"))


def _is_os_window_event(event: object) -> bool:
    event_type = getattr(event, "event_type", None)
    if getattr(event_type, "value", event_type) == "screen.window.captured":
        return True
    trigger = getattr(event, "trigger", None)
    strategy = getattr(trigger, "capture_strategy", None)
    return getattr(strategy, "value", strategy) == "os_window"


def _is_reserved_os_window_create(body: ContextEventCreate) -> bool:
    """Keep native current-window events behind the capture authority gate."""

    return (
        body.event_type == EventType.SCREEN_WINDOW_CAPTURED.value
        or body.trigger.capture_strategy == CaptureStrategy.OS_WINDOW
    )


def _trim_inspect_view(
    inspect_view: EventInspectView, *, inspect_sections: tuple[EventInspectSection, ...]
) -> EventInspectView:
    requested = set(inspect_sections) or set(_default_inspect_sections())
    readable = []
    for item in inspect_view.readable_evidence:
        text_requested = (
            (
                item.disclosure_class == DisclosureClass.SELECTION_BOUND_TEXT
                and EventInspectSection.SELECTION_TEXT in requested
            )
            or (
                item.disclosure_class == DisclosureClass.REDACTED_CANONICAL
                and EventInspectSection.CANONICAL in requested
            )
            or (
                item.disclosure_class == DisclosureClass.CLEAN_PAGE_TEXT
                and EventInspectSection.CLEAN_PAGE_TEXT in requested
            )
            or (
                item.disclosure_class == DisclosureClass.VISUAL_OCR_TEXT
                and EventInspectSection.VISUAL_OCR_TEXT in requested
            )
        )
        if text_requested:
            readable.append(item)
            continue
        if EventInspectSection.EVIDENCE_REFS in requested:
            readable.append(item.model_copy(update={"text": "", "text_truncated": False}))
    return inspect_view.model_copy(
        update={
            DisclosureField.SYSTEM_APPSHOT.value: (
                inspect_view.system_appshot if EventInspectSection.SYSTEM_APPSHOT in requested else None
            ),
            DisclosureField.CANONICAL_TEXT.value: (
                inspect_view.canonical_text if EventInspectSection.CANONICAL in requested else ""
            ),
            DisclosureField.CANONICAL_TEXT_TRUNCATED.value: (
                inspect_view.canonical_text_truncated if EventInspectSection.CANONICAL in requested else False
            ),
            DisclosureField.CLEAN_PAGE_TEXT.value: (
                inspect_view.clean_page_text if EventInspectSection.CLEAN_PAGE_TEXT in requested else ""
            ),
            DisclosureField.CLEAN_PAGE_TEXT_TRUNCATED.value: (
                inspect_view.clean_page_text_truncated if EventInspectSection.CLEAN_PAGE_TEXT in requested else False
            ),
            DisclosureField.READABLE_EVIDENCE.value: tuple(readable),
            DisclosureField.KEYFRAMES.value: (
                inspect_view.keyframes if EventInspectSection.KEYFRAMES in requested else ()
            ),
            DisclosureField.ACTIVE_CAPTURE.value: (
                inspect_view.active_capture if _active_capture_sections_requested(tuple(requested)) else None
            ),
            DisclosureField.RAW_ARTIFACTS.value: (
                inspect_view.raw_artifacts if EventInspectSection.SCREENSHOT_REF in requested else ()
            ),
            DisclosureField.HIDDEN_ARTIFACTS.value: (
                inspect_view.hidden_artifacts if EventInspectSection.ARTIFACT_METADATA in requested else ()
            ),
            DisclosureField.DISCLOSURE_DECISION.value: _trim_disclosure_decision(
                inspect_view.disclosure_decision, requested=requested
            ),
        }
    )


def _trim_disclosure_decision(
    disclosure_decision: DisclosureDecision, *, requested: set[EventInspectSection]
) -> DisclosureDecision:
    delivered_fields = [
        field
        for field in disclosure_decision.delivered_fields
        if field not in {DisclosureField.KEYFRAMES, DisclosureField.RAW_ARTIFACT_REFS, DisclosureField.HIDDEN_ARTIFACTS}
    ]
    if EventInspectSection.KEYFRAMES in requested:
        delivered_fields.append(DisclosureField.KEYFRAMES)
    if _active_capture_sections_requested(tuple(requested)):
        delivered_fields.append(DisclosureField.ACTIVE_CAPTURE)
    if EventInspectSection.SCREENSHOT_REF in requested:
        delivered_fields.append(DisclosureField.RAW_ARTIFACT_REFS)
    if EventInspectSection.ARTIFACT_METADATA in requested:
        delivered_fields.append(DisclosureField.HIDDEN_ARTIFACTS)
    details = dict(disclosure_decision.details)
    if EventInspectSection.SCREENSHOT_REF not in requested:
        details["raw_ref_count"] = 0
    if EventInspectSection.KEYFRAMES not in requested:
        details.pop("keyframe_count", None)
    if not _active_capture_sections_requested(tuple(requested)):
        details.pop("active_capture_session_id", None)
        details.pop("active_capture_safe_text_block_count", None)
    if EventInspectSection.ARTIFACT_METADATA not in requested:
        details["hidden_artifact_count"] = 0
    return disclosure_decision.model_copy(
        update={
            "delivered_fields": tuple(dict.fromkeys(delivered_fields)),
            "hidden_artifacts": (
                disclosure_decision.hidden_artifacts if EventInspectSection.ARTIFACT_METADATA in requested else ()
            ),
            "details": details,
        }
    )


def _with_runtime_appshot_status(inspect_view: EventInspectView, *, visual_ocr_status: str) -> EventInspectView:
    if inspect_view.system_appshot is None:
        return inspect_view
    try:
        status = VisualOCRStatus(visual_ocr_status)
    except ValueError:
        return inspect_view
    quality = inspect_view.system_appshot.quality.model_copy(
        update={
            "diagnostics": tuple(
                dict.fromkeys((*inspect_view.system_appshot.quality.diagnostics, f"ocr_status_{status.value}"))
            )
        }
    )
    return inspect_view.model_copy(
        update={
            "system_appshot": inspect_view.system_appshot.model_copy(
                update={"ocr_job_status": status, "quality": quality}
            )
        }
    )


def _unknown_inspect_views(inspect_views: str) -> set[str]:
    requested = {item.strip() for item in inspect_views.split(",") if item.strip()}
    return requested.difference(section.value for section in EventInspectSection)


def _parse_inspect_sections(inspect_views: str) -> tuple[EventInspectSection, ...]:
    requested = tuple(EventInspectSection(item.strip()) for item in inspect_views.split(",") if item.strip())
    return requested or _default_inspect_sections()


def _default_inspect_sections() -> tuple[EventInspectSection, ...]:
    return (EventInspectSection.SELECTION_TEXT, EventInspectSection.EVIDENCE_REFS)


def _active_capture_sections_requested(inspect_sections: tuple[EventInspectSection, ...]) -> bool:
    requested = set(inspect_sections)
    return bool(
        requested.intersection(
            {
                EventInspectSection.ACTIVE_CAPTURE_SUMMARY,
                EventInspectSection.RECORDING_TIMELINE,
                EventInspectSection.VIDEO_REF,
                EventInspectSection.HUMAN_DEMO_SUMMARY,
            }
        )
    )


@router.delete("/{event_id}")
def _delete_event(event_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.DELETE_EVENT,
        resource_type="event",
        resource_id=event_id,
        reason="delete context event",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    event = container.repositories.events.get(event_id)
    if event is None:
        envelope = container.responses.error(ErrorCode.NOT_FOUND, "Event not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    try:
        deleted = container.events.mark_deleted(event)
        container.indexing.delete_event(event_id)
    except Exception:
        logger.exception("failed to delete context event", extra={"request_id": request_id, "event_id": event_id})
        audit_id = route_support.audit_action(
            request=request,
            request_id=request_id,
            actor=actor,
            action=AuditAction.EVENT_DELETED,
            resource_type="event",
            resource_id=event_id,
            policy_decision_id=decision_id,
            success=False,
        )
        envelope = container.responses.error(
            ErrorCode.INTERNAL_ERROR,
            "Failed to delete event",
            request_id=request_id,
            audit_id=audit_id,
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=envelope.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_DELETED,
        resource_type="event",
        resource_id=event_id,
        policy_decision_id=decision_id,
        success=True,
    )
    envelope = container.responses.success(
        safe_public_payload(deleted, _os_window_context=_is_os_window_event(deleted)),
        request_id=request_id,
        audit_id=audit_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))
