"""Typed provider registries used by capture and source adapters."""

from __future__ import annotations

from typing import Generic, TypeVar

from packages.contracts import EvidenceKind, ProviderKind

from .base import NamedProvider, SourceCaptureProvider, SystemEvidenceProvider

TProvider = TypeVar("TProvider", bound=NamedProvider)


class ProviderRegistry(Generic[TProvider]):
    """Registry that avoids source-specific if-else dispatch."""

    def __init__(self) -> None:
        """Create an empty provider registry."""

        self._providers: dict[str, TProvider] = {}

    def register(self, provider: TProvider) -> None:
        """Register or replace a provider by name.

        Args:
            provider: Provider implementing the ``NamedProvider`` protocol.
        """

        self._providers[provider.name] = provider

    def get(self, name: str) -> TProvider | None:
        """Return a provider by name.

        Args:
            name: Provider name.

        Returns:
            Provider when registered.
        """

        return self._providers.get(name)

    def list(self) -> tuple[TProvider, ...]:
        """Return registered providers in stable name order.

        Returns:
            Registered providers sorted by provider name.
        """

        return tuple(self._providers[name] for name in sorted(self._providers))


class SourceProviderRegistry(ProviderRegistry[SourceCaptureProvider]):
    """Registry for capture-time source providers."""

    def register(self, provider: SourceCaptureProvider) -> None:
        """Register a source provider after validating SDK-required fields.

        Args:
            provider: Source provider implementation to register.

        Raises:
            ValueError: If the provider does not declare a typed capture
                evidence kind. This prevents future providers from silently
                falling back to Web evidence semantics.
        """

        evidence_kind = getattr(provider, "capture_evidence_kind", None)
        if not isinstance(evidence_kind, EvidenceKind):
            raise ValueError(f"source provider {provider.name} must declare capture_evidence_kind")
        super().register(provider)


class SystemEvidenceProviderRegistry(ProviderRegistry[SystemEvidenceProvider]):
    """Registry for common system evidence providers."""

    _default_order = {
        "system.screenshot": 0,
        "system.macos_a11y": 1,
        "system.appshot": 2,
    }

    def register(self, provider: SystemEvidenceProvider) -> None:
        """Register a system evidence provider after SDK shape validation.

        Args:
            provider: System evidence provider implementation.

        Raises:
            ValueError: If the provider does not declare a typed evidence kind.
        """

        evidence_kind = getattr(provider, "evidence_kind", None)
        if not isinstance(evidence_kind, EvidenceKind):
            raise ValueError(f"system provider {provider.name} must declare evidence_kind")
        manifest = provider.manifest
        if manifest.provider_key != provider.name:
            raise ValueError(f"system provider {provider.name} manifest key mismatch")
        if manifest.provider_kind != ProviderKind.SYSTEM_EVIDENCE:
            raise ValueError(f"system provider {provider.name} must declare system_evidence kind")
        if evidence_kind not in manifest.evidence_kinds:
            raise ValueError(f"system provider {provider.name} manifest must include evidence_kind")
        super().register(provider)

    def list(self) -> tuple[SystemEvidenceProvider, ...]:
        """Return system providers in capture-composition order.

        Returns:
            Registered system providers with screenshot before dependent
            metadata/composite providers.
        """

        return tuple(
            self._providers[name]
            for name in sorted(
                self._providers,
                key=lambda item: (self._default_order.get(item, 100), item),
            )
        )
