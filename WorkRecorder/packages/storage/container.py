"""Repository container for daemon services."""

from __future__ import annotations

from packages.active_capture.adapters.sqlite_repository import SQLiteActiveCaptureRepository

from .agent_run_repository import AgentRunLedgerRepository
from .agent_run_trace_repository import AgentRunTraceRepository
from .artifact_repository import ArtifactRepository
from .bundle_repository import AgentUsageRepository, ContextBundleRepository
from .capture_post_commit_context_resolver import SQLiteCapturePostCommitContextResolver
from .capture_post_commit_outbox_repository import CapturePostCommitOutboxRepository
from .capture_repository import CaptureRepository
from .database import SQLiteDatabase
from .event_change_repository import EventChangeRepository
from .event_repository import ContextEventRepository
from .index_policy_audit_repository import IndexPolicyAuditRepository
from .job_repository import CaptureJobRepository
from .ledger_repository import CaptureLedgerRepository
from .migrations import MigrationRunner
from .security_repository import AuditLogRepository, PolicyDecisionRepository
from .settings_repository import LocalSettingsRepository
from .share_repository import ContextShareRepository


class RepositoryContainer:
    """Bundle repositories that share one SQLite database.

    Attributes:
        database: Shared database wrapper.
        events: Context event repository.
        artifacts: Artifact metadata repository.
        captures: Atomic capture hot-path repository.
        policies: Policy decision repository.
        audits: Audit log repository.
        bundles: Context bundle repository.
        usage: Agent usage repository.
    """

    def __init__(self, database: SQLiteDatabase) -> None:
        """Create repositories and apply migrations.

        Args:
            database: Database wrapper used by all repositories.
        """

        self.database = database
        MigrationRunner(database).apply()
        self.events = ContextEventRepository(database)
        self.artifacts = ArtifactRepository(database)
        self.captures = CaptureRepository(database)
        self.capture_post_commit_outbox = CapturePostCommitOutboxRepository(database)
        self.capture_post_commit_context_resolver = SQLiteCapturePostCommitContextResolver(database)
        self.policies = PolicyDecisionRepository(database)
        self.audits = AuditLogRepository(database)
        self.bundles = ContextBundleRepository(database)
        self.usage = AgentUsageRepository(database)
        self.agent_run_ledger = AgentRunLedgerRepository(database)
        self.agent_run_traces = AgentRunTraceRepository(database)
        self.jobs = CaptureJobRepository(database)
        self.ledger = CaptureLedgerRepository(database)
        self.index_policy_decisions = IndexPolicyAuditRepository(database)
        self.active_capture = SQLiteActiveCaptureRepository(database)
        self.settings = LocalSettingsRepository(database)
        self.event_changes = EventChangeRepository(database)
        self.shares = ContextShareRepository(database)
