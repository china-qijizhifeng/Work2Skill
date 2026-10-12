"""Small view helpers for disclosure response builders."""

from __future__ import annotations

from typing import cast
from urllib.parse import urlsplit, urlunsplit

from packages.contracts import ContextEvent, SearchMatchReason, SearchResultSource
from packages.safety import safe_public_payload


class BoundedText:
    """Text plus truncation state after a disclosure limit is applied."""

    def __init__(self, text: str, truncated: bool) -> None:
        self.text = text
        self.truncated = truncated


def source_for_event(event: ContextEvent) -> SearchResultSource:
    """Build the safe source summary for an event.

    Args:
        event: Context event whose source metadata should be exposed.

    Returns:
        Source summary with origin and URL query/fragment removed.
    """

    source_ref = event.source_binding.source_ref
    app_name = safe_public_payload(source_ref.app_name)
    title = safe_public_payload(source_ref.title)
    origin_payload = cast(dict[str, object], safe_public_payload({"origin": sanitized_url(source_ref.origin)}))
    sanitized_payload = cast(dict[str, object], safe_public_payload({"sanitized_url": sanitized_url(source_ref.url)}))
    origin = origin_payload.get("origin")
    sanitized = sanitized_payload.get("sanitized_url")
    return SearchResultSource(
        app_name=app_name if isinstance(app_name, str) else "",
        title=title if isinstance(title, str) else "",
        origin=origin if isinstance(origin, str) else None,
        sanitized_url=sanitized if isinstance(sanitized, str) else None,
    )


def sanitized_url(url: str | None) -> str | None:
    """Remove query and fragment from a URL-like source reference.

    Args:
        url: Raw URL-like value from a source binding.

    Returns:
        URL without query or fragment, or ``None`` for empty input.
    """

    if not url:
        return None
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def bounded_text(text: str, *, limit: int) -> BoundedText:
    """Apply a character limit while preserving an explicit truncation marker.

    Args:
        text: Text to bound.
        limit: Maximum number of characters before the marker is appended.

    Returns:
        Bounded text object with an explicit truncation flag.
    """

    if len(text) <= limit:
        return BoundedText(text, False)
    return BoundedText(text[:limit].rstrip() + "\n[TRUNCATED]", True)


def snippet(text: str, *, query: str, limit: int = 500) -> str:
    """Build a short preview around the query when possible.

    Args:
        text: Candidate text used for preview.
        query: Optional query to center the snippet around.
        limit: Maximum preview length.

    Returns:
        Query-centered snippet when possible, otherwise a leading preview.
    """

    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    if query:
        index = normalized.lower().find(query.lower())
        if index >= 0:
            start = max(0, index - (limit // 3))
            end = min(len(normalized), start + limit)
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(normalized) else ""
            return f"{prefix}{normalized[start:end].strip()}{suffix}"
    return normalized[:limit].strip() + "..."


def match_reason(*, query: str, selection_text: str, canonical_text: str, event: ContextEvent) -> SearchMatchReason:
    """Explain why an event matched a search result card.

    Args:
        query: User or agent query text.
        selection_text: Default selection text for the event.
        canonical_text: Canonical text considered by search.
        event: Event metadata used for title/note fallbacks.

    Returns:
        Stable reason for safe result-card diagnostics.
    """

    normalized_query = query.lower()
    if normalized_query and normalized_query in selection_text.lower():
        return SearchMatchReason.SELECTION_TEXT
    if normalized_query and normalized_query in canonical_text.lower():
        return SearchMatchReason.CANONICAL_TEXT
    if normalized_query and normalized_query in (event.intent_text or "").lower():
        return SearchMatchReason.INTENT
    if normalized_query and normalized_query in event.source_binding.source_ref.title.lower():
        return SearchMatchReason.TITLE
    if not normalized_query:
        return SearchMatchReason.RECENT
    return SearchMatchReason.METADATA
