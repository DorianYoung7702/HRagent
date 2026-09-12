from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.db.models import Base, CandidateSnapshot
from packages.db.repositories import ConversationRepository, WorkflowRepository
from services.agent_service import candidate_dialogue_service


@pytest.fixture
def session_factory(tmp_path):
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'dialogue.db').as_posix()}"
    engine = create_async_engine(db_url, connect_args={"timeout": 30})

    async def _setup() -> async_sessionmaker[AsyncSession]:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    return _setup, engine


async def _seed_dialogue(session):
    wf_repo = WorkflowRepository(session)
    conv_repo = ConversationRepository(session)
    wf = await wf_repo.create(
        name="dialogue",
        platform="liepin",
        start_url="https://example.com",
        job_id="job-1",
        config={
            "fetch": {"browser_profile": "hr_default"},
            "job": {"title": "Latam Sales", "description": "Sales role"},
            "job_qa_profile": {"salary_range": "15-25K"},
        },
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
        "What is the salary range?",
        status="received",
        platform_message_id="m1",
    )
    await conv_repo.update_status(conv.id, "REPLY_RECEIVED")
    await session.commit()
    return wf.id, snap.id, conv.id


@pytest.mark.asyncio
async def test_process_dialogue_auto_sends_whitelisted_answer(session_factory, monkeypatch):
    setup, engine = session_factory
    factory = await setup()
    async with factory() as session:
        wf_id, snap_id, conv_id = await _seed_dialogue(session)

    monkeypatch.setattr(candidate_dialogue_service, "async_session_factory", factory)
    with patch.object(
        candidate_dialogue_service,
        "run_im_send_batch",
        new_callable=AsyncMock,
        return_value=[{"ok": True, "conversation_id": conv_id}],
    ) as send_mock:
        result = await candidate_dialogue_service.process_pending_dialogue_replies(wf_id)

    async with factory() as session:
        conv_repo = ConversationRepository(session)
        conv = await conv_repo.get(conv_id)
        messages = await conv_repo.list_messages(conv_id)

    await engine.dispose()

    assert result["auto_reply_sent"] == 1
    send_mock.assert_awaited_once()
    assert conv is not None
    assert conv.status == "WAITING_REPLY"
    outbound = [m for m in messages if m.direction == "outbound"]
    assert len(outbound) == 1
    assert outbound[0].status == "sent"
    assert outbound[0].extracted_fields["agent_type"] == "candidate_dialogue_agent"
    assert outbound[0].extracted_fields["question_type"] == "salary"


@pytest.mark.asyncio
async def test_process_dialogue_does_not_duplicate_answer_for_same_inbound(session_factory, monkeypatch):
    setup, engine = session_factory
    factory = await setup()
    async with factory() as session:
        wf_id, snap_id, conv_id = await _seed_dialogue(session)
        conv_repo = ConversationRepository(session)
        await conv_repo.save_message(
            conv_id,
            snap_id,
            "outbound",
            "The salary range is 15-25K.",
            status="sent",
            extracted_fields={
                "agent_type": "candidate_dialogue_agent",
                "reply_to_message_id": "m1",
                "question_type": "salary",
            },
        )
        await session.commit()

    monkeypatch.setattr(candidate_dialogue_service, "async_session_factory", factory)
    with patch.object(
        candidate_dialogue_service,
        "run_im_send_batch",
        new_callable=AsyncMock,
        return_value=[],
    ) as send_mock:
        result = await candidate_dialogue_service.process_pending_dialogue_replies(wf_id)

    await engine.dispose()

    assert result["skipped_duplicate"] == 1
    send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_dialogue_review_mode_keeps_auto_reply_drafted(session_factory, monkeypatch):
    setup, engine = session_factory
    factory = await setup()
    async with factory() as session:
        wf_id, _snap_id, conv_id = await _seed_dialogue(session)
        wf_repo = WorkflowRepository(session)
        wf = await wf_repo.get(wf_id)
        wf.config = {
            **(wf.config or {}),
            "outreach": {"im_review_required": True},
        }
        await session.commit()

    monkeypatch.setattr(candidate_dialogue_service, "async_session_factory", factory)
    with patch.object(
        candidate_dialogue_service,
        "run_im_send_batch",
        new_callable=AsyncMock,
        return_value=[{"ok": True, "conversation_id": conv_id}],
    ) as send_mock:
        result = await candidate_dialogue_service.process_pending_dialogue_replies(wf_id)

    await engine.dispose()

    assert result["auto_reply_sent"] == 0
    assert result["drafted"] == 1
    send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_dialogue_leaves_unknown_answer_for_hr(session_factory, monkeypatch):
    setup, engine = session_factory
    factory = await setup()
    async with factory() as session:
        wf_id, _snap_id, conv_id = await _seed_dialogue(session)
        wf_repo = WorkflowRepository(session)
        wf = await wf_repo.get(wf_id)
        wf.config = {"job_qa_profile": {}, "fetch": {"browser_profile": "hr_default"}, "job": {}}
        await session.commit()

    monkeypatch.setattr(candidate_dialogue_service, "async_session_factory", factory)
    with patch.object(
        candidate_dialogue_service,
        "run_im_send_batch",
        new_callable=AsyncMock,
        return_value=[],
    ) as send_mock:
        result = await candidate_dialogue_service.process_pending_dialogue_replies(wf_id)

    async with factory() as session:
        conv_repo = ConversationRepository(session)
        conv = await conv_repo.get(conv_id)
        messages = await conv_repo.list_messages(conv_id)

    await engine.dispose()

    assert result["needs_hr"] == 1
    send_mock.assert_not_awaited()
    assert conv is not None
    assert conv.status == "NEEDS_HR"
    draft = [m for m in messages if m.direction == "outbound"]
    assert len(draft) == 1
    assert draft[0].status == "drafted"
    assert draft[0].extracted_fields["auto_send_allowed"] is False
