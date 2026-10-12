from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from packages.artifacts.vault import LocalArtifactVault
from packages.contracts import (
    ActorRef,
    CaptureStrategy,
    ContextEvent,
    DisclosureClass,
    EventStatus,
    IndexHit,
    RedactionState,
    SearchExplain,
    SearchFieldKind,
    SearchFilters,
    SearchMatchReason,
    SearchQuery,
    SearchResultCard,
    SearchResultSource,
    SearchSort,
    SensitiveSurfaceType,
    SourceBinding,
    SourceRef,
    SourceType,
    TriggerEnvelope,
    TriggerType,
)
from packages.contracts.common import JsonScalar
from packages.disclosure import DisclosurePolicyService
from packages.indexing.backends import SQLiteKeywordIndexBackend
from packages.indexing.contracts import (
    IndexDocument,
    IndexFieldKind,
    IndexHealth,
    IndexQuery,
    IndexReceipt,
    IndexWriteBatch,
)
from packages.indexing.registry import IndexBackendRegistry
from packages.indexing.safety import IndexableTextSource, SafeIndexProjectionService
from packages.indexing.search import SearchCardOverlay, SearchService
from packages.indexing.service import IndexingService
from packages.shared.ids import IdFactory
from packages.storage.database import SQLiteDatabase
from packages.storage.event_repository import ContextEventRepository


def test_sqlite_keyword_backend_indexes_metadata_text_and_cjk(tmp_path):
    backend = SQLiteKeywordIndexBackend(SQLiteDatabase(tmp_path / "index.sqlite"))
    captured_at = datetime(2026, 5, 18, 9, 30, tzinfo=UTC)
    docs = (
        _doc("evt_1", "note", "用于 ACME 续约 brief", IndexFieldKind.USER_NOTE, captured_at),
        _doc("evt_1", "canonical", "Budget variance +18%", IndexFieldKind.CANONICAL_TEXT, captured_at),
    )

    receipt = backend.upsert(IndexWriteBatch(event_id="evt_1", documents=docs))
    english = backend.search(IndexQuery(query="Budget variance"))
    cjk = backend.search(IndexQuery(query="续约"))

    assert receipt.indexed_count == 2
    assert english[0].event_id == "evt_1"
    assert english[0].match_reason == "canonical_text"
    assert cjk[0].event_id == "evt_1"
    assert cjk[0].match_reason == "user_note"


def test_sqlite_keyword_backend_filters_and_delete_event(tmp_path):
    backend = SQLiteKeywordIndexBackend(SQLiteDatabase(tmp_path / "index.sqlite"))
    captured_at = datetime(2026, 5, 18, 9, 30, tzinfo=UTC)
    backend.upsert(
        IndexWriteBatch(
            event_id="evt_1",
            documents=(
                _doc("evt_1", "chrome", "Budget variance", IndexFieldKind.CANONICAL_TEXT, captured_at, app="Chrome"),
                _doc("evt_2", "safari", "Budget variance", IndexFieldKind.CANONICAL_TEXT, captured_at, app="Safari"),
            ),
        )
    )

    chrome = backend.search(IndexQuery(query="Budget", filters=SearchFilters(app="Chrome")))
    backend.delete_event("evt_1")
    after_delete = backend.search(IndexQuery(query="Budget", filters=SearchFilters(app="Chrome")))

    assert [hit.event_id for hit in chrome] == ["evt_1"]
    assert after_delete == ()


def test_sqlite_keyword_upsert_replaces_entire_event(tmp_path):
    backend = SQLiteKeywordIndexBackend(SQLiteDatabase(tmp_path / "index.sqlite"))
    captured_at = datetime(2026, 5, 18, 9, 30, tzinfo=UTC)
    backend.upsert(
        IndexWriteBatch(
            event_id="evt_1",
            documents=(_doc("evt_1", "old", "SHOULD_NOT_REMAIN", IndexFieldKind.CANONICAL_TEXT, captured_at),),
        )
    )

    receipt = backend.upsert(
        IndexWriteBatch(
            event_id="evt_1",
            documents=(_doc("evt_1", "new", "Budget variance", IndexFieldKind.CANONICAL_TEXT, captured_at),),
        )
    )
    stale = backend.search(IndexQuery(query="SHOULD_NOT_REMAIN"))
    fresh = backend.search(IndexQuery(query="Budget variance"))

    assert receipt.deleted_count == 1
    assert stale == ()
    assert fresh[0].event_id == "evt_1"


