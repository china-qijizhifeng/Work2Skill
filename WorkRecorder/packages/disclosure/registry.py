"""Disclosure policy registry and default SDK profiles."""

from __future__ import annotations

import logging
from pathlib import Path

from packages.contracts import (
    AccessScope,
    ArtifactRole,
    ArtifactType,
    DisclosureClass,
    DisclosureProfile,
    DisclosureProfileOverride,
    DisclosureRule,
    DisclosureView,
    EvidenceKind,
    ProviderManifest,
    SourceBinding,
    SourceType,
    WorkspaceDisclosureConfig,
)

DEFAULT_PROFILE_KEY = "default.context_capture"
CHROME_PROFILE_KEY = "app.chrome.web_capture"
MAX_SUMMARY_TEXT_CHARS = 8000
MAX_INSPECT_TEXT_CHARS = 128000
RAW_VISUAL_ARTIFACT_TYPES = (
    ArtifactType.SCREENSHOT,
    ArtifactType.OS_REGION_SCREENSHOT,
    ArtifactType.OS_REGION_CROP,
)
SAFE_TEXT_DISCLOSURE_CLASSES = (
    DisclosureClass.SELECTION_BOUND_TEXT,
    DisclosureClass.VISUAL_OCR_TEXT,
    DisclosureClass.REDACTED_CANONICAL,
    DisclosureClass.CLEAN_PAGE_TEXT,
)

logger = logging.getLogger(__name__)


