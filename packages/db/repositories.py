import hashlib
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import (
    CandidateProfileCurrent,
    CandidateScreeningResult,
    CandidateSnapshot,
    CandidateSupplementalInfo,
    OutreachConversation,
    OutreachMessage,
    RecruitingWorkflow,
    Shortlist,
    ShortlistCandidate,
    TalentArchiveProfile,
    new_id,
)
from packages.candidate_identity import candidate_identity_hash, snapshot_identity_key
from packages.schemas.candidate import CandidateSnapshotData
from packages.schemas.screening import ScreeningOutput, ShortlistCandidate as ShortlistCandidateSchema


async def _require_workflow_platform(
    session: AsyncSession,
    workflow_id: str,
    platform: str,
) -> None:
    result = await session.execute(
        select(RecruitingWorkflow.platform).where(RecruitingWorkflow.id == workflow_id)
    )
    workflow_platform = result.scalar_one_or_none()
    if workflow_platform is None:
        raise ValueError(f"Workflow not found: {workflow_id}")
    if workflow_platform != platform:
        raise ValueError(
            f"Candidate platform {platform!r} does not match workflow platform {workflow_platform!r}"
        )


async def _require_candidate_in_workflow(
    session: AsyncSession,
    workflow_id: str,
    candidate_snapshot_id: str,
) -> None:
    result = await session.execute(
        select(CandidateSnapshot.workflow_id).where(CandidateSnapshot.id == candidate_snapshot_id)
    )
    owner_workflow_id = result.scalar_one_or_none()
    if owner_workflow_id is None:
        raise ValueError(f"Candidate snapshot not found: {candidate_snapshot_id}")
    if owner_workflow_id != workflow_id:
        raise ValueError(
            "Candidate snapshot does not belong to workflow "
            f"{workflow_id}: {candidate_snapshot_id}"
        )


class WorkflowRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, name: str, platform: str, start_url: str, job_id: str, config: dict) -> RecruitingWorkflow:
        wf = RecruitingWorkflow(
            id=new_id(),
            name=name,
            platform=platform,
            start_url=start_url,
            job_id=job_id,
            status="CREATED",
            config=config,
        )
        self.session.add(wf)
        await self.session.flush()
        return wf

    async def get(self, workflow_id: str) -> RecruitingWorkflow | None:
        result = await self.session.execute(
            select(RecruitingWorkflow).where(RecruitingWorkflow.id == workflow_id)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        workflow_id: str,
        status: str,
        *,
        fetch_task_id: str | None = None,
        shortlist_id: str | None = None,
        temporal_workflow_id: str | None = None,
        error_message: str | None = None,
    ) -> None:
        values: dict = {"status": status, "updated_at": datetime.now(timezone.utc)}
        if fetch_task_id is not None:
            values["fetch_task_id"] = fetch_task_id
        if shortlist_id is not None:
            values["shortlist_id"] = shortlist_id
        if temporal_workflow_id is not None:
            values["temporal_workflow_id"] = temporal_workflow_id
        if error_message is not None:
            values["error_message"] = error_message
        await self.session.execute(
            update(RecruitingWorkflow).where(RecruitingWorkflow.id == workflow_id).values(**values)
        )

    async def patch_config(self, workflow_id: str, patch: dict) -> dict:
        wf = await self.get(workflow_id)
        if not wf:
            raise ValueError(f"Workflow not found: {workflow_id}")
        merged = dict(wf.config or {})
        merged.update(patch)
        await self.session.execute(
            update(RecruitingWorkflow)
            .where(RecruitingWorkflow.id == workflow_id)
            .values(config=merged, updated_at=datetime.now(timezone.utc))
        )
        await self.session.flush()
        return merged

    async def patch_fetch(self, workflow_id: str, **fetch_patch) -> dict:
        wf = await self.get(workflow_id)
        if not wf:
            raise ValueError(f"Workflow not found: {workflow_id}")
        merged = dict(wf.config or {})
        fetch = dict(merged.get("fetch") or {})
        fetch.update(fetch_patch)
        merged["fetch"] = fetch
        await self.session.execute(
            update(RecruitingWorkflow)
            .where(RecruitingWorkflow.id == workflow_id)
            .values(config=merged, updated_at=datetime.now(timezone.utc))
        )
        await self.session.flush()
        return merged

    async def list_all(self, limit: int = 50) -> list[RecruitingWorkflow]:
        result = await self.session.execute(
            select(RecruitingWorkflow).order_by(RecruitingWorkflow.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def list_starting(self, limit: int = 20) -> list[RecruitingWorkflow]:
        result = await self.session.execute(
            select(RecruitingWorkflow)
            .where(RecruitingWorkflow.status == "CREATED")
            .order_by(RecruitingWorkflow.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_active(self, limit: int = 20) -> list[RecruitingWorkflow]:
        active_statuses = (
            "CREATED",
            "FETCHING",
            "FETCH_COMPLETED",
            "SCREENING",
            "SCREENING_COMPLETED",
            "CONVERSATIONS_STARTED",
        )
        result = await self.session.execute(
            select(RecruitingWorkflow)
            .where(RecruitingWorkflow.status.in_(active_statuses))
            .order_by(RecruitingWorkflow.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_statuses(self, statuses: set[str] | frozenset[str]) -> list[RecruitingWorkflow]:
        if not statuses:
            return []
        result = await self.session.execute(
            select(RecruitingWorkflow).where(RecruitingWorkflow.status.in_(tuple(statuses)))
        )
        return list(result.scalars().all())

    async def delete_workflow_data(self, workflow_id: str) -> bool:
        """Delete a workflow and all related rows in recruiting.db."""
        wf = await self.get(workflow_id)
        if not wf:
            return False

        snap_result = await self.session.execute(
            select(CandidateSnapshot.id).where(CandidateSnapshot.workflow_id == workflow_id)
        )
        snap_ids = list(snap_result.scalars().all())

        conv_result = await self.session.execute(
            select(OutreachConversation.id).where(OutreachConversation.workflow_id == workflow_id)
        )
        conv_ids = list(conv_result.scalars().all())

        sl_result = await self.session.execute(
            select(Shortlist.id).where(Shortlist.workflow_id == workflow_id)
        )
        shortlist_ids = list(sl_result.scalars().all())

        if conv_ids:
            await self.session.execute(
                delete(OutreachMessage).where(OutreachMessage.conversation_id.in_(conv_ids))
            )
        if snap_ids:
            await self.session.execute(
                delete(OutreachMessage).where(OutreachMessage.candidate_snapshot_id.in_(snap_ids))
            )
        await self.session.execute(
            delete(OutreachConversation).where(OutreachConversation.workflow_id == workflow_id)
        )

        if shortlist_ids:
            await self.session.execute(
                delete(ShortlistCandidate).where(ShortlistCandidate.shortlist_id.in_(shortlist_ids))
            )
        await self.session.execute(delete(Shortlist).where(Shortlist.workflow_id == workflow_id))

        await self.session.execute(
            delete(CandidateScreeningResult).where(CandidateScreeningResult.workflow_id == workflow_id)
        )
        await self.session.execute(
            delete(CandidateSupplementalInfo).where(CandidateSupplementalInfo.workflow_id == workflow_id)
        )
        await self.session.execute(
            delete(CandidateProfileCurrent).where(CandidateProfileCurrent.workflow_id == workflow_id)
        )
        await self.session.execute(
            delete(CandidateSnapshot).where(CandidateSnapshot.workflow_id == workflow_id)
        )
        await self.session.execute(
            delete(RecruitingWorkflow).where(RecruitingWorkflow.id == workflow_id)
        )
        await self.session.flush()
        return True


class CandidateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_snapshot(self, data: CandidateSnapshotData) -> CandidateSnapshot:
        await _require_workflow_platform(self.session, data.workflow_id, data.platform)
        raw_hash = hashlib.sha256(data.raw_text.encode()).hexdigest() if data.raw_text else None
        metadata = {
            "missing_fields": data.missing_fields,
            "template_type": data.template_type,
            **data.metadata,
        }
        identity_key = candidate_identity_hash(
            display_name=data.display_name,
            raw_text=data.raw_text,
            fallback_parts=(
                metadata.get("card_age") or metadata.get("age"),
                metadata.get("card_school") or metadata.get("school"),
                data.education,
                data.city,
                data.work_years,
            ),
        )
        if identity_key:
            metadata["candidate_identity_key"] = identity_key
            existing = await self.session.execute(
                select(CandidateSnapshot)
                .where(
                    CandidateSnapshot.workflow_id == data.workflow_id,
                    CandidateSnapshot.platform == data.platform,
                )
                .order_by(CandidateSnapshot.captured_at.asc())
            )
            for row in existing.scalars().all():
                row_meta = row.metadata_ or {}
                if row_meta.get("candidate_identity_key") == identity_key:
                    metadata["duplicate_candidate"] = True
                    metadata["duplicate_of_snapshot_id"] = row.id
                    metadata["duplicate_detected_at"] = datetime.now(timezone.utc).isoformat()
                    break
            else:
                metadata["duplicate_candidate"] = False

        snap = CandidateSnapshot(
            id=new_id(),
            workflow_id=data.workflow_id,
            platform=data.platform,
            source_candidate_id=data.source_candidate_id,
            source_url=data.source_url,
            display_name=data.display_name,
            current_title=data.current_title,
            current_company=data.current_company,
            work_years=data.work_years,
            education=data.education,
            city=data.city,
            skills=data.skills,
            summary=data.summary,
            experience_summary=data.experience_summary,
            project_summary=data.project_summary,
            raw_text=data.raw_text,
            raw_text_hash=raw_hash,
            extraction_confidence=data.extraction_confidence,
            metadata_=metadata,
        )
        self.session.add(snap)
        await self.session.flush()
        return snap

    async def get(self, snapshot_id: str) -> CandidateSnapshot | None:
        result = await self.session.execute(
            select(CandidateSnapshot).where(CandidateSnapshot.id == snapshot_id)
        )
        return result.scalar_one_or_none()

    async def list_by_workflow(self, workflow_id: str) -> list[CandidateSnapshot]:
        result = await self.session.execute(
            select(CandidateSnapshot)
            .where(CandidateSnapshot.workflow_id == workflow_id)
            .order_by(CandidateSnapshot.captured_at.desc())
        )
        return list(result.scalars().all())

    async def count_by_workflow(self, workflow_id: str) -> int:
        snaps = await self.list_by_workflow(workflow_id)
        return len(snaps)

    async def patch_metadata(self, snapshot_id: str, patch: dict) -> None:
        from packages.db.sqlite_guard import is_sqlite_locked_error
        import asyncio

        for attempt in range(6):
            try:
                snap = await self.get(snapshot_id)
                if not snap:
                    return
                merged = dict(snap.metadata_ or {})
                merged.update(patch)
                await self.session.execute(
                    update(CandidateSnapshot)
                    .where(CandidateSnapshot.id == snapshot_id)
                    .values(metadata_=merged)
                )
                return
            except OperationalError as exc:
                if not is_sqlite_locked_error(exc) or attempt >= 5:
                    raise
                await self.session.rollback()
                await asyncio.sleep(0.15 * (attempt + 1))

    async def update_current_company(self, snapshot_id: str, company: str | None) -> None:
        name = (company or "").strip()
        if not name:
            return
        name = name[:40]
        snap = await self.get(snapshot_id)
        if not snap:
            return
        merged = dict(snap.metadata_ or {})
        merged["current_company"] = name
        merged["company_source"] = "agent_parse"
        await self.session.execute(
            update(CandidateSnapshot)
            .where(CandidateSnapshot.id == snapshot_id)
            .values(current_company=name, metadata_=merged)
        )


class ScreeningRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_result(
        self, workflow_id: str, job_id: str | None, output: ScreeningOutput, round_num: int = 1
    ) -> CandidateScreeningResult:
        await _require_candidate_in_workflow(self.session, workflow_id, output.candidate_snapshot_id)
        result = CandidateScreeningResult(
            id=new_id(),
            workflow_id=workflow_id,
            candidate_snapshot_id=output.candidate_snapshot_id,
            job_id=job_id,
            screening_round=round_num,
            total_score=output.total_score,
            level=output.level,
            score_detail=output.score_detail,
            matched_points=output.matched_points,
            gaps=output.gaps,
            missing_info=[m.model_dump() for m in output.missing_info],
            suggested_action=output.suggested_action,
        )
        self.session.add(result)
        await self.session.flush()
        if (output.level or "").lower() in {"observe", "followup", "recommend", "backup"}:
            snapshot = await self.session.get(CandidateSnapshot, output.candidate_snapshot_id)
            if snapshot:
                await TalentArchiveRepository(self.session).upsert_from_screening(snapshot, result)
        return result

    async def get_latest_for_candidate(
        self, workflow_id: str, candidate_snapshot_id: str
    ) -> CandidateScreeningResult | None:
        result = await self.session.execute(
            select(CandidateScreeningResult)
            .where(
                CandidateScreeningResult.workflow_id == workflow_id,
                CandidateScreeningResult.candidate_snapshot_id == candidate_snapshot_id,
            )
            .order_by(CandidateScreeningResult.screening_round.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_by_workflow(self, workflow_id: str) -> list[CandidateScreeningResult]:
        result = await self.session.execute(
            select(CandidateScreeningResult)
            .where(CandidateScreeningResult.workflow_id == workflow_id)
            .order_by(CandidateScreeningResult.total_score.desc())
        )
        return list(result.scalars().all())

    async def list_latest_by_workflow(self, workflow_id: str) -> list[CandidateScreeningResult]:
        result = await self.session.execute(
            select(CandidateScreeningResult)
            .where(CandidateScreeningResult.workflow_id == workflow_id)
            .order_by(
                CandidateScreeningResult.candidate_snapshot_id,
                CandidateScreeningResult.screening_round.desc(),
                CandidateScreeningResult.created_at.desc(),
            )
        )
        latest: dict[str, CandidateScreeningResult] = {}
        for row in result.scalars().all():
            if row.candidate_snapshot_id not in latest:
                latest[row.candidate_snapshot_id] = row
        rows = list(latest.values())
        rows.sort(key=lambda r: float(r.total_score or 0), reverse=True)
        return rows

    async def next_round_for_candidate(self, workflow_id: str, candidate_snapshot_id: str) -> int:
        latest = await self.get_latest_for_candidate(workflow_id, candidate_snapshot_id)
        if not latest or latest.screening_round is None:
            return 1
        return int(latest.screening_round) + 1

    async def create_shortlist(
        self,
        workflow_id: str,
        job_id: str | None,
        candidates: list[ShortlistCandidateSchema],
        min_score: float,
        total_candidates: int,
    ) -> Shortlist:
        for c in candidates:
            await _require_candidate_in_workflow(self.session, workflow_id, c.candidate_snapshot_id)
        shortlist = Shortlist(
            id=new_id(),
            workflow_id=workflow_id,
            job_id=job_id,
            total_candidates=total_candidates,
            selected_count=len(candidates),
            min_score=min_score,
        )
        self.session.add(shortlist)
        await self.session.flush()

        for c in candidates:
            sc = ShortlistCandidate(
                id=new_id(),
                shortlist_id=shortlist.id,
                candidate_snapshot_id=c.candidate_snapshot_id,
                rank=c.rank,
                score=c.score,
                level=c.level,
            )
            self.session.add(sc)
        await self.session.flush()
        return shortlist

    async def get_shortlist(self, shortlist_id: str) -> tuple[Shortlist | None, list[ShortlistCandidate]]:
        sl_result = await self.session.execute(select(Shortlist).where(Shortlist.id == shortlist_id))
        shortlist = sl_result.scalar_one_or_none()
        if not shortlist:
            return None, []
        sc_result = await self.session.execute(
            select(ShortlistCandidate)
            .where(ShortlistCandidate.shortlist_id == shortlist_id)
            .order_by(ShortlistCandidate.rank)
        )
        return shortlist, list(sc_result.scalars().all())

    async def update_shortlist_candidate_level(
        self,
        shortlist_id: str,
        candidate_snapshot_id: str,
        level: str,
        *,
        score: float | None = None,
    ) -> None:
        values: dict = {"level": level}
        if score is not None:
            values["score"] = score
        await self.session.execute(
            update(ShortlistCandidate)
            .where(
                ShortlistCandidate.shortlist_id == shortlist_id,
                ShortlistCandidate.candidate_snapshot_id == candidate_snapshot_id,
            )
            .values(**values)
        )
        await self.session.flush()

    async def replace_shortlist_candidates(
        self,
        shortlist_id: str,
        candidates: list[ShortlistCandidateSchema],
    ) -> None:
        shortlist_result = await self.session.execute(
            select(Shortlist).where(Shortlist.id == shortlist_id)
        )
        shortlist = shortlist_result.scalar_one_or_none()
        if not shortlist:
            return
        for c in candidates:
            await _require_candidate_in_workflow(self.session, shortlist.workflow_id, c.candidate_snapshot_id)
        await self.session.execute(
            delete(ShortlistCandidate).where(ShortlistCandidate.shortlist_id == shortlist_id)
        )
        for c in candidates:
            self.session.add(
                ShortlistCandidate(
                    id=new_id(),
                    shortlist_id=shortlist_id,
                    candidate_snapshot_id=c.candidate_snapshot_id,
                    rank=c.rank,
                    score=c.score,
                    level=c.level,
                )
            )
        shortlist.selected_count = len(candidates)
        await self.session.flush()


class ConversationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_workflow(self, workflow_id: str) -> list[OutreachConversation]:
        result = await self.session.execute(
            select(OutreachConversation)
            .where(OutreachConversation.workflow_id == workflow_id)
            .order_by(OutreachConversation.created_at)
        )
        return list(result.scalars().all())

    async def create(
        self,
        workflow_id: str,
        candidate_snapshot_id: str,
        missing_info: list,
        *,
        channel: str = "im_center",
        conversation_type: str = "followup",
        im_contact_key: str | None = None,
    ) -> OutreachConversation:
        await _require_candidate_in_workflow(self.session, workflow_id, candidate_snapshot_id)
        conv = OutreachConversation(
            id=new_id(),
            workflow_id=workflow_id,
            candidate_snapshot_id=candidate_snapshot_id,
            channel=channel,
            conversation_type=conversation_type,
            status="CREATED",
            missing_info=missing_info,
            im_contact_key=im_contact_key,
        )
        self.session.add(conv)
        await self.session.flush()
        return conv

    async def get(self, conversation_id: str) -> OutreachConversation | None:
        result = await self.session.execute(
            select(OutreachConversation).where(OutreachConversation.id == conversation_id)
        )
        return result.scalar_one_or_none()

    async def get_by_candidate(
        self, workflow_id: str, candidate_snapshot_id: str
    ) -> OutreachConversation | None:
        result = await self.session.execute(
            select(OutreachConversation).where(
                OutreachConversation.workflow_id == workflow_id,
                OutreachConversation.candidate_snapshot_id == candidate_snapshot_id,
            )
        )
        return result.scalar_one_or_none()

    async def update_status(self, conversation_id: str, status: str, **kwargs) -> None:
        values: dict = {"status": status, "updated_at": datetime.now(timezone.utc)}
        values.update(kwargs)
        await self.session.execute(
            update(OutreachConversation)
            .where(OutreachConversation.id == conversation_id)
            .values(**values)
        )

    async def list_waiting_reply(self) -> list[OutreachConversation]:
        result = await self.session.execute(
            select(OutreachConversation).where(OutreachConversation.status == "WAITING_REPLY")
        )
        return list(result.scalars().all())

    async def save_message(
        self,
        conversation_id: str,
        candidate_snapshot_id: str,
        direction: str,
        message_text: str,
        status: str = "drafted",
        round_num: int | None = None,
        platform_message_id: str | None = None,
        extracted_fields: dict | None = None,
    ) -> OutreachMessage:
        conv = await self.get(conversation_id)
        if not conv:
            raise ValueError(f"Conversation not found: {conversation_id}")
        if conv.candidate_snapshot_id != candidate_snapshot_id:
            raise ValueError(
                "Message candidate does not match conversation candidate: "
                f"{candidate_snapshot_id}"
            )
        await _require_candidate_in_workflow(self.session, conv.workflow_id, candidate_snapshot_id)
        msg = OutreachMessage(
            id=new_id(),
            conversation_id=conversation_id,
            candidate_snapshot_id=candidate_snapshot_id,
            direction=direction,
            message_text=message_text,
            status=status,
            round=round_num,
            platform_message_id=platform_message_id,
            extracted_fields=extracted_fields,
        )
        self.session.add(msg)
        await self.session.flush()
        return msg

    async def get_message(self, message_id: str) -> OutreachMessage | None:
        result = await self.session.execute(
            select(OutreachMessage).where(OutreachMessage.id == message_id)
        )
        return result.scalar_one_or_none()

    async def update_message_status(
        self, message_id: str, status: str, error_message: str | None = None
    ) -> None:
        values: dict = {"status": status}
        if error_message:
            values["error_message"] = error_message
        await self.session.execute(
            update(OutreachMessage).where(OutreachMessage.id == message_id).values(**values)
        )

    async def update_message_text(self, message_id: str, message_text: str) -> None:
        await self.session.execute(
            update(OutreachMessage)
            .where(OutreachMessage.id == message_id)
            .values(message_text=message_text, status="drafted", error_message=None)
        )

    async def list_messages(self, conversation_id: str) -> list[OutreachMessage]:
        result = await self.session.execute(
            select(OutreachMessage)
            .where(OutreachMessage.conversation_id == conversation_id)
            .order_by(OutreachMessage.created_at)
        )
        return list(result.scalars().all())


class ProfileRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_merged_profile(
        self, workflow_id: str, candidate_snapshot_id: str, merged_profile: dict
    ) -> CandidateProfileCurrent:
        await _require_candidate_in_workflow(self.session, workflow_id, candidate_snapshot_id)
        result = await self.session.execute(
            select(CandidateProfileCurrent).where(
                CandidateProfileCurrent.workflow_id == workflow_id,
                CandidateProfileCurrent.candidate_snapshot_id == candidate_snapshot_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.merged_profile = merged_profile
            existing.profile_version += 1
            existing.updated_at = datetime.now(timezone.utc)
            await self.session.flush()
            return existing

        profile = CandidateProfileCurrent(
            id=new_id(),
            workflow_id=workflow_id,
            candidate_snapshot_id=candidate_snapshot_id,
            merged_profile=merged_profile,
        )
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def save_supplemental(
        self,
        workflow_id: str,
        candidate_snapshot_id: str,
        raw_message: str,
        extracted_fields: dict,
        confidence: float,
        source_channel: str = "liepin",
    ) -> CandidateSupplementalInfo:
        await _require_candidate_in_workflow(self.session, workflow_id, candidate_snapshot_id)
        info = CandidateSupplementalInfo(
            id=new_id(),
            workflow_id=workflow_id,
            candidate_snapshot_id=candidate_snapshot_id,
            source_channel=source_channel,
            raw_message=raw_message,
            extracted_fields=extracted_fields,
            confidence=confidence,
        )
        self.session.add(info)
        await self.session.flush()
        return info


class TalentArchiveRepository:
    """Internal, cross-workflow profiles for candidates that were not eliminated."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_from_screening(
        self,
        snapshot: CandidateSnapshot,
        screening: CandidateScreeningResult,
    ) -> TalentArchiveProfile | None:
        from packages.talent_archive_policy import talent_archive_enabled

        if not talent_archive_enabled():
            return None
        identity_key = snapshot_identity_key(snapshot)
        if not identity_key:
            return None

        result = await self.session.execute(
            select(TalentArchiveProfile).where(TalentArchiveProfile.identity_key == identity_key)
        )
        existing = result.scalar_one_or_none()
        score = float(screening.total_score) if screening.total_score is not None else None
        profile_data = {
            "matched_points": list(screening.matched_points or []),
            "gaps": list(screening.gaps or []),
            "missing_info": list(screening.missing_info or []),
            "score_detail": dict(screening.score_detail or {}),
        }
        if existing:
            existing.platform = snapshot.platform or existing.platform
            existing.source_snapshot_id = snapshot.id
            existing.latest_workflow_id = snapshot.workflow_id
            existing.source_url = snapshot.source_url or existing.source_url
            existing.display_name = snapshot.display_name or existing.display_name
            existing.current_title = snapshot.current_title or existing.current_title
            existing.current_company = snapshot.current_company or existing.current_company
            existing.work_years = snapshot.work_years if snapshot.work_years is not None else existing.work_years
            existing.education = snapshot.education or existing.education
            existing.city = snapshot.city or existing.city
            existing.skills = _merge_unique_strings(existing.skills, snapshot.skills)
            existing.summary = snapshot.summary or existing.summary
            existing.experience_summary = snapshot.experience_summary or existing.experience_summary
            existing.project_summary = snapshot.project_summary or existing.project_summary
            if len(snapshot.raw_text or "") >= len(existing.resume_raw_text or ""):
                existing.resume_raw_text = snapshot.raw_text or existing.resume_raw_text
            existing.profile_data = profile_data
            existing.last_score = score
            existing.last_level = screening.level
            existing.best_score = max(
                [value for value in (existing.best_score, score) if value is not None],
                default=None,
            )
            existing.source_workflow_ids = _merge_unique_strings(
                existing.source_workflow_ids,
                [snapshot.workflow_id],
            )
            existing.last_archived_at = datetime.now(timezone.utc)
            await self.session.flush()
            return existing

        archived = TalentArchiveProfile(
            id=new_id(),
            identity_key=identity_key,
            platform=snapshot.platform,
            source_snapshot_id=snapshot.id,
            latest_workflow_id=snapshot.workflow_id,
            source_url=snapshot.source_url,
            display_name=snapshot.display_name,
            current_title=snapshot.current_title,
            current_company=snapshot.current_company,
            work_years=snapshot.work_years,
            education=snapshot.education,
            city=snapshot.city,
            skills=list(snapshot.skills or []),
            summary=snapshot.summary,
            experience_summary=snapshot.experience_summary,
            project_summary=snapshot.project_summary,
            resume_raw_text=snapshot.raw_text or "",
            profile_data=profile_data,
            best_score=score,
            last_score=score,
            last_level=screening.level,
            source_workflow_ids=[snapshot.workflow_id],
        )
        self.session.add(archived)
        await self.session.flush()
        return archived

    async def search(self, query: str = "", *, limit: int = 20) -> list[TalentArchiveProfile]:
        result = await self.session.execute(
            select(TalentArchiveProfile).order_by(
                TalentArchiveProfile.best_score.desc(),
                TalentArchiveProfile.last_archived_at.desc(),
            )
        )
        rows = list(result.scalars().all())
        terms = [term.strip().lower() for term in query.split() if term.strip()]
        if not terms:
            return rows[: max(1, min(limit, 100))]

        def matches(profile: TalentArchiveProfile) -> bool:
            searchable = " ".join(
                str(value or "")
                for value in (
                    profile.display_name,
                    profile.current_title,
                    profile.current_company,
                    profile.education,
                    profile.city,
                    profile.summary,
                    profile.experience_summary,
                    profile.project_summary,
                    profile.resume_raw_text,
                    " ".join(profile.skills or []),
                    profile.profile_data,
                )
            ).lower()
            return all(term in searchable for term in terms)

        return [profile for profile in rows if matches(profile)][: max(1, min(limit, 100))]


def _merge_unique_strings(existing: list | None, incoming: list | None) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*(existing or []), *(incoming or [])]:
        value = str(item or "").strip()
        if value and value not in seen:
            seen.add(value)
            merged.append(value)
    return merged