def test_sqlite_keyword_upsert_can_append_active_capture_projection(tmp_path):
    backend = SQLiteKeywordIndexBackend(SQLiteDatabase(tmp_path / "index.sqlite"))
    captured_at = datetime(2026, 5, 18, 9, 30, tzinfo=UTC)
    backend.upsert(
        IndexWriteBatch(
            event_id="evt_1",
            documents=(_doc("evt_1", "canonical", "Budget variance", IndexFieldKind.CANONICAL_TEXT, captured_at),),
        )
    )

    backend.upsert(
        IndexWriteBatch(
            event_id="evt_1",
            documents=(
                _doc(
                    "evt_1",
                    "timeline",
                    "hotkey: submit form",
                    IndexFieldKind.RECORDING_TIMELINE,
                    captured_at,
                ),
            ),
            replace_event=False,
        )
    )

    assert backend.search(IndexQuery(query="Budget"))[0].event_id == "evt_1"
    hit = backend.search(IndexQuery(query="submit form"))[0]
    assert hit.event_id == "evt_1"
    assert hit.match_reason == "recording_timeline"


def test_sqlite_keyword_upsert_replaces_chunk_prefix_literally(tmp_path):
    backend = SQLiteKeywordIndexBackend(SQLiteDatabase(tmp_path / "index.sqlite"))
    captured_at = datetime(2026, 5, 18, 9, 30, tzinfo=UTC)
    backend.upsert(
        IndexWriteBatch(
            event_id="evt_1",
            documents=(
                _doc("evt_1", "old", "SHOULD_NOT_REMAIN", IndexFieldKind.RECORDING_TIMELINE, captured_at),
                _doc("evtX1", "neighbor", "SHOULD_REMAIN_NEIGHBOR", IndexFieldKind.RECORDING_TIMELINE, captured_at),
            ),
            replace_event=False,
        )
    )

    receipt = backend.upsert(
        IndexWriteBatch(
            event_id="evt_1",
            documents=(
                _doc("evt_1", "fresh", "fresh active timeline", IndexFieldKind.RECORDING_TIMELINE, captured_at),
            ),
            replace_event=False,
            replace_chunk_prefixes=("chk_evt_1",),
        )
    )

    assert receipt.deleted_count == 1
    assert backend.search(IndexQuery(query="SHOULD_NOT_REMAIN")) == ()
    assert backend.search(IndexQuery(query="SHOULD_REMAIN_NEIGHBOR"))[0].event_id == "evtX1"


def test_safe_index_projection_redacts_and_suppresses_sensitive_sources():
    event = _event()
    service = SafeIndexProjectionService(ids=IdFactory())

    batch = service.project(
        event_id=event.event_id,
        sources=(
            IndexableTextSource(
                event=event,
                field_kind=SearchFieldKind.ACTIVE_CAPTURE_SUMMARY,
                text="Token api_key=SHOULD_NOT_LEAK_INDEX_TOKEN",
                captured_at=event.trigger.occurred_at,
                redaction_state=RedactionState.REDACTED,
            ),
            IndexableTextSource(
                event=event,
                field_kind=SearchFieldKind.RECORDING_TIMELINE,
                text="hidden password timeline",
                captured_at=event.trigger.occurred_at,
                sensitive_surface_type=SensitiveSurfaceType.PASSWORD_FIELD,
            ),
        ),
    )

    assert batch.audit.redacted_count == 1
    assert "[REDACTED]" in batch.projections[0].text
    assert batch.projections[1].text == ""
    assert batch.audit.suppressed_count == 1


