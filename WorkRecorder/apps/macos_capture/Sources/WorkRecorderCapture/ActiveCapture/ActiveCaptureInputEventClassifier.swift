import Carbon
import CoreGraphics
import Foundation

enum ActiveCaptureInputEventClassifier {
    static let producerKind = "macos_capture"
    static let producerVersion = "active_capture_input_v1"

    static func pointerClick(
        button: ActiveCapturePointerButton,
        clickCount: Int,
        location: CGPoint,
        scope: ActiveCaptureRecordingScope? = nil,
        wallTime: Date? = Date(),
        monotonicMilliseconds: Int? = nil
    ) -> ActiveCaptureProducerEventCommand {
        let point = ActiveCaptureActionPoint(
            x: location.x,
            y: location.y,
            coordinateSpace: "macos_global",
            displayId: nil,
            scaleFactor: nil
        )
        let coordinates = ActiveCaptureActionCoordinates(
            screenAbs: point,
            screenshotRel: nil,
            scopeRel: nil,
            targetBounds: nil
        )
        return ActiveCaptureProducerEventCommand(
            eventKind: .pointerClick,
            producerKind: producerKind,
            producerVersion: producerVersion,
            occurredAtWallTime: wallTime,
            occurredAtMonotonicMs: monotonicMilliseconds,
            scope: scope,
            pointer: ActiveCapturePointerPayload(
                button: button,
                clickCount: max(1, clickCount),
                coordinates: coordinates
            ),
            scroll: nil,
            keyboard: nil,
            metadata: [:]
        )
    }

    static func pointerDrag(
        button: ActiveCapturePointerButton,
        startLocation: CGPoint,
        endLocation: CGPoint,
        path: [CGPoint],
        durationMilliseconds: Int?,
        scope: ActiveCaptureRecordingScope? = nil,
        wallTime: Date? = Date(),
        monotonicMilliseconds: Int? = nil
    ) -> ActiveCaptureProducerEventCommand {
        let point = ActiveCaptureActionPoint(
            x: endLocation.x,
            y: endLocation.y,
            coordinateSpace: "macos_global",
            displayId: nil,
            scaleFactor: nil
        )
        let coordinates = ActiveCaptureActionCoordinates(
            screenAbs: point,
            screenshotRel: nil,
            scopeRel: nil,
            targetBounds: nil
        )
        let deltaX = endLocation.x - startLocation.x
        let deltaY = endLocation.y - startLocation.y
        var metadata: [String: JSONScalar] = [
            "button": .string(button.rawValue),
            "drag_start_x": .double(startLocation.x),
            "drag_start_y": .double(startLocation.y),
            "drag_end_x": .double(endLocation.x),
            "drag_end_y": .double(endLocation.y),
            "drag_delta_x": .double(deltaX),
            "drag_delta_y": .double(deltaY),
            "drag_distance": .double(hypot(deltaX, deltaY)),
            "drag_path": .string(pathString(path))
        ]
        if let durationMilliseconds {
            metadata["drag_duration_ms"] = .int(durationMilliseconds)
        }
        return ActiveCaptureProducerEventCommand(
            eventKind: .pointerDrag,
            producerKind: producerKind,
            producerVersion: producerVersion,
            occurredAtWallTime: wallTime,
            occurredAtMonotonicMs: monotonicMilliseconds,
            scope: scope,
            pointer: ActiveCapturePointerPayload(
                button: button,
                clickCount: 1,
                coordinates: coordinates
            ),
            scroll: nil,
            keyboard: nil,
            metadata: metadata
        )
    }

