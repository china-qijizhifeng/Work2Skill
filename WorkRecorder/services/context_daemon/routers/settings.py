"""Workbench settings routes for local feature configuration.

Settings routes expose user-editable daemon preferences to the macOS app while
keeping secrets behind the daemon-side secret store. Visual OCR configuration
uses this module for masked reads, controlled updates, and provider probes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from packages.contracts import AccessScope, ErrorCode, ShortcutSettings, VisualOCRSettingsUpdate
from packages.settings.vm_a11y import VMA11yProbeSettingsUpdate

from ..dependencies import route_support
from .validation_errors import safe_validation_error_details

router = APIRouter(prefix="/v1/settings", tags=["settings"])
logger = logging.getLogger(__name__)


@router.get("/shortcuts")
def _get_shortcut_settings(request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="settings",
        reason="read shortcut settings",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    response = container.responses.success(container.shortcut_settings.get(), request_id=request_id)
    return JSONResponse(content=response.model_dump(mode="json"))


@router.put("/shortcuts")
async def _put_shortcut_settings(request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.MANAGE_LOCAL_SETTINGS,
        resource_type="settings",
        reason="update shortcut settings",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    try:
        body: object = await request.json()
    except ValueError:
        response = container.responses.error(
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid shortcut settings payload",
            request_id=request_id,
            details={"errors": "request body must be valid JSON"},
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=response.model_dump(mode="json"))
    try:
        parsed = ShortcutSettings.model_validate(body)
    except ValidationError as exc:
        response = container.responses.error(
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid shortcut settings payload",
            request_id=request_id,
            details=safe_validation_error_details(exc),
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=response.model_dump(mode="json"))
    try:
        settings = container.shortcut_settings.update(parsed)
    except Exception:
        logger.exception("failed to update shortcut settings", extra={"request_id": request_id})
        response = container.responses.error(
            ErrorCode.INTERNAL_ERROR,
            "Failed to update shortcut settings",
            request_id=request_id,
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=response.model_dump(mode="json"))
    response = container.responses.success(settings, request_id=request_id)
    return JSONResponse(content=response.model_dump(mode="json"))


@router.get("/visual-ocr")
def _get_visual_ocr_settings(request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="settings",
        reason="read visual OCR settings",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    response = container.responses.success(container.visual_ocr_settings.public(), request_id=request_id)
    return JSONResponse(content=response.model_dump(mode="json"))


@router.put("/visual-ocr")
def _put_visual_ocr_settings(body: VisualOCRSettingsUpdate, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.MANAGE_LOCAL_SETTINGS,
        resource_type="settings",
        reason="update visual OCR settings",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    try:
        settings = container.visual_ocr_settings.update(body)
    except Exception:
        logger.exception("failed to update visual OCR settings", extra={"request_id": request_id})
        response = container.responses.error(
            ErrorCode.INTERNAL_ERROR,
            "Failed to update visual OCR settings",
            request_id=request_id,
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=response.model_dump(mode="json"))
    response = container.responses.success(settings, request_id=request_id)
    return JSONResponse(content=response.model_dump(mode="json"))


@router.get("/vm-a11y-probe")
def _get_vm_a11y_probe_settings(request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="settings",
        reason="read VM accessibility probe settings",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    response = container.responses.success(container.vm_a11y_probe_settings.public(), request_id=request_id)
    return JSONResponse(content=response.model_dump(mode="json"))


@router.put("/vm-a11y-probe")
def _put_vm_a11y_probe_settings(body: VMA11yProbeSettingsUpdate, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.MANAGE_LOCAL_SETTINGS,
        resource_type="settings",
        reason="update VM accessibility probe settings",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    try:
        settings = container.vm_a11y_probe_settings.update(body)
    except Exception:
        logger.exception("failed to update VM accessibility probe settings", extra={"request_id": request_id})
        response = container.responses.error(
            ErrorCode.INTERNAL_ERROR,
            "Failed to update VM accessibility probe settings",
            request_id=request_id,
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=response.model_dump(mode="json"))
    response = container.responses.success(settings, request_id=request_id)
    return JSONResponse(content=response.model_dump(mode="json"))


@router.post("/visual-ocr/test")
async def _test_visual_ocr_settings(request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.MANAGE_LOCAL_SETTINGS,
        resource_type="settings",
        reason="test visual OCR settings",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    settings = container.visual_ocr_settings.public()
    probe_ok = False
    probe_message = "Provider probe failed. Check endpoint, key, model, or local runtime."
    try:
        await container.visual_ocr.service.test_provider()
        probe_ok = True
        probe_message = "Provider connection and schema response succeeded."
    except Exception as exc:
        logger.exception("visual OCR provider probe failed", extra={"request_id": request_id})
        probe_message = str(exc)[:160] or probe_message
    response = container.responses.success(
        {
            "ok": probe_ok,
            "api_key_configured": settings.api_key_configured,
            "provider_kind": settings.provider_kind.value,
            "api_style": settings.api_style.value,
            "base_url": settings.base_url,
            "model": settings.model,
            "message": probe_message,
        },
        request_id=request_id,
    )
    return JSONResponse(content=response.model_dump(mode="json"))
