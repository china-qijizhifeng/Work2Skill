"""Ports for publishing context share packages to external targets."""

from __future__ import annotations

from typing import Protocol

from packages.contracts import ExternalShareTarget, ShareRevision, ShareTargetKind


class SharePublisher(Protocol):
    """Adapter boundary implemented by Feishu, local bundle, and future targets."""

    target: ShareTargetKind

    def publish(self, *, share_id: str, revision: ShareRevision, html: bytes) -> ExternalShareTarget:
        """Publish one immutable share revision and return durable target status.

        Args:
            share_id: Share whose revision is being published.
            revision: Immutable revision metadata and package manifest.
            html: Human-readable HTML package bytes.

        Returns:
            External target state, including provider URL or failure details.
        """
        ...

    def revoke(self, *, target: ExternalShareTarget) -> ExternalShareTarget:
        """Best-effort revoke for an external target.

        Args:
            target: Previously published external target record.

        Returns:
            Updated external target with revoked or failure status.
        """
        ...


class SharePublisherRegistry:
    """Typed registry for share publisher adapters."""

    def __init__(self, publishers: tuple[SharePublisher, ...] = ()) -> None:
        self._publishers: dict[ShareTargetKind, SharePublisher] = {}
        for publisher in publishers:
            if publisher.target in self._publishers:
                raise ValueError(f"Duplicate share publisher target: {publisher.target.value}")
            self._publishers[publisher.target] = publisher

    def get(self, target: ShareTargetKind) -> SharePublisher | None:
        """Return the publisher for a target if it is configured.

        Args:
            target: External target kind requested by the share.

        Returns:
            Matching publisher adapter, or None when unsupported.
        """

        return self._publishers.get(target)