    static func scroll(
        deltaX: Double,
        deltaY: Double,
        phase: ActiveCaptureScrollPhase,
        durationMilliseconds: Int? = nil,
        location: CGPoint? = nil,
        scope: ActiveCaptureRecordingScope? = nil,
        wallTime: Date? = Date(),
        monotonicMilliseconds: Int? = nil
    ) -> ActiveCaptureProducerEventCommand {
        let coordinates: ActiveCaptureActionCoordinates?
        if let location {
            let point = ActiveCaptureActionPoint(
                x: location.x,
                y: location.y,
                coordinateSpace: "macos_global",
                displayId: nil,
                scaleFactor: nil
            )
            coordinates = ActiveCaptureActionCoordinates(
                screenAbs: point,
                screenshotRel: nil,
                scopeRel: nil,
                targetBounds: nil
            )
        } else {
            coordinates = nil
        }
        return ActiveCaptureProducerEventCommand(
            eventKind: .scroll,
            producerKind: producerKind,
            producerVersion: producerVersion,
            occurredAtWallTime: wallTime,
            occurredAtMonotonicMs: monotonicMilliseconds,
            scope: scope,
            pointer: nil,
            scroll: ActiveCaptureScrollPayload(
                deltaX: deltaX,
                deltaY: deltaY,
                phase: phase,
                durationMs: durationMilliseconds,
                velocityBucket: velocityBucket(deltaX: deltaX, deltaY: deltaY),
                coordinates: coordinates
            ),
            keyboard: nil,
            metadata: [:]
        )
    }

    static func hotkey(
        keyCode: Int,
        flags: CGEventFlags,
        isRepeat: Bool = false,
        scope: ActiveCaptureRecordingScope? = nil,
        wallTime: Date? = Date(),
        monotonicMilliseconds: Int? = nil
    ) -> ActiveCaptureProducerEventCommand {
        let modifiers = normalizedModifiers(from: flags)
        let semantic = hotkeySemantic(keyCode: keyCode, modifiers: modifiers)
        let chord = ActiveCaptureKeyChord(
            physicalKeyCode: keyCode,
            normalizedKeyLabel: normalizedKeyLabel(for: keyCode),
            modifiers: modifiers,
            keyboardLayoutId: nil,
            isRepeat: isRepeat,
            semantic: semantic,
            characters: nil
        )
        return ActiveCaptureProducerEventCommand(
            eventKind: .hotkey,
            producerKind: producerKind,
            producerVersion: producerVersion,
            occurredAtWallTime: wallTime,
            occurredAtMonotonicMs: monotonicMilliseconds,
            scope: scope,
            pointer: nil,
            scroll: nil,
            keyboard: ActiveCaptureKeyboardPayload(
                keyboardEventKind: .hotkey,
                inputClass: .shortcut,
                capturePolicy: .keyChordAllowed,
                keyChord: chord,
                typingSummary: nil,
                hotkeySemantic: semantic
            ),
            metadata: [:]
        )
    }

    static func rawKey(
        eventKind: ActiveCaptureProducerEventKind,
        keyCode: Int,
        characters: String?,
        flags: CGEventFlags,
        isRepeat: Bool = false,
        scope: ActiveCaptureRecordingScope? = nil,
        wallTime: Date? = Date(),
        monotonicMilliseconds: Int? = nil
    ) -> ActiveCaptureProducerEventCommand {
        precondition(eventKind == .keyDown || eventKind == .keyUp)
        let modifiers = normalizedModifiers(from: flags)
        let semantic = hotkeySemantic(keyCode: keyCode, modifiers: modifiers)
        let keyboardEventKind: ActiveCaptureKeyboardEventKind = eventKind == .keyDown ? .keyDown : .keyUp
        return ActiveCaptureProducerEventCommand(
            eventKind: eventKind,
            producerKind: producerKind,
            producerVersion: producerVersion,
            occurredAtWallTime: wallTime,
            occurredAtMonotonicMs: monotonicMilliseconds,
            scope: scope,
            pointer: nil,
            scroll: nil,
            keyboard: ActiveCaptureKeyboardPayload(
                keyboardEventKind: keyboardEventKind,
                inputClass: keyboardInputClass(keyCode: keyCode, characters: characters, flags: flags),
                capturePolicy: .fullContent,
                keyChord: ActiveCaptureKeyChord(
                    physicalKeyCode: keyCode,
                    normalizedKeyLabel: normalizedKeyLabel(for: keyCode),
                    modifiers: modifiers,
                    keyboardLayoutId: nil,
                    isRepeat: isRepeat,
                    semantic: semantic,
                    characters: characters
                ),
                typingSummary: nil,
                hotkeySemantic: semantic == .unknown ? nil : semantic
            ),
            metadata: [:]
        )
    }

