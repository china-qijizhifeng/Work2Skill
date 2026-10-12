"""Search and bundle services over index backends."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import cast

from packages.contracts import (
    ContextBundle,
    ContextBundleItem,
    EventStatus,
    EvidenceRef,
    IndexHit,
    SearchExplain,
    SearchFilters,
    SearchMatchReason,
    SearchQuery,
    SearchResponse,
    SearchResultCard,
)
from packages.disclosure import DisclosurePolicyService
from packages.indexing.contracts import IndexQuery
from packages.indexing.registry import IndexBackendRegistry
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from packages.storage.artifact_repository import ArtifactRepository
from packages.storage.bundle_repository import ContextBundleRepository
from packages.storage.event_repository import ContextEventRepository


@dataclass(frozen=True)
class SearchCardOverlay:
    """Safe per-event card overlay from adjacent bounded contexts.

    Attributes:
        hidden_artifacts: Extra safe artifact markers to merge into the card.
        user_note: Optional user-authored note from an adjacent context.
    """

    hidden_artifacts: tuple[str, ...] = ()
    user_note: str | None = None


class SearchService:
    """Search application service that keeps CLI/API decoupled from index backends."""

    def __init__(
        self,
        *,
        events: ContextEventRepository,
        disclosure: DisclosurePolicyService,
        index_registry: IndexBackendRegistry,
        card_overlay: Callable[[str], SearchCardOverlay | None] | None = None,
    ) -> None:
        self.events = events
        self.disclosure = disclosure
        self.index_registry = index_registry
        self.card_overlay = card_overlay

    def search(self, query: SearchQuery) -> SearchResponse:
        """Return policy-built cards for index hits."""

        backend = self.index_registry.default()
        search_limit = self._overfetch_limit(query.limit)
        hits = backend.search(IndexQuery(query=query.query, filters=query.filters, limit=search_limit, explain=True))
        cards: list[SearchResultCard] = []
        explanations: list[SearchExplain] = []
        seen: set[str] = set()
        secondary_active_capture_event_ids = self._secondary_active_capture_event_ids(hits)
        for hit in self._rank_hits(hits, query=query):
            if hit.event_id in seen:
                continue
            if hit.event_id in secondary_active_capture_event_ids:
                seen.add(hit.event_id)
                continue
            event = self.events.get(hit.event_id)
            if event is None or event.status in {EventStatus.DELETED, EventStatus.RESTRICTED}:
                continue
            card = self.disclosure.summary_card(event=event, query=query.query)
            if self._active_capture_hit(hit):
                card = self._active_capture_card(card, hit)
                card = self._apply_card_overlay(card, hit.event_id)
                if self._is_secondary_active_capture_material(card):
                    seen.add(hit.event_id)
                    continue
                if self._is_recording_raw_text_hit(card, hit):
                    continue
                cards.append(card)
                if query.explain and hit.explain is not None:
                    explanations.append(self._safe_explain_for_card(card=card, explain=hit.explain))
                seen.add(hit.event_id)
                if len(cards) >= query.limit:
                    break
                continue
            if card.match_reason in {SearchMatchReason.METADATA, SearchMatchReason.RECENT} or hit.match_reason in {
                SearchMatchReason.USER_NOTE,
            }:
                card = card.model_copy(update={"match_reason": hit.match_reason})
            card = self._apply_card_overlay(card, hit.event_id)
            if self._is_secondary_active_capture_material(card):
                seen.add(hit.event_id)
                continue
            if self._is_recording_raw_text_hit(card, hit):
                continue
            cards.append(card)
            if query.explain and hit.explain is not None:
                explanations.append(self._safe_explain_for_card(card=card, explain=hit.explain))
            seen.add(hit.event_id)
            if len(cards) >= query.limit:
                break
        health = backend.health()
        return SearchResponse(
            events=(),
            results=tuple(cards),
            degraded=query.mode.value == "hybrid" or health.degraded,
            explain=tuple(explanations),
            backend=backend.name,
        )

    def facets(self, query: SearchQuery) -> dict[str, tuple[str, ...]]:
        """Return safe source facets for developer/agent discovery commands."""

        backend = self.index_registry.default()
        index_query = IndexQuery(
            query=query.query, filters=query.filters, limit=self._overfetch_limit(query.limit), explain=False
        )
        visible_event_ids = self._visible_event_ids(query)
        if not visible_event_ids:
            return backend.facets_for_event_ids(index_query, set())
        return backend.facets_for_event_ids(index_query, visible_event_ids)

    def _rank_hits(self, hits: tuple[IndexHit, ...], *, query: SearchQuery) -> tuple[IndexHit, ...]:
        if query.sort.value == "captured_at":
            return hits
        priority = {
            SearchMatchReason.SELECTION_TEXT: 5,
            SearchMatchReason.USER_NOTE: 4,
            SearchMatchReason.VISUAL_OCR_TEXT: 3,
            SearchMatchReason.CANONICAL_TEXT: 3,
            SearchMatchReason.CLEAN_PAGE_TEXT: 2,
            SearchMatchReason.ACTIVE_CAPTURE_SUMMARY: 2,
            SearchMatchReason.RECORDING_TIMELINE: 2,
            SearchMatchReason.HUMAN_DEMO_SUMMARY: 2,
            SearchMatchReason.METADATA: 1,
        }
        return tuple(sorted(hits, key=lambda hit: (priority.get(hit.match_reason, 0), hit.score), reverse=True))

    def _active_capture_hit(self, hit: IndexHit) -> bool:
        if hit.match_reason in {
            SearchMatchReason.ACTIVE_CAPTURE_SUMMARY,
            SearchMatchReason.RECORDING_TIMELINE,
            SearchMatchReason.HUMAN_DEMO_SUMMARY,
        }:
            return True
        if hit.explain is None:
            return False
        session_id = hit.explain.details.get("active_capture_session_id")
        return isinstance(session_id, str) and bool(session_id)

    def _secondary_active_capture_event_ids(self, hits: tuple[IndexHit, ...]) -> set[str]:
        event_ids: set[str] = set()
        for hit in hits:
            if hit.explain is None:
                continue
            details = hit.explain.details
            keyframe_id = details.get("active_capture_keyframe_id")
            primary_event_id = details.get("active_capture_primary_event_id")
            if isinstance(keyframe_id, str) and (
                not isinstance(primary_event_id, str) or primary_event_id != hit.event_id
            ):
                event_ids.add(hit.event_id)
        return event_ids

    def _active_capture_card(self, card: SearchResultCard, hit: IndexHit) -> SearchResultCard:
        details = hit.explain.details if hit.explain is not None else {}
        mode = details.get("active_capture_mode")
        user_note = details.get("active_capture_user_note")
        keyframe_id = details.get("active_capture_keyframe_id")
        primary_event_id = details.get("active_capture_primary_event_id")
        is_secondary_keyframe_material = isinstance(keyframe_id, str) and (
            not isinstance(primary_event_id, str) or primary_event_id != hit.event_id
        )
        markers = [*card.hidden_artifacts, "active_capture_raw_materials"]
        if is_secondary_keyframe_material:
            markers.append("active_capture_keyframe_material")
        elif mode == "recording_session":
            markers.append("active_capture_recording")
        return card.model_copy(
            update={
                "match_reason": hit.match_reason,
                "selection_text": "",
                "selection_text_snippet": "",
                "canonical_text_snippet": "",
                "canonical_text_truncated": False,
                "preview_evidence_id": None,
                "preview_citation_id": None,
                "preview_confidence": 0.0,
                "user_note": user_note if isinstance(user_note, str) and user_note else card.user_note,
                "hidden_artifacts": tuple(dict.fromkeys(markers)),
            }
        )

    def _apply_card_overlay(self, card: SearchResultCard, event_id: str) -> SearchResultCard:
        if self.card_overlay is None:
            return card
        overlay = self.card_overlay(event_id)
        if overlay is None:
            return card
        markers = tuple(dict.fromkeys((*card.hidden_artifacts, *overlay.hidden_artifacts)))
        updates: dict[str, object] = {"hidden_artifacts": markers}
        if overlay.user_note is not None and overlay.user_note.strip():
            updates["user_note"] = overlay.user_note.strip()
        if "active_capture_keyframe_material" in markers or "active_capture_recording" in markers:
            updates.update(
                {
                    "match_reason": SearchMatchReason.ACTIVE_CAPTURE_SUMMARY,
                    "selection_text": "",
                    "selection_text_snippet": "",
                    "canonical_text_snippet": "",
                    "canonical_text_truncated": False,
                    "preview_evidence_id": None,
                    "preview_citation_id": None,
                    "preview_confidence": 0.0,
                }
            )
        return card.model_copy(update=updates)

    def _is_secondary_active_capture_material(self, card: SearchResultCard) -> bool:
        return "active_capture_keyframe_material" in card.hidden_artifacts

    def _is_recording_raw_text_hit(self, card: SearchResultCard, hit: IndexHit) -> bool:
        if "active_capture_recording" not in card.hidden_artifacts:
            return False
        if hit.explain is not None and isinstance(hit.explain.details.get("active_capture_session_id"), str):
            return False
        return hit.match_reason not in {
            SearchMatchReason.ACTIVE_CAPTURE_SUMMARY,
            SearchMatchReason.RECORDING_TIMELINE,
            SearchMatchReason.HUMAN_DEMO_SUMMARY,
            SearchMatchReason.USER_NOTE,
            SearchMatchReason.METADATA,
            SearchMatchReason.RECENT,
        }

    def _safe_explain_for_card(self, *, card: SearchResultCard, explain: SearchExplain) -> SearchExplain:
        if not {"active_capture_recording", "active_capture_keyframe_material"}.intersection(card.hidden_artifacts):
            return explain
        allowed_keys = {
            "active_capture_session_id",
            "active_capture_mode",
            "active_capture_primary_event_id",
        }
        return explain.model_copy(
            update={
                "score": 0.0,
                "matched_fields": (),
                "match_reason": SearchMatchReason.ACTIVE_CAPTURE_SUMMARY,
                "details": {key: value for key, value in explain.details.items() if key in allowed_keys},
            }
        )

    def _visible_event_ids(self, query: SearchQuery) -> set[str]:
        backend = self.index_registry.default()
        event_ids_fn = getattr(backend, "event_ids", None)
        if not callable(event_ids_fn):
            hits = backend.search(IndexQuery(query=query.query, filters=query.filters))
            return self._visible_event_ids_from_iterable(hit.event_id for hit in hits)
        typed_event_ids_fn = cast(Callable[[IndexQuery], Iterable[object]], event_ids_fn)
        event_ids = typed_event_ids_fn(
            IndexQuery(query=query.query, filters=query.filters, limit=self._overfetch_limit(query.limit))
        )
        return self._visible_event_ids_from_iterable(str(event_id) for event_id in event_ids)

    def _overfetch_limit(self, limit: int) -> int:
        return min(100, max(limit, limit * 8, limit + 80))

    def _visible_event_ids_from_iterable(self, event_ids: Iterable[object]) -> set[str]:
        visible: set[str] = set()
        for event_id in event_ids:
            event = self.events.get(str(event_id))
            if event is not None and event.status not in {EventStatus.DELETED, EventStatus.RESTRICTED}:
                overlay = self.card_overlay(event.event_id) if self.card_overlay is not None else None
                if overlay is not None and {
                    "active_capture_keyframe_material",
                    "active_capture_recording",
                }.intersection(overlay.hidden_artifacts):
                    continue
                visible.add(event.event_id)
        return visible


class ContextBundleBuilder:
    """Build and persist retrieval-time context bundles from search results."""

    def __init__(
        self,
        *,
        search: SearchService,
        bundles: ContextBundleRepository,
        artifacts: ArtifactRepository | None = None,
        ids: IdFactory,
        clock: Clock,
    ) -> None:
        self.search = search
        self.bundles = bundles
        self.artifacts = artifacts
        self.ids = ids
        self.clock = clock

    def build(self, request: object) -> ContextBundle:
        """Build a compact bundle using the same search/disclosure path as CLI."""

        from packages.contracts import BundleRequest

        body = BundleRequest.model_validate(request)
        response = self.search.search(
            SearchQuery(query=body.query, filters=SearchFilters(entity=body.entity), limit=20)
        )
        items = tuple(
            ContextBundleItem(
                event_id=card.event_id,
                claim=card.selection_text_snippet or card.user_note or card.source.title,
                citations=self._citations_for_card(card),
            )
            for card in response.results
        )
        return ContextBundle(
            bundle_id=self.ids.new("cb"),
            query=body.query,
            purpose=body.purpose,
            items=items,
            degraded=response.degraded or not items,
            created_at=self.clock.now(),
        )

    def save(self, bundle: ContextBundle) -> ContextBundle:
        """Persist a prebuilt context bundle manifest."""

        return self.bundles.save(bundle)

    def create(self, request: object) -> ContextBundle:
        """Create and persist a context bundle."""

        return self.save(self.build(request))

    def _citations_for_card(self, card: SearchResultCard) -> tuple[EvidenceRef, ...]:
        if self.artifacts is None or card.preview_evidence_id is None:
            return ()
        for artifact in self.artifacts.list_for_event(card.event_id):
            if artifact.evidence_id != card.preview_evidence_id:
                continue
            return (
                EvidenceRef(
                    event_id=card.event_id,
                    artifact_id=artifact.artifact_id,
                    evidence_ref=card.preview_evidence_id,
                    redaction_state=artifact.redaction_state,
                    provenance_path=tuple(
                        item
                        for item in (
                            artifact.provider_key,
                            artifact.extractor_name,
                            artifact.extractor_version,
                        )
                        if item
                    ),
                ),
            )
        return ()
