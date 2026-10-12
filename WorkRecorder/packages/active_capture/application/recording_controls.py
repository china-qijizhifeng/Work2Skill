"""Recording control orchestration for active capture sessions."""

from __future__ import annotations

from datetime import datetime

from packages.active_capture.application.service_helpers import is_terminal_status
from packages.active_capture.domain.session_state import ActiveCaptureSessionStateMachine
from packages.active_capture.repositories.protocol import ActiveCaptureRepository
from packages.contracts import (
    ActiveCaptureMode,
    ActiveCapturePolicyConfig,
    ActiveCaptureSession,
    ActiveCaptureStatus,
    ApplyRecordingControlCommand,
    AttachRecordingSegmentCommand,
    RecordingControlEvent,
    RecordingControlKind,
    RecordingControlSource,
    RecordingPauseInterval,
    RecordingSegmentCloseReason,
    RecordingSegmentManifest,
    RecordingSegmentState,
    RecordingVideoSegmentRef,
)
from packages.contracts.common import JsonScalar
from packages.shared.ids import IdFactory
from packages.shared.time import Clock


class RecordingControlError(ValueError):
    """Raised when a recording control cannot be applied."""


def _duration_ms(segment: RecordingVideoSegmentRef) -> int:
    if segment.duration_ms is not None:
        return segment.duration_ms
    if segment.started_at_monotonic_ms is not None and segment.ended_at_monotonic_ms is not None:
        return max(0, segment.ended_at_monotonic_ms - segment.started_at_monotonic_ms)
    return 0


def _pause_duration_ms(pause: RecordingPauseInterval) -> int:
    if pause.started_at_monotonic_ms is not None and pause.ended_at_monotonic_ms is not None:
        return max(0, pause.ended_at_monotonic_ms - pause.started_at_monotonic_ms)
    return 0


