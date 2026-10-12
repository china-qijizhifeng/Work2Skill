"""Replay filtering for current event visibility."""

from __future__ import annotations

from packages.contracts import AgentRunReplay, DeliveredContextSnapshot, EventStatus
from packages.storage.event_repository import ContextEventRepository

from .snapshots import DeliveredSnapshotBuilder


class AgentRunReplayFilter:
    """Hide delivered text for events no longer visible to the caller."""

    def __init__(self, *, events: ContextEventRepository, snapshots: DeliveredSnapshotBuilder) -> None:
        """Create a replay filter.

        Args:
            events: Event repository used for current lifecycle checks.
            snapshots: Snapshot helper used for stable tombstone hashes.
        """

        self.events = events
        self.snapshots = snapshots

    def filter(self, replay: AgentRunReplay) -> AgentRunReplay:
        """Return replay with deleted/restricted events replaced by tombstones.

        Args:
            replay: Replay rows loaded from the immutable run ledger.

        Returns:
            A replay safe for user-facing reads under current event visibility.
        """

        restricted = {
            item.event_id for item in replay.snapshot_items if item.event_id and not self._event_visible(item.event_id)
        }
        if not restricted:
            return replay
        snapshots = tuple(self._tombstone_snapshot(snapshot, restricted) for snapshot in replay.snapshots)
        items = tuple(
            (
                item.model_copy(
                    update={
                        "evidence_id": None,
                        "artifact_id": None,
                        "citation_id": None,
                        "text_hash": None,
                        "metadata": {"redacted": True, "reason": "event_not_visible"},
                    }
                )
                if item.event_id in restricted
                else item
            )
            for item in replay.snapshot_items
        )
        return replay.model_copy(update={"snapshots": snapshots, "snapshot_items": items})

    def _event_visible(self, event_id: str) -> bool:
        event = self.events.get(event_id)
        return event is not None and event.status not in {EventStatus.DELETED, EventStatus.RESTRICTED}

    def _tombstone_snapshot(
        self, snapshot: DeliveredContextSnapshot, restricted_event_ids: set[str]
    ) -> DeliveredContextSnapshot:
        if not self._payload_mentions_event(snapshot.payload_json, restricted_event_ids):
            return snapshot
        payload = {
            "redacted": True,
            "reason": "event_not_visible",
            "restricted_event_ids": sorted(restricted_event_ids),
            "original_payload_hash": snapshot.payload_hash,
        }
        return snapshot.model_copy(
            update={
                "payload_json": payload,
                "delivered_fields": tuple(payload.keys()),
                "payload_hash": self.snapshots.hash_json(payload),
                "byte_size": len(self.snapshots.json_bytes(payload)),
            }
        )

    def _payload_mentions_event(self, value: object, restricted_event_ids: set[str]) -> bool:
        if isinstance(value, dict):
            event_id = value.get("event_id")
            if isinstance(event_id, str) and event_id in restricted_event_ids:
                return True
            return any(self._payload_mentions_event(nested, restricted_event_ids) for nested in value.values())
        if isinstance(value, list):
            return any(self._payload_mentions_event(nested, restricted_event_ids) for nested in value)
        return False