def test_indexing_service_safe_projection_uses_stable_active_capture_chunks(tmp_path):
    backend = SQLiteKeywordIndexBackend(SQLiteDatabase(tmp_path / "index.sqlite"))
    registry = IndexBackendRegistry()
    registry.register(backend, default=True)
    service = IndexingService(
        registry=registry,
        vault=LocalArtifactVault(staging_dir=tmp_path / "staging", vault_dir=tmp_path / "vault"),
        safe_projection=SafeIndexProjectionService(ids=IdFactory()),
    )
    event = _event()

    def _batch(include_human_demo: bool):
        sources = [
            IndexableTextSource(
                event=event,
                field_kind=SearchFieldKind.RECORDING_TIMELINE,
                text="recording ended after submit",
                captured_at=event.trigger.occurred_at,
                metadata={"index_document_key": "active_capture:acs_test:timeline"},
            )
        ]
        if include_human_demo:
            sources.append(
                IndexableTextSource(
                    event=event,
                    field_kind=SearchFieldKind.HUMAN_DEMO_SUMMARY,
                    text="clicked hidden stale action",
                    captured_at=event.trigger.occurred_at,
                    metadata={"index_document_key": "active_capture:acs_test:human_demo"},
                )
            )
        batch = service.safe_projection.project(
            event_id=event.event_id,
            sources=tuple(sources),
            replace_event=False,
        )
        return batch.model_copy(update={"replace_chunk_prefixes": ("idxchk_evt_1_active_capture:acs_test:",)})

    first = service.index_safe_projection(_batch(include_human_demo=True))
    second = service.index_safe_projection(_batch(include_human_demo=False))
    hits = backend.search(IndexQuery(query="submit"))

    assert first.indexed_count == 2
    assert second.indexed_count == 1
    assert len(hits) == 1
    assert hits[0].chunk_id == "idxchk_evt_1_active_capture:acs_test:timeline_0"
    assert backend.search(IndexQuery(query="stale action")) == ()


def test_active_capture_search_hit_uses_coarse_card_without_screenshot_text(tmp_path):
    event = _event()
    backend = SQLiteKeywordIndexBackend(SQLiteDatabase(tmp_path / "index.sqlite"))
    backend.upsert(
        IndexWriteBatch(
            event_id=event.event_id,
            documents=(
                _doc(
                    event.event_id,
                    "timeline",
                    "recording ended after submit",
                    IndexFieldKind.RECORDING_TIMELINE,
                    event.trigger.occurred_at,
                ),
            ),
        )
    )
    registry = IndexBackendRegistry()
    registry.register(backend, default=True)
    search = SearchService(
        events=cast(ContextEventRepository, _FakeEventRepository(event)),
        disclosure=cast(DisclosurePolicyService, _FakeDisclosure()),
        index_registry=registry,
    )

    result = search.search(SearchQuery(query="submit"))

    assert result.results[0].match_reason == "recording_timeline"
    assert result.results[0].selection_text_snippet == ""
    assert result.results[0].canonical_text_snippet == ""
    assert result.results[0].preview_evidence_id is None
    assert "active_capture_raw_materials" in result.results[0].hidden_artifacts


def test_active_capture_user_note_search_hit_uses_recording_card_scrub(tmp_path):
    event = _event()
    backend = SQLiteKeywordIndexBackend(SQLiteDatabase(tmp_path / "index.sqlite"))
    backend.upsert(
        IndexWriteBatch(
            event_id=event.event_id,
            documents=(
                _doc(
                    event.event_id,
                    "active_capture_user_note",
                    "API key rotation demo note",
                    IndexFieldKind.USER_NOTE,
                    event.trigger.occurred_at,
                    metadata={
                        "active_capture_session_id": "acs_demo",
                        "active_capture_mode": "recording_session",
                        "active_capture_user_note": "API key rotation demo note",
                        "index_document_key": "active_capture:acs_demo:user_note",
                    },
                ),
            ),
        )
    )
    registry = IndexBackendRegistry()
    registry.register(backend, default=True)
    search = SearchService(
        events=cast(ContextEventRepository, _FakeEventRepository(event)),
        disclosure=cast(DisclosurePolicyService, _FakeDisclosure()),
        index_registry=registry,
    )

    result = search.search(SearchQuery(query="rotation"))

    assert result.results[0].match_reason == "user_note"
    assert result.results[0].selection_text == ""
    assert result.results[0].selection_text_snippet == ""
    assert result.results[0].canonical_text_snippet == ""
    assert result.results[0].preview_evidence_id is None
    assert result.results[0].user_note == "API key rotation demo note"
    assert "active_capture_raw_materials" in result.results[0].hidden_artifacts
    assert "active_capture_recording" in result.results[0].hidden_artifacts


