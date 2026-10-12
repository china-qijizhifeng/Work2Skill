"""Privacy-preserving click target label policy."""

from __future__ import annotations

import re
from hashlib import sha256

from packages.contracts import ClickTargetSemanticKind

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")
_WHITESPACE = re.compile(r"\s+")
_SENSITIVE = re.compile(
    r"(should_not_leak|password|passwd|secret|token|bearer|api[_-]?key|"
    r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|https?://\S*[?#]\S+)",
    re.IGNORECASE,
)


class ClickTargetLabelPolicy:
    """Normalize, redact, and shorten labels before they cross public boundaries."""

    def __init__(self, *, max_chars: int) -> None:
        self.max_chars = max_chars

    def safe_label(self, raw_label: str | None, *, semantic_kind: ClickTargetSemanticKind) -> str | None:
        """Return a short display label or None when the text is sensitive."""

        if raw_label is None:
            return None
        normalized = _WHITESPACE.sub(" ", _CONTROL_CHARS.sub(" ", raw_label)).strip()
        if not normalized or _SENSITIVE.search(normalized):
            return None
        if len(normalized) > self.max_chars:
            normalized = f"{normalized[: self.max_chars - 1].rstrip()}…"
        if semantic_kind == ClickTargetSemanticKind.SEARCH_FIELD and "搜索" not in normalized.lower():
            return normalized or "搜索框"
        return normalized

    def fallback_label(self, semantic_kind: ClickTargetSemanticKind) -> str:
        """Return a low-sensitivity Chinese fallback for an inferred target kind."""

        return {
            ClickTargetSemanticKind.BUTTON: "按钮",
            ClickTargetSemanticKind.LINK: "链接",
            ClickTargetSemanticKind.INPUT: "输入框",
            ClickTargetSemanticKind.SEARCH_FIELD: "搜索框",
            ClickTargetSemanticKind.MENU_ITEM: "菜单项",
            ClickTargetSemanticKind.NAV_ITEM: "导航项",
            ClickTargetSemanticKind.TAB: "标签页",
            ClickTargetSemanticKind.CHECKBOX: "复选框",
            ClickTargetSemanticKind.WINDOW: "窗口",
            ClickTargetSemanticKind.UNKNOWN: "目标待确认",
        }[semantic_kind]

    def label_fingerprint(self, label: str | None) -> str | None:
        """Hash a label without retaining the raw string."""

        if label is None:
            return None
        return sha256(label.encode("utf-8")).hexdigest()
