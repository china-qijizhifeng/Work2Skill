"""Module entry point for WorkRecorder routing and audit APIs."""

from .sqlite_keyword import SQLiteKeywordIndexBackend

__all__ = ["SQLiteKeywordIndexBackend"]