def test_active_capture_screenshot_keyframe_hit_is_not_marked_as_recording_card(tmp_path):
    event = _event()
    backend = SQLiteKeywordIndexBackend(SQLiteDatabase(tmp_path / "index.sqlite"))
    backend.upsert(
        IndexWriteBatch(
            event_id=event.event_id,
            documents=(
                _doc(
                    event.event_id,
                    "active_capture_user_note",
                    "single screenshot anchor context",
                    IndexFieldKind.USER_NOTE,
                    event.trigger.occurred_at,
                    metadata={
                        "active_capture_session_id": "acs_anchor",
                        "active_capture_mode": "screenshot_keyframes",
                        "index_document_key": "active_capture:acs_anchor:user_note",
                    },
                ),
            ),
        )
    )
    registry = IndexBackendRegistry()
    registry.register(backend, default=True)
    search = SearchService(
        events=cast(ContextEventRepository, _FakeEventRepository(event)),
        disclosure=cast(DisclosurePolicyService, _FakeDisclosure()),
        index_registry=registry,
    )

    result = search.search(SearchQuery(query="anchor"))

    assert "active_capture_raw_materials" in result.results[0].hidden_artifacts
    assert "active_capture_recording" not in result.results[0].hidden_artifacts


def test_recent_active_capture_recording_prefers_user_note_hit(tmp_path):
    event = _event()
    backend = SQLiteKeywordIndexBackend(SQLiteDatabase(tmp_path / "index.sqlite"))
    backend.upsert(
        IndexWriteBatch(
            event_id=event.event_id,
            documents=(
                _doc(
                    event.event_id,
                    "metadata",
                    "Desktop region",
                    IndexFieldKind.SAFE_METADATA,
                    event.trigger.occurred_at,
                ),
                _doc(
                    event.event_id,
                    "active_capture_user_note",
                    "Review billing workflow demo",
                    IndexFieldKind.USER_NOTE,
                    event.trigger.occurred_at,
                    metadata={
                        "active_capture_session_id": "acs_demo",
                        "active_capture_mode": "recording_session",
                        "active_capture_user_note": "Review billing workflow demo",
                        "index_document_key": "active_capture:acs_demo:user_note",
                    },
                ),
                _doc(
                    event.event_id,
                    "active_capture_summary",
                    "active capture acs_demo completed",
                    IndexFieldKind.ACTIVE_CAPTURE_SUMMARY,
                    event.trigger.occurred_at,
                    metadata={
                        "active_capture_session_id": "acs_demo",
                        "active_capture_mode": "recording_session",
                        "index_document_key": "active_capture:acs_demo:summary",
                    },
                ),
            ),
        )
    )
    registry = IndexBackendRegistry()
    registry.register(backend, default=True)
    search = SearchService(
        events=cast(ContextEventRepository, _FakeEventRepository(event)),
        disclosure=cast(DisclosurePolicyService, _FakeDisclosure()),
        index_registry=registry,
    )

    result = search.search(SearchQuery(query="", sort=SearchSort.CAPTURED_AT))

    assert result.results[0].match_reason == "user_note"
    assert result.results[0].user_note == "Review billing workflow demo"
    assert "active_capture_recording" in result.results[0].hidden_artifacts


