from __future__ import annotations

from datetime import UTC, datetime

from packages.contracts import (
    ActorRef,
    AgentRun,
    AgentRunOrigin,
    AgentRunReplay,
    AgentRunStatus,
    AgentUsageEventV2,
    AnswerRecord,
    CitationRecord,
    CitationUseState,
    ContextQuery,
    DeliveredContextSnapshot,
    RetrievalCall,
    RetrievalCallKind,
    SnapshotKind,
)


def test_agent_run_ledger_contracts_round_trip() -> None:
    now = datetime(2026, 5, 18, 8, 0, tzinfo=UTC)
    actor = ActorRef(actor_id="test-cli", display_name="Test CLI")
    run = AgentRun(
        agent_run_id="arun_test",
        actor=actor,
        agent="codex",
        purpose="customer_brief",
        origin=AgentRunOrigin.CLI_EXPLICIT,
        status=AgentRunStatus.ACTIVE,
        user_question="What did ACME procurement say?",
        user_question_hash="hash_question",
        started_at=now,
        last_seen_at=now,
    )
    query = ContextQuery(
        context_query_id="ctxq_test",
        agent_run_id=run.agent_run_id,
        query_text="ACME procurement",
        query_hash="hash_query",
        purpose="customer_brief",
        created_at=now,
    )
    call = RetrievalCall(
        retrieval_call_id="ret_test",
        agent_run_id=run.agent_run_id,
        context_query_id=query.context_query_id,
        request_id="req_test",
        kind=RetrievalCallKind.SEARCH,
        resource_type="search",
        purpose="search",
        request_hash="hash_request",
        response_hash="hash_response",
        created_at=now,
        completed_at=now,
    )
    snapshot = DeliveredContextSnapshot(
        snapshot_id="snap_test",
        agent_run_id=run.agent_run_id,
        retrieval_call_id=call.retrieval_call_id,
        context_query_id=query.context_query_id,
        kind=SnapshotKind.SEARCH_RESULT,
        payload_hash="hash_response",
        payload_json={"results": [{"event_id": "evt_test"}]},
        delivered_fields=("results",),
        byte_size=42,
        item_count=1,
        created_at=now,
    )
    citation = CitationRecord(
        citation_id="cit_test",
        agent_run_id=run.agent_run_id,
        event_id="evt_test",
        evidence_id="ev_test",
        artifact_id="art_test",
        state=CitationUseState.DELIVERED,
        created_at=now,
    )
    answer = AnswerRecord(
        answer_id="ans_test",
        agent_run_id=run.agent_run_id,
        output_ref="answer_1",
        citation_ids=(citation.citation_id,),
        bundle_ids=("cb_test",),
        created_at=now,
    )
    usage = AgentUsageEventV2(
        usage_id="usage_test",
        agent_run_id=run.agent_run_id,
        context_query_ids=(query.context_query_id,),
        retrieval_call_ids=(call.retrieval_call_id,),
        snapshot_ids=(snapshot.snapshot_id,),
        bundle_ids=("cb_test",),
        citation_ids=(citation.citation_id,),
        answer_id=answer.answer_id,
        agent="codex",
        purpose="customer_brief",
        output_ref="answer_1",
        created_at=now,
    )
    replay = AgentRunReplay(
        agent_run=run,
        context_queries=(query,),
        retrieval_calls=(call,),
        snapshots=(snapshot,),
        citations=(citation,),
        answers=(answer,),
        usage_events=(usage,),
    )

    payload = AgentRunReplay.model_validate_json(replay.model_dump_json())

    assert payload.agent_run.agent_run_id == "arun_test"
    assert payload.retrieval_calls[0].kind == RetrievalCallKind.SEARCH
    assert payload.citations[0].state == CitationUseState.DELIVERED
    assert payload.usage_events[0].answer_id == "ans_test"
