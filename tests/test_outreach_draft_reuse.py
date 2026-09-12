"""Tests for IM draft reuse (no duplicate generation)."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.db.models import Base, CandidateSnapshot
from packages.db.repositories import ConversationRepository, ScreeningRepository, WorkflowRepository
from packages.schemas.screening import ScreeningOutput
from services.agent_service import candidate_dialogue_service, im_autopilot
from services.agent_service.followup_conversation_service import prepare_followup_for_candidate


@pytest.fixture
def session_factory(tmp_path):
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'draft_reuse.db').as_posix()}"
    engine = create_async_engine(db_url, connect_args={"timeout": 30})

    async def _setup() -> async_sessionmaker[AsyncSession]:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    return _setup, engine


async def _seed_followup_candidate(session):
    wf_repo = WorkflowRepository(session)
    conv_repo = ConversationRepository(session)
    screening_repo = ScreeningRepository(session)
    wf = await wf_repo.create(
        name="followup",
        platform="liepin",
        start_url="https://example.com",
        job_id="job-1",
        config={"job": {"title": "Sales"}, "fetch": {"browser_profile": "hr_default"}},
    )
    snap = CandidateSnapshot(
        workflow_id=wf.id,
        platform="liepin",
        display_name="Bob",
        current_title="Sales",
        raw_text="Bob resume",
        metadata_={"chat_initiated": True},
    )
    session.add(snap)
    await session.flush()
    await screening_repo.save_result(
        wf.id,
        "job-1",
        ScreeningOutput(
            candidate_snapshot_id=snap.id,
            total_score=70,
            level="followup",
            score_detail={},
            matched_points=[],
            gaps=[],
            missing_info=[{"field": "visa", "question": "是否有美签？", "importance": "high"}],
            suggested_action="followup",
        ),
    )
    conv = await conv_repo.create(wf.id, snap.id, [], conversation_type="followup")
    await conv_repo.save_message(
        conv.id,
        snap.id,
        "outbound",
        "请问是否有美签？",
        status="drafted",
        round_num=1,
    )
    await conv_repo.update_status(conv.id, "MESSAGE_DRAFTED", current_round=1)
    await session.commit()
    return wf.id, snap.id


@pytest.mark.asyncio
async def test_prepare_followup_reuses_existing_draft(session_factory, monkeypatch):
    setup, engine = session_factory
    factory = await setup()
    async with factory() as session:
        wf_id, snap_id = await _seed_followup_candidate(session)

    monkeypatch.setattr(
        "services.agent_service.followup_conversation_service.async_session_factory",
        factory,
    )
    with patch(
        "services.agent_service.followup_conversation_service.generate_followup_message",
        new_callable=AsyncMock,
    ) as gen_mock:
        draft = await prepare_followup_for_candidate(wf_id, snap_id)

    await engine.dispose()

    assert draft is not None
    assert draft["reused_existing"] is True
    assert draft["message_text"] == "请问是否有美签？"
    gen_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_dialogue_skips_when_draft_already_pending(session_factory, monkeypatch):
    setup, engine = session_factory
    factory = await setup()
    async with factory() as session:
        wf_repo = WorkflowRepository(session)
        conv_repo = ConversationRepository(session)
        wf = await wf_repo.create(
            name="dialogue",
            platform="liepin",
            start_url="https://example.com",
            job_id="job-1",
            config={"fetch": {"browser_profile": "hr_default"}, "job": {"title": "Sales"}},
        )
        snap = CandidateSnapshot(
            workflow_id=wf.id,
            platform="liepin",
            display_name="Alice",
            current_title="Sales",
            raw_text="Alice resume",
            metadata_={"chat_initiated": True},
        )
        session.add(snap)
        await session.flush()
        conv = await conv_repo.create(wf.id, snap.id, [], conversation_type="dialogue")
        await conv_repo.save_message(
            conv.id,
            snap.id,
            "inbound",
            "What is the salary?",
            status="received",
            platform_message_id="m1",
        )
        await conv_repo.save_message(
            conv.id,
            snap.id,
            "outbound",
            "Salary is 15-25K.",
            status="drafted",
            extracted_fields={
                "agent_type": "candidate_dialogue_agent",
                "reply_to_message_id": "m1",
                "question_type": "salary",
                "action": "auto_reply",
                "auto_send_allowed": True,
            },
        )
        await conv_repo.update_status(conv.id, "REPLY_RECEIVED")
        await session.commit()
        wf_id = wf.id

    monkeypatch.setattr(candidate_dialogue_service, "async_session_factory", factory)
    with patch.object(
        candidate_dialogue_service,
        "generate_candidate_dialogue_reply",
    ) as gen_mock:
        result = await candidate_dialogue_service.process_pending_dialogue_replies(wf_id)

    await engine.dispose()

    assert result["skipped_duplicate"] == 1
    gen_mock.assert_not_called()


@pytest.mark.asyncio
async def test_auto_outreach_review_mode_silent_on_reused_draft():
    draft = {
        "conversation_id": "c1",
        "candidate_snapshot_id": "s1",
        "display_name": "张三",
        "message_text": "请问是否有美签？",
        "round": 1,
        "reused_existing": True,
    }
    with (
        patch.object(im_autopilot, "is_chat_initiated", new_callable=AsyncMock, return_value=True),
        patch.object(im_autopilot, "is_prior_communication", new_callable=AsyncMock, return_value=False),
        patch.object(im_autopilot, "_workflow_im_review_required", new_callable=AsyncMock, return_value=True),
        patch.object(im_autopilot, "prepare_followup_for_candidate", new_callable=AsyncMock, return_value=draft),
        patch.object(im_autopilot, "_emit_review_pending_draft", new_callable=AsyncMock) as emit_mock,
        patch.object(im_autopilot, "_send_single_draft", new_callable=AsyncMock),
    ):
        result = await im_autopilot.auto_outreach_for_candidate("wf1", "s1", "追问")
    assert result is not None
    assert result["reused_existing"] is True
    emit_mock.assert_not_awaited()