    static func keyboardInputClass(
        keyCode: Int,
        characters: String?,
        flags: CGEventFlags
    ) -> ActiveCaptureKeyboardInputClass {
        if isShortcut(keyCode: keyCode, flags: flags) {
            return .shortcut
        }
        switch keyCode {
        case kVK_Delete, kVK_ForwardDelete:
            return .editingKey
        case kVK_Tab, kVK_Escape, kVK_LeftArrow, kVK_RightArrow, kVK_UpArrow,
             kVK_DownArrow, kVK_Home, kVK_End, kVK_PageUp, kVK_PageDown:
            return .navigationKey
        default:
            return characters?.isEmpty == false ? .textInput : .unknown
        }
    }

    static func typingPause(
        eventCount: Int,
        textEventCount: Int,
        characterCount: Int,
        deletionKeyCount: Int,
        nonTextKeyCount: Int,
        submittedByEnter: Bool,
        durationMs: Int?,
        scope: ActiveCaptureRecordingScope? = nil,
        wallTime: Date? = Date(),
        monotonicMilliseconds: Int? = nil
    ) -> ActiveCaptureProducerEventCommand {
        ActiveCaptureProducerEventCommand(
            eventKind: .typingPause,
            producerKind: producerKind,
            producerVersion: producerVersion,
            occurredAtWallTime: wallTime,
            occurredAtMonotonicMs: monotonicMilliseconds,
            scope: scope,
            pointer: nil,
            scroll: nil,
            keyboard: ActiveCaptureKeyboardPayload(
                keyboardEventKind: .typingPause,
                inputClass: .textInput,
                capturePolicy: .aggregateOnly,
                keyChord: nil,
                typingSummary: ActiveCaptureTypingSummary(
                    eventCount: eventCount,
                    textEventCount: textEventCount,
                    characterCount: characterCount,
                    deletionKeyCount: deletionKeyCount,
                    nonTextKeyCount: nonTextKeyCount,
                    compositionUsed: false,
                    submittedByEnter: submittedByEnter,
                    durationMs: durationMs
                ),
                hotkeySemantic: nil
            ),
            metadata: [:]
        )
    }

    static func normalizedModifiers(from flags: CGEventFlags) -> [ActiveCaptureModifierKey] {
        var modifiers: [ActiveCaptureModifierKey] = []
        if flags.contains(.maskCommand) {
            modifiers.append(.command)
        }
        if flags.contains(.maskShift) {
            modifiers.append(.shift)
        }
        if flags.contains(.maskAlternate) {
            modifiers.append(.option)
        }
        if flags.contains(.maskControl) {
            modifiers.append(.control)
        }
        if flags.contains(.maskSecondaryFn) {
            modifiers.append(.function)
        }
        if flags.contains(.maskAlphaShift) {
            modifiers.append(.capsLock)
        }
        return modifiers.sorted()
    }

    private static func pathString(_ path: [CGPoint]) -> String {
        path.map { point in
            "\(Int(point.x.rounded())),\(Int(point.y.rounded()))"
        }
        .joined(separator: ";")
    }

    static func isShortcut(keyCode: Int, flags: CGEventFlags) -> Bool {
        if isStandaloneCommandKey(keyCode: keyCode) {
            return true
        }
        if flags.contains(.maskCommand) || flags.contains(.maskControl) {
            return true
        }
        // Option-only letter chords are often ordinary text composition/dead-key input
        // on macOS, so they stay aggregate-only unless the physical key is a
        // non-text command key handled above.
        return false
    }

    static func isCommandKey(keyCode: Int) -> Bool {
        isStandaloneCommandKey(keyCode: keyCode)
    }

    static func isStandaloneCommandKey(keyCode: Int) -> Bool {
        switch keyCode {
        case kVK_Return,
             kVK_ANSI_KeypadEnter,
             kVK_Escape:
            return true
        default:
            return false
        }
    }

