from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from packages.contracts import (
    CapturePostCommitOutboxConfig,
    CapturePostCommitOutboxTask,
    CapturePostCommitRef,
    CapturePostCommitTaskKind,
    CapturePostCommitTaskStatus,
)
from packages.storage.container import RepositoryContainer
from packages.storage.database import SQLiteDatabase


def test_capture_post_commit_outbox_rejects_stale_claim_transitions() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    now = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)
    task = _task(now)
    with repositories.database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO context_events(event_id, status, payload, created_at, updated_at)
            VALUES (?, 'agent_ready', '{}', ?, ?)
            """,
            (task.event_id, now.isoformat(), now.isoformat()),
        )
        repositories.capture_post_commit_outbox.save_many_in_transaction(connection, tasks=(task,))

    first_claim = repositories.capture_post_commit_outbox.claim_due(
        now=now,
        limit=1,
        stale_running_before=now - timedelta(seconds=1),
    )[0]
    second_claim = repositories.capture_post_commit_outbox.claim_due(
        now=now + timedelta(minutes=2),
        limit=1,
        stale_running_before=now + timedelta(seconds=1),
    )[0]

    assert first_claim.status == CapturePostCommitTaskStatus.RUNNING
    assert first_claim.lease_id is not None
    assert second_claim.status == CapturePostCommitTaskStatus.RUNNING
    assert second_claim.attempt_count == 2
    assert second_claim.lease_id is not None
    assert second_claim.lease_id != first_claim.lease_id

    assert not repositories.capture_post_commit_outbox.mark_completed(
        task=first_claim,
        now=now + timedelta(minutes=2, seconds=1),
    )
    still_running = repositories.capture_post_commit_outbox.get(task.task_id)
    assert still_running is not None
    assert still_running.status == CapturePostCommitTaskStatus.RUNNING
    assert still_running.lease_id == second_claim.lease_id

    assert repositories.capture_post_commit_outbox.mark_retryable(
        task=second_claim,
        error="retry from valid lease",
        now=now + timedelta(minutes=2, seconds=2),
        next_attempt_at=now + timedelta(minutes=2, seconds=3),
    )
    assert not repositories.capture_post_commit_outbox.mark_failed(
        task=first_claim,
        error="late stale failure",
        now=now + timedelta(minutes=2, seconds=4),
    )
    retryable = repositories.capture_post_commit_outbox.get(task.task_id)
    assert retryable is not None
    assert retryable.status == CapturePostCommitTaskStatus.RETRYABLE
    assert retryable.last_error == "retry from valid lease"


def test_capture_post_commit_outbox_stale_running_at_attempt_limit_fails_terminally() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    now = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)
    task = _task(now).model_copy(update={"max_attempts": 1})
    with repositories.database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO context_events(event_id, status, payload, created_at, updated_at)
            VALUES (?, 'agent_ready', '{}', ?, ?)
            """,
            (task.event_id, now.isoformat(), now.isoformat()),
        )
        repositories.capture_post_commit_outbox.save_many_in_transaction(connection, tasks=(task,))

    first_claim = repositories.capture_post_commit_outbox.claim_due(
        now=now,
        limit=1,
        stale_running_before=now - timedelta(seconds=1),
    )[0]
    second_claim = repositories.capture_post_commit_outbox.claim_due(
        now=now + timedelta(minutes=2),
        limit=1,
        stale_running_before=now + timedelta(seconds=1),
    )
    failed = repositories.capture_post_commit_outbox.get(task.task_id)

    assert first_claim.attempt_count == 1
    assert second_claim == ()
    assert failed is not None
    assert failed.status == CapturePostCommitTaskStatus.FAILED
    assert failed.attempt_count == 1
    assert failed.last_error == "stale running task exceeded max attempts"


def test_capture_post_commit_outbox_terminal_states_ignore_stale_transitions() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    now = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)
    completed_task = _insert_claimed_task(repositories, _task(now), now)

    assert repositories.capture_post_commit_outbox.mark_completed(task=completed_task, now=now + timedelta(seconds=1))
    assert not repositories.capture_post_commit_outbox.mark_retryable(
        task=completed_task,
        error="late retry",
        now=now + timedelta(seconds=2),
        next_attempt_at=now + timedelta(seconds=3),
    )
    completed = repositories.capture_post_commit_outbox.get(completed_task.task_id)
    assert completed is not None
    assert completed.status == CapturePostCommitTaskStatus.COMPLETED

    failed_source = _task(now).model_copy(
        update={
            "task_id": "cpc_failed",
            "event_id": "evt_failed",
            "trigger_id": "trg_failed",
            "ref": CapturePostCommitRef(
                event_id="evt_failed",
                capture_run_id="run_failed",
                trigger_id="trg_failed",
                artifact_ids=("art_failed",),
            ),
        }
    )
    failed_task = _insert_claimed_task(repositories, failed_source, now)
    assert repositories.capture_post_commit_outbox.mark_failed(
        task=failed_task,
        error="terminal failure",
        now=now + timedelta(seconds=1),
    )
    assert not repositories.capture_post_commit_outbox.mark_completed(
        task=failed_task,
        now=now + timedelta(seconds=2),
    )
    failed = repositories.capture_post_commit_outbox.get(failed_task.task_id)
    assert failed is not None
    assert failed.status == CapturePostCommitTaskStatus.FAILED
    assert failed.last_error == "terminal failure"


def test_capture_post_commit_outbox_config_rejects_invalid_retry_window() -> None:
    with pytest.raises(ValueError, match="max_retry_delay_ms"):
        CapturePostCommitOutboxConfig(retry_backoff_ms=2_000, max_retry_delay_ms=1_000)


def _task(now: datetime) -> CapturePostCommitOutboxTask:
    return CapturePostCommitOutboxTask(
        task_id="cpc_test",
        kind=CapturePostCommitTaskKind.ACTIVE_CAPTURE_KEYFRAME,
        handler_id="active_capture.keyframe.v1",
        status=CapturePostCommitTaskStatus.PENDING,
        event_id="evt_test",
        trigger_id="trg_test",
        max_attempts=3,
        next_attempt_at=now,
        ref=CapturePostCommitRef(
            event_id="evt_test",
            capture_run_id="run_test",
            trigger_id="trg_test",
            artifact_ids=("art_test",),
        ),
        created_at=now,
        updated_at=now,
    )


def _insert_claimed_task(
    repositories: RepositoryContainer,
    task: CapturePostCommitOutboxTask,
    now: datetime,
) -> CapturePostCommitOutboxTask:
    with repositories.database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO context_events(event_id, status, payload, created_at, updated_at)
            VALUES (?, 'agent_ready', '{}', ?, ?)
            """,
            (task.event_id, now.isoformat(), now.isoformat()),
        )
        repositories.capture_post_commit_outbox.save_many_in_transaction(connection, tasks=(task,))
    return repositories.capture_post_commit_outbox.claim_due(
        now=now,
        limit=1,
        stale_running_before=now - timedelta(seconds=1),
    )[0]
