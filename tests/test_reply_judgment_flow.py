from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.db.models import Base, CandidateSnapshot, ShortlistCandidate
from packages.db.repositories import ConversationRepository, ScreeningRepository, WorkflowRepository
from packages.schemas.outreach import (
    FollowupReplyEnrichmentOutput,
    ReplyJudgmentSummaryOutput,
    ReplySummaryCandidateOutput,
)
from packages.schemas.screening import MissingInfo, ScreeningOutput
from packages.schemas.screening import ShortlistCandidate as ShortlistCandidateSchema
from services.agent_service import followup_conversation_service, reply_summary_agent


@pytest.fixture
def session_factory(tmp_path):
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'reply_judgment.db').as_posix()}"
    engine = create_async_engine(db_url, connect_args={"timeout": 30})

    async def _setup() -> async_sessionmaker[AsyncSession]:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    return _setup, engine


@pytest.mark.asyncio
async def test_apply_reply_enrichment_marks_followup_passed_and_syncs_shortlist(session_factory):
    setup, engine = session_factory
    factory = await setup()

    async with factory() as session:
        wf_repo = WorkflowRepository(session)
        screening_repo = ScreeningRepository(session)
        conv_repo = ConversationRepository(session)
        wf = await wf_repo.create(
            name="reply judgment",
            platform="liepin",
            start_url="https://example.com",
            job_id="job-1",
            config={"job": {"screening_criteria": "Need Spanish and Shenzhen."}, "fetch": {}},
        )
        snap = CandidateSnapshot(
            workflow_id=wf.id,
            platform="liepin",
            display_name="Alice",
            current_title="Sales",
            raw_text="Alice resume",
            metadata_={},
        )
        session.add(snap)
        await session.flush()
        await screening_repo.save_result(
            wf.id,
            wf.job_id,
            ScreeningOutput(
                candidate_snapshot_id=snap.id,
                total_score=66,
                level="followup",
                score_detail={"reason": "Need language evidence"},
                matched_points=["Sales background"],
                gaps=["Spanish unclear"],
                missing_info=[
                    MissingInfo(
                        field="spanish",
                        question="Do you speak Spanish?",
                        importance="high",
                    )
                ],
                suggested_action="ask_for_more_info",
            ),
        )
        shortlist = await screening_repo.create_shortlist(
            wf.id,
            wf.job_id,
            [
                ShortlistCandidateSchema(
                    candidate_snapshot_id=snap.id,
                    rank=1,
                    score=66,
                    level="followup",
                )
            ],
            min_score=60,
            total_candidates=1,
        )
        wf.shortlist_id = shortlist.id
        conv = await conv_repo.create(wf.id, snap.id, [], conversation_type="followup")
        await conv_repo.save_message(conv.id, snap.id, "outbound", "Please confirm.", status="sent")
        await session.commit()

        with patch.object(
            followup_conversation_service,
            "enrich_followup_reply",
            new_callable=AsyncMock,
            return_value=FollowupReplyEnrichmentOutput(
                candidate_snapshot_id=snap.id,
                updated_level="observe",
                extracted_fields={"spanish": "business fluent"},
                answered_fields=["spanish"],
                summary_for_list="Confirmed business Spanish and available in Shenzhen.",
                remaining_missing_info=[],
                confidence=0.9,
            ),
        ):
            applied = await followup_conversation_service.apply_reply_enrichment(
                workflow_id=wf.id,
                snap_id=snap.id,
                raw_reply="Yes, business Spanish. Shenzhen is fine.",
                wf=wf,
                criteria="Need Spanish and Shenzhen.",
                session=session,
            )
        await session.commit()

        latest = await screening_repo.get_latest_for_candidate(wf.id, snap.id)
        refreshed = await session.get(CandidateSnapshot, snap.id)
        shortlist_rows = (
            await session.execute(
                select(ShortlistCandidate).where(ShortlistCandidate.shortlist_id == shortlist.id)
            )
        ).scalars().all()

    await engine.dispose()

    assert applied["updated_level"] == "observe"
    assert applied["followup_passed"] is True
    assert latest is not None
    assert latest.screening_round == 2
    assert latest.level == "observe"
    assert latest.score_detail["followup_passed"] is True
    assert latest.score_detail["followup_origin_level"] == "followup"
    assert refreshed is not None
    assert refreshed.metadata_["followup_passed"] is True
    assert refreshed.metadata_["final_judgment_source"] == "reply_judgment_agent"
    assert shortlist_rows[0].level == "observe"


