"""Private SQLite keyword backend query and schema internals."""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from collections import Counter

from packages.contracts import IndexHit, SearchExplain, SearchFilters, SearchMatchReason
from packages.contracts.common import JsonScalar
from packages.indexing.contracts import IndexDocument, IndexFieldKind, IndexQuery
from packages.storage.database import SQLiteDatabase

logger = logging.getLogger(__name__)


def _escape_sql_like_prefix(prefix: str) -> str:
    """Escape SQLite LIKE wildcard characters in a prefix."""

    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class _SQLiteKeywordBackendInternals:
    """Private mixin for SQL schema, query, ranking, and fallback helpers."""

    database: SQLiteDatabase
    _fts_available: bool
    name: str

    def _ensure_schema(self) -> None:
        with self.database.transaction() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS keyword_index_documents (
                  chunk_id TEXT PRIMARY KEY,
                  document_id TEXT NOT NULL,
                  event_id TEXT NOT NULL,
                  evidence_id TEXT,
                  artifact_id TEXT,
                  provider_key TEXT,
                  source_uri TEXT,
                  captured_at TEXT NOT NULL,
                  observed_at TEXT,
                  extractor_name TEXT,
                  extractor_version TEXT,
                  policy_version TEXT NOT NULL,
                  disclosure_class TEXT NOT NULL,
                  evidence_kind TEXT,
                  artifact_type TEXT,
                  sensitivity TEXT NOT NULL,
                  redaction_state TEXT NOT NULL,
                  event_status TEXT NOT NULL,
                  field_kind TEXT NOT NULL,
                  text_hash TEXT NOT NULL,
                  title TEXT,
                  app_name TEXT,
                  origin TEXT,
                  sanitized_url TEXT,
                  source_type TEXT,
                  workspace_id TEXT,
                  user_id TEXT,
                  user_display_name TEXT,
                  search_text TEXT NOT NULL,
                  payload TEXT NOT NULL
                )
                """)
            self._ensure_column(connection, "keyword_index_documents", "user_id", "TEXT")
            self._ensure_column(connection, "keyword_index_documents", "user_display_name", "TEXT")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS keyword_index_ngrams (
                  gram TEXT NOT NULL,
                  chunk_id TEXT NOT NULL,
                  event_id TEXT NOT NULL,
                  PRIMARY KEY(gram, chunk_id)
                )
                """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_keyword_index_event ON keyword_index_documents(event_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_keyword_index_time ON keyword_index_documents(captured_at)"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_keyword_index_origin ON keyword_index_documents(origin)")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_keyword_index_ngrams_event ON keyword_index_ngrams(event_id)"
            )
            try:
                connection.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS keyword_index_fts USING fts5(
                      chunk_id UNINDEXED,
                      search_text,
                      title,
                      user_note,
                      selection_text,
                      canonical_text,
                      clean_page_text
                    )
                    """)
                self._fts_available = True
            except sqlite3.OperationalError:
                logger.warning("SQLite FTS5 unavailable; keyword index will use LIKE/ngram fallback")
                self._fts_available = False

    def _document_row(self, document: IndexDocument) -> tuple[object, ...]:
        return (
            document.chunk_id,
            document.document_id,
            document.event_id,
            document.evidence_id,
            document.artifact_id,
            document.provider_key,
            document.source_uri,
            document.captured_at.isoformat(),
            document.observed_at.isoformat() if document.observed_at else None,
            document.extractor_name,
            document.extractor_version,
            document.policy_version,
            document.disclosure_class.value,
            document.evidence_kind.value if document.evidence_kind else None,
            document.artifact_type.value if document.artifact_type else None,
            document.sensitivity.value,
            document.redaction_state.value,
            document.event_status.value,
            document.field_kind.value,
            document.text_hash,
            document.title,
            document.app_name,
            document.origin,
            document.sanitized_url,
            document.source_type,
            document.workspace_id,
            document.user_id,
            document.user_display_name,
            document.text,
            document.model_dump_json(),
        )

    def _ensure_column(self, connection: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        if column not in {str(row["name"]) for row in rows}:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def _delete_chunk(self, connection: sqlite3.Connection, chunk_id: str) -> None:
        connection.execute("DELETE FROM keyword_index_documents WHERE chunk_id = ?", (chunk_id,))
        connection.execute("DELETE FROM keyword_index_ngrams WHERE chunk_id = ?", (chunk_id,))
        if self._fts_available:
            connection.execute("DELETE FROM keyword_index_fts WHERE chunk_id = ?", (chunk_id,))

    def _delete_event(self, connection: sqlite3.Connection, event_id: str) -> int:
        rows = connection.execute(
            "SELECT chunk_id FROM keyword_index_documents WHERE event_id = ?",
            (event_id,),
        ).fetchall()
        for row in rows:
            self._delete_chunk(connection, str(row["chunk_id"]))
        return len(rows)

    def _delete_chunk_prefix(self, connection: sqlite3.Connection, chunk_id_prefix: str) -> int:
        like_prefix = _escape_sql_like_prefix(chunk_id_prefix)
        rows = connection.execute(
            "SELECT chunk_id FROM keyword_index_documents WHERE chunk_id LIKE ? ESCAPE '\\'",
            (f"{like_prefix}%",),
        ).fetchall()
        for row in rows:
            self._delete_chunk(connection, str(row["chunk_id"]))
        return len(rows)

    def _fts_search(self, query: IndexQuery) -> tuple[IndexHit, ...]:
        fts_query = self._fts_query(query.query)
        where_sql, params = self._filter_sql(query.filters, include_status=True, table_alias="d")
        sql = f"""
            SELECT d.payload, bm25(keyword_index_fts) AS rank
            FROM keyword_index_fts
            JOIN keyword_index_documents d ON d.chunk_id = keyword_index_fts.chunk_id
            {where_sql + " AND" if where_sql else "WHERE"} keyword_index_fts MATCH ?
            ORDER BY rank ASC
            LIMIT ?
        """
        try:
            with self.database.transaction() as connection:
                rows = connection.execute(sql, (*params, fts_query, query.limit * 4)).fetchall()
        except sqlite3.OperationalError:
            logger.info("FTS query failed; falling back to LIKE", extra={"query_hash": self._hash(query.query)})
            return ()
        return tuple(self._hit_from_row(row, score=max(0.0, 100.0 - float(row["rank"]))) for row in rows)

    def _like_search(self, query: IndexQuery) -> tuple[IndexHit, ...]:
        where_sql, params = self._filter_sql(query.filters, include_status=True)
        like = f"%{query.query.lower()}%"
        sql = f"""
            SELECT payload
            FROM keyword_index_documents
            {where_sql + " AND" if where_sql else "WHERE"} lower(search_text || ' ' || coalesce(title, '') || ' ' || coalesce(origin, '')) LIKE ?
            ORDER BY captured_at DESC
            LIMIT ?
        """
        with self.database.transaction() as connection:
            rows = connection.execute(sql, (*params, like, query.limit * 4)).fetchall()
        return tuple(self._hit_from_row(row, score=50.0) for row in rows)

    def _ngram_search(self, query: IndexQuery) -> tuple[IndexHit, ...]:
        grams = self._ngrams(query.query)
        if not grams:
            return ()
        where_sql, params = self._filter_sql(query.filters, include_status=True, table_alias="d")
        placeholders = ", ".join("?" for _ in grams)
        sql = f"""
            SELECT d.payload, count(g.gram) AS matched_count
            FROM keyword_index_ngrams g
            JOIN keyword_index_documents d ON d.chunk_id = g.chunk_id
            {where_sql + " AND" if where_sql else "WHERE"} g.gram IN ({placeholders})
            GROUP BY d.chunk_id
            ORDER BY matched_count DESC, d.captured_at DESC
            LIMIT ?
        """
        with self.database.transaction() as connection:
            rows = connection.execute(sql, (*params, *grams, query.limit * 4)).fetchall()
        return tuple(self._hit_from_row(row, score=60.0 + float(row["matched_count"])) for row in rows)

    def _recent(self, query: IndexQuery) -> tuple[IndexHit, ...]:
        where_sql, params = self._filter_sql(query.filters, include_status=True)
        sql = f"""
            SELECT payload
            FROM keyword_index_documents
            {where_sql}
            ORDER BY
              captured_at DESC,
              CASE field_kind
                WHEN 'user_note' THEN 0
                WHEN 'active_capture_summary' THEN 1
                WHEN 'recording_timeline' THEN 2
                WHEN 'human_demo_summary' THEN 3
                WHEN payload LIKE '%"active_capture_session_id"%' THEN 4
                ELSE 10
              END ASC
            LIMIT ?
        """
        with self.database.transaction() as connection:
            rows = connection.execute(sql, (*params, query.limit * 4)).fetchall()
        return tuple(self._hit_from_row(row, score=1.0) for row in rows)

    def _hit_from_row(self, row: sqlite3.Row, *, score: float) -> IndexHit:
        document = IndexDocument.model_validate_json(str(row["payload"]))
        matched_fields = (document.field_kind,)
        reason = self._match_reason(document.field_kind)
        weighted_score = score + self._field_weight(document.field_kind)
        explain_details: dict[str, JsonScalar] = {
            "chunk_id": document.chunk_id,
            "evidence_id": document.evidence_id,
            "artifact_id": document.artifact_id,
            "field_kind": document.field_kind.value,
            "text_hash": document.text_hash,
        }
        active_capture_session_id = document.metadata.get("active_capture_session_id")
        if isinstance(active_capture_session_id, str) and active_capture_session_id:
            explain_details["active_capture_session_id"] = active_capture_session_id
        active_capture_mode = document.metadata.get("active_capture_mode")
        if isinstance(active_capture_mode, str) and active_capture_mode:
            explain_details["active_capture_mode"] = active_capture_mode
        active_capture_primary_event_id = document.metadata.get("active_capture_primary_event_id")
        if isinstance(active_capture_primary_event_id, str) and active_capture_primary_event_id:
            explain_details["active_capture_primary_event_id"] = active_capture_primary_event_id
        active_capture_keyframe_id = document.metadata.get("active_capture_keyframe_id")
        if isinstance(active_capture_keyframe_id, str) and active_capture_keyframe_id:
            explain_details["active_capture_keyframe_id"] = active_capture_keyframe_id
        active_capture_user_note = document.metadata.get("active_capture_user_note")
        if isinstance(active_capture_user_note, str) and active_capture_user_note:
            explain_details["active_capture_user_note"] = active_capture_user_note
        elif active_capture_session_id and document.field_kind == IndexFieldKind.USER_NOTE and document.text:
            explain_details["active_capture_user_note"] = document.text
        explain = SearchExplain(
            event_id=document.event_id,
            backend=self.name,
            score=weighted_score,
            matched_fields=matched_fields,
            match_reason=reason,
            degraded=not self._fts_available,
            details=explain_details,
        )
        return IndexHit(
            event_id=document.event_id,
            chunk_id=document.chunk_id,
            evidence_id=document.evidence_id,
            artifact_id=document.artifact_id,
            backend=self.name,
            score=weighted_score,
            matched_fields=matched_fields,
            match_reason=reason,
            explain=explain,
        )

    def _field_weight(self, field_kind: IndexFieldKind) -> float:
        return {
            IndexFieldKind.SELECTION_TEXT: 35.0,
            IndexFieldKind.USER_NOTE: 25.0,
            IndexFieldKind.VISUAL_OCR_TEXT: 18.0,
            IndexFieldKind.SAFE_METADATA: 15.0,
            IndexFieldKind.ACTIVE_CAPTURE_SUMMARY: 14.0,
            IndexFieldKind.RECORDING_TIMELINE: 12.0,
            IndexFieldKind.CLEAN_PAGE_TEXT: 10.0,
            IndexFieldKind.CANONICAL_TEXT: 5.0,
            IndexFieldKind.HUMAN_DEMO_SUMMARY: 5.0,
        }.get(field_kind, 0.0)

    def _match_reason(self, field_kind: IndexFieldKind) -> SearchMatchReason:
        return {
            IndexFieldKind.SELECTION_TEXT: SearchMatchReason.SELECTION_TEXT,
            IndexFieldKind.VISUAL_OCR_TEXT: SearchMatchReason.VISUAL_OCR_TEXT,
            IndexFieldKind.CANONICAL_TEXT: SearchMatchReason.CANONICAL_TEXT,
            IndexFieldKind.CLEAN_PAGE_TEXT: SearchMatchReason.CLEAN_PAGE_TEXT,
            IndexFieldKind.USER_NOTE: SearchMatchReason.USER_NOTE,
            IndexFieldKind.ACTIVE_CAPTURE_SUMMARY: SearchMatchReason.ACTIVE_CAPTURE_SUMMARY,
            IndexFieldKind.RECORDING_TIMELINE: SearchMatchReason.RECORDING_TIMELINE,
            IndexFieldKind.HUMAN_DEMO_SUMMARY: SearchMatchReason.HUMAN_DEMO_SUMMARY,
        }.get(field_kind, SearchMatchReason.METADATA)

    def _empty_facets(self) -> dict[str, tuple[str, ...]]:
        return {key: () for key in self._facet_columns()}

    def _facet_columns(self) -> dict[str, str]:
        return {
            "apps": "app_name",
            "origins": "origin",
            "source_types": "source_type",
            "providers": "provider_key",
            "workspaces": "workspace_id",
        }

    def _merge_hits(self, first: tuple[IndexHit, ...], second: tuple[IndexHit, ...]) -> tuple[IndexHit, ...]:
        by_key: dict[tuple[str, str | None], IndexHit] = {}
        for hit in (*first, *second):
            key = (hit.event_id, hit.chunk_id)
            current = by_key.get(key)
            if current is None or hit.score > current.score:
                by_key[key] = hit
        return tuple(sorted(by_key.values(), key=lambda hit: hit.score, reverse=True))

    def _filter_sql(
        self,
        filters: SearchFilters,
        *,
        include_status: bool,
        table_alias: str | None = None,
    ) -> tuple[str, tuple[object, ...]]:
        prefix = f"{table_alias}." if table_alias else ""
        clauses: list[str] = []
        params: list[object] = []
        if include_status:
            clauses.append(f"{prefix}event_status NOT IN ('deleted', 'restricted')")
        if filters.since is not None:
            clauses.append(f"{prefix}captured_at >= ?")
            params.append(filters.since.isoformat())
        if filters.until is not None:
            clauses.append(f"{prefix}captured_at <= ?")
            params.append(filters.until.isoformat())
        if filters.workspace:
            clauses.append(f"{prefix}workspace_id = ?")
            params.append(filters.workspace)
        if filters.app:
            clauses.append(f"lower(coalesce({prefix}app_name, '')) LIKE ?")
            params.append(f"%{filters.app.lower()}%")
        if filters.domain:
            clauses.append(f"lower(coalesce({prefix}origin, '')) LIKE ?")
            params.append(f"%{filters.domain.lower()}%")
        if filters.origin:
            clauses.append(f"{prefix}origin = ?")
            params.append(filters.origin)
        if filters.source:
            clauses.append(f"{prefix}source_type = ?")
            params.append(filters.source.value)
        if filters.provider:
            clauses.append(f"{prefix}provider_key = ?")
            params.append(filters.provider)
        if filters.event_type:
            clauses.append(f"json_extract({prefix}payload, '$.metadata.event_type') = ?")
            params.append(filters.event_type)
        if filters.evidence_kind:
            clauses.append(f"{prefix}evidence_kind = ?")
            params.append(filters.evidence_kind.value)
        if filters.status:
            clauses.append(f"{prefix}event_status = ?")
            params.append(filters.status.value)
        if filters.sensitivity:
            clauses.append(f"{prefix}sensitivity = ?")
            params.append(filters.sensitivity.value)
        if filters.entity:
            clauses.append(f"lower({prefix}search_text || ' ' || coalesce({prefix}title, '')) LIKE ?")
            params.append(f"%{filters.entity.lower()}%")
        if filters.project:
            clauses.append(f"lower({prefix}search_text || ' ' || coalesce({prefix}title, '')) LIKE ?")
            params.append(f"%{filters.project.lower()}%")
        if filters.user:
            user_filter = filters.user
            if user_filter.query:
                clauses.append(
                    f"lower(coalesce({prefix}user_id, '') || ' ' || coalesce({prefix}user_display_name, '')) LIKE ?"
                )
                params.append(f"%{user_filter.query.lower()}%")
            if user_filter.user_id:
                clauses.append(f"{prefix}user_id = ?")
                params.append(user_filter.user_id)
            if user_filter.display_name:
                clauses.append(f"lower(coalesce({prefix}user_display_name, '')) LIKE ?")
                params.append(f"%{user_filter.display_name.lower()}%")
            if user_filter.identity_provider:
                clauses.append(f"json_extract({prefix}payload, '$.metadata.user_identity_provider') = ?")
                params.append(user_filter.identity_provider.value)
            if user_filter.tenant_key:
                clauses.append(f"json_extract({prefix}payload, '$.metadata.user_tenant_key') = ?")
                params.append(user_filter.tenant_key)
            if user_filter.feishu_open_id:
                clauses.append(f"json_extract({prefix}payload, '$.metadata.user_feishu_open_id') = ?")
                params.append(user_filter.feishu_open_id)
        return (f"WHERE {' AND '.join(clauses)}" if clauses else "", tuple(params))

    def _fts_query(self, query: str) -> str:
        terms = re.findall(r"[\w.-]+", query.lower())
        return " ".join(f'"{term}"' for term in terms[:12])

    def _ngrams(self, text: str) -> tuple[str, ...]:
        normalized = re.sub(r"\s+", "", text.lower())
        grams: Counter[str] = Counter()
        for size in (2, 3):
            if len(normalized) < size:
                continue
            for index in range(0, len(normalized) - size + 1):
                gram = normalized[index : index + size]
                if self._contains_non_ascii(gram):
                    grams[gram] += 1
        return tuple(grams)

    def _contains_non_ascii(self, text: str) -> bool:
        return any(ord(char) > 127 for char in text)

    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
