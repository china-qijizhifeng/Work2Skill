"""Search query parameter helpers for the CLI."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from packages.contracts import RetrievalMode, SearchSort


def search_params(
    *,
    query: str,
    mode: RetrievalMode,
    limit: int,
    since: str | None = None,
    until: str | None = None,
    workspace: str | None = None,
    app_name: str | None = None,
    domain: str | None = None,
    origin: str | None = None,
    source: str | None = None,
    provider: str | None = None,
    event_type: str | None = None,
    evidence_kind: str | None = None,
    status: str | None = None,
    sensitivity: str | None = None,
    entity: str | None = None,
    project: str | None = None,
    user: str | None = None,
    cursor: str | None = None,
    sort: SearchSort = SearchSort.SCORE,
    explain: bool = False,
) -> str:
    """Return encoded `/v1/search` query parameters.

    Args:
        query: Search text passed to the daemon.
        mode: Search mode selected by the CLI.
        limit: Maximum number of returned cards.
        since: Inclusive lower captured-at bound or relative window.
        until: Exclusive upper captured-at bound.
        workspace: Optional workspace filter.
        app_name: Optional app name filter.
        domain: Optional URL domain filter.
        origin: Optional URL origin filter.
        source: Optional source type filter.
        provider: Optional provider key filter.
        event_type: Optional event type filter.
        evidence_kind: Optional evidence kind filter.
        status: Optional event status filter.
        sensitivity: Optional evidence sensitivity filter.
        entity: Optional entity facet filter.
        project: Optional project facet filter.
        user: Optional user filter.
        cursor: Pagination cursor returned by a previous search.
        sort: Result ordering mode.
        explain: Whether to request backend ranking explanations.

    Returns:
        URL-encoded query string suitable for `/v1/search`.
    """

    params: dict[str, object] = {"query": query, "mode": mode.value, "limit": limit, "sort": sort.value}
    optional: dict[str, object | None] = {
        "since": _normalize_time_filter(since),
        "until": _normalize_time_filter(until),
        "workspace": workspace,
        "app": app_name,
        "domain": domain,
        "origin": origin,
        "source": source,
        "provider": provider,
        "event_type": event_type,
        "evidence_kind": evidence_kind,
        "status": status,
        "sensitivity": sensitivity,
        "entity": entity,
        "project": project,
        "user": user,
        "cursor": cursor,
    }
    params.update({key: value for key, value in optional.items() if value is not None})
    if explain:
        params["explain"] = "true"
    return urlencode(params)


def _normalize_time_filter(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("h", "d")) and text[:-1].isdigit():
        amount = int(text[:-1])
        delta = timedelta(hours=amount) if text.endswith("h") else timedelta(days=amount)
        return (datetime.now(UTC) - delta).isoformat()
    return text