def test_recent_active_capture_secondary_keyframe_is_excluded_from_default_results(tmp_path):
    event = _event()
    backend = SQLiteKeywordIndexBackend(SQLiteDatabase(tmp_path / "index.sqlite"))
    backend.upsert(
        IndexWriteBatch(
            event_id=event.event_id,
            documents=(
                _doc(
                    event.event_id,
                    "regular_ocr",
                    "Regular OCR from keyframe",
                    IndexFieldKind.VISUAL_OCR_TEXT,
                    event.trigger.occurred_at,
                ),
                _doc(
                    event.event_id,
                    "active_capture_keyframe_ocr",
                    "Active capture keyframe OCR",
                    IndexFieldKind.VISUAL_OCR_TEXT,
                    event.trigger.occurred_at,
                    metadata={
                        "active_capture_session_id": "acs_demo",
                        "active_capture_mode": "recording_session",
                        "active_capture_primary_event_id": "evt_primary_recording",
                        "active_capture_keyframe_id": "kf_final",
                        "index_document_key": "active_capture:acs_demo:text:final",
                    },
                ),
            ),
        )
    )
    registry = IndexBackendRegistry()
    registry.register(backend, default=True)
    search = SearchService(
        events=cast(ContextEventRepository, _FakeEventRepository(event)),
        disclosure=cast(DisclosurePolicyService, _FakeDisclosure()),
        index_registry=registry,
    )

    result = search.search(SearchQuery(query="", sort=SearchSort.CAPTURED_AT))

    assert result.results == ()


def test_card_overlay_excludes_recording_keyframe_material_from_plain_hit(tmp_path):
    event = _event()
    backend = SQLiteKeywordIndexBackend(SQLiteDatabase(tmp_path / "index.sqlite"))
    backend.upsert(
        IndexWriteBatch(
            event_id=event.event_id,
            documents=(
                _doc(
                    event.event_id,
                    "regular_ocr",
                    "Regular OCR from recording boundary keyframe",
                    IndexFieldKind.VISUAL_OCR_TEXT,
                    event.trigger.occurred_at,
                ),
            ),
        )
    )
    registry = IndexBackendRegistry()
    registry.register(backend, default=True)
    search = SearchService(
        events=cast(ContextEventRepository, _FakeEventRepository(event)),
        disclosure=cast(DisclosurePolicyService, _FakeDisclosure()),
        index_registry=registry,
        card_overlay=lambda _: SearchCardOverlay(
            hidden_artifacts=("active_capture_raw_materials", "active_capture_keyframe_material")
        ),
    )

    result = search.search(SearchQuery(query="", sort=SearchSort.CAPTURED_AT))

    assert result.results == ()


def test_card_overlay_scrubs_recording_card_from_plain_ocr_hit(tmp_path):
    event = _event()
    backend = SQLiteKeywordIndexBackend(SQLiteDatabase(tmp_path / "index.sqlite"))
    active_metadata: dict[str, JsonScalar] = {
        "active_capture_session_id": "acs_1",
        "active_capture_mode": "recording_session",
        "active_capture_primary_event_id": event.event_id,
    }
    backend.upsert(
        IndexWriteBatch(
            event_id=event.event_id,
            documents=(
                _doc(
                    event.event_id,
                    "regular_ocr",
                    "SHOULD_NOT_LEAK_RECORDING_OCR",
                    IndexFieldKind.VISUAL_OCR_TEXT,
                    event.trigger.occurred_at,
                ),
                _doc(
                    event.event_id,
                    "active_summary",
                    "安全录制摘要",
                    IndexFieldKind.ACTIVE_CAPTURE_SUMMARY,
                    event.trigger.occurred_at,
                    metadata=active_metadata,
                ),
            ),
        )
    )
    registry = IndexBackendRegistry()
    registry.register(backend, default=True)
    search = SearchService(
        events=cast(ContextEventRepository, _FakeEventRepository(event)),
        disclosure=cast(DisclosurePolicyService, _FakeDisclosure()),
        index_registry=registry,
        card_overlay=lambda _: SearchCardOverlay(
            hidden_artifacts=("active_capture_raw_materials", "active_capture_recording")
        ),
    )

    leaked = search.search(SearchQuery(query="SHOULD_NOT_LEAK_RECORDING_OCR", explain=True))
    result = search.search(SearchQuery(query="安全录制摘要", explain=True))
    card = result.results[0]
    explain = result.explain[0]

    assert leaked.results == ()
    assert leaked.explain == ()
    assert card.match_reason == "active_capture_summary"
    assert card.selection_text == ""
    assert card.selection_text_snippet == ""
    assert card.canonical_text_snippet == ""
    assert card.preview_evidence_id is None
    assert card.preview_confidence == 0.0
    assert "active_capture_recording" in card.hidden_artifacts
    assert "artifact_id" not in explain.details
    assert "evidence_id" not in explain.details
    assert "field_kind" not in explain.details
    assert "text_hash" not in explain.details
    assert explain.matched_fields == ()
    assert explain.match_reason == SearchMatchReason.ACTIVE_CAPTURE_SUMMARY
    assert explain.score == 0.0
    assert explain.details["active_capture_session_id"] == "acs_1"


