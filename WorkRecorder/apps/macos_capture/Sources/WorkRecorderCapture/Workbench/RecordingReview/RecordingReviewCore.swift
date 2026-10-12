import Foundation

enum RecordingReviewSelectionMode: Equatable {
    case follow
    case pinned
}

enum RecordingReviewTimelineFilter: Equatable {
    case all
    case actions
    case keyframes
    case warnings
    case marks
}

struct RecordingReviewTimelineDensityConfig: Equatable {
    let representativeTimerIntervalMs: Int

    static let `default` = RecordingReviewTimelineDensityConfig(
        representativeTimerIntervalMs: 8_000
    )
}

struct RecordingReviewTimelineVisibility: Equatable {
    let visibleSteps: [WorkbenchRecordingTimelineStepView]
    let hiddenLowValueStepCount: Int
}

struct RecordingReviewEvidenceFrame: Equatable {
    enum Role: Equatable {
        case current
        case before
        case after
        case target
        case result

        var title: String {
            switch self {
            case .current: "当前帧"
            case .before: "前一帧"
            case .after: "后一帧"
            case .target: "目标证据"
            case .result: "结果帧"
            }
        }
    }

    let keyframeId: String
    let role: Role
    let mediaTimeMs: Int
}

enum RecordingReviewCore {
    static func orderedSteps(_ steps: [WorkbenchRecordingTimelineStepView]) -> [WorkbenchRecordingTimelineStepView] {
        steps.sorted { lhs, rhs in
            let lhsTime = lhs.mediaTimeMs ?? Int.max
            let rhsTime = rhs.mediaTimeMs ?? Int.max
            if lhsTime != rhsTime {
                return lhsTime < rhsTime
            }
            let lhsSequence = lhs.sequenceIndex ?? Int.max
            let rhsSequence = rhs.sequenceIndex ?? Int.max
            if lhsSequence != rhsSequence {
                return lhsSequence < rhsSequence
            }
            return lhs.stepId < rhs.stepId
        }
    }

    static func selectedStep(
        in recording: WorkbenchActiveCaptureInspectView,
        selectedStepId: String?
    ) -> WorkbenchRecordingTimelineStepView? {
        guard let steps = recording.timeline?.steps, !steps.isEmpty else {
            return nil
        }
        let ordered = orderedSteps(steps)
        let defaultVisibility = visibleTimelineSteps(ordered, selectedStepId: nil)
        if let selectedStepId,
           let selected = defaultVisibility.visibleSteps.first(where: { $0.stepId == selectedStepId }) {
            return selected
        }
        return defaultVisibility.visibleSteps.first { $0.kind == .action || ($0.needsReview && isReviewWorthyStep($0)) }
            ?? defaultVisibility.visibleSteps.first
            ?? ordered.first(where: isUserFacingTimelineStep)
    }

    static func stepNeighbor(
        in steps: [WorkbenchRecordingTimelineStepView],
        selectedStep: WorkbenchRecordingTimelineStepView?,
        offset: Int
    ) -> WorkbenchRecordingTimelineStepView? {
        let ordered = orderedSteps(steps)
        guard !ordered.isEmpty else { return nil }
        let selectedIndex: Int
        if let selectedStep,
           let index = ordered.firstIndex(where: { $0.stepId == selectedStep.stepId }) {
            selectedIndex = index
        } else {
            if let selectedStep,
               let neighbor = neighborForHiddenAnchor(in: ordered, selectedStep: selectedStep, offset: offset) {
                return neighbor
            }
            selectedIndex = 0
        }
        let targetIndex = selectedIndex + offset
        guard ordered.indices.contains(targetIndex) else {
            return nil
        }
        return ordered[targetIndex]
    }

    private static func neighborForHiddenAnchor(
        in visibleSteps: [WorkbenchRecordingTimelineStepView],
        selectedStep: WorkbenchRecordingTimelineStepView,
        offset: Int
    ) -> WorkbenchRecordingTimelineStepView? {
        guard offset != 0 else { return nil }
        if offset < 0 {
            return visibleSteps.last { isTimelineStep($0, before: selectedStep) }
        }
        return visibleSteps.first { isTimelineStep(selectedStep, before: $0) }
    }

