"""Runtime state objects for provider WebSocket command sessions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from packages.contracts import (
    CollectEvidenceCommand,
    CollectEvidenceResult,
    EvidenceKind,
    ProviderSessionRef,
    ProviderSessionRegistration,
)


class ProviderWebSocket(Protocol):
    """Minimal WebSocket surface used by the command bus."""

    async def send_text(self, data: str) -> None:
        """Send one text frame.

        Args:
            See the typed signature for the accepted parameters and validation boundary."""
        ...


@dataclass(slots=True)
class ProviderSessionState:
    """Mutable runtime state for one connected provider session.

    Attributes:
        Public fields mirror the dataclass annotations and hold provider/session state."""

    registration: ProviderSessionRegistration
    websocket: ProviderWebSocket
    last_seen_at: datetime

    def expires_at(self) -> datetime:
        """Return the current session expiry timestamp.

        Returns:
            The typed result described by the method contract."""

        return self.last_seen_at + timedelta(milliseconds=self.registration.ttl_ms)

    def ref(self) -> ProviderSessionRef:
        """Return redacted session metadata suitable for diagnostics.

        Returns:
            The typed result described by the method contract."""

        return ProviderSessionRef(
            provider_key=self.registration.provider_key,
            provider_session_id=self.registration.provider_session_id,
            provider_kind=self.registration.provider_kind,
            display_name=self.registration.display_name,
            app_name=self.registration.app_name,
            process_id=self.registration.process_id,
            window_id=self.registration.window_id,
            tab=self.registration.tab,
            capabilities=self.registration.capabilities,
            registered_at=self.registration.registered_at,
            last_seen_at=self.last_seen_at,
            expires_at=self.expires_at(),
            connected=True,
        )


@dataclass(slots=True)
class PendingProviderCommand:
    """Command result slot bound to the session the daemon actually commanded.

    Attributes:
        Public fields mirror the dataclass annotations and hold provider/session state."""

    command: CollectEvidenceCommand
    provider_key: str
    provider_session_id: str
    evidence_kind: EvidenceKind
    future: asyncio.Future[CollectEvidenceResult]
    expected_tab_id: str | None = None
    expected_window_id: str | None = None
