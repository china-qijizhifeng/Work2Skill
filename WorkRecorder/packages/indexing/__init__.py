"""Pluggable index layer for agent-facing retrieval."""

from .contracts import IndexDocument, IndexHealth, IndexQuery, IndexReceipt, IndexWriteBatch
from .registry import IndexBackendRegistry
from .search import ContextBundleBuilder, SearchService
from .service import IndexingService

__all__ = [
    "IndexBackendRegistry",
    "IndexDocument",
    "IndexHealth",
    "IndexQuery",
    "IndexReceipt",
    "IndexWriteBatch",
    "IndexingService",
    "ContextBundleBuilder",
    "SearchService",
]