    private static func isTimelineStep(
        _ lhs: WorkbenchRecordingTimelineStepView,
        before rhs: WorkbenchRecordingTimelineStepView
    ) -> Bool {
        let lhsTime = lhs.mediaTimeMs ?? Int.max
        let rhsTime = rhs.mediaTimeMs ?? Int.max
        if lhsTime != rhsTime {
            return lhsTime < rhsTime
        }
        let lhsSequence = lhs.sequenceIndex ?? Int.max
        let rhsSequence = rhs.sequenceIndex ?? Int.max
        if lhsSequence != rhsSequence {
            return lhsSequence < rhsSequence
        }
        return lhs.stepId < rhs.stepId
    }

    static func followStep(
        in steps: [WorkbenchRecordingTimelineStepView],
        mediaTimeMs: Int
    ) -> WorkbenchRecordingTimelineStepView? {
        let ordered = orderedSteps(steps)
        guard !ordered.isEmpty else { return nil }
        var candidate = ordered.first
        for step in ordered {
            guard let stepTime = step.mediaTimeMs else { continue }
            if stepTime <= mediaTimeMs {
                candidate = step
            } else {
                break
            }
        }
        return candidate
    }

    static func safeTextForStep(
        _ recording: WorkbenchActiveCaptureInspectView,
        step: WorkbenchRecordingTimelineStepView
    ) -> WorkbenchRecordingSafeTextBlock? {
        for keyframeId in stepTextEvidenceIds(step) {
            if let match = recording.safeTextBlocks.first(where: { $0.keyframeId == keyframeId || $0.eventId == keyframeId }) {
                return match
            }
        }
        for refId in step.safeTextRefIds where !refId.isEmpty {
            if let match = recording.safeTextBlocks.first(where: {
                $0.blockId == refId || $0.keyframeId == refId || $0.eventId == refId
            }) {
                return match
            }
        }
        if let eventId = step.keyframeEventId,
           isUniqueTimelineEvent(recording, eventId: eventId),
           let match = recording.safeTextBlocks.first(where: { $0.eventId == eventId }) {
            return match
        }
        guard step.kind != .action else {
            return nil
        }
        if let primaryEventId = recording.primaryEventId,
           let match = recording.safeTextBlocks.first(where: { $0.eventId == primaryEventId }) {
            return match
        }
        if let summary = recording.safeTextBlocks.first(where: { block in
            let source = block.sourceField.lowercased()
            return source.contains("summary") || source.contains("demo")
        }) {
            return summary
        }
        return nil
    }

    static func stepTextEvidenceIds(_ step: WorkbenchRecordingTimelineStepView) -> [String] {
        var ids: [String] = []
        if let keyframeId = step.keyframeId, !keyframeId.isEmpty {
            ids.append(keyframeId)
        }
        if let result = step.actionSummary?.resultKeyframeId, !result.isEmpty {
            ids.append(result)
        }
        ids.append(contentsOf: step.actionSummary?.targetEvidenceKeyframeIds.filter { !$0.isEmpty } ?? [])
        ids.append(contentsOf: step.actionSummary?.afterKeyframeIds.filter { !$0.isEmpty } ?? [])
        ids.append(contentsOf: step.actionSummary?.beforeKeyframeIds.filter { !$0.isEmpty } ?? [])
        var seen: Set<String> = []
        return ids.filter { seen.insert($0).inserted }
    }

    static func evidenceFrames(
        in recording: WorkbenchActiveCaptureInspectView,
        for step: WorkbenchRecordingTimelineStepView
    ) -> [RecordingReviewEvidenceFrame] {
        guard let timelineSteps = recording.timeline?.steps else { return [] }
        var candidates: [(String, RecordingReviewEvidenceFrame.Role)] = []
        if let keyframeId = step.keyframeId, !keyframeId.isEmpty {
            candidates.append((keyframeId, .current))
        }
        candidates.append(contentsOf: (step.actionSummary?.beforeKeyframeIds ?? []).map { ($0, .before) })
        candidates.append(contentsOf: (step.actionSummary?.targetEvidenceKeyframeIds ?? []).map { ($0, .target) })
        candidates.append(contentsOf: (step.actionSummary?.target?.evidenceKeyframeIds ?? []).map { ($0, .target) })
        candidates.append(contentsOf: (step.actionSummary?.afterKeyframeIds ?? []).map { ($0, .after) })
        if let resultKeyframeId = step.actionSummary?.resultKeyframeId, !resultKeyframeId.isEmpty {
            candidates.append((resultKeyframeId, .result))
        }

        var seen: Set<String> = []
        return candidates.compactMap { keyframeId, role in
            guard !keyframeId.isEmpty,
                  seen.insert(keyframeId).inserted,
                  let frameStep = timelineSteps.first(where: { $0.keyframeId == keyframeId }),
                  let mediaTimeMs = frameStep.mediaTimeMs
            else { return nil }
            return RecordingReviewEvidenceFrame(
                keyframeId: keyframeId,
                role: role,
                mediaTimeMs: mediaTimeMs
            )
        }
    }

