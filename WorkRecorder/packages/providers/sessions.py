"""In-memory provider session and command bus for local capture providers."""

from __future__ import annotations

import logging
from threading import RLock

from packages.contracts import (
    CollectEvidenceCommand,
    CollectEvidenceResult,
    DetectedSurface,
    EvidenceKind,
    ProviderCapability,
    ProviderCommandStatus,
    ProviderHeartbeat,
    ProviderSessionRef,
    ProviderSessionRegistration,
)
from packages.shared.time import Clock

from .session_internals import _ProviderSessionInternals
from .session_state import PendingProviderCommand, ProviderSessionState, ProviderWebSocket

logger = logging.getLogger(__name__)


class ProviderSessionService(_ProviderSessionInternals):
    """Track local provider command sessions and route collect commands."""

    def __init__(self, *, clock: Clock) -> None:
        """Create an empty provider session registry."""

        self.clock = clock
        self._sessions: dict[str, ProviderSessionState] = {}
        self._pending: dict[str, PendingProviderCommand] = {}
        self._lock = RLock()

    async def register(
        self, *, websocket: ProviderWebSocket, registration: ProviderSessionRegistration
    ) -> ProviderSessionRef:
        """Register or replace one provider session.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        state = ProviderSessionState(
            registration=registration,
            websocket=websocket,
            last_seen_at=self.clock.now(),
        )
        with self._lock:
            self._sessions[registration.provider_session_id] = state
        logger.info(
            "provider session registered provider_key=%s session_id=%s kind=%s capabilities=%s has_tab=%s",
            registration.provider_key,
            registration.provider_session_id,
            registration.provider_kind,
            len(registration.capabilities),
            registration.tab is not None,
            extra={
                "provider_key": registration.provider_key,
                "session_id": registration.provider_session_id,
                "provider_kind": registration.provider_kind,
                "app_name": registration.app_name,
                "capability_count": len(registration.capabilities),
                "has_tab": registration.tab is not None,
            },
        )
        return state.ref()

    async def unregister(self, provider_session_id: str, *, websocket: ProviderWebSocket | None = None) -> None:
        """Remove one provider session and fail pending commands for it.

        Args:
            See the typed signature for the accepted parameters and validation boundary."""

        with self._lock:
            state = self._sessions.get(provider_session_id)
            if state is not None and websocket is not None and state.websocket is not websocket:
                logger.info(
                    "provider session unregister ignored for stale socket provider_key=%s session_id=%s",
                    state.registration.provider_key,
                    provider_session_id,
                    extra={"provider_key": state.registration.provider_key, "session_id": provider_session_id},
                )
                return
            state = self._sessions.pop(provider_session_id, None)
            pending = tuple(
                command
                for command in self._pending.values()
                if command.provider_session_id == provider_session_id and not command.future.done()
            )
        if state is None:
            return
        logger.info(
            "provider session unregistered provider_key=%s session_id=%s",
            state.registration.provider_key,
            provider_session_id,
            extra={"provider_key": state.registration.provider_key, "session_id": provider_session_id},
        )
        for command in pending:
            command.future.set_result(
                self._failed_result(
                    command=command.command,
                    evidence_kind=command.evidence_kind,
                    status=ProviderCommandStatus.FAILED,
                    error_message="Provider session disconnected",
                )
            )

    async def heartbeat(
        self,
        heartbeat: ProviderHeartbeat,
        *,
        provider_key: str | None = None,
        provider_session_id: str | None = None,
    ) -> ProviderSessionRef | None:
        """Refresh one provider session without accepting evidence.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        if provider_key is not None and heartbeat.provider_key != provider_key:
            logger.warning(
                "provider heartbeat rejected for wrong provider_key expected_provider_key=%s actual_provider_key=%s session_id=%s",
                provider_key,
                heartbeat.provider_key,
                provider_session_id or heartbeat.provider_session_id,
                extra={
                    "expected_provider_key": provider_key,
                    "actual_provider_key": heartbeat.provider_key,
                    "provider_session_id": provider_session_id or heartbeat.provider_session_id,
                },
            )
            return None
        if provider_session_id is not None and heartbeat.provider_session_id != provider_session_id:
            logger.warning(
                "provider heartbeat rejected for wrong session expected_session_id=%s actual_session_id=%s provider_key=%s",
                provider_session_id,
                heartbeat.provider_session_id,
                heartbeat.provider_key,
                extra={
                    "expected_session_id": provider_session_id,
                    "actual_session_id": heartbeat.provider_session_id,
                    "provider_key": heartbeat.provider_key,
                },
            )
            return None
        with self._lock:
            state = self._sessions.get(heartbeat.provider_session_id)
            if state is None:
                return None
            if state.registration.provider_key != heartbeat.provider_key:
                logger.warning(
                    "provider heartbeat rejected for mismatched registered provider_key expected_provider_key=%s actual_provider_key=%s session_id=%s",
                    state.registration.provider_key,
                    heartbeat.provider_key,
                    heartbeat.provider_session_id,
                    extra={
                        "expected_provider_key": state.registration.provider_key,
                        "actual_provider_key": heartbeat.provider_key,
                        "provider_session_id": heartbeat.provider_session_id,
                    },
                )
                return None
            update: dict[str, object] = {}
            if heartbeat.tab is not None:
                update["tab"] = heartbeat.tab
            if heartbeat.viewport is not None:
                update["viewport"] = heartbeat.viewport
            if heartbeat.window is not None:
                update["window"] = heartbeat.window
            if heartbeat.metadata:
                update["metadata"] = {**state.registration.metadata, **heartbeat.metadata}
            if update:
                state.registration = state.registration.model_copy(update=update)
            state.last_seen_at = self.clock.now()
            return state.ref()

    async def handle_collect_result(self, result: CollectEvidenceResult, *, provider_session_id: str) -> None:
        """Attach a provider result to the pending command future.

        Args:
            See the typed signature for the accepted parameters and validation boundary."""

        pending = self._pending.get(result.command_id)
        if pending is None:
            logger.warning(
                "provider returned result for unknown command command_id=%s provider_session_id=%s",
                result.command_id,
                provider_session_id,
                extra={"command_id": result.command_id, "provider_session_id": provider_session_id},
            )
            return
        if pending.provider_session_id != provider_session_id:
            logger.warning(
                "provider returned result on the wrong session command_id=%s expected_session_id=%s actual_session_id=%s",
                result.command_id,
                pending.provider_session_id,
                provider_session_id,
                extra={
                    "command_id": result.command_id,
                    "expected_session_id": pending.provider_session_id,
                    "actual_session_id": provider_session_id,
                },
            )
            return
        if pending.provider_key != result.provider_key or pending.evidence_kind != result.evidence_kind:
            logger.warning(
                "provider returned result with mismatched identity command_id=%s expected_provider_key=%s actual_provider_key=%s expected_evidence_kind=%s actual_evidence_kind=%s",
                result.command_id,
                pending.provider_key,
                result.provider_key,
                pending.evidence_kind,
                result.evidence_kind,
                extra={
                    "command_id": result.command_id,
                    "expected_provider_key": pending.provider_key,
                    "actual_provider_key": result.provider_key,
                    "expected_evidence_kind": pending.evidence_kind,
                    "actual_evidence_kind": result.evidence_kind,
                },
            )
            return
        target_mismatch = self._target_mismatch(pending, result)
        if target_mismatch is not None:
            result_source_binding = self._source_binding_for_result(result)
            actual_tab_id = result_source_binding.source_ref.external_id if result_source_binding is not None else None
            logger.warning(
                "provider returned result for wrong routed target command_id=%s provider_key=%s session_id=%s reason=%s expected_tab_id=%s actual_tab_id=%s expected_window_id=%s actual_window_id=%s",
                result.command_id,
                pending.provider_key,
                provider_session_id,
                target_mismatch,
                pending.expected_tab_id,
                actual_tab_id,
                pending.expected_window_id,
                result.diagnostics.get("actual_window_id"),
                extra={
                    "command_id": result.command_id,
                    "provider_key": pending.provider_key,
                    "provider_session_id": provider_session_id,
                    "reason": target_mismatch,
                    "expected_tab_id": pending.expected_tab_id,
                    "actual_tab_id": actual_tab_id,
                    "expected_window_id": pending.expected_window_id,
                    "actual_window_id": result.diagnostics.get("actual_window_id"),
                },
            )
            return
        authoritative = result.model_copy(update={"provider_session_id": provider_session_id})
        if not pending.future.done():
            evidence_count = len(result.evidence_bundle.evidence) if result.evidence_bundle is not None else 0
            logger.info(
                "provider command result accepted provider_key=%s session_id=%s command_id=%s status=%s evidence_kind=%s evidence=%s",
                pending.provider_key,
                provider_session_id,
                result.command_id,
                result.status,
                result.evidence_kind,
                evidence_count,
                extra={
                    "provider_key": pending.provider_key,
                    "provider_session_id": provider_session_id,
                    "command_id": result.command_id,
                    "status": result.status,
                    "evidence_kind": result.evidence_kind,
                    "evidence_count": evidence_count,
                },
            )
            pending.future.set_result(authoritative)

    async def list_sessions(self) -> tuple[ProviderSessionRef, ...]:
        """Return all non-expired sessions.

        Returns:
            The typed result described by the method contract."""

        await self.prune_expired()
        with self._lock:
            return tuple(state.ref() for state in self._sessions.values())

    async def freshness_score(
        self,
        *,
        provider_key: str,
        surface: DetectedSurface | None,
        required_capabilities: tuple[ProviderCapability, ...] = (),
    ) -> float:
        """Return a zero-to-one liveness score for a provider/surface pair.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        await self.prune_expired()
        with self._lock:
            sessions = [
                state
                for state in self._sessions.values()
                if state.registration.provider_key == provider_key
                and self._matches_surface(state, surface)
                and self._has_capabilities(state, required_capabilities)
            ]
        if not sessions:
            return 0.0
        return max(self._freshness_for_state(state) for state in sessions)

    async def collect(
        self,
        *,
        command: CollectEvidenceCommand,
        surface: DetectedSurface | None,
        evidence_kind: EvidenceKind,
        timeout_seconds: float,
    ) -> CollectEvidenceResult:
        """Send one collect command and wait for the provider result.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        state = await self._best_session(
            provider_key=command.provider_key,
            surface=surface,
            required_capabilities=command.required_capabilities,
        )
        if state is None:
            return self._no_eligible_session_result(command=command, surface=surface, evidence_kind=evidence_kind)
        command = self._command_for_session(command, state)
        return await self._dispatch_collect_command(
            command=command,
            state=state,
            surface=surface,
            evidence_kind=evidence_kind,
            timeout_seconds=timeout_seconds,
        )

    async def prune_expired(self) -> None:
        """Drop sessions whose heartbeat TTL has elapsed."""

        now = self.clock.now()
        with self._lock:
            expired = [session_id for session_id, state in self._sessions.items() if state.expires_at() <= now]
            for session_id in expired:
                self._sessions.pop(session_id, None)
