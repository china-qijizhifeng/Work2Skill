import Foundation

enum RecordingSessionControlError: Error, Equatable, LocalizedError {
    case noActiveRecording
    case controlAlreadyInFlight
    case missingActiveVideoSegment
    case notPaused
    case invalidPhase(RecordingSessionControlPhase, RecordingSessionControlIntent)

    var errorDescription: String? {
        switch self {
        case .noActiveRecording:
            return "没有正在进行的录制。"
        case .controlAlreadyInFlight:
            return "录制控制正在处理。"
        case .missingActiveVideoSegment:
            return "当前录制没有可停止的视频段。"
        case .notPaused:
            return "录制当前没有暂停。"
        case .invalidPhase(let phase, let intent):
            return "录制状态 \(phase.rawValue) 不能执行 \(intent.rawValue)。"
        }
    }
}

enum RecordingSessionControlPhase: String, Equatable {
    case idle
    case recording
    case paused
    case stopping
    case completionReview = "completion_review"
}

enum RecordingSessionControlIntent: String, Equatable {
    case pause
    case resume
    case finishForReview = "finish_for_review"
}

struct RecordingSessionControlSnapshot: Equatable {
    let phase: RecordingSessionControlPhase
    let inFlight: Bool
    let pausedAtMonotonicMilliseconds: Int?
    let pausedAccumulatedMilliseconds: Int

    var isPaused: Bool {
        pausedAtMonotonicMilliseconds != nil
    }
}

struct RecordingPauseTransaction: Equatable {
    let pausedAtMonotonicMilliseconds: Int
    let segmentCloseReason: ActiveCaptureRecordingSegmentCloseReason
    let rollbackBackendKind: ActiveCaptureRecordingControlKind
}

struct RecordingResumeTransaction: Equatable {
    let pausedAtMonotonicMilliseconds: Int
    let rollbackBackendKind: ActiveCaptureRecordingControlKind
}

struct RecordingFinishTransaction: Equatable {
    let closeReason: ActiveCaptureRecordingSegmentCloseReason
}

struct RecordingSessionController {
    private(set) var phase: RecordingSessionControlPhase = .idle
    private(set) var inFlight = false
    private(set) var pausedAtMonotonicMilliseconds: Int?
    private(set) var pausedAccumulatedMilliseconds = 0

    var snapshot: RecordingSessionControlSnapshot {
        RecordingSessionControlSnapshot(
            phase: phase,
            inFlight: inFlight,
            pausedAtMonotonicMilliseconds: pausedAtMonotonicMilliseconds,
            pausedAccumulatedMilliseconds: pausedAccumulatedMilliseconds
        )
    }

    mutating func activateRecording() {
        phase = .recording
        inFlight = false
        pausedAtMonotonicMilliseconds = nil
        pausedAccumulatedMilliseconds = 0
    }

    mutating func reset() {
        phase = .idle
        inFlight = false
        pausedAtMonotonicMilliseconds = nil
        pausedAccumulatedMilliseconds = 0
    }

    mutating func beginPause(
        nowMonotonicMilliseconds: Int,
        hasActiveVideoSegment: Bool
    ) throws -> RecordingPauseTransaction {
        try ensureNotInFlight()
        guard phase == .recording else {
            throw RecordingSessionControlError.invalidPhase(phase, .pause)
        }
        guard hasActiveVideoSegment else {
            throw RecordingSessionControlError.missingActiveVideoSegment
        }
        inFlight = true
        return RecordingPauseTransaction(
            pausedAtMonotonicMilliseconds: nowMonotonicMilliseconds,
            segmentCloseReason: .paused,
            rollbackBackendKind: .resume
        )
    }

    mutating func commitPause(_ transaction: RecordingPauseTransaction) {
        phase = .paused
        pausedAtMonotonicMilliseconds = transaction.pausedAtMonotonicMilliseconds
        inFlight = false
    }

    mutating func rollbackPause() {
        phase = .recording
        pausedAtMonotonicMilliseconds = nil
        inFlight = false
    }

    mutating func beginResume() throws -> RecordingResumeTransaction {
        try ensureNotInFlight()
        guard phase == .paused else {
            throw RecordingSessionControlError.notPaused
        }
        guard let pausedAtMonotonicMilliseconds else {
            throw RecordingSessionControlError.notPaused
        }
        inFlight = true
        return RecordingResumeTransaction(
            pausedAtMonotonicMilliseconds: pausedAtMonotonicMilliseconds,
            rollbackBackendKind: .pause
        )
    }

    mutating func commitResume(
        _ transaction: RecordingResumeTransaction,
        nowMonotonicMilliseconds: Int
    ) {
        pausedAccumulatedMilliseconds += max(
            0,
            nowMonotonicMilliseconds - transaction.pausedAtMonotonicMilliseconds
        )
        pausedAtMonotonicMilliseconds = nil
        phase = .recording
        inFlight = false
    }

    mutating func rollbackResume() {
        phase = .paused
        inFlight = false
    }

    mutating func beginFinishForReview() throws -> RecordingFinishTransaction {
        try ensureNotInFlight()
        guard phase == .recording || phase == .paused else {
            throw RecordingSessionControlError.invalidPhase(phase, .finishForReview)
        }
        phase = .stopping
        inFlight = true
        return RecordingFinishTransaction(closeReason: .stopped)
    }

    mutating func commitFinishForReview() {
        phase = .completionReview
        pausedAtMonotonicMilliseconds = nil
        inFlight = false
    }

    mutating func rollbackFinishForReviewToPaused() {
        phase = .paused
        inFlight = false
    }

    private func ensureNotInFlight() throws {
        if inFlight {
            throw RecordingSessionControlError.controlAlreadyInFlight
        }
    }
}
