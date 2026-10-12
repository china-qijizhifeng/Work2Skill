"""Agent-facing search output compaction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum


class SearchCardField(StrEnum):
    """Fields intentionally exposed by `workrecorder events search` and `workrecorder events grep`."""

    EVENT_ID = "event_id"
    CAPTURED_AT = "captured_at"
    APP = "app"
    TITLE = "title"
    URL = "url"
    USER_NOTE = "user_note"
    SELECTION_TEXT = "selection_text"
    AVAILABLE_FIELDS = "available_fields"


class InspectableField(StrEnum):
    """Explicit follow-up fields an agent may request with `events inspect`."""

    SELECTION_TEXT = "selection_text"
    CANONICAL = "canonical"
    CLEAN_PAGE_TEXT = "clean_page_text"
    SCREENSHOT_REF = "screenshot_ref"
    SYSTEM_APPSHOT = "system_appshot"
    EVIDENCE_REFS = "evidence_refs"
    ARTIFACT_METADATA = "artifact_metadata"


class SearchOutputCompactor:
    """Collapse daemon search cards into the rough-search view agents should see."""

    selection_text_max_chars = 800

    def compact_envelope(self, payload: Mapping[str, object]) -> dict[str, object]:
        """Return an agent-facing copy of a search response envelope.

        The daemon response may contain policy/debug fields needed by Workbench,
        audit, citations, or future UI. The CLI search surface is deliberately
        smaller: enough to decide which `event_id` to inspect, not enough to
        smuggle detailed evidence into rough search.

        Args:
            payload: Decoded daemon response envelope.

        Returns:
            A compact response envelope for CLI rough search output.
        """

        data = payload.get("data")
        if not isinstance(data, Mapping):
            return dict(payload)
        results = data.get("results")
        if not isinstance(results, Sequence) or isinstance(results, (str, bytes, bytearray)):
            return dict(payload)

        compact_data: dict[str, object] = {
            "results": tuple(self._compact_card(card) for card in results if isinstance(card, Mapping)),
        }
        cursor = data.get("cursor")
        if isinstance(cursor, Mapping) and any(cursor.values()):
            compact_data["cursor"] = dict(cursor)
        if data.get("degraded") is True:
            compact_data["degraded"] = True
        compact_payload = dict(payload)
        compact_payload["data"] = compact_data
        return compact_payload

    def _compact_card(self, card: Mapping[str, object]) -> dict[str, object]:
        source = card.get("source")
        source_map = source if isinstance(source, Mapping) else {}
        selection_text, selection_truncated = self._bounded_selection_text(card)
        compact: dict[str, object] = {
            SearchCardField.EVENT_ID.value: self._string(card.get("event_id")),
            SearchCardField.CAPTURED_AT.value: self._string(card.get("captured_at")),
            SearchCardField.APP.value: self._string(source_map.get("app_name")),
            SearchCardField.TITLE.value: self._string(source_map.get("title")),
            SearchCardField.URL.value: self._string(source_map.get("sanitized_url")),
            SearchCardField.USER_NOTE.value: self._optional_string(card.get("user_note")),
            SearchCardField.SELECTION_TEXT.value: selection_text,
            "selection_text_truncated": selection_truncated,
            SearchCardField.AVAILABLE_FIELDS.value: tuple(field.value for field in self._available_fields(card)),
        }
        return compact

    def _bounded_selection_text(self, card: Mapping[str, object]) -> tuple[str, bool]:
        text = self._clean_selection_text(self._string(card.get("selection_text")))
        already_truncated = bool(card.get("selection_text_truncated"))
        if len(text) <= self.selection_text_max_chars:
            return text, already_truncated
        clipped = text[: self.selection_text_max_chars].rstrip()
        return f"{clipped}\n[truncated: use events inspect --view selection_text for full text]", True

    def _clean_selection_text(self, text: str) -> str:
        cleaned_lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped in {"## Visual OCR evidence", "## Visual OCR warnings"}:
                if stripped == "## Visual OCR warnings":
                    break
                continue
            if stripped.startswith("The following block is transcribed from a screenshot."):
                continue
            if stripped == ">":
                continue
            if stripped.startswith("> "):
                stripped = stripped[2:].strip()
            cleaned_lines.append(stripped)
        return "\n".join(cleaned_lines).strip()

    def _available_fields(self, card: Mapping[str, object]) -> tuple[InspectableField, ...]:
        source = card.get("source")
        source_map = source if isinstance(source, Mapping) else {}
        fields = [
            InspectableField.SELECTION_TEXT,
            InspectableField.SYSTEM_APPSHOT,
            InspectableField.SCREENSHOT_REF,
            InspectableField.EVIDENCE_REFS,
            InspectableField.ARTIFACT_METADATA,
        ]
        if self._string(source_map.get("sanitized_url")):
            fields.insert(1, InspectableField.CANONICAL)
            fields.insert(2, InspectableField.CLEAN_PAGE_TEXT)
        return tuple(dict.fromkeys(fields))

    def _optional_string(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text or None

    def _string(self, value: object) -> str:
        return "" if value is None else str(value)