class RecordingControlService:
    """Stateful application service for pause/resume/mark/stop controls."""

    def __init__(
        self,
        *,
        repository: ActiveCaptureRepository,
        ids: IdFactory,
        clock: Clock,
        config: ActiveCapturePolicyConfig,
        state_machine: ActiveCaptureSessionStateMachine,
    ) -> None:
        self.repository = repository
        self.ids = ids
        self.clock = clock
        self.config = config
        self.state_machine = state_machine

    def initialize_recording_session(self, session: ActiveCaptureSession) -> None:
        """Create the initial segment/control rows for a newly recording session."""

        if session.started_at is None:
            return
        if self.repository.list_recording_segments_for_session(session.session_id):
            return
        segment = RecordingVideoSegmentRef(
            segment_id=self.ids.new("rseg"),
            session_id=session.session_id,
            sequence_index=0,
            state=RecordingSegmentState.RECORDING,
            started_at=session.started_at,
        )
        control = RecordingControlEvent(
            control_id=self.ids.new("rctl"),
            session_id=session.session_id,
            kind=RecordingControlKind.START_SEGMENT,
            source=RecordingControlSource.POLICY,
            occurred_at=session.started_at,
            segment_id=segment.segment_id,
        )
        self.repository.save_recording_segment(segment)
        self.repository.save_control_event(control)

    def apply_control(
        self,
        *,
        session: ActiveCaptureSession,
        command: ApplyRecordingControlCommand,
    ) -> ActiveCaptureSession:
        """Apply one control and persist the state transition graph."""

        if is_terminal_status(session.status):
            raise RecordingControlError("cannot apply recording control to terminal active capture session")
        if not self.config.pause_resume_enabled and command.kind in {
            RecordingControlKind.PAUSE,
            RecordingControlKind.RESUME,
        }:
            raise RecordingControlError("active capture pause/resume controls are disabled")
        match command.kind:
            case RecordingControlKind.PAUSE:
                return self._pause(session=session, command=command)
            case RecordingControlKind.RESUME:
                return self._resume(session=session, command=command)
            case RecordingControlKind.USER_MARK:
                return self._mark(session=session, command=command)
            case RecordingControlKind.STOP | RecordingControlKind.AUTO_STOP:
                return self._stop(session=session, command=command)
            case RecordingControlKind.SCOPE_LOST:
                return self._scope_lost(session=session, command=command)
            case RecordingControlKind.START_SEGMENT:
                return self._start_segment(session=session, command=command)
            case RecordingControlKind.END_SEGMENT:
                return self._end_segment(session=session, command=command)

    def attach_segment(
        self,
        *,
        session: ActiveCaptureSession,
        command: AttachRecordingSegmentCommand,
    ) -> RecordingVideoSegmentRef:
        """Build a trusted native segment update without committing staged paths."""

        if session.mode != ActiveCaptureMode.RECORDING_SESSION:
            raise RecordingControlError("recording segment updates require a recording session")
        if is_terminal_status(session.status):
            raise RecordingControlError("cannot update recording segments for terminal active capture session")
        existing = self.repository.get_recording_segment(command.segment_id)
        if existing is None:
            now = self.clock.now()
            existing = RecordingVideoSegmentRef(
                segment_id=command.segment_id,
                session_id=session.session_id,
                sequence_index=len(self.repository.list_recording_segments_for_session(session.session_id)),
                state=command.state,
                started_at=now,
                started_at_monotonic_ms=command.started_at_monotonic_ms,
                media_start_monotonic_ms=command.media_start_monotonic_ms,
                media_start_wall_time_epoch_ms=command.media_start_wall_time_epoch_ms,
            )
        if existing.session_id != session.session_id:
            raise RecordingControlError("recording segment does not belong to active capture session")
        updated = existing.model_copy(
            update={
                "state": command.state,
                "ended_at": self.clock.now() if command.ended_at_monotonic_ms is not None else existing.ended_at,
                "started_at_monotonic_ms": (
                    command.started_at_monotonic_ms
                    if command.started_at_monotonic_ms is not None
                    else existing.started_at_monotonic_ms
                ),
                "media_start_monotonic_ms": (
                    command.media_start_monotonic_ms
                    if command.media_start_monotonic_ms is not None
                    else existing.media_start_monotonic_ms
                ),
                "media_start_wall_time_epoch_ms": (
                    command.media_start_wall_time_epoch_ms
                    if command.media_start_wall_time_epoch_ms is not None
                    else existing.media_start_wall_time_epoch_ms
                ),
                "ended_at_monotonic_ms": (
                    command.ended_at_monotonic_ms
                    if command.ended_at_monotonic_ms is not None
                    else existing.ended_at_monotonic_ms
                ),
                "duration_ms": command.duration_ms if command.duration_ms is not None else existing.duration_ms,
                "close_reason": command.close_reason or existing.close_reason,
                "staged_video": None,
                "metadata": existing.metadata | command.metadata,
            }
        )
        return updated

    def finalize_live_graph(
        self,
        session: ActiveCaptureSession,
        *,
        ended_at_monotonic_ms: int | None = None,
    ) -> None:
        """Close open control intervals before final timeline construction."""

        now = self.clock.now()
        for segment in self.repository.list_recording_segments_for_session(session.session_id):
            if segment.ended_at is None and segment.state == RecordingSegmentState.RECORDING:
                self.repository.save_recording_segment(
                    self._close_segment(
                        segment=segment,
                        ended_at=now,
                        ended_at_monotonic_ms=ended_at_monotonic_ms,
                        state=RecordingSegmentState.FINALIZING,
                        close_reason=RecordingSegmentCloseReason.STOPPED,
                    )
                )
        for pause in self.repository.list_pause_intervals_for_session(session.session_id):
            if pause.ended_at is None:
                self.repository.save_pause_interval(
                    pause.model_copy(update={"ended_at": now, "ended_at_monotonic_ms": ended_at_monotonic_ms})
                )

    def build_segment_manifest(self, session_id: str) -> RecordingSegmentManifest:
        """Build a typed manifest over segments, pauses, and controls."""

        now = self.clock.now()
        segments = self.repository.list_recording_segments_for_session(session_id)
        pauses = self.repository.list_pause_intervals_for_session(session_id)
        controls = self.repository.list_control_events_for_session(session_id)
        return RecordingSegmentManifest(
            manifest_id=self.ids.new("rsm"),
            session_id=session_id,
            segments=segments,
            pause_intervals=pauses,
            control_events=controls,
            total_recorded_duration_ms=sum(_duration_ms(item) for item in segments),
            total_paused_duration_ms=sum(_pause_duration_ms(item) for item in pauses),
            created_at=now,
            updated_at=now,
        )

    def _pause(
        self,
        *,
        session: ActiveCaptureSession,
        command: ApplyRecordingControlCommand,
    ) -> ActiveCaptureSession:
        if session.status != ActiveCaptureStatus.RECORDING:
            raise RecordingControlError("pause requires a recording session")
        now = self.clock.now()
        segment = self._active_segment(session.session_id)
        if segment is not None:
            self.repository.save_recording_segment(
                self._close_segment(
                    segment=segment,
                    ended_at=now,
                    ended_at_monotonic_ms=command.occurred_at_monotonic_ms,
                    state=RecordingSegmentState.PAUSED,
                    close_reason=RecordingSegmentCloseReason.PAUSED,
                )
            )
        pause = RecordingPauseInterval(
            pause_id=self.ids.new("rps"),
            session_id=session.session_id,
            started_at=now,
            started_at_monotonic_ms=command.occurred_at_monotonic_ms,
        )
        updated = self.state_machine.transition(session, ActiveCaptureStatus.PAUSED).model_copy(
            update={"updated_at": now}
        )
        self.repository.save_pause_interval(pause)
        self.repository.save_session(updated)
        self._record_control(session=updated, command=command, segment_id=segment.segment_id if segment else None)
        return updated

    def _resume(
        self,
        *,
        session: ActiveCaptureSession,
        command: ApplyRecordingControlCommand,
    ) -> ActiveCaptureSession:
        if session.status not in {ActiveCaptureStatus.PAUSED, ActiveCaptureStatus.SCOPE_LOST}:
            raise RecordingControlError("resume requires a paused or scope_lost session")
        now = self.clock.now()
        self._close_open_pause(session_id=session.session_id, ended_at_monotonic_ms=command.occurred_at_monotonic_ms)
        updated = self.state_machine.transition(session, ActiveCaptureStatus.RECORDING).model_copy(
            update={"updated_at": now}
        )
        segment = self._new_segment(session=updated, started_at_monotonic_ms=command.occurred_at_monotonic_ms)
        self.repository.save_session(updated)
        self._record_control(session=updated, command=command, segment_id=segment.segment_id)
        return updated

    def _mark(
        self,
        *,
        session: ActiveCaptureSession,
        command: ApplyRecordingControlCommand,
    ) -> ActiveCaptureSession:
        updated = session.model_copy(update={"updated_at": self.clock.now()})
        self.repository.save_session(updated)
        self._record_control(session=updated, command=command, segment_id=self._active_segment_id(session.session_id))
        return updated

    def _stop(
        self,
        *,
        session: ActiveCaptureSession,
        command: ApplyRecordingControlCommand,
    ) -> ActiveCaptureSession:
        now = self.clock.now()
        segment = self._active_segment(session.session_id)
        if segment is not None:
            self.repository.save_recording_segment(
                self._close_segment(
                    segment=segment,
                    ended_at=now,
                    ended_at_monotonic_ms=command.occurred_at_monotonic_ms,
                    state=RecordingSegmentState.FINALIZING,
                    close_reason=(
                        RecordingSegmentCloseReason.MAX_DURATION
                        if command.kind == RecordingControlKind.AUTO_STOP
                        else RecordingSegmentCloseReason.STOPPED
                    ),
                )
            )
        self._close_open_pause(session_id=session.session_id, ended_at_monotonic_ms=command.occurred_at_monotonic_ms)
        updated = self.state_machine.transition(session, ActiveCaptureStatus.STOPPING).model_copy(
            update={"updated_at": now}
        )
        self.repository.save_session(updated)
        self._record_control(session=updated, command=command, segment_id=segment.segment_id if segment else None)
        return updated

    def _scope_lost(
        self,
        *,
        session: ActiveCaptureSession,
        command: ApplyRecordingControlCommand,
    ) -> ActiveCaptureSession:
        if session.status != ActiveCaptureStatus.RECORDING:
            raise RecordingControlError("scope_lost requires a recording session")
        now = self.clock.now()
        segment = self._active_segment(session.session_id)
        if segment is not None:
            self.repository.save_recording_segment(
                self._close_segment(
                    segment=segment,
                    ended_at=now,
                    ended_at_monotonic_ms=command.occurred_at_monotonic_ms,
                    state=RecordingSegmentState.PAUSED,
                    close_reason=RecordingSegmentCloseReason.SCOPE_LOST,
                )
            )
        pause = RecordingPauseInterval(
            pause_id=self.ids.new("rps"),
            session_id=session.session_id,
            started_at=now,
            started_at_monotonic_ms=command.occurred_at_monotonic_ms,
            reason=RecordingControlKind.SCOPE_LOST,
        )
        updated = self.state_machine.transition(session, ActiveCaptureStatus.SCOPE_LOST).model_copy(
            update={"updated_at": now}
        )
        self.repository.save_pause_interval(pause)
        self.repository.save_session(updated)
        self._record_control(session=updated, command=command, segment_id=segment.segment_id if segment else None)
        return updated

    def _start_segment(
        self,
        *,
        session: ActiveCaptureSession,
        command: ApplyRecordingControlCommand,
    ) -> ActiveCaptureSession:
        if session.status != ActiveCaptureStatus.RECORDING:
            raise RecordingControlError("start_segment requires a recording session")
        segment = self._new_segment(session=session, started_at_monotonic_ms=command.occurred_at_monotonic_ms)
        self._record_control(session=session, command=command, segment_id=segment.segment_id)
        return session

    def _end_segment(
        self,
        *,
        session: ActiveCaptureSession,
        command: ApplyRecordingControlCommand,
    ) -> ActiveCaptureSession:
        segment = self._active_segment(session.session_id)
        if segment is None:
            raise RecordingControlError("end_segment requires an active segment")
        self.repository.save_recording_segment(
            self._close_segment(
                segment=segment,
                ended_at=self.clock.now(),
                ended_at_monotonic_ms=command.occurred_at_monotonic_ms,
                state=RecordingSegmentState.FINALIZING,
                close_reason=RecordingSegmentCloseReason.STOPPED,
            )
        )
        self._record_control(session=session, command=command, segment_id=segment.segment_id)
        return session

    def _new_segment(
        self,
        *,
        session: ActiveCaptureSession,
        started_at_monotonic_ms: int | None,
    ) -> RecordingVideoSegmentRef:
        existing = self.repository.list_recording_segments_for_session(session.session_id)
        segment = RecordingVideoSegmentRef(
            segment_id=self.ids.new("rseg"),
            session_id=session.session_id,
            sequence_index=len(existing),
            state=RecordingSegmentState.RECORDING,
            started_at=self.clock.now(),
            started_at_monotonic_ms=started_at_monotonic_ms,
        )
        return self.repository.save_recording_segment(segment)

    def _record_control(
        self,
        *,
        session: ActiveCaptureSession,
        command: ApplyRecordingControlCommand,
        segment_id: str | None,
    ) -> RecordingControlEvent:
        event = RecordingControlEvent(
            control_id=self.ids.new("rctl"),
            session_id=session.session_id,
            kind=command.kind,
            source=command.source,
            occurred_at=self.clock.now(),
            occurred_at_monotonic_ms=command.occurred_at_monotonic_ms,
            segment_id=segment_id,
            note=command.note,
            metadata=command.metadata,
        )
        return self.repository.save_control_event(event)

    def _active_segment(self, session_id: str) -> RecordingVideoSegmentRef | None:
        for segment in reversed(self.repository.list_recording_segments_for_session(session_id)):
            if segment.state == RecordingSegmentState.RECORDING and segment.ended_at is None:
                return segment
        return None

    def _active_segment_id(self, session_id: str) -> str | None:
        segment = self._active_segment(session_id)
        return segment.segment_id if segment is not None else None

    def _close_segment(
        self,
        *,
        segment: RecordingVideoSegmentRef,
        ended_at: datetime,
        ended_at_monotonic_ms: int | None,
        state: RecordingSegmentState,
        close_reason: RecordingSegmentCloseReason,
    ) -> RecordingVideoSegmentRef:
        duration_ms = segment.duration_ms
        if ended_at_monotonic_ms is not None and segment.started_at_monotonic_ms is not None:
            duration_ms = max(0, ended_at_monotonic_ms - segment.started_at_monotonic_ms)
        return segment.model_copy(
            update={
                "state": state,
                "ended_at": ended_at,
                "ended_at_monotonic_ms": ended_at_monotonic_ms,
                "duration_ms": duration_ms,
                "close_reason": close_reason,
            }
        )

    def _close_open_pause(self, *, session_id: str, ended_at_monotonic_ms: int | None) -> None:
        now = self.clock.now()
        for pause in reversed(self.repository.list_pause_intervals_for_session(session_id)):
            if pause.ended_at is None:
                self.repository.save_pause_interval(
                    pause.model_copy(update={"ended_at": now, "ended_at_monotonic_ms": ended_at_monotonic_ms})
                )
                return
