from packages.db.repositories import CandidateRepository
from packages.db.session import async_session_factory
from packages.schemas.candidate import CandidateSnapshotData


async def save_snapshots(snapshots: list[CandidateSnapshotData]) -> list[str]:
    ids: list[str] = []
    async with async_session_factory() as session:
        repo = CandidateRepository(session)
        for snap in snapshots:
            saved = await repo.save_snapshot(snap)
            ids.append(saved.id)
        await session.commit()
    return ids
