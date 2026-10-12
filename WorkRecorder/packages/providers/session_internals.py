"""Private provider-session routing and command dispatch helpers."""

from __future__ import annotations

import asyncio
import logging
from threading import RLock

from packages.contracts import (
    BoundingBox,
    CollectEvidenceCommand,
    CollectEvidenceResult,
    DetectedSurface,
    EvidenceKind,
    ProviderCapability,
    ProviderCommandEnvelope,
    ProviderCommandStatus,
    ProviderCommandType,
    SourceBinding,
)
from packages.shared.time import Clock

from .session_state import PendingProviderCommand, ProviderSessionState

logger = logging.getLogger(__name__)


class _ProviderSessionInternals:
    """Private routing, freshness, and command dispatch helpers for sessions."""

    clock: Clock
    _sessions: dict[str, ProviderSessionState]
    _pending: dict[str, PendingProviderCommand]
    _lock: RLock

    async def prune_expired(self) -> None:
        """Drop expired sessions in concrete session services.

        Raises:
            NotImplementedError: The concrete session service must provide storage access.
        """

        raise NotImplementedError

    async def _best_session(
        self,
        *,
        provider_key: str,
        surface: DetectedSurface | None,
        required_capabilities: tuple[ProviderCapability, ...],
    ) -> ProviderSessionState | None:
        await self.prune_expired()
        with self._lock:
            candidates = [
                state
                for state in self._sessions.values()
                if state.registration.provider_key == provider_key
                and self._matches_surface(state, surface)
                and self._has_capabilities(state, required_capabilities)
            ]
        if not candidates:
            return None
        return max(candidates, key=self._freshness_for_state)

    def _matches_surface(self, state: ProviderSessionState, surface: DetectedSurface | None) -> bool:
        if surface is None:
            return True
        registration = state.registration
        if registration.provider_key.startswith("web.") and registration.tab is None:
            return False
        if (
            registration.provider_key.startswith("web.")
            and registration.tab is not None
            and surface.title
            and not self._browser_title_matches_surface(
                registration.tab.title,
                surface.title,
                app_name=surface.app_name,
            )
        ):
            return False
        if registration.process_id is not None and surface.process_id is not None:
            return registration.process_id == surface.process_id
        if (
            registration.window is not None
            and registration.window.native_window_id is not None
            and surface.window_id is not None
        ):
            return registration.window.native_window_id == surface.window_id
        if registration.window_id is not None and surface.window_id is not None:
            return registration.window_id == surface.window_id
        if (
            registration.window is not None
            and registration.window.screen_rect is not None
            and surface.frame is not None
        ):
            if registration.window.screen_rect.coordinate_space != surface.frame.coordinate_space:
                return False
            return self._overlap_ratio(registration.window.screen_rect, surface.frame) > 0.15
        if registration.app_name and surface.app_name:
            return (
                registration.app_name.lower() in surface.app_name.lower()
                or surface.app_name.lower() in registration.app_name.lower()
            )
        return False

    def _browser_title_matches_surface(
        self, tab_title: str, surface_title: str, *, app_name: str | None = None
    ) -> bool:
        normalized_tab = self._normalized_title(tab_title)
        normalized_surface = self._normalized_title(surface_title)
        if not normalized_tab or not normalized_surface:
            return True
        normalized_app = self._normalized_title(app_name or "")
        if normalized_app and normalized_surface == normalized_app:
            return False
        surface_without_app = self._strip_browser_title_suffix(normalized_surface, normalized_app)
        if not surface_without_app:
            return False
        return (
            normalized_tab in normalized_surface
            or normalized_surface in normalized_tab
            or normalized_tab in surface_without_app
            or surface_without_app in normalized_tab
        )

    def _normalized_title(self, value: str) -> str:
        return " ".join(value.casefold().split())

    def _strip_browser_title_suffix(self, title: str, app_name: str) -> str:
        suffixes = [app_name] if app_name else []
        suffixes.extend(("google chrome", "chrome", "microsoft edge", "edge", "arc"))
        for suffix in suffixes:
            if not suffix:
                continue
            for separator in (" - ", " — ", " – ", " | "):
                marker = f"{separator}{suffix}"
                if title.endswith(marker):
                    return title[: -len(marker)].strip()
        return title

    def _has_capabilities(
        self, state: ProviderSessionState, required_capabilities: tuple[ProviderCapability, ...]
    ) -> bool:
        if not required_capabilities:
            return True
        actual = set(state.registration.capabilities)
        return all(capability in actual for capability in required_capabilities)

    def _command_for_session(
        self, command: CollectEvidenceCommand, state: ProviderSessionState
    ) -> CollectEvidenceCommand:
        metadata = dict(command.metadata)
        if state.registration.tab is not None:
            metadata["target_tab_id"] = state.registration.tab.tab_id
            metadata["target_window_id"] = state.registration.tab.window_id
            metadata["target_url"] = state.registration.tab.url
        elif state.registration.window_id is not None:
            metadata["target_window_id"] = state.registration.window_id
        elif state.registration.window is not None:
            metadata["target_window_id"] = state.registration.window.window_id
        metadata["target_provider_session_id"] = state.registration.provider_session_id
        return command.model_copy(update={"metadata": metadata})

    def _target_mismatch(self, pending: PendingProviderCommand, result: CollectEvidenceResult) -> str | None:
        if pending.expected_tab_id is not None:
            source_binding = self._source_binding_for_result(result)
            actual_tab_id = source_binding.source_ref.external_id if source_binding else None
            if actual_tab_id != pending.expected_tab_id:
                return "tab_id_mismatch"
        if pending.expected_window_id is not None:
            actual_window_id = result.diagnostics.get("actual_window_id")
            if actual_window_id is None:
                return "window_id_missing"
            if str(actual_window_id) != pending.expected_window_id:
                return "window_id_mismatch"
        return None

    def _source_binding_for_result(self, result: CollectEvidenceResult) -> SourceBinding | None:
        return result.source_binding or (
            result.evidence_bundle.source_binding if result.evidence_bundle is not None else None
        )

    def _overlap_ratio(self, lhs: BoundingBox, rhs: BoundingBox) -> float:
        left = max(lhs.x, rhs.x)
        top = max(lhs.y, rhs.y)
        right = min(lhs.x + lhs.width, rhs.x + rhs.width)
        bottom = min(lhs.y + lhs.height, rhs.y + rhs.height)
        if right <= left or bottom <= top:
            return 0.0
        intersection = (right - left) * (bottom - top)
        area = max(float(rhs.width * rhs.height), 1.0)
        return intersection / area

    def _freshness_for_state(self, state: ProviderSessionState) -> float:
        now = self.clock.now()
        ttl_seconds = max(state.registration.ttl_ms / 1000, 1.0)
        age = max((now - state.last_seen_at).total_seconds(), 0.0)
        return max(0.0, min(1.0, 1.0 - (age / ttl_seconds)))

    def _failed_result(
        self,
        *,
        command: CollectEvidenceCommand,
        evidence_kind: EvidenceKind,
        status: ProviderCommandStatus,
        error_message: str,
    ) -> CollectEvidenceResult:
        return CollectEvidenceResult(
            command_id=command.command_id,
            provider_key=command.provider_key,
            status=status,
            evidence_kind=evidence_kind,
            diagnostics={},
            error_message=error_message,
            completed_at=self.clock.now(),
        )

    def _no_eligible_session_result(
        self,
        *,
        command: CollectEvidenceCommand,
        surface: DetectedSurface | None,
        evidence_kind: EvidenceKind,
    ) -> CollectEvidenceResult:
        logger.warning(
            "provider command has no eligible session provider_key=%s command_id=%s evidence_kind=%s surface_id=%s required_capabilities=%s",
            command.provider_key,
            command.command_id,
            evidence_kind,
            surface.surface_id if surface else None,
            len(command.required_capabilities),
            extra={
                "provider_key": command.provider_key,
                "command_id": command.command_id,
                "evidence_kind": evidence_kind,
                "surface_id": surface.surface_id if surface else None,
                "required_capability_count": len(command.required_capabilities),
            },
        )
        return self._failed_result(
            command=command,
            evidence_kind=evidence_kind,
            status=ProviderCommandStatus.TIMEOUT,
            error_message="No connected provider session",
        )

    async def _dispatch_collect_command(
        self,
        *,
        command: CollectEvidenceCommand,
        state: ProviderSessionState,
        surface: DetectedSurface | None,
        evidence_kind: EvidenceKind,
        timeout_seconds: float,
    ) -> CollectEvidenceResult:
        expected_tab_id = state.registration.tab.tab_id if state.registration.tab is not None else None
        expected_window_id = state.registration.tab.window_id if state.registration.tab is not None else None
        loop = asyncio.get_running_loop()
        future: asyncio.Future[CollectEvidenceResult] = loop.create_future()
        self._pending[command.command_id] = PendingProviderCommand(
            command=command,
            provider_key=command.provider_key,
            provider_session_id=state.registration.provider_session_id,
            evidence_kind=evidence_kind,
            future=future,
            expected_tab_id=expected_tab_id,
            expected_window_id=expected_window_id,
        )
        envelope = ProviderCommandEnvelope(
            message_type=ProviderCommandType.COLLECT_EVIDENCE,
            command=command,
            sent_at=self.clock.now(),
        )
        try:
            logger.info(
                "provider command dispatched provider_key=%s session_id=%s command_id=%s evidence_kind=%s surface_id=%s deadline_ms=%s",
                command.provider_key,
                state.registration.provider_session_id,
                command.command_id,
                evidence_kind,
                surface.surface_id if surface else None,
                command.deadline_ms,
                extra={
                    "provider_key": command.provider_key,
                    "provider_session_id": state.registration.provider_session_id,
                    "command_id": command.command_id,
                    "evidence_kind": evidence_kind,
                    "surface_id": surface.surface_id if surface else None,
                    "deadline_ms": command.deadline_ms,
                },
            )
            await state.websocket.send_text(envelope.model_dump_json())
            result = await asyncio.wait_for(future, timeout=timeout_seconds)
            self._log_collect_success(command=command, state=state, result=result)
            return result
        except TimeoutError:
            logger.warning(
                "provider command timed out provider_key=%s session_id=%s command_id=%s timeout_seconds=%s",
                command.provider_key,
                state.registration.provider_session_id,
                command.command_id,
                timeout_seconds,
                extra={
                    "provider_key": command.provider_key,
                    "provider_session_id": state.registration.provider_session_id,
                    "command_id": command.command_id,
                    "timeout_seconds": timeout_seconds,
                },
            )
            return self._failed_result(
                command=command,
                evidence_kind=evidence_kind,
                status=ProviderCommandStatus.TIMEOUT,
                error_message="Provider command timed out",
            )
        except Exception as exc:
            logger.exception(
                "provider command failed provider_key=%s command_id=%s",
                command.provider_key,
                command.command_id,
                extra={"provider_key": command.provider_key, "command_id": command.command_id},
            )
            return self._failed_result(
                command=command,
                evidence_kind=evidence_kind,
                status=ProviderCommandStatus.FAILED,
                error_message=str(exc),
            )
        finally:
            self._pending.pop(command.command_id, None)

    def _log_collect_success(
        self, *, command: CollectEvidenceCommand, state: ProviderSessionState, result: CollectEvidenceResult
    ) -> None:
        evidence_count = len(result.evidence_bundle.evidence) if result.evidence_bundle is not None else 0
        logger.info(
            "provider command completed provider_key=%s session_id=%s command_id=%s status=%s evidence=%s",
            command.provider_key,
            state.registration.provider_session_id,
            command.command_id,
            result.status,
            evidence_count,
            extra={
                "provider_key": command.provider_key,
                "provider_session_id": state.registration.provider_session_id,
                "command_id": command.command_id,
                "status": result.status,
                "evidence_count": evidence_count,
            },
        )
