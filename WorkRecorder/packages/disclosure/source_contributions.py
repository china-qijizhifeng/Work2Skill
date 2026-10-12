"""Build user-facing source/provider contribution rows for event inspect."""

from __future__ import annotations

from packages.contracts import (
    ContextEvent,
    EventSourceContributionView,
    ProviderCaptureOutcomeStatus,
    ProviderKind,
    ProviderRouteRole,
)
from packages.storage.ledger_repository import CaptureLedgerRepository


class EventSourceContributionBuilder:
    """Convert capture envelope routing data into inspect-view source rows.

    Attributes:
        ledger: Capture ledger used to load the event's auditable envelope.
    """

    def __init__(self, ledger: CaptureLedgerRepository) -> None:
        """Create a source contribution builder.

        Args:
            ledger: Repository that returns the persisted capture envelope.
        """

        self.ledger = ledger

    def build(self, event: ContextEvent) -> tuple[EventSourceContributionView, ...]:
        """Return primary, secondary, and system contribution rows.

        Args:
            event: Context event being inspected.

        Returns:
            Rows suitable for disclosure-safe event inspection. The primary
            source binding is used as display fallback, while provider outcome
            status and evidence counts come from the auditable envelope.
        """

        envelope = self.ledger.get_envelope_by_event_id(event.event_id)
        primary_surface_id = envelope.route_plan.primary_surface_id if envelope is not None else None
        surface_details: dict[str, dict[str, object]] = {}
        if envelope is not None:
            for index, surface in enumerate(envelope.detected_surfaces, start=1):
                surface_details[surface.surface_id] = {
                    "rank": index,
                    "source_kind": surface.kind,
                    "app_name": surface.app_name,
                    "title": surface.title,
                    "overlap_ratio": surface.overlap_ratio,
                    "confidence": surface.confidence,
                }

        rows = [self._primary_row(event=event, primary_surface_id=primary_surface_id, surface_details=surface_details)]
        if envelope is None:
            return tuple(rows)

        route_targets = {route.route_id: route.target for route in envelope.route_plan.routes if route.route_id}
        seen = {self._row_key(rows[0])}
        for outcome in envelope.provider_outcomes:
            target = route_targets.get(outcome.route_id or "", {})
            details = surface_details.get(outcome.surface_id or "", {})
            row = EventSourceContributionView(
                role=outcome.role,
                app_name=_string_or_none(target.get("app_name")) or _string_or_none(details.get("app_name")),
                title=_string_or_none(target.get("title")) or _string_or_none(details.get("title")),
                source_kind=_string_or_none(target.get("surface_kind")) or _string_or_none(details.get("source_kind")),
                provider_key=outcome.provider_key,
                provider_kind=outcome.provider_kind,
                status=outcome.status,
                surface_id=outcome.surface_id,
                rank=_int_or_none(details.get("rank")),
                overlap_ratio=_float_or_none(target.get("overlap_ratio"))
                or _float_or_none(details.get("overlap_ratio")),
                confidence=_float_or_none(target.get("confidence")) or _float_or_none(details.get("confidence")),
                evidence_count=len(outcome.evidence_ids),
                reason_code=outcome.reason_code,
            )
            key = self._row_key(row)
            if key in seen:
                rows = self._merge_row(rows, row, key)
                continue
            rows.append(row)
            seen.add(key)
        return tuple(rows)

    def _primary_row(
        self,
        *,
        event: ContextEvent,
        primary_surface_id: str | None,
        surface_details: dict[str, dict[str, object]],
    ) -> EventSourceContributionView:
        primary_details = surface_details.get(primary_surface_id or "", {})
        binding_provider_key = event.source_binding.provider_key
        binding_is_system = binding_provider_key is not None and binding_provider_key.startswith("system.")
        return EventSourceContributionView(
            role=ProviderRouteRole.PRIMARY_SOURCE,
            app_name=event.source_binding.source_ref.app_name,
            title=event.source_binding.source_ref.title,
            source_kind=_string_or_none(primary_details.get("source_kind")),
            provider_key=event.source_binding.provider_key,
            provider_kind=(
                ProviderKind.SYSTEM_EVIDENCE
                if binding_is_system
                else ProviderKind.SOURCE if event.source_binding.provider_key else None
            ),
            status=(
                None if binding_is_system else ProviderCaptureOutcomeStatus.SUCCEEDED if binding_provider_key else None
            ),
            surface_id=primary_surface_id,
            rank=_int_or_none(primary_details.get("rank")),
            overlap_ratio=_float_or_none(primary_details.get("overlap_ratio")),
            confidence=_float_or_none(primary_details.get("confidence")),
            evidence_count=0,
            reason_code="system_source_binding" if binding_is_system else None,
        )

    def _row_key(self, row: EventSourceContributionView) -> tuple[object, ...]:
        return (row.role, row.surface_id, row.provider_key)

    def _merge_row(
        self,
        rows: list[EventSourceContributionView],
        incoming: EventSourceContributionView,
        key: tuple[object, ...],
    ) -> list[EventSourceContributionView]:
        for index, row in enumerate(rows):
            if self._row_key(row) != key:
                continue
            rows[index] = row.model_copy(
                update={
                    "status": incoming.status or row.status,
                    "provider_kind": incoming.provider_kind or row.provider_kind,
                    "evidence_count": max(row.evidence_count, incoming.evidence_count),
                    "reason_code": incoming.reason_code or row.reason_code,
                    "source_kind": incoming.source_kind or row.source_kind,
                    "overlap_ratio": (
                        incoming.overlap_ratio if incoming.overlap_ratio is not None else row.overlap_ratio
                    ),
                    "confidence": incoming.confidence if incoming.confidence is not None else row.confidence,
                }
            )
            break
        return rows


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