def test_card_overlay_allows_active_capture_safe_text_projection(tmp_path):
    event = _event()
    backend = SQLiteKeywordIndexBackend(SQLiteDatabase(tmp_path / "index.sqlite"))
    active_metadata: dict[str, JsonScalar] = {
        "active_capture_session_id": "acs_1",
        "active_capture_mode": "recording_session",
        "active_capture_primary_event_id": event.event_id,
    }
    backend.upsert(
        IndexWriteBatch(
            event_id=event.event_id,
            documents=(
                _doc(
                    event.event_id,
                    "active_safe_ocr",
                    "安全 OCR 摘要来自录制关键帧",
                    IndexFieldKind.VISUAL_OCR_TEXT,
                    event.trigger.occurred_at,
                    metadata=active_metadata,
                ),
            ),
        )
    )
    registry = IndexBackendRegistry()
    registry.register(backend, default=True)
    search = SearchService(
        events=cast(ContextEventRepository, _FakeEventRepository(event)),
        disclosure=cast(DisclosurePolicyService, _FakeDisclosure()),
        index_registry=registry,
        card_overlay=lambda _: SearchCardOverlay(
            hidden_artifacts=("active_capture_raw_materials", "active_capture_recording")
        ),
    )

    result = search.search(SearchQuery(query="安全 OCR 摘要", explain=True))
    card = result.results[0]
    explain = result.explain[0]

    assert card.event_id == event.event_id
    assert card.match_reason == "active_capture_summary"
    assert card.selection_text == ""
    assert card.preview_evidence_id is None
    assert explain.details["active_capture_session_id"] == "acs_1"
    assert "field_kind" not in explain.details
    assert explain.matched_fields == ()
    assert explain.match_reason == SearchMatchReason.ACTIVE_CAPTURE_SUMMARY
    assert explain.score == 0.0
    assert "artifact_id" not in explain.details


def test_facets_exclude_secondary_active_capture_keyframe_material(tmp_path):
    event = _event()
    backend = SQLiteKeywordIndexBackend(SQLiteDatabase(tmp_path / "index.sqlite"))
    backend.upsert(
        IndexWriteBatch(
            event_id=event.event_id,
            documents=(
                _doc(
                    event.event_id,
                    "regular_ocr",
                    "Regular OCR from keyframe",
                    IndexFieldKind.VISUAL_OCR_TEXT,
                    event.trigger.occurred_at,
                    app="Chrome",
                ),
            ),
        )
    )
    registry = IndexBackendRegistry()
    registry.register(backend, default=True)
    search = SearchService(
        events=cast(ContextEventRepository, _FakeEventRepository(event)),
        disclosure=cast(DisclosurePolicyService, _FakeDisclosure()),
        index_registry=registry,
        card_overlay=lambda _: SearchCardOverlay(
            hidden_artifacts=("active_capture_raw_materials", "active_capture_keyframe_material")
        ),
    )

    facets = search.facets(SearchQuery(query="", sort=SearchSort.CAPTURED_AT))

    assert facets["apps"] == ()
    assert facets["origins"] == ()


