"""Compose immutable share snapshots from disclosure-approved event views."""

from __future__ import annotations

import hashlib
import json
import logging
from builtins import list as builtin_list
from typing import cast

from pydantic import BaseModel

from packages.artifacts.vault import ArtifactVaultError, LocalArtifactVault
from packages.contracts import (
    ActorRef,
    Artifact,
    ArtifactType,
    ContextEvent,
    ContextShare,
    EventInspectSection,
    SharePackageManifest,
    ShareSnapshot,
)
from packages.disclosure import DisclosurePolicyService
from packages.safety import safe_public_payload
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from packages.storage.artifact_repository import ArtifactRepository

from .package import SharePackage, SharePackageBuilder

logger = logging.getLogger(__name__)

SCREENSHOT_TYPES = {
    ArtifactType.SCREENSHOT,
    ArtifactType.OS_REGION_SCREENSHOT,
    ArtifactType.OS_REGION_CROP,
}


class ShareSnapshotComposer:
    """Build frozen share snapshots without owning share lifecycle decisions."""

    def __init__(
        self,
        *,
        disclosure: DisclosurePolicyService,
        artifacts: ArtifactRepository,
        vault: LocalArtifactVault,
        ids: IdFactory,
        clock: Clock,
        package_builder: SharePackageBuilder,
    ) -> None:
        self.disclosure = disclosure
        self.artifacts = artifacts
        self.vault = vault
        self.ids = ids
        self.clock = clock
        self.package_builder = package_builder

    def build(
        self,
        *,
        share: ContextShare,
        event: ContextEvent,
        actor: ActorRef,
        revision_number: int,
    ) -> tuple[ShareSnapshot, SharePackage]:
        """Create the snapshot record plus static package for one revision.

        Args:
            share: Share ledger row being materialized.
            event: Local event whose safe views are being frozen.
            actor: Actor requesting the share; forwarded to disclosure policy.
            revision_number: Immutable share revision number.

        Returns:
            Snapshot metadata and rendered package bytes.
        """

        card = self.disclosure.summary_card(event=event)
        inspect = self.disclosure.inspect_event(
            event=event,
            actor=actor,
            purpose="context_share",
            requested_sections=(
                EventInspectSection.SYSTEM_APPSHOT,
                EventInspectSection.SELECTION_TEXT,
                EventInspectSection.VISUAL_OCR_TEXT,
                EventInspectSection.CANONICAL,
                EventInspectSection.CLEAN_PAGE_TEXT,
                EventInspectSection.SCREENSHOT_REF,
                EventInspectSection.EVIDENCE_REFS,
            ),
        )
        screenshot_artifact = self._screenshot_artifact(event.event_id)
        screenshot_png = self._screenshot_bytes(screenshot_artifact)
        safe_context = self._safe_context_payload(card=card, inspect=inspect, share=share)
        payload_json = json.dumps(safe_context, ensure_ascii=False, sort_keys=True).encode("utf-8")
        snapshot = ShareSnapshot(
            snapshot_id=self.ids.new("shr_snap"),
            share_id=share.share_id,
            event_id=share.event_id,
            revision=revision_number,
            payload_hash=hashlib.sha256(payload_json).hexdigest(),
            payload_json=safe_context,
            delivered_fields=tuple(sorted(safe_context.keys())),
            screenshot_artifact_id=screenshot_artifact.artifact_id if screenshot_artifact is not None else None,
            screenshot_sha256=screenshot_artifact.sha256 if screenshot_artifact is not None else None,
            created_at=self.clock.now(),
        )
        package = self.package_builder.build(
            share_id=share.share_id,
            event_id=share.event_id,
            revision=revision_number,
            safe_context=safe_context,
            screenshot_png=screenshot_png,
        )
        return snapshot, package

    def _safe_context_payload(
        self,
        *,
        card: object,
        inspect: object,
        share: ContextShare,
    ) -> dict[str, object]:
        card_json = _model_json(card)
        inspect_json = _model_json(inspect)
        readable_raw = inspect_json.get("readable_evidence")
        readable_items = readable_raw if isinstance(readable_raw, list) else []
        visual_ocr_text = _first_visual_ocr_text(readable_items)
        payload = {
            "share_id": share.share_id,
            "event_id": share.event_id,
            "scope": share.scope.value,
            "created_by": share.created_by.model_dump(mode="json"),
            "user": share.user.model_dump(mode="json"),
            "captured_at": card_json.get("captured_at"),
            "summary_card": card_json,
            "source_contributions": inspect_json.get("source_contributions", []),
            "system_appshot": inspect_json.get("system_appshot"),
            "canonical_text": inspect_json.get("canonical_text") or "",
            "clean_page_text": inspect_json.get("clean_page_text") or "",
            "visual_ocr_text": visual_ocr_text,
            "readable_evidence": readable_items,
            "hidden_materials": card_json.get("hidden_artifacts", []),
            "available_fields": self._available_fields(card_json, inspect_json, visual_ocr_text),
            "policy": {
                "disclosure_policy_version": card_json.get("disclosure_policy_version"),
                "raw_dom_uploaded": False,
                "raw_a11y_tree_uploaded": False,
                "url_query_hash_uploaded": False,
            },
        }
        return cast(dict[str, object], safe_public_payload(payload))

    def _available_fields(
        self,
        card: dict[str, object],
        inspect: dict[str, object],
        visual_ocr_text: str,
    ) -> builtin_list[str]:
        fields = ["event_id", "captured_at", "app", "title"]
        source = card.get("source") if isinstance(card.get("source"), dict) else {}
        if isinstance(source, dict) and source.get("sanitized_url"):
            fields.append("sanitized_url")
        if card.get("user_note"):
            fields.append("user_note")
        if card.get("selection_text"):
            fields.append("selection_text")
        if inspect.get("canonical_text"):
            fields.append("canonical_text")
        if inspect.get("clean_page_text"):
            fields.append("clean_page_text")
        if visual_ocr_text:
            fields.append("visual_ocr_text")
        fields.append("screenshot_ref")
        return fields

    def _screenshot_artifact(self, event_id: str) -> Artifact | None:
        candidates = [
            artifact
            for artifact in self.artifacts.list_for_event(event_id)
            if artifact.artifact_type in SCREENSHOT_TYPES
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda artifact: artifact.created_at)[0]

    def _screenshot_bytes(self, artifact: Artifact | None) -> bytes | None:
        if artifact is None or not artifact.storage_uri:
            return None
        try:
            return self.vault.read(artifact.storage_uri)
        except ArtifactVaultError:
            logger.warning("share package could not read screenshot", extra={"artifact_id": artifact.artifact_id})
            return None


def _model_json(value: object) -> dict[str, object]:
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _first_visual_ocr_text(readable_items: list[object]) -> str:
    for item in readable_items:
        if isinstance(item, dict) and item.get("artifact_type") == ArtifactType.VISUAL_OCR_TEXT.value:
            return str(item.get("text") or "")
    return ""