    static func isUniqueTimelineEvent(_ recording: WorkbenchActiveCaptureInspectView, eventId: String) -> Bool {
        guard let steps = recording.timeline?.steps else {
            return true
        }
        let matchingSteps = steps.filter { $0.keyframeEventId == eventId }
        return matchingSteps.count <= 1
    }

    static func visibleTimelineSteps(
        _ steps: [WorkbenchRecordingTimelineStepView],
        selectedStepId: String?,
        filter: RecordingReviewTimelineFilter = .all,
        density: RecordingReviewTimelineDensityConfig = .default
    ) -> RecordingReviewTimelineVisibility {
        let ordered = orderedSteps(steps)
        var visible: [WorkbenchRecordingTimelineStepView] = []
        var hiddenLowValueCount = 0
        var lastRepresentativeTimerTime: Int?
        var hasActionLikeStep = false

        for step in ordered {
            if !matches(filter: filter, step: step) {
                continue
            }
            if isProjectionFoldedStep(step) {
                hiddenLowValueCount += 1
                continue
            }
            if step.stepId == selectedStepId, isUserFacingTimelineStep(step) {
                visible.append(step)
                hasActionLikeStep = hasActionLikeStep || step.kind == .action
                continue
            }
            if isLowValueControlStep(step) {
                hiddenLowValueCount += 1
                continue
            }
            if isHighValueStep(step) {
                visible.append(step)
                hasActionLikeStep = hasActionLikeStep || step.kind == .action
                if isLowValueTimerFrame(step) {
                    lastRepresentativeTimerTime = step.mediaTimeMs ?? lastRepresentativeTimerTime
                }
                continue
            }
            if isLowValueTimerFrame(step) {
                let stepTime = step.mediaTimeMs ?? 0
                let shouldKeepRepresentative = lastRepresentativeTimerTime == nil
                    || stepTime - (lastRepresentativeTimerTime ?? 0) >= density.representativeTimerIntervalMs
                if shouldKeepRepresentative {
                    visible.append(step)
                    lastRepresentativeTimerTime = stepTime
                } else {
                    hiddenLowValueCount += 1
                }
                continue
            }
            visible.append(step)
        }

        if !hasActionLikeStep {
            visible = ensureKeyframeOnlyTimelineHasMiddleFrame(
                orderedSteps: ordered,
                visibleSteps: visible,
                selectedStepId: selectedStepId
            )
        }

        return RecordingReviewTimelineVisibility(
            visibleSteps: orderedSteps(visible),
            hiddenLowValueStepCount: hiddenLowValueCount
        )
    }

    static func userFacingStepCount(_ steps: [WorkbenchRecordingTimelineStepView]) -> Int {
        visibleTimelineSteps(steps, selectedStepId: nil).visibleSteps.count
    }

    static func isUserFacingTimelineStep(_ step: WorkbenchRecordingTimelineStepView) -> Bool {
        !isProjectionFoldedStep(step) && !isLowValueControlStep(step) && (isHighValueStep(step) || !isLowValueTimerFrame(step))
    }

    static func isHighValueStep(_ step: WorkbenchRecordingTimelineStepView) -> Bool {
        if isProjectionFoldedStep(step) {
            return false
        }
        if step.needsReview && isReviewWorthyStep(step) {
            return true
        }
        switch step.kind {
        case .action, .warning:
            return true
        case .control:
            return step.controlKind == .userMark && (step.keyframeId?.isEmpty == false || step.mediaTimeMs != nil)
        case .keyframe, .unknown:
            break
        }
        let role = step.keyframeRole?.lowercased()
        if role == "start" || role == "final" || role == "end" {
            return true
        }
        let trigger = step.triggerKind?.lowercased()
        if trigger == "recording_start" || trigger == "recording_stop" || trigger == "user_mark" {
            return true
        }
        return false
    }