    static func normalizedKeyLabel(for keyCode: Int) -> String {
        switch keyCode {
        case kVK_Return, kVK_ANSI_KeypadEnter:
            return "enter"
        case kVK_Escape:
            return "escape"
        case kVK_Delete:
            return "backspace"
        case kVK_ForwardDelete:
            return "delete"
        case kVK_Tab:
            return "tab"
        case kVK_LeftArrow:
            return "left_arrow"
        case kVK_RightArrow:
            return "right_arrow"
        case kVK_UpArrow:
            return "up_arrow"
        case kVK_DownArrow:
            return "down_arrow"
        case kVK_Home:
            return "home"
        case kVK_End:
            return "end"
        case kVK_PageUp:
            return "page_up"
        case kVK_PageDown:
            return "page_down"
        case kVK_ANSI_A:
            return "a"
        case kVK_ANSI_B:
            return "b"
        case kVK_ANSI_C:
            return "c"
        case kVK_ANSI_D:
            return "d"
        case kVK_ANSI_E:
            return "e"
        case kVK_ANSI_F:
            return "f"
        case kVK_ANSI_G:
            return "g"
        case kVK_ANSI_H:
            return "h"
        case kVK_ANSI_I:
            return "i"
        case kVK_ANSI_J:
            return "j"
        case kVK_ANSI_K:
            return "k"
        case kVK_ANSI_L:
            return "l"
        case kVK_ANSI_M:
            return "m"
        case kVK_ANSI_N:
            return "n"
        case kVK_ANSI_O:
            return "o"
        case kVK_ANSI_P:
            return "p"
        case kVK_ANSI_Q:
            return "q"
        case kVK_ANSI_R:
            return "r"
        case kVK_ANSI_S:
            return "s"
        case kVK_ANSI_T:
            return "t"
        case kVK_ANSI_U:
            return "u"
        case kVK_ANSI_V:
            return "v"
        case kVK_ANSI_W:
            return "w"
        case kVK_ANSI_X:
            return "x"
        case kVK_ANSI_Y:
            return "y"
        case kVK_ANSI_Z:
            return "z"
        case kVK_ANSI_0:
            return "0"
        case kVK_ANSI_1:
            return "1"
        case kVK_ANSI_2:
            return "2"
        case kVK_ANSI_3:
            return "3"
        case kVK_ANSI_4:
            return "4"
        case kVK_ANSI_5:
            return "5"
        case kVK_ANSI_6:
            return "6"
        case kVK_ANSI_7:
            return "7"
        case kVK_ANSI_8:
            return "8"
        case kVK_ANSI_9:
            return "9"
        default:
            return "key_\(keyCode)"
        }
    }

    static func hotkeySemantic(
        keyCode: Int,
        modifiers: [ActiveCaptureModifierKey]
    ) -> ActiveCaptureHotkeySemantic {
        let set = Set(modifiers)
        let hasCommand = set.contains(.command)
        let hasShift = set.contains(.shift)
        switch (keyCode, hasCommand, hasShift) {
        case (kVK_ANSI_C, true, _):
            return .copy
        case (kVK_ANSI_X, true, _):
            return .cut
        case (kVK_ANSI_V, true, _):
            return .paste
        case (kVK_ANSI_S, true, _):
            return .save
        case (kVK_ANSI_W, true, _):
            return .close
        case (kVK_ANSI_N, true, _):
            return .newItem
        case (kVK_ANSI_A, true, _):
            return .selectAll
        case (kVK_ANSI_Z, true, false):
            return .undo
        case (kVK_ANSI_Z, true, true):
            return .redo
        case (kVK_ANSI_R, true, _):
            return .refresh
        case (kVK_ANSI_K, true, _):
            return .openCommand
        case (kVK_Return, _, _), (kVK_ANSI_KeypadEnter, _, _):
            return .submit
        case (kVK_Escape, _, _):
            return .escapeCancel
        default:
            return .unknown
        }
    }

    private static func velocityBucket(deltaX: Double, deltaY: Double) -> Int {
        let magnitude = max(abs(deltaX), abs(deltaY))
        return min(10, max(0, Int((magnitude / 12.0).rounded(.up))))
    }
}
