"""Typed registry for index backend plug-ins."""

from __future__ import annotations

from packages.indexing.backends.base import IndexBackend


class IndexBackendRegistry:
    """Register and select index backends without leaking implementation details."""

    def __init__(self) -> None:
        self._backends: dict[str, IndexBackend] = {}
        self._default_backend: str | None = None

    def register(self, backend: IndexBackend, *, default: bool = False) -> None:
        """Register one backend.

        Args:
            backend: Index backend implementation to make available.
            default: Whether this backend should become the default choice.
        """

        self._backends[backend.name] = backend
        if default or self._default_backend is None:
            self._default_backend = backend.name

    def default(self) -> IndexBackend:
        """Return the default backend.

        Returns:
            The typed result described by the method contract.

        Raises:
            Propagates validation or persistence errors when the operation cannot complete."""

        if self._default_backend is None:
            raise RuntimeError("no index backend registered")
        return self._backends[self._default_backend]

    def get(self, name: str) -> IndexBackend | None:
        """Return a backend by name.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        return self._backends.get(name)

    def list(self) -> tuple[IndexBackend, ...]:
        """Return all registered backends.

        Returns:
            The typed result described by the method contract."""

        return tuple(self._backends.values())