    static func isReviewWorthyStep(_ step: WorkbenchRecordingTimelineStepView) -> Bool {
        if step.kind == .warning {
            return true
        }
        let trigger = step.triggerKind?.lowercased() ?? ""
        let role = step.keyframeRole?.lowercased() ?? ""
        if trigger.contains("error") || trigger.contains("scope") || role.contains("error") {
            return true
        }
        return step.controlKind == .scopeLost
    }

    static func isLowValueControlStep(_ step: WorkbenchRecordingTimelineStepView) -> Bool {
        guard step.kind == .control else {
            return false
        }
        if step.needsReview {
            return false
        }
        switch step.controlKind {
        case .userMark:
            return step.keyframeId == nil && step.actionId == nil && step.triggerKind != "user_mark"
        case .stop, .autoStop:
            return step.keyframeId == nil && step.actionId == nil && step.triggerKind != "recording_stop"
        case .startSegment, .endSegment, .pause, .resume:
            return true
        case .scopeLost:
            return false
        case .unknown, nil:
            return step.keyframeId == nil && step.actionId == nil
        }
    }

    static func isLowValueTimerFrame(_ step: WorkbenchRecordingTimelineStepView) -> Bool {
        guard step.kind == .keyframe else {
            return false
        }
        if isProjectionFoldedStep(step) {
            return false
        }
        if isHighValueStep(step) {
            return false
        }
        let trigger = step.triggerKind?.lowercased() ?? ""
        let role = step.keyframeRole?.lowercased() ?? ""
        if trigger.contains("timer") || trigger.contains("interval") || role.contains("timer") {
            return true
        }
        if trigger.contains("no_change") || role.contains("no_change") {
            return true
        }
        if trigger.contains("repeated") || role.contains("repeated") {
            return true
        }
        return step.actionId == nil && step.controlId == nil
    }

    static func isProjectionFoldedStep(_ step: WorkbenchRecordingTimelineStepView) -> Bool {
        if step.visibilityClass?.lowercased() == "folded" {
            return true
        }
        let foldReason = step.foldReason?.lowercased() ?? ""
        if foldReason.contains("typing")
            || foldReason.contains("target_probe")
            || foldReason.contains("control_only")
            || foldReason.contains("timeout")
            || foldReason.contains("low_information")
            || foldReason.contains("duplicate") {
            return true
        }
        let trigger = step.triggerKind?.lowercased() ?? ""
        if trigger == "target_resolution_probe" {
            return true
        }
        if trigger == "typing_settle" {
            return !hasResultEvidence(step)
        }
        return false
    }

    static func hasResultEvidence(_ step: WorkbenchRecordingTimelineStepView) -> Bool {
        if step.keyframeId?.isEmpty == false || step.keyframeEventId?.isEmpty == false {
            return true
        }
        guard let actionSummary = step.actionSummary else {
            return false
        }
        return !actionSummary.afterKeyframeIds.isEmpty
            || actionSummary.resultKeyframeId?.isEmpty == false
            || !actionSummary.targetEvidenceKeyframeIds.isEmpty
    }

    private static func matches(
        filter: RecordingReviewTimelineFilter,
        step: WorkbenchRecordingTimelineStepView
    ) -> Bool {
        switch filter {
        case .all:
            return true
        case .actions:
            return step.kind == .action
        case .keyframes:
            return step.kind == .keyframe
        case .warnings:
            return step.kind == .warning || step.needsReview
        case .marks:
            return step.controlKind == .userMark || step.actionKind == .userMark || step.triggerKind == "user_mark"
        }
    }

    private static func ensureKeyframeOnlyTimelineHasMiddleFrame(
        orderedSteps: [WorkbenchRecordingTimelineStepView],
        visibleSteps: [WorkbenchRecordingTimelineStepView],
        selectedStepId: String?
    ) -> [WorkbenchRecordingTimelineStepView] {
        guard visibleSteps.count < 3 else {
            return visibleSteps
        }
        let candidates = orderedSteps.filter { step in
            guard step.kind == .keyframe else { return false }
            guard step.stepId != selectedStepId else { return false }
            guard !isProjectionFoldedStep(step) else { return false }
            guard !isHighValueStep(step) else { return false }
            return isLowValueTimerFrame(step)
        }
        guard let middle = candidates.dropFirst(candidates.count / 2).first else {
            return visibleSteps
        }
        var output = visibleSteps
        if !output.contains(where: { $0.stepId == middle.stepId }) {
            output.append(middle)
        }
        return output
    }
}
