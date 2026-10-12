import AppKit
import ApplicationServices

@main
enum WorkRecorderCaptureApp {
    @MainActor
    private static var delegate: AppDelegate?

    @MainActor
    static func main() {
        if ActiveCaptureInputListenerE2ERunner.isRequested() {
            ActiveCaptureInputListenerE2ERunner.runFromMain()
            return
        }
        WorkRecorderLocalization.installIfNeeded()
        let application = NSApplication.shared
        let appDelegate = AppDelegate()
        delegate = appDelegate
        application.delegate = appDelegate
        application.setActivationPolicy(.accessory)
        application.run()
    }
}

enum WorkbenchLaunchPageResolver {
    static func resolve(arguments: [String], environment: [String: String]) -> WorkbenchPage? {
        if environment["WORKRECORDER_WORKBENCH_OPEN_PAGE"] != nil {
            return .recordings
        }
        if arguments.contains("--open-recordings")
            || arguments.contains("--open-workbench")
            || arguments.contains("--open-settings")
            || arguments.contains("--open-diagnostics")
            || environment["WORKRECORDER_WORKBENCH_OPEN_ON_LAUNCH"] == "1" {
            return .recordings
        }
        return .recordings
    }
}

enum RecordingE2ELaunchResolver {
    static func shouldStart(arguments: [String], environment: [String: String]) -> Bool {
        arguments.contains("--e2e-region-recording") || environment["WORKRECORDER_E2E_RECORDING_ENABLED"] == "1"
    }

    static func shouldOpenLargeReviewAfterSave(environment: [String: String]) -> Bool {
        environment["WORKRECORDER_E2E_RECORDING_OPEN_LARGE_REVIEW_AFTER_SAVE"] == "1"
    }

    static func shouldAutoLoadLargeReviewPlayback(environment: [String: String] = ProcessInfo.processInfo.environment) -> Bool {
        environment["WORKRECORDER_E2E_RECORDING_REVIEW_AUTO_LOAD_PLAYBACK"] == "1"
    }
}

