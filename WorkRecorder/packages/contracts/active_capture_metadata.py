"""Shared metadata privacy rules for active-capture contracts."""

from __future__ import annotations

from .active_capture_enums import SensitiveActionMetadataKey
from .common import JsonScalar

SENSITIVE_METADATA_EXACT_KEYS = frozenset(item.value for item in SensitiveActionMetadataKey) | {
    "a11y_label",
    "accessible_name",
    "accessibility_label",
    "aria_label",
    "ax_path",
    "characters",
    "clipboard_text",
    "dom_path",
    "element_label",
    "input_text",
    "local_path",
    "node_label",
    "ocr_lines",
    "ocr_text",
    "plain_text",
    "raw_character",
    "raw_key",
    "raw_selector",
    "raw_text",
    "selector",
    "storage_uri",
    "typed_characters",
    "typed_text",
}
SENSITIVE_METADATA_FRAGMENTS = (
    "a11y",
    "accessible_name",
    "accessibility",
    "aria",
    "ax_path",
    "character",
    "clipboard",
    "dom_path",
    "input",
    "keystroke",
    "local_path",
    "label",
    "node",
    "ocr",
    "ocr_text",
    "password",
    "raw",
    "secret",
    "selector",
    "storage",
    "text",
    "token",
    "typed",
    "value",
)


def canonical_metadata_key(key: str) -> str:
    """Normalize metadata keys so camelCase and snake_case are audited equally.

    Args:
        key: Metadata key supplied by a native producer or backend service.

    Returns:
        Lowercase underscore-separated key suitable for exact and fragment checks.
    """

    normalized: list[str] = []
    previous_lower = False
    for char in key.strip():
        if char.isupper() and previous_lower:
            normalized.append("_")
        normalized.append(char.lower() if char.isalnum() else "_")
        previous_lower = char.islower() or char.isdigit()
    return "_".join(part for part in "".join(normalized).split("_") if part)


def validate_safe_metadata(
    metadata: dict[str, JsonScalar],
    *,
    context: str,
    extra_exact_keys: frozenset[str] = frozenset(),
    extra_fragments: tuple[str, ...] = (),
) -> None:
    """Reject metadata keys that could carry raw user or local-machine data.

    Args:
        metadata: Metadata bag to validate.
        context: Human-readable owner used in validation errors.
        extra_exact_keys: Additional exact canonical keys blocked by a caller.
        extra_fragments: Additional canonical key fragments blocked by a caller.

    Raises:
        ValueError: If a metadata key could contain sensitive user or machine data.
    """

    canonical_keys = {canonical_metadata_key(key) for key in metadata}
    exact_keys = SENSITIVE_METADATA_EXACT_KEYS | extra_exact_keys
    fragments = (*SENSITIVE_METADATA_FRAGMENTS, *extra_fragments)
    forbidden = set(exact_keys.intersection(canonical_keys))
    forbidden.update(key for key in canonical_keys if any(fragment in key.split("_") for fragment in fragments))
    if forbidden:
        keys = ", ".join(sorted(forbidden))
        raise ValueError(f"{context} includes forbidden sensitive metadata keys: {keys}")
