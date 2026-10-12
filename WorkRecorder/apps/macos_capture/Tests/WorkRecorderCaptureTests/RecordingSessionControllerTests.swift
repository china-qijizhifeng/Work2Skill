import Testing
@testable import WorkRecorderCapture

struct RecordingSessionControllerTests {
    @Test func pauseCommitMovesToPausedAndLocksCloseReason() throws {
        var controller = RecordingSessionController()
        controller.activateRecording()

        let transaction = try controller.beginPause(nowMonotonicMilliseconds: 1_000, hasActiveVideoSegment: true)

        #expect(controller.snapshot.inFlight)
        #expect(transaction.segmentCloseReason == .paused)
        #expect(transaction.rollbackBackendKind == .resume)

        controller.commitPause(transaction)

        #expect(controller.snapshot.phase == .paused)
        #expect(!controller.snapshot.inFlight)
        #expect(controller.snapshot.pausedAtMonotonicMilliseconds == 1_000)
    }

    @Test func pauseRollbackReturnsToRecording() throws {
        var controller = RecordingSessionController()
        controller.activateRecording()
        _ = try controller.beginPause(nowMonotonicMilliseconds: 1_000, hasActiveVideoSegment: true)

        controller.rollbackPause()

        #expect(controller.snapshot.phase == .recording)
        #expect(!controller.snapshot.inFlight)
        #expect(controller.snapshot.pausedAtMonotonicMilliseconds == nil)
    }

    @Test func resumeCommitAddsPausedDuration() throws {
        var controller = RecordingSessionController()
        controller.activateRecording()
        let pause = try controller.beginPause(nowMonotonicMilliseconds: 2_000, hasActiveVideoSegment: true)
        controller.commitPause(pause)

        let resume = try controller.beginResume()
        controller.commitResume(resume, nowMonotonicMilliseconds: 2_450)

        #expect(controller.snapshot.phase == .recording)
        #expect(!controller.snapshot.inFlight)
        #expect(controller.snapshot.pausedAtMonotonicMilliseconds == nil)
        #expect(controller.snapshot.pausedAccumulatedMilliseconds == 450)
    }

    @Test func resumeRollbackKeepsPausedState() throws {
        var controller = RecordingSessionController()
        controller.activateRecording()
        let pause = try controller.beginPause(nowMonotonicMilliseconds: 2_000, hasActiveVideoSegment: true)
        controller.commitPause(pause)

        _ = try controller.beginResume()
        controller.rollbackResume()

        #expect(controller.snapshot.phase == .paused)
        #expect(!controller.snapshot.inFlight)
        #expect(controller.snapshot.pausedAtMonotonicMilliseconds == 2_000)
    }

    @Test func finishForReviewCommitsToCompletionReview() throws {
        var controller = RecordingSessionController()
        controller.activateRecording()

        let finish = try controller.beginFinishForReview()

        #expect(finish.closeReason == .stopped)
        #expect(controller.snapshot.phase == .stopping)
        #expect(controller.snapshot.inFlight)

        controller.commitFinishForReview()

        #expect(controller.snapshot.phase == .completionReview)
        #expect(!controller.snapshot.inFlight)
    }

    @Test func rejectsConcurrentControlTransitions() throws {
        var controller = RecordingSessionController()
        controller.activateRecording()
        _ = try controller.beginPause(nowMonotonicMilliseconds: 1_000, hasActiveVideoSegment: true)

        #expect(throws: RecordingSessionControlError.controlAlreadyInFlight) {
            _ = try controller.beginFinishForReview()
        }
    }

    @Test func pauseRequiresActiveVideoSegment() throws {
        var controller = RecordingSessionController()
        controller.activateRecording()

        #expect(throws: RecordingSessionControlError.missingActiveVideoSegment) {
            _ = try controller.beginPause(nowMonotonicMilliseconds: 1_000, hasActiveVideoSegment: false)
        }
    }
}