enum PermissionPromptLaunchPolicy {
    static func shouldRequest(arguments: [String], environment: [String: String]) -> Bool {
        guard environment["WORKRECORDER_ALLOW_PERMISSION_PROMPTS"] == "1" else {
            return false
        }
        return arguments.contains("--request-permissions")
            || environment["WORKRECORDER_REQUEST_PERMISSIONS_ON_LAUNCH"] == "1"
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var menuController: MenuBarController?
    private var hotKeyController: HotKeyController?
    private var captureCoordinator: CaptureCoordinator?
    private var a11yProviderSession: A11yProviderSession?
    private var workbench: WorkbenchWindowController?
    private var recordingReviewCoordinator: RecordingReviewWindowCoordinator?
    private var daemonSupervisor: DaemonSupervisor?
    private var logStore: AppLogStore?
    private var shortcutStore: ShortcutPreferencesStore?
    private var workbenchClient: WorkbenchDaemonClient?
    private var terminationCleanupInFlight = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        let runtimeConfig = RuntimeConfig.load()
        let logStore = AppLogStore()
        let shortcutStore = ShortcutPreferencesStore()
        let arguments = ProcessInfo.processInfo.arguments
        let previewHUD = arguments.contains("--preview-hud")
            || ProcessInfo.processInfo.environment["WORKRECORDER_CAPTURE_PREVIEW_HUD"] == "1"
        let previewHotKey = previewHUD
            || arguments.contains("--preview-hotkey")
            || ProcessInfo.processInfo.environment["WORKRECORDER_CAPTURE_PREVIEW_HOTKEY"] == "1"
        let launchWorkbenchPage = WorkbenchLaunchPageResolver.resolve(
            arguments: arguments,
            environment: ProcessInfo.processInfo.environment
        )
        self.logStore = logStore
        self.shortcutStore = shortcutStore
        installRuntimeComponents(config: runtimeConfig, logStore: logStore, shortcutStore: shortcutStore, previewHotKey: previewHotKey)
        handlePermissionLaunchRequest(arguments: arguments, environment: ProcessInfo.processInfo.environment)
        menuController?.openRecordingCenter = { [weak self] in self?.workbench?.show(page: .recordings) }
        menuController?.openPermissionGuide = { [weak self] in
            self?.workbench?.showPermissionGuide()
        }
        hotKeyController = HotKeyController(
            preferences: shortcutStore,
            commandHandler: { [weak self] _ in
                self?.captureCoordinator?.startRegionRecordingPreparation()
            },
            logStore: logStore
        )
        hotKeyController?.register()
        Task {
            let resolvedConfig = await Task.detached(priority: .utility) {
                RuntimeConfig.resolveStartupConfig(from: runtimeConfig)
            }.value
            if !resolvedConfig.hasSameRuntimeEndpoints(as: runtimeConfig) {
                logStore.append("本机服务端点已刷新：\(resolvedConfig.daemonURL.absoluteString)")
                self.installRuntimeComponents(
                    config: resolvedConfig,
                    logStore: logStore,
                    shortcutStore: shortcutStore,
                    previewHotKey: previewHotKey
                )
            }
            guard let daemonSupervisor = self.daemonSupervisor,
                  let a11yProvider = self.a11yProviderSession,
                  let client = self.workbenchClient
            else {
                logStore.append("运行时组件初始化失败。")
                return
            }
            await daemonSupervisor.startIfNeeded()
            a11yProvider.start()
            await self.mirrorLocalShortcutSettingsToDaemon(client: client, store: shortcutStore, logStore: logStore)
            if let launchWorkbenchPage {
                self.workbench?.show(page: launchWorkbenchPage)
            }
            if RecordingE2ELaunchResolver.shouldStart(arguments: arguments, environment: ProcessInfo.processInfo.environment) {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) { [weak self] in
                    self?.captureCoordinator?.startRegionRecordingPreparation()
                }
            }
        }
    }

    private func handlePermissionLaunchRequest(arguments: [String], environment: [String: String]) {
        guard PermissionPromptLaunchPolicy.shouldRequest(arguments: arguments, environment: environment) else {
            return
        }
        let key = "AXTrustedCheckOptionPrompt"
        let options = [key: true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
        openPermissionURL("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
        openPermissionURL("x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent")
    }

    private func openPermissionURL(_ rawURL: String) {
        guard let url = URL(string: rawURL) else { return }
        NSWorkspace.shared.open(url)
    }

    private func installRuntimeComponents(
        config: RuntimeConfig,
        logStore: AppLogStore,
        shortcutStore: ShortcutPreferencesStore,
        previewHotKey: Bool
    ) {
        if captureCoordinator?.hasRecordingSessionSurface == true {
            logStore.append("录制正在进行或待保存，已暂缓刷新本机服务端点。")
            captureCoordinator?.focusRecordingControls()
            return
        }
        let environment = CaptureEnvironment.fromRuntimeConfig(config)
        let coordinator = CaptureCoordinator(environment: environment, logStore: logStore)
        let a11yProvider = A11yProviderSession(environment: environment)
        let daemonSupervisor = DaemonSupervisor(config: config, logs: logStore)
        let client = WorkbenchDaemonClient(config: config)
        captureCoordinator?.closeHUD()
        recordingReviewCoordinator?.close()
        a11yProviderSession?.stop()
        captureCoordinator = coordinator
        a11yProviderSession = a11yProvider
        self.daemonSupervisor = daemonSupervisor
        workbenchClient = client
        let reviewCoordinator = RecordingReviewWindowCoordinator(client: client, logStore: logStore)
        recordingReviewCoordinator = reviewCoordinator
        workbench = WorkbenchWindowController(
            daemon: daemonSupervisor,
            client: client,
            coordinator: coordinator,
            logStore: logStore
        )
        workbench?.openRecordingReview = { [weak self] request in
            self?.recordingReviewCoordinator?.open(request)
        }
        coordinator.openRecentCaptures = { [weak self] in self?.workbench?.show(page: .recordings) }
        coordinator.openRecordingsLibrary = { [weak self] in self?.workbench?.show(page: .recordings) }
        coordinator.openRecordingReviewForSavedEvent = { [weak self] eventId in
            guard let self else { return }
            self.workbench?.show(page: .recordings)
            self.workbench?.openRecordingReviewForEventId(eventId)
        }
        coordinator.onCaptureSaved = { [weak self] eventId in self?.workbench?.refreshAfterCaptureSaved(eventId: eventId) }
        coordinator.onStateChanged = { [weak self] _ in
            self?.menuController?.refreshFromCoordinator()
        }
        if let menuController {
            menuController.updateCoordinator(coordinator)
        } else {
            menuController = MenuBarController(coordinator: coordinator, shortcutStore: shortcutStore, previewOnly: previewHotKey)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        captureCoordinator?.stopActiveCaptureInputProducer()
        recordingReviewCoordinator?.close()
        hotKeyController?.unregister()
        a11yProviderSession?.stop()
        daemonSupervisor?.stopOwnedProcess()
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if terminationCleanupInFlight {
            return .terminateLater
        }
        if captureCoordinator?.blockApplicationTerminationForRecordingIfNeeded() == true {
            return .terminateCancel
        }
        guard let captureCoordinator,
              captureCoordinator.prepareForApplicationTermination({ [weak self, weak sender] in
                  self?.terminationCleanupInFlight = false
                  sender?.reply(toApplicationShouldTerminate: true)
              })
        else {
            return .terminateNow
        }
        terminationCleanupInFlight = true
        return .terminateLater
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        workbench?.show()
        return true
    }

    private func mirrorLocalShortcutSettingsToDaemon(
        client: WorkbenchDaemonClient,
        store: ShortcutPreferencesStore,
        logStore: AppLogStore
    ) async {
        do {
            _ = try await client.updateShortcutSettings(store.load())
            logStore.append("本机快捷键设置已镜像到 daemon。")
        } catch {
            logStore.append("快捷键已使用本机设置；daemon 镜像失败：\(error.localizedDescription)")
        }
    }

}
