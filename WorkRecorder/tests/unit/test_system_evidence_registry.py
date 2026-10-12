from __future__ import annotations

from typing import cast

import pytest

from packages.capture.system_evidence import (
    A11Y_PROVIDER_KEY,
    APPSHOT_PROVIDER_KEY,
    SCREENSHOT_PROVIDER_KEY,
    register_default_system_evidence_providers,
)
from packages.contracts import (
    EvidenceKind,
    ProviderCapability,
    ProviderKind,
    ProviderManifest,
    ProviderMode,
    SourceType,
)
from packages.providers.base import SystemEvidenceProvider
from packages.providers.registry import SystemEvidenceProviderRegistry
from packages.providers.sessions import ProviderSessionService
from packages.shared.ids import IdFactory
from packages.shared.time import Clock


def test_default_system_evidence_registry_orders_capture_components() -> None:
    registry = SystemEvidenceProviderRegistry()
    register_default_system_evidence_providers(
        registry=registry,
        sessions=ProviderSessionService(clock=Clock()),
        ids=IdFactory(),
        clock=Clock(),
    )

    assert [provider.name for provider in registry.list()] == [
        SCREENSHOT_PROVIDER_KEY,
        A11Y_PROVIDER_KEY,
        APPSHOT_PROVIDER_KEY,
    ]


def test_system_evidence_registry_rejects_manifest_mismatch() -> None:
    class BadProvider:
        name = "system.bad"
        evidence_kind = EvidenceKind.SYSTEM_APPSHOT
        manifest = ProviderManifest(
            provider_key="source.bad",
            display_name="Bad Provider",
            provider_kind=ProviderKind.SOURCE,
            modes=(ProviderMode.SYSTEM,),
            source_types=(SourceType.DESKTOP_WINDOW,),
            capabilities=(ProviderCapability.COLLECT_SYSTEM_APPSHOT,),
            evidence_kinds=(EvidenceKind.SYSTEM_APPSHOT,),
        )

    registry = SystemEvidenceProviderRegistry()

    with pytest.raises(ValueError):
        registry.register(cast(SystemEvidenceProvider, BadProvider()))