def test_facets_fallback_excludes_active_capture_material_without_event_ids() -> None:
    event = _event()
    backend = _FakeSearchOnlyBackend(
        hits=(_hit(event.event_id, match_reason=SearchMatchReason.VISUAL_OCR_TEXT),),
        facets={"apps": ("Chrome",), "origins": ("https://example.test",)},
    )
    registry = IndexBackendRegistry()
    registry.register(backend, default=True)
    search = SearchService(
        events=cast(ContextEventRepository, _FakeEventRepository(event)),
        disclosure=cast(DisclosurePolicyService, _FakeDisclosure()),
        index_registry=registry,
        card_overlay=lambda _: SearchCardOverlay(
            hidden_artifacts=("active_capture_raw_materials", "active_capture_keyframe_material")
        ),
    )

    facets = search.facets(SearchQuery(query="SHOULD_NOT_LEAK_RECORDING_OCR"))

    assert facets["apps"] == ()
    assert facets["origins"] == ()


def test_search_overfetches_after_filtering_active_capture_keyframe_material() -> None:
    hidden_a = _event("evt_hidden_a")
    hidden_b = _event("evt_hidden_b")
    visible = _event("evt_visible")
    backend = _FakeSearchOnlyBackend(
        hits=(
            _hit(hidden_a.event_id, match_reason=SearchMatchReason.VISUAL_OCR_TEXT),
            _hit(hidden_b.event_id, match_reason=SearchMatchReason.VISUAL_OCR_TEXT),
            _hit(visible.event_id, match_reason=SearchMatchReason.VISUAL_OCR_TEXT),
        ),
        facets={},
    )
    registry = IndexBackendRegistry()
    registry.register(backend, default=True)
    search = SearchService(
        events=cast(
            ContextEventRepository,
            _FakeEventRepository({event.event_id: event for event in (hidden_a, hidden_b, visible)}),
        ),
        disclosure=cast(DisclosurePolicyService, _FakeDisclosure()),
        index_registry=registry,
        card_overlay=lambda event_id: SearchCardOverlay(
            hidden_artifacts=("active_capture_keyframe_material",) if event_id.startswith("evt_hidden") else ()
        ),
    )

    result = search.search(SearchQuery(query="录制", limit=1))

    assert [card.event_id for card in result.results] == [visible.event_id]
    assert backend.search_queries[-1].limit > 1


def _hit(event_id: str, *, match_reason: SearchMatchReason) -> IndexHit:
    return IndexHit(
        event_id=event_id,
        chunk_id=f"chk_{event_id}",
        evidence_id=f"ev_{event_id}",
        artifact_id=f"art_{event_id}",
        backend="fake",
        score=1.0,
        matched_fields=(SearchFieldKind.VISUAL_OCR_TEXT,),
        match_reason=match_reason,
        explain=SearchExplain(
            event_id=event_id,
            backend="fake",
            score=1.0,
            matched_fields=(SearchFieldKind.VISUAL_OCR_TEXT,),
            match_reason=match_reason,
            degraded=False,
            details={"artifact_id": f"art_{event_id}", "evidence_id": f"ev_{event_id}"},
        ),
    )


