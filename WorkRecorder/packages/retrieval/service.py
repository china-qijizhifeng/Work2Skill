"""Retrieval and bundle services for the P0 skeleton."""

from __future__ import annotations

from packages.artifacts.vault import ArtifactVaultError, LocalArtifactVault
from packages.contracts import (
    ArtifactIngestState,
    ArtifactType,
    BundleRequest,
    ContextBundle,
    ContextBundleItem,
    ContextEvent,
    RedactionState,
    RetrievalQuery,
    SearchResultCard,
)
from packages.disclosure import DisclosurePolicyService
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from packages.storage.artifact_repository import ArtifactRepository
from packages.storage.bundle_repository import ContextBundleRepository
from packages.storage.event_repository import ContextEventRepository
from packages.storage.ledger_repository import CaptureLedgerRepository


class RetrievalService:
    """Provide keyword-only P0 retrieval over event metadata."""

    def __init__(
        self,
        event_repository: ContextEventRepository,
        *,
        artifact_repository: ArtifactRepository | None = None,
        vault: LocalArtifactVault | None = None,
        ledger_repository: CaptureLedgerRepository | None = None,
        disclosure: DisclosurePolicyService,
    ) -> None:
        """Create a retrieval service.

        Args:
            event_repository: Event repository to query.
        """

        self.event_repository = event_repository
        self.artifact_repository = artifact_repository
        self.vault = vault
        self.ledger_repository = ledger_repository
        self.disclosure = disclosure

    def search(self, query: RetrievalQuery) -> tuple[ContextEvent, ...]:
        """Return metadata matches for a query.

        Args:
            query: Typed retrieval query.

        Returns:
            Matching context events. Hybrid mode degrades to keyword in P0.
        """

        normalized = query.query.lower().strip()
        candidates = self.event_repository.list(limit=max(query.limit * 10, 100))
        if not normalized:
            return candidates[: query.limit]
        ledger_event_ids = (
            set(self.ledger_repository.search_canonical_event_ids(query=normalized, limit=query.limit * 10))
            if self.ledger_repository is not None
            else set()
        )
        matches = tuple(
            event
            for event in candidates
            if event.event_id in ledger_event_ids
            or normalized in (event.intent_text or "").lower()
            or normalized in event.source_binding.source_ref.title.lower()
            or normalized in event.event_type.lower()
            or normalized in self._canonical_text_for_event(event.event_id)
        )
        return matches[: query.limit]

    def cards_for_events(
        self, *, events: tuple[ContextEvent, ...], query: RetrievalQuery
    ) -> tuple[SearchResultCard, ...]:
        """Return safe default preview cards for matched events.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        normalized = query.query.lower().strip()
        return tuple(self.disclosure.summary_card(event=event, query=normalized) for event in events)

    def _canonical_text_for_event(self, event_id: str) -> str:
        if self.artifact_repository is None or self.vault is None:
            return ""
        texts: list[str] = []
        for artifact in self.artifact_repository.list_for_event(event_id):
            if artifact.artifact_type != ArtifactType.CANONICAL_TEXT:
                continue
            if artifact.ingest_state not in {ArtifactIngestState.DLP_PASSED, ArtifactIngestState.INDEXED}:
                continue
            if artifact.redaction_state in {RedactionState.BLOCKED, RedactionState.QUARANTINED}:
                continue
            try:
                texts.append(self.vault.read(artifact.storage_uri).decode("utf-8").lower())
            except (ArtifactVaultError, UnicodeDecodeError):
                continue
        return "\n".join(texts)


class ContextBundleBuilder:
    """Build and persist minimal retrieval-time context bundles."""

    def __init__(
        self,
        *,
        events: ContextEventRepository,
        bundles: ContextBundleRepository,
        ids: IdFactory,
        clock: Clock,
    ) -> None:
        """Create a bundle builder.

        Args:
            events: Event repository used for P0 candidate retrieval.
            bundles: Bundle repository used for persistence.
            ids: Identifier generator.
            clock: Clock used for bundle timestamps.
        """

        self.events = events
        self.bundles = bundles
        self.ids = ids
        self.clock = clock

    def build(self, request: BundleRequest) -> ContextBundle:
        """Build a minimal bundle manifest without persisting it.

        Args:
            request: Bundle request from CLI or API.

        Returns:
            Context bundle ready for persistence.
        """

        items = tuple(
            ContextBundleItem(
                event_id=event.event_id,
                claim=event.intent_text or event.source_binding.source_ref.title,
                citations=(),
            )
            for event in self.events.list(limit=20)
        )
        return ContextBundle(
            bundle_id=self.ids.new("cb"),
            query=request.query,
            purpose=request.purpose,
            items=items,
            degraded=True,
            created_at=self.clock.now(),
        )

    def save(self, bundle: ContextBundle) -> ContextBundle:
        """Persist a prebuilt context bundle manifest.

        Args:
            bundle: Context bundle created by ``build``.

        Returns:
            Persisted context bundle.
        """

        return self.bundles.save(bundle)

    def create(self, request: BundleRequest) -> ContextBundle:
        """Create and persist a minimal bundle manifest.

        Args:
            request: Bundle request from CLI or API.

        Returns:
            Persisted context bundle.
        """

        return self.save(self.build(request))