@pytest.mark.asyncio
async def test_reply_summary_candidates_include_observe_and_followup(session_factory, monkeypatch):
    setup, engine = session_factory
    factory = await setup()

    async with factory() as session:
        wf_repo = WorkflowRepository(session)
        screening_repo = ScreeningRepository(session)
        wf = await wf_repo.create(
            name="summary",
            platform="liepin",
            start_url="https://example.com",
            job_id="job-1",
            config={"job": {"screening_criteria": "Prioritize Spanish sales."}},
        )

        async def add_candidate(name: str, level: str, *, passed: bool = False):
            snap = CandidateSnapshot(
                workflow_id=wf.id,
                platform="liepin",
                display_name=name,
                current_title="Sales",
                raw_text=f"{name} resume",
                metadata_={"followup_passed": passed} if passed else {},
            )
            session.add(snap)
            await session.flush()
            await screening_repo.save_result(
                wf.id,
                wf.job_id,
                ScreeningOutput(
                    candidate_snapshot_id=snap.id,
                    total_score=80 if level == "observe" else 50,
                    level=level,
                    score_detail={"followup_passed": passed} if passed else {},
                    matched_points=["matched"] if level == "observe" else [],
                    gaps=[],
                    missing_info=[],
                    suggested_action="contact_now" if level == "observe" else "ask_for_more_info",
                ),
            )
            return snap.id

        observe_id = await add_candidate("Observe", "observe")
        passed_id = await add_candidate("Passed", "observe", passed=True)
        followup_id = await add_candidate("Still followup", "followup")
        await add_candidate("Excluded", "exclude")
        await session.commit()

    monkeypatch.setattr(reply_summary_agent, "async_session_factory", factory)
    rows = await reply_summary_agent.list_reply_summary_candidates(wf.id)
    await engine.dispose()

    ids = {row["candidate_snapshot_id"] for row in rows}
    assert ids == {observe_id, passed_id, followup_id}
    passed_row = next(row for row in rows if row["candidate_snapshot_id"] == passed_id)
    assert passed_row["followup_passed"] is True
    followup_row = next(row for row in rows if row["candidate_snapshot_id"] == followup_id)
    assert followup_row["pending_followup"] is True


def test_reply_summary_normalized_report_renders_all_ranked_candidates():
    candidates = [
        {
            "candidate_snapshot_id": f"s{i}",
            "display_name": f"Candidate {i}",
            "total_score": 90 - i,
            "reason": f"Reason {i}",
            "gaps": [f"Risk {i}"],
            "matched_points": [f"Point {i}"],
            "followup_passed": False,
        }
        for i in range(1, 8)
    ]
    output = ReplyJudgmentSummaryOutput(
        ranked_candidates=[
            ReplySummaryCandidateOutput(
                candidate_snapshot_id="s1",
                display_name="Candidate 1",
                rank=1,
                priority="high",
                recommendation="Top 1",
                score=95,
            ),
            ReplySummaryCandidateOutput(
                candidate_snapshot_id="s2",
                display_name="Candidate 2",
                rank=2,
                priority="high",
                recommendation="Top 2",
                score=92,
            ),
            ReplySummaryCandidateOutput(
                candidate_snapshot_id="s3",
                display_name="Candidate 3",
                rank=3,
                priority="medium",
                recommendation="Top 3",
                score=82,
            ),
        ],
        summary="本次进入候选列表的共3位候选人。\n\n| 排名 | 候选人 |\n|---|---|\n|1|Candidate 1|",
    )

    report = reply_summary_agent._normalize_report("wf", candidates, output)

    assert len(report["ranked_candidates"]) == 7
    assert "共 7 位" in report["summary"]
    assert "| 7 | Candidate 7 |" in report["summary"]
    assert "共3位" not in report["summary"]


def test_reply_summary_prompt_payload_keeps_all_candidates_with_long_fields():
    candidates = [
        {
            "candidate_snapshot_id": f"s{i}",
            "display_name": f"Candidate {i}",
            "resume_summary": "Long resume. " * 200,
            "reason": "Long reason. " * 120,
            "criteria_analysis": "Long criteria. " * 160,
            "summary_for_list": "Long summary. " * 120,
            "matched_points": [f"Point {j}" for j in range(12)],
            "gaps": [f"Risk {j}" for j in range(12)],
        }
        for i in range(1, 8)
    ]

    payload = reply_summary_agent._candidate_prompt_payload(candidates)

    assert [item["candidate_snapshot_id"] for item in payload] == [f"s{i}" for i in range(1, 8)]
    assert all(len(item["resume_summary"]) <= 703 for item in payload)
    assert all(len(item["matched_points"]) == 8 for item in payload)
    assert all(len(item["gaps"]) == 8 for item in payload)


@pytest.mark.asyncio
async def test_reply_judgment_report_persistence_round_trip(session_factory, monkeypatch):
    setup, engine = session_factory
    factory = await setup()
    report = {
        "workflow_id": "",
        "generated_at": "2026-06-12T00:00:00+00:00",
        "ranked_candidates": [
            {
                "candidate_snapshot_id": "snap-1",
                "display_name": "Alice",
                "rank": 1,
                "priority": "high",
                "recommendation": "Best fit",
                "risk_points": [],
                "talking_points": ["Spanish"],
                "followup_passed": True,
                "score": 88,
            }
        ],
        "summary": "One final candidate.",
    }

    async with factory() as session:
        wf_repo = WorkflowRepository(session)
        wf = await wf_repo.create(
            name="report",
            platform="liepin",
            start_url="https://example.com",
            job_id="job-1",
            config={},
        )
        report["workflow_id"] = wf.id
        await session.commit()
        wf_id = wf.id

    monkeypatch.setattr(reply_summary_agent, "async_session_factory", factory)
    await reply_summary_agent.persist_reply_judgment_summary_report(wf_id, report)
    loaded = await reply_summary_agent.get_reply_judgment_summary_report(wf_id)
    await engine.dispose()
    assert loaded is not None
    assert "共 1 位" in loaded["summary"]
    assert "| 1 | Alice | 88 | 高 | Best fit |" in loaded["summary"]
