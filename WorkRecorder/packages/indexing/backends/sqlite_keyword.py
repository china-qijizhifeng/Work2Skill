"""SQLite keyword index backend with FTS5 and ngram fallback."""

from __future__ import annotations

from packages.contracts import IndexHit
from packages.indexing.backends.sqlite_keyword_internals import _SQLiteKeywordBackendInternals
from packages.indexing.contracts import (
    IndexFieldKind,
    IndexHealth,
    IndexQuery,
    IndexReceipt,
    IndexWriteBatch,
)
from packages.storage.database import SQLiteDatabase


class SQLiteKeywordIndexBackend(_SQLiteKeywordBackendInternals):
    """Local keyword backend for daemon-owned redacted text projections."""

    name = "sqlite_keyword"
    version = "sqlite_keyword_v1"

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database
        self._fts_available = False
        self._ensure_schema()

    def upsert(self, batch: IndexWriteBatch) -> IndexReceipt:
        """Insert or replace one batch of index documents.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        indexed = 0
        skipped = 0
        with self.database.transaction() as connection:
            existing_count = self._delete_event(connection, batch.event_id) if batch.replace_event else 0
            for prefix in batch.replace_chunk_prefixes:
                existing_count += self._delete_chunk_prefix(connection, prefix)
            for document in batch.documents:
                if not document.text.strip():
                    skipped += 1
                    continue
                self._delete_chunk(connection, document.chunk_id)
                connection.execute(
                    """
                    INSERT OR REPLACE INTO keyword_index_documents(
                      chunk_id, document_id, event_id, evidence_id, artifact_id,
                      provider_key, source_uri, captured_at, observed_at,
                      extractor_name, extractor_version, policy_version,
                      disclosure_class, evidence_kind, artifact_type, sensitivity,
                      redaction_state, event_status, field_kind, text_hash,
                      title, app_name, origin, sanitized_url, source_type,
                      workspace_id, user_id, user_display_name, search_text, payload
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._document_row(document),
                )
                if self._fts_available:
                    connection.execute(
                        """
                        INSERT INTO keyword_index_fts(
                          chunk_id, search_text, title, user_note,
                          selection_text, canonical_text, clean_page_text
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            document.chunk_id,
                            document.text,
                            document.title or "",
                            document.text if document.field_kind == IndexFieldKind.USER_NOTE else "",
                            document.text if document.field_kind == IndexFieldKind.SELECTION_TEXT else "",
                            document.text if document.field_kind == IndexFieldKind.CANONICAL_TEXT else "",
                            document.text if document.field_kind == IndexFieldKind.CLEAN_PAGE_TEXT else "",
                        ),
                    )
                for gram in self._ngrams(document.text):
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO keyword_index_ngrams(gram, chunk_id, event_id)
                        VALUES (?, ?, ?)
                        """,
                        (gram, document.chunk_id, document.event_id),
                    )
                indexed += 1
        return IndexReceipt(
            backend=self.name,
            backend_version=self.version,
            event_id=batch.event_id,
            indexed_count=indexed,
            deleted_count=existing_count,
            skipped_count=skipped,
            degraded=not self._fts_available,
            details={"fts_available": self._fts_available},
        )

    def delete_event(self, event_id: str) -> IndexReceipt:
        """Delete all rows for one event.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        with self.database.transaction() as connection:
            deleted_count = self._delete_event(connection, event_id)
        return IndexReceipt(
            backend=self.name,
            backend_version=self.version,
            event_id=event_id,
            deleted_count=deleted_count,
            degraded=not self._fts_available,
        )

    def search(self, query: IndexQuery) -> tuple[IndexHit, ...]:
        """Return safe hit references for the query.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        normalized = query.query.strip()
        if not normalized:
            return self._recent(query)
        hits = self._fts_search(query) if self._fts_available and self._fts_query(normalized) else ()
        if not hits:
            hits = self._like_search(query)
        if self._contains_non_ascii(normalized):
            hits = self._merge_hits(hits, self._ngram_search(query))
        return hits[: query.limit]

    def facets(self, query: IndexQuery) -> dict[str, tuple[str, ...]]:
        """Return safe facets for sources/entities CLI helpers.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        where_sql, params = self._filter_sql(query.filters, include_status=True)
        return self._facets(where_sql=where_sql, params=params)

    def facets_for_event_ids(self, query: IndexQuery, event_ids: set[str]) -> dict[str, tuple[str, ...]]:
        """Return safe facets constrained to live-visible event ids.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        if not event_ids:
            return self._empty_facets()
        where_sql, params = self._filter_sql(query.filters, include_status=True)
        placeholders = ", ".join("?" for _ in event_ids)
        event_clause = f"event_id IN ({placeholders})"
        where_sql = f"{where_sql} AND {event_clause}" if where_sql else f"WHERE {event_clause}"
        return self._facets(where_sql=where_sql, params=(*params, *sorted(event_ids)))

    def _facets(self, *, where_sql: str, params: tuple[object, ...]) -> dict[str, tuple[str, ...]]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT app_name, origin, source_type, provider_key, workspace_id
                FROM keyword_index_documents
                {where_sql}
                ORDER BY captured_at DESC
                LIMIT 500
                """,
                params,
            ).fetchall()
        facets: dict[str, set[str]] = {key: set() for key in self._facet_columns()}
        for row in rows:
            for key, column in self._facet_columns().items():
                value = row[column]
                if value:
                    facets[key].add(str(value))
        return {key: tuple(sorted(values)) for key, values in facets.items()}

    def event_ids(self, query: IndexQuery) -> tuple[str, ...]:
        """Return event ids matching safe filters for live visibility checks.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        where_sql, params = self._filter_sql(query.filters, include_status=True)
        with self.database.transaction() as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT event_id
                FROM keyword_index_documents
                {where_sql}
                ORDER BY captured_at DESC
                LIMIT ?
                """,
                (*params, query.limit * 4),
            ).fetchall()
        return tuple(str(row["event_id"]) for row in rows)

    def explain(self, hit: IndexHit) -> IndexHit:
        """Return the hit with its existing safe explanation.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        return hit

    def health(self) -> IndexHealth:
        """Return backend health.

        Returns:
            Availability, degradation state, capabilities, and backend details.
        """

        return IndexHealth(
            backend=self.name,
            backend_version=self.version,
            available=True,
            degraded=not self._fts_available,
            capabilities=("keyword", "ngram", "facets", "explain"),
            details={"fts_available": self._fts_available},
        )

    def rebuild(self, batches: tuple[IndexWriteBatch, ...]) -> IndexReceipt:
        """Clear and rebuild all keyword index rows.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        with self.database.transaction() as connection:
            connection.execute("DELETE FROM keyword_index_ngrams")
            connection.execute("DELETE FROM keyword_index_documents")
            if self._fts_available:
                connection.execute("DELETE FROM keyword_index_fts")
        indexed = 0
        skipped = 0
        for batch in batches:
            receipt = self.upsert(batch)
            indexed += receipt.indexed_count
            skipped += receipt.skipped_count
        return IndexReceipt(
            backend=self.name,
            backend_version=self.version,
            indexed_count=indexed,
            skipped_count=skipped,
            degraded=not self._fts_available,
            details={"rebuild_batch_count": len(batches), "fts_available": self._fts_available},
        )
