"""Provider lifecycle registry and Workbench-facing status service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from packages.contracts import (
    ProviderDefinition,
    ProviderDiagnosticCheck,
    ProviderDiagnosticResult,
    ProviderDiagnosticStatus,
    ProviderInstallKind,
    ProviderInstallSpec,
    ProviderInstallTarget,
    ProviderKind,
    ProviderPermissionKind,
    ProviderPermissionSpec,
    ProviderPermissionState,
    ProviderRuntimeHealth,
    ProviderRuntimeState,
    ProviderSessionRef,
    ProviderStatusReport,
    SourceType,
)
from packages.providers.sessions import ProviderSessionService


class ProviderLifecycleRegistry:
    """Registry for install, permission, and diagnostic provider definitions."""

    def __init__(self) -> None:
        """Create an empty lifecycle definition registry."""

        self._definitions: dict[str, ProviderDefinition] = {}

    def register(self, definition: ProviderDefinition) -> None:
        """Register or replace one lifecycle provider definition.

        Args:
            definition: Provider definition exposed to setup UIs and diagnostics.
        """

        self._definitions[definition.provider_key] = definition

    def get(self, provider_key: str) -> ProviderDefinition | None:
        """Return a provider definition by key.

        Args:
            provider_key: Stable provider key.

        Returns:
            Matching definition, when registered.
        """

        return self._definitions.get(provider_key)

    def list(self) -> tuple[ProviderDefinition, ...]:
        """Return registered definitions in stable key order.

        Returns:
            Tuple of provider definitions.
        """

        return tuple(self._definitions[key] for key in sorted(self._definitions))


@dataclass(frozen=True, slots=True)
class ProviderLifecycleDiagnostics:
    """Result payload returned by diagnostic routes.

    Attributes:
        provider_key: Stable provider key being diagnosed.
        diagnostics: Individual diagnostic check results.
        status: Aggregate provider status at the time diagnostics were run.
    """

    provider_key: str
    diagnostics: tuple[ProviderDiagnosticResult, ...]
    status: ProviderStatusReport


class ProviderLifecycleService:
    """Compose provider definitions, session liveness, and diagnostics."""

    def __init__(self, *, registry: ProviderLifecycleRegistry, sessions: ProviderSessionService) -> None:
        """Create a provider lifecycle service.

        Args:
            registry: Definition registry populated during daemon boot.
            sessions: Runtime session service used only for liveness.
        """

        self.registry = registry
        self.sessions = sessions

    def definitions(self) -> tuple[ProviderDefinition, ...]:
        """Return lifecycle definitions.

        Returns:
            Registered provider definitions.
        """

        return self.registry.list()

    async def status_reports(self) -> tuple[ProviderStatusReport, ...]:
        """Return status reports for all registered providers.

        Returns:
            Status reports with session-derived runtime liveness.
        """

        return self._status_reports(definitions=self.registry.list(), sessions=await self.sessions.list_sessions())

    async def diagnostics(self, provider_key: str) -> ProviderLifecycleDiagnostics | None:
        """Run lightweight diagnostics for one provider.

        Args:
            provider_key: Provider to diagnose.

        Returns:
            Diagnostic payload, or ``None`` when the provider is unknown.
        """

        definition = self.registry.get(provider_key)
        if definition is None:
            return None
        report = self._status_reports(definitions=(definition,), sessions=await self.sessions.list_sessions())[0]
        return ProviderLifecycleDiagnostics(
            provider_key=provider_key,
            diagnostics=report.diagnostics,
            status=report,
        )

    def _status_reports(
        self, *, definitions: tuple[ProviderDefinition, ...], sessions: tuple[ProviderSessionRef, ...]
    ) -> tuple[ProviderStatusReport, ...]:
        reports: list[ProviderStatusReport] = []
        for definition in definitions:
            provider_sessions = tuple(
                session for session in sessions if session.provider_key == definition.provider_key
            )
            state = _runtime_state(definition=definition, session_count=len(provider_sessions))
            permissions = tuple(_permission_status(permission, state=state) for permission in definition.permissions)
            reports.append(
                ProviderStatusReport(
                    provider_key=definition.provider_key,
                    display_name=definition.display_name,
                    installed=_installed(definition),
                    configured=_configured(definition=definition, state=state),
                    permissions=permissions,
                    runtime=ProviderRuntimeHealth(
                        state=state,
                        connected_session_count=len(provider_sessions),
                        last_seen_at=_last_seen(provider_sessions),
                        message=_runtime_message(
                            definition=definition,
                            state=state,
                            session_count=len(provider_sessions),
                        ),
                        metadata={"install_kind": definition.install.install_kind.value},
                    ),
                    diagnostics=tuple(
                        _diagnostic_result(
                            definition=definition,
                            check=check,
                            state=state,
                            session_count=len(provider_sessions),
                        )
                        for check in definition.diagnostics
                    ),
                    # Lifecycle status is READ_METADATA and Workbench-facing; session
                    # refs may carry tab URLs, so expose only aggregate liveness here.
                    sessions=(),
                )
            )
        return tuple(reports)


def register_default_lifecycle_definitions(registry: ProviderLifecycleRegistry) -> None:
    """Register built-in and first-party provider lifecycle definitions.

    Args:
        registry: Lifecycle registry to populate.
    """

    for definition in _default_lifecycle_definitions():
        registry.register(definition)


def _default_lifecycle_definitions() -> tuple[ProviderDefinition, ...]:
    return (
        ProviderDefinition(
            provider_key="system.screenshot",
            display_name="系统截图",
            summary="把用户框选的屏幕区域保存成本机 PNG 证据。",
            provider_kind=ProviderKind.SYSTEM_EVIDENCE,
            source_types=(SourceType.DESKTOP_WINDOW, SourceType.WEB, SourceType.DOCUMENT),
            install=ProviderInstallSpec(
                install_kind=ProviderInstallKind.BUILT_IN,
                supports_auto_install=True,
                instructions=("已内置在 WorkRecorder.app。",),
            ),
            permissions=(
                ProviderPermissionSpec(
                    permission_key=ProviderPermissionKind.SCREEN_RECORDING,
                    display_name="屏幕录制",
                    state=ProviderPermissionState.UNKNOWN,
                    reason="用于保存用户框选的截图区域。",
                    action_label="打开系统设置",
                    action_url="x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
                ),
            ),
            diagnostics=(
                ProviderDiagnosticCheck(
                    check_key="screen_recording_permission",
                    display_name="屏幕录制授权",
                    description="检查本机应用是否能暂存截图证据。",
                ),
            ),
            metadata={"built_in": True},
        ),
        ProviderDefinition(
            provider_key="system.macos_a11y",
            display_name="macOS 辅助功能",
            summary="采集截图框内的可见文字块和基础 UI 结构，用来生成 selection_text。",
            provider_kind=ProviderKind.SYSTEM_EVIDENCE,
            source_types=(SourceType.DESKTOP_WINDOW, SourceType.WEB, SourceType.DOCUMENT),
            install=ProviderInstallSpec(
                install_kind=ProviderInstallKind.BUILT_IN,
                supports_auto_install=True,
                instructions=("已内置在 WorkRecorder.app。", "需要在系统设置里授权辅助功能。"),
            ),
            permissions=(
                ProviderPermissionSpec(
                    permission_key=ProviderPermissionKind.ACCESSIBILITY,
                    display_name="辅助功能",
                    state=ProviderPermissionState.UNKNOWN,
                    reason="用于读取截图框内的文本块。",
                    action_label="打开系统设置",
                    action_url="x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
                ),
            ),
            diagnostics=(
                ProviderDiagnosticCheck(
                    check_key="a11y_provider_session",
                    display_name="辅助功能来源连接",
                    description="检查本机辅助功能来源是否已经连接到 daemon。",
                ),
            ),
            metadata={"built_in": True},
        ),
        ProviderDefinition(
            provider_key="system.appshot",
            display_name="系统底片",
            summary="把截图、窗口/App 事实、文字状态和质量诊断串成一份只读快照。",
            provider_kind=ProviderKind.SYSTEM_EVIDENCE,
            source_types=(SourceType.DESKTOP_WINDOW, SourceType.WEB, SourceType.DOCUMENT),
            install=ProviderInstallSpec(
                install_kind=ProviderInstallKind.BUILT_IN,
                supports_auto_install=True,
                instructions=("已内置在 WorkRecorder.app；每次截图都会自动生成。",),
            ),
            permissions=(
                ProviderPermissionSpec(
                    permission_key=ProviderPermissionKind.SCREEN_RECORDING,
                    display_name="屏幕录制",
                    state=ProviderPermissionState.UNKNOWN,
                    reason="用于引用截图证据和判断画面质量。",
                    action_label="打开系统设置",
                    action_url="x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
                ),
                ProviderPermissionSpec(
                    permission_key=ProviderPermissionKind.ACCESSIBILITY,
                    display_name="辅助功能",
                    state=ProviderPermissionState.UNKNOWN,
                    reason="用于引用框内文字与 UI 结构状态。",
                    action_label="打开系统设置",
                    action_url="x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
                ),
            ),
            diagnostics=(
                ProviderDiagnosticCheck(
                    check_key="system_appshot_composition",
                    display_name="系统底片生成",
                    description="检查截图、窗口事实、辅助功能和 OCR 状态是否能被串联成快照。",
                ),
            ),
            metadata={"built_in": True, "read_only": True},
        ),
        ProviderDefinition(
            provider_key="web.browser_extension",
            display_name="网页来源",
            summary="通过浏览器扩展采集 URL、标题、页面正文、完整 DOM 和网页选区映射。",
            provider_kind=ProviderKind.SOURCE,
            source_types=(SourceType.WEB,),
            install=ProviderInstallSpec(
                install_kind=ProviderInstallKind.MANUAL_UNPACKED_BROWSER_EXTENSION,
                bundled_resource="browser_extension",
                open_url="chrome://extensions",
                copy_path_hint="WorkRecorder.app/Contents/Resources/browser_extension",
                supports_auto_install=False,
                runtime_targets=(
                    ProviderInstallTarget(
                        target_key="chrome",
                        display_name="Google Chrome",
                        open_url="chrome://extensions",
                        instructions=(
                            "打开 Chrome 扩展页右上角的开发者模式",
                            "点击加载已解压的扩展程序",
                            "选择 Workbench 中显示的 WorkRecorder 扩展目录",
                        ),
                    ),
                    ProviderInstallTarget(
                        target_key="chrome_for_testing",
                        display_name="Google Chrome for Testing",
                        open_url="chrome://extensions",
                        instructions=(
                            "打开 Chrome 扩展页右上角的开发者模式",
                            "点击加载已解压的扩展程序",
                            "选择 Workbench 中显示的 WorkRecorder 扩展目录",
                        ),
                    ),
                    ProviderInstallTarget(
                        target_key="edge",
                        display_name="Microsoft Edge",
                        open_url="edge://extensions",
                        instructions=(
                            "打开 Edge 扩展页左侧的开发人员模式",
                            "点击加载解压缩的扩展",
                            "选择 Workbench 中显示的 WorkRecorder 扩展目录",
                        ),
                    ),
                ),
                instructions=(
                    "打开浏览器扩展管理页。",
                    "打开开发者模式。",
                    "选择“加载已解压的扩展程序”，并选择 Workbench 中显示的 WorkRecorder 扩展目录。",
                ),
            ),
            permissions=(
                ProviderPermissionSpec(
                    permission_key=ProviderPermissionKind.BROWSER_EXTENSION,
                    display_name="浏览器扩展",
                    state=ProviderPermissionState.UNKNOWN,
                    reason="用于采集 URL、DOM、清洗后的页面正文和选区映射证据。",
                    action_label="打开浏览器扩展页",
                    action_url="chrome://extensions",
                ),
            ),
            diagnostics=(
                ProviderDiagnosticCheck(
                    check_key="browser_provider_session",
                    display_name="网页来源连接",
                    description="检查浏览器扩展是否有在线 WebSocket 会话。",
                ),
            ),
            manifest_key="web.browser_extension",
            metadata={"browser_family": "chromium"},
        ),
    )


def _installed(definition: ProviderDefinition) -> bool:
    if definition.install.install_kind == ProviderInstallKind.BUILT_IN:
        return True
    return definition.install.bundled_resource is not None


def _configured(*, definition: ProviderDefinition, state: ProviderRuntimeState) -> bool:
    if definition.provider_key in {"system.screenshot", "system.appshot"}:
        return True
    if definition.install.install_kind == ProviderInstallKind.BUILT_IN:
        return state in {ProviderRuntimeState.READY, ProviderRuntimeState.ONLINE}
    return state == ProviderRuntimeState.ONLINE


def _runtime_state(*, definition: ProviderDefinition, session_count: int) -> ProviderRuntimeState:
    if definition.provider_key in {"system.screenshot", "system.appshot"}:
        return ProviderRuntimeState.READY
    if session_count > 0:
        return ProviderRuntimeState.ONLINE
    if definition.install.install_kind == ProviderInstallKind.BUILT_IN:
        return ProviderRuntimeState.NEEDS_SETUP
    return ProviderRuntimeState.OFFLINE


def _last_seen(sessions: tuple[ProviderSessionRef, ...]) -> datetime | None:
    return max((session.last_seen_at for session in sessions), default=None)


def _runtime_message(*, definition: ProviderDefinition, state: ProviderRuntimeState, session_count: int) -> str:
    if definition.provider_key == "system.screenshot":
        return "已内置。屏幕录制授权由 WorkRecorder.app 检查。"
    if definition.provider_key == "system.appshot":
        return "已内置。每次截图都会生成只读系统底片。"
    if state == ProviderRuntimeState.ONLINE:
        return f"已有 {session_count} 个来源会话连接。"
    if definition.provider_key == "system.macos_a11y":
        return "辅助功能来源未连接；请授权后保持 WorkRecorder.app 运行。"
    if definition.provider_key == "web.browser_extension":
        return "浏览器扩展未连接；请在扩展管理页加载 Workbench 显示的文件夹，并打开一个网页。"
    return "Provider 尚未连接。"


def _permission_status(permission: ProviderPermissionSpec, *, state: ProviderRuntimeState) -> ProviderPermissionSpec:
    if permission.state != ProviderPermissionState.UNKNOWN:
        return permission
    if permission.permission_key == ProviderPermissionKind.BROWSER_EXTENSION and state == ProviderRuntimeState.ONLINE:
        return permission.model_copy(update={"state": ProviderPermissionState.GRANTED})
    if permission.permission_key == ProviderPermissionKind.BROWSER_EXTENSION:
        return permission.model_copy(update={"state": ProviderPermissionState.NEEDS_USER_ACTION})
    return permission


def _diagnostic_result(
    *, definition: ProviderDefinition, check: ProviderDiagnosticCheck, state: ProviderRuntimeState, session_count: int
) -> ProviderDiagnosticResult:
    if definition.provider_key == "system.screenshot":
        return ProviderDiagnosticResult(
            check_key=check.check_key,
            status=ProviderDiagnosticStatus.WARNING,
            message="屏幕录制授权需要由本机应用检查。",
            details={"provider_key": definition.provider_key},
        )
    if definition.provider_key == "system.appshot":
        return ProviderDiagnosticResult(
            check_key=check.check_key,
            status=ProviderDiagnosticStatus.PASSED,
            message="系统底片会随每次截图生成；权限和质量状态会写入事件。",
            details={"provider_key": definition.provider_key},
        )
    if session_count > 0:
        return ProviderDiagnosticResult(
            check_key=check.check_key,
            status=ProviderDiagnosticStatus.PASSED,
            message="来源会话在线。",
            details={"provider_key": definition.provider_key, "session_count": session_count},
        )
    return ProviderDiagnosticResult(
        check_key=check.check_key,
        status=(
            ProviderDiagnosticStatus.FAILED
            if state == ProviderRuntimeState.NEEDS_SETUP
            else ProviderDiagnosticStatus.WARNING
        ),
        message=_runtime_message(definition=definition, state=state, session_count=session_count),
        details={"provider_key": definition.provider_key, "session_count": session_count},
    )
