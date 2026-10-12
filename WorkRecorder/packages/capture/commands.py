"""Application service for daemon-to-provider collect commands."""

from __future__ import annotations

from packages.contracts import CollectEvidenceCommand, CollectEvidenceResult, DetectedSurface, EvidenceKind
from packages.providers.sessions import ProviderSessionService


class ProviderCommandService:
    """Send typed capture-time commands to registered provider sessions."""

    def __init__(self, *, sessions: ProviderSessionService) -> None:
        """Create the command service."""

        self.sessions = sessions

    async def collect(
        self,
        *,
        command: CollectEvidenceCommand,
        surface: DetectedSurface | None,
        evidence_kind: EvidenceKind,
    ) -> CollectEvidenceResult:
        """Send a collect command and return the provider's typed result.

        Args:
            command: Typed provider command envelope for this capture attempt.
            surface: Detected surface the provider should collect from, if any.
            evidence_kind: Primary evidence kind expected from the provider.

        Returns:
            Provider command result with evidence or typed failure diagnostics.
        """

        return await self.sessions.collect(
            command=command,
            surface=surface,
            evidence_kind=evidence_kind,
            timeout_seconds=max(command.deadline_ms / 1000, 0.1),
        )
