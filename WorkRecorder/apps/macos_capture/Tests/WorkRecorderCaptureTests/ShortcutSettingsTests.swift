import Carbon
import Foundation
import Testing
@testable import WorkRecorderCapture

struct ShortcutSettingsTests {
    @Test func defaultShortcutOnlyContainsRecording() {
        let defaults = ShortcutSettings.defaults

        #expect(CaptureCommandKind.allCases == [.regionRecording])
        #expect(defaults.bindings.count == 1)
        #expect(defaults.binding(for: .regionRecording).shortcut.displayString == "⌃⌥⌘R")
    }

    @MainActor
    @Test func preferencesStoreRoundTripsRecordingOverride() throws {
        let suiteName = "WorkRecorderShortcutSettingsTests.\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suiteName))
        defaults.removePersistentDomain(forName: suiteName)
        let store = ShortcutPreferencesStore(defaults: defaults)
        var settings = ShortcutSettings.defaults
        settings.setShortcut(
            KeyboardShortcut(keyCode: UInt32(kVK_ANSI_1), keyLabel: "1", modifiers: [.control, .option]),
            for: .regionRecording
        )

        store.save(settings)
        let loaded = store.load()

        #expect(loaded.bindings.count == 1)
        #expect(loaded.binding(for: .regionRecording).shortcut.displayString == "⌃⌥1")
    }

    @Test func workbenchShortcutSettingsViewRoundTripsRecordingSettings() throws {
        var settings = ShortcutSettings.defaults
        settings.setShortcut(
            KeyboardShortcut(keyCode: UInt32(kVK_ANSI_1), keyLabel: "1", modifiers: [.control, .option]),
            for: .regionRecording
        )

        let view = WorkbenchShortcutSettingsView(settings: settings)
        let roundTripped = try #require(view.shortcutSettings)

        #expect(roundTripped.bindings.count == 1)
        #expect(roundTripped.binding(for: .regionRecording).shortcut.displayString == "⌃⌥1")
    }

    @Test func launchResolversOnlyOpenRecordingSurfaces() {
        #expect(WorkbenchLaunchPageResolver.resolve(arguments: ["WorkRecorder", "--open-recordings"], environment: [:]) == .recordings)
        #expect(WorkbenchLaunchPageResolver.resolve(arguments: ["WorkRecorder", "--open-workbench"], environment: [:]) == .recordings)
        #expect(WorkbenchLaunchPageResolver.resolve(arguments: ["WorkRecorder"], environment: [:]) == .recordings)
        #expect(RecordingE2ELaunchResolver.shouldStart(arguments: ["WorkRecorder", "--e2e-region-recording"], environment: [:]))
        #expect(!RecordingE2ELaunchResolver.shouldStart(arguments: ["WorkRecorder"], environment: [:]))
    }

    @Test func permissionPromptsStayOffUnlessExplicitlyOptedIn() {
        #expect(!PermissionPromptLaunchPolicy.shouldRequest(arguments: ["WorkRecorder"], environment: [:]))
        #expect(!PermissionPromptLaunchPolicy.shouldRequest(
            arguments: ["WorkRecorder", "--request-permissions"],
            environment: [:]
        ))
        #expect(PermissionPromptLaunchPolicy.shouldRequest(
            arguments: ["WorkRecorder", "--request-permissions"],
            environment: ["WORKRECORDER_ALLOW_PERMISSION_PROMPTS": "1"]
        ))
    }
}
