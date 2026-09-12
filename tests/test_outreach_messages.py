"""Tests for outreach message edit API."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.dependencies import get_db
from apps.api.main import app
from packages.db.models import Base, CandidateSnapshot
from packages.db.repositories import ConversationRepository, WorkflowRepository


@pytest.fixture
async def session_factory(tmp_path):
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'outreach_messages.db').as_posix()}"
    engine = create_async_engine(db_url, connect_args={"timeout": 30})

    async def _setup() -> async_sessionmaker[AsyncSession]:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    yield _setup, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_update_message_text_repository(session_factory):
    setup, _engine = session_factory
    factory = await setup()

    async with factory() as session:
        wf_repo = WorkflowRepository(session)
        wf = await wf_repo.create(
            name="test",
            platform="liepin",
            start_url="https://example.com",
            job_id="job-1",
            config={},
        )
        snap = CandidateSnapshot(
            workflow_id=wf.id,
            platform="liepin",
            display_name="Test",
            raw_text="resume",
        )
        session.add(snap)
        await session.flush()
        conv_repo = ConversationRepository(session)
        conv = await conv_repo.create(wf.id, snap.id, [])
        msg = await conv_repo.save_message(
            conversation_id=conv.id,
            candidate_snapshot_id=snap.id,
            direction="outbound",
            message_text="old draft",
            status="drafted",
            round_num=1,
        )
        await conv_repo.update_message_text(msg.id, "new draft")
        await session.commit()
        saved = await conv_repo.get_message(msg.id)

    assert saved is not None
    assert saved.message_text == "new draft"
    assert saved.status == "drafted"


@pytest.mark.asyncio
async def test_patch_outreach_message_updates_drafted_text(session_factory):
    setup, _engine = session_factory
    factory = await setup()

    async with factory() as session:
        wf_repo = WorkflowRepository(session)
        wf = await wf_repo.create(
            name="test",
            platform="liepin",
            start_url="https://example.com",
            job_id="job-1",
            config={},
        )
        snap = CandidateSnapshot(
            workflow_id=wf.id,
            platform="liepin",
            display_name="Test",
            raw_text="resume",
        )
        session.add(snap)
        await session.flush()
        conv_repo = ConversationRepository(session)
        conv = await conv_repo.create(wf.id, snap.id, [])
        msg = await conv_repo.save_message(
            conversation_id=conv.id,
            candidate_snapshot_id=snap.id,
            direction="outbound",
            message_text="old draft",
            status="drafted",
            round_num=1,
        )
        await session.commit()
        message_id = msg.id

    async def override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/outreach_messages/{message_id}",
                json={"message_text": "edited draft"},
            )
            assert resp.status_code == 200
            assert resp.json()["message_text"] == "edited draft"
    finally:
        app.dependency_overrides.clear()

    async with factory() as session:
        conv_repo = ConversationRepository(session)
        saved = await conv_repo.get_message(message_id)
        assert saved is not None
        assert saved.message_text == "edited draft"


@pytest.mark.asyncio
async def test_patch_outreach_message_rejects_sent_status(session_factory):
    setup, _engine = session_factory
    factory = await setup()

    async with factory() as session:
        wf_repo = WorkflowRepository(session)
        wf = await wf_repo.create(
            name="test",
            platform="liepin",
            start_url="https://example.com",
            job_id="job-1",
            config={},
        )
        snap = CandidateSnapshot(
            workflow_id=wf.id,
            platform="liepin",
            display_name="Test",
            raw_text="resume",
        )
        session.add(snap)
        await session.flush()
        conv_repo = ConversationRepository(session)
        conv = await conv_repo.create(wf.id, snap.id, [])
        msg = await conv_repo.save_message(
            conversation_id=conv.id,
            candidate_snapshot_id=snap.id,
            direction="outbound",
            message_text="sent msg",
            status="sent",
            round_num=1,
        )
        await session.commit()
        message_id = msg.id

    async def override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/outreach_messages/{message_id}",
                json={"message_text": "cannot edit"},
            )
            assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()
