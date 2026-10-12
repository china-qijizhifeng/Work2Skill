"""SQLite connection and transaction helpers for WorkRecorder P0."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


class SQLiteDatabase:
    """Own the SQLite connection settings used by repositories.

    Attributes:
        path: Database file path. ``:memory:`` is supported for tests.
    """

    def __init__(self, path: Path | str) -> None:
        """Create a database handle wrapper.

        Args:
            path: SQLite database path or ``:memory:`` for tests.
        """

        self.path = path
        self._memory_connection: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Return a configured SQLite connection.

        Returns:
            Connection with row factory and foreign keys enabled.
        """

        if self.path == ":memory:":
            if self._memory_connection is None:
                self._memory_connection = self._create_connection(":memory:")
            return self._memory_connection
        db_path = Path(self.path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return self._create_connection(str(db_path))

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        """Run operations in one SQLite transaction.

        Args:
            immediate: When true, acquire the SQLite write lock before reads so
                count/check/insert sequences cannot race another writer.

        Yields:
            Configured SQLite connection.

        Returns:
            Iterator that yields one transaction-bound connection.

        Raises:
            Exception: Re-raises database operation failures after rollback.
        """

        connection = self.connect()
        try:
            if immediate:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            logger.exception("SQLite transaction failed; rolling back.")
            connection.rollback()
            raise
        finally:
            if self.path != ":memory:":
                connection.close()

    def _create_connection(self, path: str) -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection
