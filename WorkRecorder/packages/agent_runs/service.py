"""Application services for replayable agent context usage."""

from __future__ import annotations

import hashlib
from datetime import timedelta

from packages.active_capture.application.citations import ActiveCaptureCitationResolver
from packages.artifacts.service import ArtifactAccessService
from packages.contracts import (
    ActorRef,
    AgentRun,
    AgentRunBeginRequest,
    AgentRunOrigin,
    AgentRunReplay,
    AgentRunStatus,
    AgentUsageEventV2,
    AgentUsageEventV2Create,
    AnswerRecord,
    CitationResolveResponse,
    CitationUseState,
    ContextBundle,
    ContextQuery,
    DeliveredContextSnapshot,
    EventInspectView,
    RetrievalCall,
    RetrievalCallKind,
    SearchResponse,
    SnapshotKind,
)
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from packages.storage.agent_run_repository import AgentRunLedgerRepository
from packages.storage.agent_run_trace_repository import AgentRunTraceRepository
from packages.storage.artifact_repository import ArtifactRepository
from packages.storage.event_repository import ContextEventRepository

from .citations import CitationRegistryService
from .replay import AgentRunReplayFilter
from .snapshots import DeliveredSnapshotBuilder


class AgentRunAccessError(RuntimeError):
    """Raised when a run/query/citation id is missing or foreign."""