class DisclosurePolicyRegistry:
    """Typed registry for read-time disclosure profiles.

    Provider manifests and workspace overrides can register additional profiles
    without changing daemon routes. The daemon still owns final decisions.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, DisclosureProfile] = {}
        self._provider_profile_keys: dict[str, str] = {}
        self._workspace_override_warnings: tuple[str, ...] = ()
        self.register(_default_profile())
        self.register(_chrome_profile())

    def register(self, profile: DisclosureProfile) -> None:
        """Register or replace one disclosure profile.

        Args:
            profile: Profile to store under its typed profile key.
        """

        self._profiles[profile.profile_key] = profile
        for provider_key in profile.provider_keys:
            self._provider_profile_keys[provider_key] = profile.profile_key

    def list_profiles(self) -> tuple[DisclosureProfile, ...]:
        """Return registered profiles in stable key order.

        Returns:
            Registered disclosure profiles sorted by profile key.
        """

        return tuple(self._profiles[key] for key in sorted(self._profiles))

    def get(self, profile_key: str) -> DisclosureProfile | None:
        """Return one profile by key.

        Args:
            profile_key: Profile key to look up.

        Returns:
            Matching disclosure profile, otherwise ``None``.
        """

        return self._profiles.get(profile_key)

    def register_provider_manifest(self, manifest: ProviderManifest) -> None:
        """Bind one provider manifest to its disclosure profile when declared.

        Args:
            manifest: Provider manifest whose optional disclosure profile should be registered.
        """

        if manifest.disclosure_profile_key is None:
            return
        if manifest.disclosure_profile_key not in self._profiles:
            return
        self._provider_profile_keys[manifest.provider_key] = manifest.disclosure_profile_key

    def load_workspace_overrides(self, path: Path | None) -> tuple[DisclosureProfile, ...]:
        """Load workspace disclosure profiles from a typed JSON config file.

        The override file is a developer-facing SDK surface, not a privilege
        escalation point. Profiles are merged with built-ins and sanitized
        before registration, so unsafe raw-source/UI-tree rules are dropped.

        Args:
            path: Optional JSON config path.

        Returns:
            Sanitized profiles applied from the workspace override file.
        """

        if path is None:
            return ()
        expanded = path.expanduser()
        if not expanded.exists():
            return ()
        config = WorkspaceDisclosureConfig.model_validate_json(expanded.read_text(encoding="utf-8"))
        applied: list[DisclosureProfile] = []
        warnings: list[str] = []
        for override in config.profiles:
            profile = self._profile_from_override(override)
            sanitized, dropped = self._sanitized_workspace_profile(profile)
            warnings.extend(f"{override.profile_key}: {message}" for message in dropped)
            self.register(sanitized)
            applied.append(sanitized)
        self._workspace_override_warnings = tuple(warnings)
        logger.info(
            "workspace disclosure overrides loaded",
            extra={
                "path": str(expanded),
                "profile_count": len(applied),
                "dropped_rule_count": len(warnings),
            },
        )
        return tuple(applied)

    def workspace_override_warnings(self) -> tuple[str, ...]:
        """Return warnings produced while sanitizing workspace overrides.

        Returns:
            Human-readable warnings for dropped unsafe override rules.
        """

        return self._workspace_override_warnings

    def profile_for_source_binding(self, binding: SourceBinding) -> DisclosureProfile:
        """Return the best profile for a resolved source binding.

        Args:
            binding: Source binding on the event being disclosed.

        Returns:
            Most specific disclosure profile for the binding.
        """

        provider_keys = (
            binding.provider_key,
            binding.source_ref.connector_name,
        )
        for provider_key in provider_keys:
            if provider_key and provider_key in self._provider_profile_keys:
                return self._profiles[self._provider_profile_keys[provider_key]]
        return self.profile_for_app(binding.source_ref.app_name)

    def profile_for_app(self, app_name: str | None) -> DisclosureProfile:
        """Return the best profile for a source app name.

        Args:
            app_name: Application name reported by source detection.

        Returns:
            App-specific profile, or the default profile.
        """

        normalized = (app_name or "").strip().lower()
        for profile in self._profiles.values():
            if any(app.lower() == normalized for app in profile.app_names):
                return profile
        return self._profiles[DEFAULT_PROFILE_KEY]

    def profile_for_provider(self, provider_key: str | None) -> DisclosureProfile:
        """Return the best profile for a provider key.

        Args:
            provider_key: Provider key that produced evidence.

        Returns:
            Provider-specific profile, or the default profile.
        """

        if provider_key:
            profile_key = self._provider_profile_keys.get(provider_key)
            if profile_key is not None:
                return self._profiles[profile_key]
            for profile in self._profiles.values():
                if provider_key in profile.provider_keys:
                    return profile
        return self._profiles[DEFAULT_PROFILE_KEY]

    def _profile_from_override(self, override: DisclosureProfileOverride) -> DisclosureProfile:
        base = self._profiles.get(override.extends_profile_key)
        if base is None:
            raise ValueError(f"unknown disclosure profile base: {override.extends_profile_key}")
        rule_map = {rule.rule_id: rule for rule in (() if override.replace_rules else base.rules)}
        for rule in override.rules:
            rule_map[rule.rule_id] = rule
        return DisclosureProfile(
            profile_key=override.profile_key,
            display_name=override.display_name or f"{base.display_name} Workspace Override",
            version=override.version,
            provider_keys=override.provider_keys if override.provider_keys is not None else base.provider_keys,
            app_names=override.app_names if override.app_names is not None else base.app_names,
            source_types=override.source_types if override.source_types is not None else base.source_types,
            policy_tags=tuple(
                dict.fromkeys(
                    (
                        *(override.policy_tags if override.policy_tags is not None else base.policy_tags),
                        "workspace_override",
                    )
                )
            ),
            rules=tuple(rule_map[key] for key in sorted(rule_map)),
            metadata={
                **base.metadata,
                **override.metadata,
                "extends_profile_key": override.extends_profile_key,
                "workspace_override": True,
            },
        )

    def _sanitized_workspace_profile(self, profile: DisclosureProfile) -> tuple[DisclosureProfile, tuple[str, ...]]:
        rules: list[DisclosureRule] = []
        dropped: list[str] = []
        for rule in profile.rules:
            sanitized = self._sanitized_workspace_rule(rule)
            if sanitized is None:
                dropped.append(f"dropped unsafe rule {rule.rule_id}")
                continue
            rules.append(sanitized)
        metadata = {
            **profile.metadata,
            "sanitized_rule_count": len(rules),
            "dropped_rule_count": len(dropped),
        }
        return profile.model_copy(update={"rules": tuple(rules), "metadata": metadata}), tuple(dropped)

    def _sanitized_workspace_rule(self, rule: DisclosureRule) -> DisclosureRule | None:
        if rule.view == DisclosureView.SUMMARY_CARD:
            if rule.disclosure_class != DisclosureClass.SELECTION_BOUND_TEXT:
                return None
            return self._bounded_rule(
                rule.model_copy(update={"allow_raw": False}),
                allowed_scopes=(AccessScope.READ_TEXT,),
                max_chars=MAX_SUMMARY_TEXT_CHARS,
            )
        if rule.view in {DisclosureView.EVENT_INSPECT, DisclosureView.ARTIFACT_PREVIEW, DisclosureView.BUNDLE_ITEM}:
            if rule.disclosure_class not in SAFE_TEXT_DISCLOSURE_CLASSES:
                return None
            return self._bounded_rule(
                rule.model_copy(update={"allow_raw": False}),
                allowed_scopes=(AccessScope.READ_TEXT,),
                max_chars=MAX_INSPECT_TEXT_CHARS,
            )
        if rule.view == DisclosureView.RAW_ARTIFACT:
            if rule.disclosure_class != DisclosureClass.RAW_VISUAL:
                return None
            artifact_types = rule.artifact_types or RAW_VISUAL_ARTIFACT_TYPES
            if any(artifact_type not in RAW_VISUAL_ARTIFACT_TYPES for artifact_type in artifact_types):
                return None
            return rule.model_copy(
                update={
                    "artifact_types": artifact_types,
                    "allowed_scopes": tuple(
                        scope
                        for scope in (AccessScope.READ_RAW_ARTIFACT, AccessScope.READ_IMAGE)
                        if scope in set(rule.allowed_scopes)
                    )
                    or (AccessScope.READ_RAW_ARTIFACT,),
                    "allow_raw": bool(rule.allow_raw),
                }
            )
        if rule.view == DisclosureView.DEBUG_MANIFEST:
            return rule.model_copy(
                update={
                    "allow_raw": False,
                    "allowed_scopes": tuple(
                        scope for scope in rule.allowed_scopes if scope == AccessScope.READ_METADATA
                    )
                    or (AccessScope.READ_METADATA,),
                }
            )
        return None

    def _bounded_rule(
        self,
        rule: DisclosureRule,
        *,
        allowed_scopes: tuple[AccessScope, ...],
        max_chars: int,
    ) -> DisclosureRule:
        next_max = min(rule.max_chars or max_chars, max_chars)
        return rule.model_copy(
            update={
                "allowed_scopes": tuple(scope for scope in rule.allowed_scopes if scope in allowed_scopes)
                or allowed_scopes,
                "max_chars": next_max,
            }
        )


def _default_profile() -> DisclosureProfile:
    return DisclosureProfile(
        profile_key=DEFAULT_PROFILE_KEY,
        display_name="Default Context Capture Disclosure",
        app_names=(),
        source_types=(SourceType.WEB, SourceType.DESKTOP_WINDOW, SourceType.UNKNOWN),
        policy_tags=("safe_summary_card", "raw_denied_by_default"),
        rules=(
            DisclosureRule(
                rule_id="default.summary.selection_text",
                view=DisclosureView.SUMMARY_CARD,
                disclosure_class=DisclosureClass.SELECTION_BOUND_TEXT,
                artifact_types=(
                    ArtifactType.A11Y_SELECTION_TEXT,
                    ArtifactType.DOM_SELECTION_TEXT,
                ),
                artifact_roles=(ArtifactRole.SELECTION_TEXT,),
                evidence_kinds=(EvidenceKind.SELECTION_TEXT,),
                allowed_scopes=(AccessScope.READ_TEXT,),
                max_chars=4000,
            ),
            DisclosureRule(
                rule_id="default.preview.selection_text",
                view=DisclosureView.ARTIFACT_PREVIEW,
                disclosure_class=DisclosureClass.SELECTION_BOUND_TEXT,
                artifact_types=(
                    ArtifactType.A11Y_SELECTION_TEXT,
                    ArtifactType.DOM_SELECTION_TEXT,
                ),
                artifact_roles=(ArtifactRole.SELECTION_TEXT,),
                evidence_kinds=(EvidenceKind.SELECTION_TEXT,),
                allowed_scopes=(AccessScope.READ_TEXT,),
                max_chars=64000,
            ),
            DisclosureRule(
                rule_id="default.preview.visual_ocr_text",
                view=DisclosureView.ARTIFACT_PREVIEW,
                disclosure_class=DisclosureClass.VISUAL_OCR_TEXT,
                artifact_types=(ArtifactType.VISUAL_OCR_TEXT,),
                artifact_roles=(ArtifactRole.VISUAL_OCR_TEXT,),
                evidence_kinds=(EvidenceKind.VISUAL_OCR_TEXT,),
                allowed_scopes=(AccessScope.READ_TEXT,),
                max_chars=64000,
            ),
            DisclosureRule(
                rule_id="default.preview.canonical_text",
                view=DisclosureView.ARTIFACT_PREVIEW,
                disclosure_class=DisclosureClass.REDACTED_CANONICAL,
                artifact_types=(ArtifactType.CANONICAL_TEXT,),
                artifact_roles=(ArtifactRole.CANONICAL_TEXT,),
                evidence_kinds=(EvidenceKind.CANONICAL_TEXT,),
                allowed_scopes=(AccessScope.READ_TEXT,),
                max_chars=64000,
            ),
            DisclosureRule(
                rule_id="default.preview.clean_page_text",
                view=DisclosureView.ARTIFACT_PREVIEW,
                disclosure_class=DisclosureClass.CLEAN_PAGE_TEXT,
                artifact_types=(ArtifactType.CLEAN_PAGE_TEXT,),
                artifact_roles=(ArtifactRole.CLEAN_PAGE_TEXT,),
                evidence_kinds=(EvidenceKind.CLEAN_PAGE_TEXT,),
                allowed_scopes=(AccessScope.READ_TEXT,),
                max_chars=64000,
            ),
            DisclosureRule(
                rule_id="default.inspect.canonical_text",
                view=DisclosureView.EVENT_INSPECT,
                disclosure_class=DisclosureClass.REDACTED_CANONICAL,
                artifact_types=(ArtifactType.CANONICAL_TEXT,),
                artifact_roles=(ArtifactRole.CANONICAL_TEXT,),
                evidence_kinds=(EvidenceKind.CANONICAL_TEXT,),
                allowed_scopes=(AccessScope.READ_TEXT,),
                max_chars=64000,
            ),
            DisclosureRule(
                rule_id="default.inspect.selection_text",
                view=DisclosureView.EVENT_INSPECT,
                disclosure_class=DisclosureClass.SELECTION_BOUND_TEXT,
                artifact_types=(
                    ArtifactType.A11Y_SELECTION_TEXT,
                    ArtifactType.DOM_SELECTION_TEXT,
                ),
                artifact_roles=(ArtifactRole.SELECTION_TEXT,),
                evidence_kinds=(EvidenceKind.SELECTION_TEXT,),
                allowed_scopes=(AccessScope.READ_TEXT,),
                max_chars=64000,
            ),
            DisclosureRule(
                rule_id="default.inspect.visual_ocr_text",
                view=DisclosureView.EVENT_INSPECT,
                disclosure_class=DisclosureClass.VISUAL_OCR_TEXT,
                artifact_types=(ArtifactType.VISUAL_OCR_TEXT,),
                artifact_roles=(ArtifactRole.VISUAL_OCR_TEXT,),
                evidence_kinds=(EvidenceKind.VISUAL_OCR_TEXT,),
                allowed_scopes=(AccessScope.READ_TEXT,),
                max_chars=64000,
            ),
            DisclosureRule(
                rule_id="default.raw.screenshot",
                view=DisclosureView.RAW_ARTIFACT,
                disclosure_class=DisclosureClass.RAW_VISUAL,
                artifact_types=(
                    ArtifactType.SCREENSHOT,
                    ArtifactType.OS_REGION_SCREENSHOT,
                    ArtifactType.OS_REGION_CROP,
                ),
                artifact_roles=(ArtifactRole.VISUAL_EVIDENCE,),
                evidence_kinds=(EvidenceKind.SCREENSHOT,),
                allowed_scopes=(AccessScope.READ_RAW_ARTIFACT, AccessScope.READ_IMAGE),
                allow_raw=True,
            ),
        ),
    )


def _chrome_profile() -> DisclosureProfile:
    return DisclosureProfile(
        profile_key=CHROME_PROFILE_KEY,
        display_name="Chrome Web Capture Disclosure",
        provider_keys=("web.browser_extension",),
        app_names=("Google Chrome", "Chrome"),
        source_types=(SourceType.WEB,),
        policy_tags=("chrome_web_v1", "extension_live_dom", "safe_summary_card"),
        rules=(
            *_default_profile().rules,
            DisclosureRule(
                rule_id="chrome.inspect.clean_page_text",
                view=DisclosureView.EVENT_INSPECT,
                disclosure_class=DisclosureClass.CLEAN_PAGE_TEXT,
                artifact_types=(ArtifactType.CLEAN_PAGE_TEXT,),
                artifact_roles=(ArtifactRole.CLEAN_PAGE_TEXT,),
                evidence_kinds=(EvidenceKind.CLEAN_PAGE_TEXT,),
                allowed_scopes=(AccessScope.READ_TEXT,),
                max_chars=64000,
            ),
        ),
    )
