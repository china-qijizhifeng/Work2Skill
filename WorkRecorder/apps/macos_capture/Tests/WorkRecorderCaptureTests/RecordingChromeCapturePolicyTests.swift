import Foundation
import Testing
@testable import WorkRecorderCapture

struct RecordingChromeCapturePolicyTests {
    @Test func probeAndTypingDoNotSuppressRecordingChrome() {
        let policy = RecordingChromeCapturePolicy()

        #expect(!policy.shouldSuppressChrome(
            for: Self.instruction(triggerKind: .typingSettle, role: .result),
            nowMonotonicMilliseconds: 10_000,
            lastSuppressedAtMonotonicMilliseconds: nil
        ))
        #expect(!policy.shouldSuppressChrome(
            for: Self.instruction(triggerKind: .targetResolutionProbe, role: .result),
            nowMonotonicMilliseconds: 10_000,
            lastSuppressedAtMonotonicMilliseconds: nil
        ))
    }

    @Test func resultKeyframesDoNotSuppressRecordingChromeButRequiredBoundariesDo() {
        let policy = RecordingChromeCapturePolicy()

        #expect(!policy.shouldSuppressChrome(
            for: Self.instruction(triggerKind: .clickSettle, role: .result),
            nowMonotonicMilliseconds: 10_000,
            lastSuppressedAtMonotonicMilliseconds: nil
        ))
        #expect(!policy.shouldSuppressChrome(
            for: Self.instruction(triggerKind: .commandSubmitted, role: .result),
            nowMonotonicMilliseconds: 10_500,
            lastSuppressedAtMonotonicMilliseconds: 10_000
        ))
        #expect(policy.shouldSuppressChrome(
            for: Self.instruction(triggerKind: .userMark, role: .userMark),
            nowMonotonicMilliseconds: 10_500,
            lastSuppressedAtMonotonicMilliseconds: 10_000
        ))
    }

    private static func instruction(
        triggerKind: ActiveCaptureKeyframeTriggerKind,
        role: ActiveCaptureKeyframeRole
    ) -> ActiveCaptureCaptureInstruction {
        let binding = ActiveCaptureBinding(
            sessionId: "acs_test",
            role: role,
            triggerKind: triggerKind,
            keepReason: nil,
            candidateId: "kfc_test",
            metadata: [:]
        )
        return ActiveCaptureCaptureInstruction(
            candidateId: "kfc_test",
            sessionId: "acs_test",
            role: role,
            triggerKind: triggerKind,
            binding: binding,
            executeAfterMonotonicMs: nil
        )
    }
}