class AgentRunLedgerService:
    """Owns agent-run ids, delivered snapshots, citations, and usage covers."""

    def __init__(
        self,
        *,
        repository: AgentRunLedgerRepository,
        traces: AgentRunTraceRepository,
        artifacts: ArtifactRepository,
        events: ContextEventRepository,
        artifact_access: ArtifactAccessService,
        ids: IdFactory,
        clock: Clock,
        active_capture_citations: ActiveCaptureCitationResolver | None = None,
    ) -> None:
        self.repository = repository
        self.traces = traces
        self.events = events
        self.ids = ids
        self.clock = clock
        self.snapshots = DeliveredSnapshotBuilder(ids)
        self.replay_filter = AgentRunReplayFilter(events=events, snapshots=self.snapshots)
        self.citations = CitationRegistryService(
            repository=repository,
            artifacts=artifacts,
            artifact_access=artifact_access,
            ids=ids,
            clock=clock,
            active_capture_resolver=active_capture_citations,
        )
        self.implicit_ttl = timedelta(hours=2)

    def begin_run(self, *, actor: ActorRef, body: AgentRunBeginRequest) -> AgentRun:
        """Create an explicit active run.

        Args:
            actor: Authenticated actor that owns the run.
            body: User-supplied run metadata and purpose.

        Returns:
            Newly persisted active agent run.
        """

        return self._create_run(
            actor=actor,
            agent=body.agent,
            purpose=body.purpose,
            origin=body.origin,
            workspace_id=body.workspace_id,
            user_question=body.user_question,
            metadata={"explicit": True},
        )

    def ensure_run(
        self,
        *,
        actor: ActorRef,
        requested_run_id: str | None,
        purpose: str,
        user_question: str | None = None,
        workspace_id: str | None = None,
        origin: AgentRunOrigin = AgentRunOrigin.DAEMON_IMPLICIT,
    ) -> AgentRun:
        """Return an existing run or create an implicit daemon run.

        Args:
            actor: Authenticated actor making the request.
            requested_run_id: Optional caller-provided run id.
            purpose: Retrieval or usage purpose used for implicit runs.
            user_question: Optional user-facing question for implicit run creation.
            workspace_id: Optional workspace scope for implicit run creation.
            origin: Run origin assigned when the daemon creates an implicit run.

        Returns:
            Active run owned by ``actor``.

        Raises:
            AgentRunAccessError: If the requested run is missing, foreign, or inactive.
        """

        if requested_run_id:
            existing = self.repository.get_run(requested_run_id)
            if existing is None:
                raise AgentRunAccessError("Agent run not found")
            self._assert_run_owned_by_actor(existing, actor)
            if existing.status != AgentRunStatus.ACTIVE:
                raise AgentRunAccessError("Agent run is not active")
            return self.touch_run(existing)
        active = self.repository.latest_active_run(actor_id=actor.actor_id)
        now = self.clock.now()
        if active is not None and now - active.last_seen_at <= self.implicit_ttl:
            return self.touch_run(active)
        return self._create_run(
            actor=actor,
            agent="codex",
            purpose=purpose,
            origin=origin,
            workspace_id=workspace_id,
            user_question=user_question,
            metadata={"implicit": True},
        )

    def touch_run(self, run: AgentRun) -> AgentRun:
        """Update last-seen time for an active run.

        Args:
            run: Existing active run to refresh.

        Returns:
            Persisted run with updated ``last_seen_at``.
        """

        touched = run.model_copy(update={"last_seen_at": self.clock.now()})
        return self.repository.save_run(touched)

    def end_run(
        self, *, agent_run_id: str, actor: ActorRef, status: AgentRunStatus = AgentRunStatus.COMPLETED
    ) -> AgentRun | None:
        """Mark a run completed or abandoned.

        Args:
            agent_run_id: Run id to close.
            actor: Authenticated actor that must own the run.
            status: Terminal status to write.

        Returns:
            Updated run, or ``None`` when the run does not exist.

        Raises:
            AgentRunAccessError: If the run belongs to another actor.
        """

        run = self.repository.get_run(agent_run_id)
        if run is None:
            return None
        self._assert_run_owned_by_actor(run, actor)
        now = self.clock.now()
        ended = run.model_copy(update={"status": status, "last_seen_at": now, "completed_at": now})
        return self.repository.save_run(ended)

    def replay(self, agent_run_id: str, *, actor: ActorRef) -> AgentRunReplay | None:
        """Return one replayable run ledger.

        Args:
            agent_run_id: Run id to replay.
            actor: Authenticated actor that must own the run.

        Returns:
            Replay ledger with restricted/deleted content filtered, or ``None``.

        Raises:
            AgentRunAccessError: If the run belongs to another actor.
        """

        replay = self.repository.replay(agent_run_id)
        if replay is None:
            return None
        self._assert_run_owned_by_actor(replay.agent_run, actor)
        return self.replay_filter.filter(replay)

    def context_query(
        self,
        *,
        run: AgentRun,
        query_text: str,
        purpose: str,
        requested_query_id: str | None = None,
        workspace_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ContextQuery:
        """Create or reuse one query ledger row.

        Args:
            run: Active run that owns the query.
            query_text: Plain local query text to hash and persist per policy.
            purpose: Retrieval purpose.
            requested_query_id: Optional existing query id to reuse.
            workspace_id: Optional query workspace scope.
            metadata: Scalar metadata for audit and diagnostics.

        Returns:
            Persisted context query row.

        Raises:
            AgentRunAccessError: If a requested query is missing or belongs to another run.
        """

        if requested_query_id:
            existing = self.repository.get_context_query(requested_query_id)
            if existing is None:
                raise AgentRunAccessError("Context query not found")
            if existing.agent_run_id != run.agent_run_id:
                raise AgentRunAccessError("Context query does not belong to the agent run")
            return existing
        text = query_text.strip()
        query = ContextQuery(
            context_query_id=self.ids.new("ctxq"),
            agent_run_id=run.agent_run_id,
            query_text=text,
            query_hash=self._hash(text),
            purpose=purpose,
            workspace_id=workspace_id or run.workspace_id,
            created_at=self.clock.now(),
            metadata=self._scalar_metadata(metadata or {}),
        )
        return self.repository.save_context_query(query)

    def trace_delivery(
        self,
        *,
        run: AgentRun,
        context_query: ContextQuery | None,
        request_id: str,
        kind: RetrievalCallKind,
        resource_type: str,
        resource_id: str | None,
        purpose: str,
        request_payload: object,
        response_payload: object,
        snapshot_kind: SnapshotKind,
        metadata: dict[str, object] | None = None,
        call_status: str = "succeeded",
    ) -> tuple[RetrievalCall, DeliveredContextSnapshot]:
        """Persist the call ledger and a safe delivered-content snapshot.

        Args:
            run: Agent run that owns the retrieval.
            context_query: Optional query row associated with this call.
            request_id: Request id from the daemon API boundary.
            kind: Retrieval call kind.
            resource_type: Logical resource type that was read.
            resource_id: Optional resource id that was read.
            purpose: Caller-declared purpose.
            request_payload: Request payload used for hashing.
            response_payload: Actual daemon response returned to the caller.
            snapshot_kind: Snapshot category to store for replay.
            metadata: Scalar audit metadata.
            call_status: Final call status such as ``succeeded`` or ``denied``.

        Returns:
            Persisted retrieval call and delivered snapshot.
        """

        safe_payload = self.snapshots.safe_payload(response_payload)
        request_hash = self.snapshots.hash_json(request_payload)
        response_hash = self.snapshots.hash_json(safe_payload)
        now = self.clock.now()
        call = RetrievalCall(
            retrieval_call_id=self.ids.new("ret"),
            agent_run_id=run.agent_run_id,
            context_query_id=context_query.context_query_id if context_query else None,
            request_id=request_id,
            kind=kind,
            resource_type=resource_type,
            resource_id=resource_id,
            purpose=purpose,
            request_hash=request_hash,
            response_hash=response_hash,
            status=call_status,
            created_at=now,
            completed_at=now,
            metadata=self._scalar_metadata(metadata or {}),
        )
        snapshot_id = self.ids.new("snap")
        items = self.snapshots.items_for_payload(snapshot_id=snapshot_id, payload=safe_payload)
        payload_bytes = self.snapshots.json_bytes(safe_payload)
        snapshot = DeliveredContextSnapshot(
            snapshot_id=snapshot_id,
            agent_run_id=run.agent_run_id,
            retrieval_call_id=call.retrieval_call_id,
            context_query_id=call.context_query_id,
            kind=snapshot_kind,
            payload_hash=response_hash,
            payload_json=safe_payload if isinstance(safe_payload, dict) else {"value": safe_payload},
            delivered_fields=tuple(sorted(safe_payload.keys())) if isinstance(safe_payload, dict) else ("value",),
            byte_size=len(payload_bytes),
            item_count=len(items),
            created_at=now,
            metadata=self._scalar_metadata(metadata or {}),
        )
        audit_id = self._str((metadata or {}).get("audit_id"))
        self.traces.save_delivery_trace(
            call=call,
            snapshot=snapshot,
            items=items,
            audit_link=(
                {
                    "agent_run_id": run.agent_run_id,
                    "audit_id": audit_id,
                    "request_id": request_id,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "created_at": now.isoformat(),
                }
                if audit_id
                else None
            ),
        )
        return call, snapshot

    def attach_search_citations(self, *, run: AgentRun, response: SearchResponse) -> SearchResponse:
        """Attach preview citation ids to search result cards.

        Args:
            run: Agent run that received the response.
            response: Search response to annotate.

        Returns:
            Search response with preview citation ids.
        """

        return self.citations.attach_search(run=run, response=response)

    def attach_inspect_citations(self, *, run: AgentRun, view: EventInspectView) -> EventInspectView:
        """Attach citation ids to inspect evidence and screenshot refs.

        Args:
            run: Agent run that requested the inspect view.
            view: Inspect view to annotate.

        Returns:
            Inspect view with citation ids.
        """

        return self.citations.attach_inspect(run=run, view=view)

    def attach_bundle_citations(self, *, run: AgentRun, bundle: ContextBundle) -> ContextBundle:
        """Register bundle citation ids and attach them to bundle items.

        Args:
            run: Agent run that created the bundle.
            bundle: Bundle to annotate.

        Returns:
            Bundle copy with citation ids.
        """

        return self.citations.attach_bundle(run=run, bundle=bundle)

    def record_usage(self, *, run: AgentRun, body: AgentUsageEventV2Create) -> AgentUsageEventV2:
        """Create answer and usage cover records for a completed response.

        Args:
            run: Agent run being finalized.
            body: Usage request with answer, citations, bundles, and risk links.

        Returns:
            Persisted v2 usage event cover.
        """

        bundle_ids = tuple(dict.fromkeys((*body.bundle_ids, *((body.bundle_id,) if body.bundle_id else ()))))
        for citation_id in body.citation_ids:
            citation = self.repository.get_citation(citation_id)
            if citation is not None and citation.agent_run_id == run.agent_run_id:
                self.repository.save_citation(citation.model_copy(update={"state": CitationUseState.USED_IN_ANSWER}))
        answer = AnswerRecord(
            answer_id=self.ids.new("ans"),
            agent_run_id=run.agent_run_id,
            output_ref=body.output_ref,
            answer_hash=body.answer_hash,
            citation_ids=body.citation_ids,
            bundle_ids=bundle_ids,
            created_at=self.clock.now(),
        )
        self.repository.save_answer(answer)
        replay = self.repository.replay(run.agent_run_id)
        usage = AgentUsageEventV2(
            usage_id=self.ids.new("usage"),
            agent_run_id=run.agent_run_id,
            context_query_ids=tuple(query.context_query_id for query in replay.context_queries) if replay else (),
            retrieval_call_ids=tuple(call.retrieval_call_id for call in replay.retrieval_calls) if replay else (),
            snapshot_ids=tuple(snapshot.snapshot_id for snapshot in replay.snapshots) if replay else (),
            bundle_ids=bundle_ids,
            citation_ids=body.citation_ids,
            answer_id=answer.answer_id,
            risk_advisory_ids=body.risk_advisory_ids,
            agent=body.agent,
            purpose=body.purpose,
            output_ref=body.output_ref,
            created_at=self.clock.now(),
        )
        return self.repository.save_usage(usage)

    def resolve_citation(self, *, citation_id: str, actor: ActorRef, run: AgentRun) -> CitationResolveResponse | None:
        """Resolve one citation to safe metadata and text when permitted.

        Args:
            citation_id: Citation id to resolve.
            actor: Authenticated actor resolving the citation.
            run: Active run that must own the citation.

        Returns:
            Safe citation response, or ``None`` for missing/foreign citations.
        """

        return self.citations.resolve(citation_id=citation_id, actor=actor, run=run)

    def _create_run(
        self,
        *,
        actor: ActorRef,
        agent: str,
        purpose: str,
        origin: AgentRunOrigin,
        workspace_id: str | None,
        user_question: str | None,
        metadata: dict[str, object],
    ) -> AgentRun:
        now = self.clock.now()
        question = user_question.strip() if user_question else None
        run = AgentRun(
            agent_run_id=self.ids.new("arun"),
            actor=actor,
            agent=agent,
            purpose=purpose,
            origin=origin,
            status=AgentRunStatus.ACTIVE,
            workspace_id=workspace_id,
            user_question=question,
            user_question_hash=self._hash(question) if question else None,
            started_at=now,
            last_seen_at=now,
            metadata=self._scalar_metadata(metadata),
        )
        return self.repository.save_run(run)

    def _assert_run_owned_by_actor(self, run: AgentRun, actor: ActorRef) -> None:
        if run.actor.actor_id != actor.actor_id:
            raise AgentRunAccessError("Agent run not found")

    def _scalar_metadata(self, metadata: dict[str, object]) -> dict[str, str | int | float | bool | None]:
        return {
            key: value for key, value in metadata.items() if isinstance(value, (str, int, float, bool)) or value is None
        }

    def _hash(self, value: str | None) -> str:
        return hashlib.sha256((value or "").encode("utf-8")).hexdigest()

    def _str(self, value: object) -> str | None:
        return value if isinstance(value, str) and value else None