class _FakeSearchOnlyBackend:
    name = "fake"
    version = "test"

    def __init__(self, *, hits: tuple[IndexHit, ...], facets: dict[str, tuple[str, ...]]) -> None:
        self._hits = hits
        self._facets = facets
        self.search_queries: list[IndexQuery] = []

    def upsert(self, batch: IndexWriteBatch) -> IndexReceipt:
        return IndexReceipt(backend=self.name, backend_version=self.version, indexed_count=0, deleted_count=0)

    def delete_event(self, event_id: str) -> IndexReceipt:
        return IndexReceipt(backend=self.name, backend_version=self.version, indexed_count=0, deleted_count=0)

    def rebuild(self, batches: tuple[IndexWriteBatch, ...]) -> IndexReceipt:
        return IndexReceipt(backend=self.name, backend_version=self.version, indexed_count=0, deleted_count=0)

    def search(self, query: IndexQuery) -> tuple[IndexHit, ...]:
        self.search_queries.append(query)
        return self._hits[: query.limit]

    def facets(self, query: IndexQuery) -> dict[str, tuple[str, ...]]:
        return self._facets

    def facets_for_event_ids(self, query: IndexQuery, event_ids: set[str]) -> dict[str, tuple[str, ...]]:
        return self._facets if event_ids else {key: () for key in self._facets}

    def explain(self, hit: IndexHit) -> IndexHit:
        return hit

    def health(self) -> IndexHealth:
        return IndexHealth(backend=self.name, backend_version=self.version, available=True)


class _FakeEventRepository:
    def __init__(self, event: ContextEvent | dict[str, ContextEvent]) -> None:
        self.events = event if isinstance(event, dict) else {event.event_id: event}

    def get(self, event_id: str) -> ContextEvent | None:
        return self.events.get(event_id)


class _FakeDisclosure:
    def summary_card(self, *, event: ContextEvent, query: str | None = None) -> SearchResultCard:
        return SearchResultCard(
            event_id=event.event_id,
            event_type=event.event_type,
            captured_at=event.trigger.occurred_at,
            source=SearchResultSource(
                app_name=event.source_binding.source_ref.app_name,
                title=event.source_binding.source_ref.title,
                origin=event.source_binding.source_ref.origin,
                sanitized_url=event.source_binding.source_ref.url,
            ),
            selection_text="SHOULD_NOT_LEAK_SCREENSHOT_TEXT",
            selection_text_snippet="SHOULD_NOT_LEAK_SCREENSHOT_TEXT",
            canonical_text_snippet="SHOULD_NOT_LEAK_CANONICAL_TEXT",
            preview_evidence_id="ev_screenshot",
            preview_confidence=0.9,
        )


def _doc(
    event_id: str,
    suffix: str,
    text: str,
    field_kind: IndexFieldKind,
    captured_at: datetime,
    *,
    app: str = "Chrome",
    metadata: dict[str, JsonScalar] | None = None,
) -> IndexDocument:
    return IndexDocument(
        document_id=f"doc_{event_id}_{suffix}",
        chunk_id=f"chk_{event_id}_{suffix}",
        event_id=event_id,
        captured_at=captured_at,
        disclosure_class=(
            DisclosureClass.REDACTED_CANONICAL
            if field_kind == IndexFieldKind.CANONICAL_TEXT
            else DisclosureClass.SAFE_METADATA
        ),
        field_kind=field_kind,
        text=text,
        text_hash=f"hash_{suffix}",
        title="ACME Dashboard",
        app_name=app,
        origin="https://example.test",
        source_type="web",
        metadata=metadata or {},
    )


def _event(event_id: str = "evt_1") -> ContextEvent:
    now = datetime(2026, 5, 18, 9, 30, tzinfo=UTC)
    return ContextEvent(
        event_id=event_id,
        event_type="screen.region.captured",
        trigger=TriggerEnvelope(
            trigger_id="trg_1",
            trigger_type=TriggerType.MANUAL_OS_REGION_HOTKEY,
            capture_strategy=CaptureStrategy.OS_REGION,
            actor=ActorRef(actor_id="actor_1"),
            occurred_at=now,
        ),
        source_binding=SourceBinding(
            binding_id="src_1",
            source_ref=SourceRef(
                source_type=SourceType.WEB,
                title="Example",
                app_name="Chrome",
                url="https://example.test/path?secret=1",
                origin="https://example.test",
            ),
            confidence=1.0,
            resolved_at=now,
        ),
        status=EventStatus.AGENT_READY,
        intent_text=None,
        created_at=now,
        updated_at=now,
    )
