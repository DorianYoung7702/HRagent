from datetime import datetime, timezone

from temporalio import activity

from packages.db.repositories import (
    CandidateRepository,
    ConversationRepository,
    ProfileRepository,
    ScreeningRepository,
    WorkflowRepository,
)
from packages.db.session import async_session_factory
from packages.schemas.candidate import FetchInput
from packages.schemas.workflow import CandidateConversationInput, ConversationState


@activity.defn
async def fetch_candidates_activity(fetch_config: dict) -> dict:
    from services.fetch_worker.runner import run_fetch_task

    fetch_input = FetchInput(**fetch_config)
    result = await run_fetch_task(fetch_input)
    return result.model_dump()


@activity.defn
async def screen_candidates_activity(payload: dict) -> dict:
    from packages.schemas.workflow import RecruitingWorkflowConfig
    from services.agent_service.screening_service import run_screening_batch

    config = RecruitingWorkflowConfig(**payload["config"])
    result = await run_screening_batch(payload["workflow_id"], config)
    return result.model_dump()


@activity.defn
async def create_conversation_state_activity(input_data: dict) -> dict:
    conv_input = CandidateConversationInput(**input_data)
    async with async_session_factory() as session:
        conv_repo = ConversationRepository(session)
        existing = await conv_repo.get_by_candidate(
            conv_input.workflow_id, conv_input.candidate_snapshot_id
        )
        if existing:
            state = ConversationState(
                conversation_id=existing.id,
                candidate_snapshot_id=conv_input.candidate_snapshot_id,
                workflow_id=conv_input.workflow_id,
                status=existing.status,
                round=existing.current_round,
                missing_info=existing.missing_info or [],
            )
            return state.model_dump()

        missing = conv_input.screening_result.get("missing_info", [])
        conv = await conv_repo.create(
            workflow_id=conv_input.workflow_id,
            candidate_snapshot_id=conv_input.candidate_snapshot_id,
            missing_info=missing,
        )
        await session.commit()
        state = ConversationState(
            conversation_id=conv.id,
            candidate_snapshot_id=conv_input.candidate_snapshot_id,
            workflow_id=conv_input.workflow_id,
            missing_info=missing,
        )
        return state.model_dump()


@activity.defn
async def generate_outreach_message_activity(state_data: dict) -> dict:
    from services.agent_service.outreach_agent import generate_outreach_message

    async with async_session_factory() as session:
        candidate_repo = CandidateRepository(session)
        snap = await candidate_repo.get(state_data["candidate_snapshot_id"])

    next_round = state_data.get("round", 0) + 1
    screening_result = state_data.get("screening_result", {})
    output = await generate_outreach_message(
        candidate_snapshot_id=state_data["candidate_snapshot_id"],
        display_name=snap.display_name if snap else None,
        current_title=snap.current_title if snap else None,
        matched_points=screening_result.get("matched_points", []),
        missing_info=state_data.get("missing_info", []),
        round_num=next_round,
    )
    return output.model_dump()


@activity.defn
async def send_or_draft_platform_message_activity(payload: dict) -> dict:
    from services.fetch_worker.message_sender import send_platform_message

    async with async_session_factory() as session:
        conv_repo = ConversationRepository(session)
        msg = await conv_repo.save_message(
            conversation_id=payload["conversation_id"],
            candidate_snapshot_id=payload["candidate_snapshot_id"],
            direction="outbound",
            message_text=payload["message_text"],
            status="drafted",
            round_num=payload.get("round"),
        )

        send_mode = payload.get("send_mode", "draft_first")
        if send_mode == "auto_send":
            try:
                await send_platform_message(
                    payload["candidate_snapshot_id"],
                    payload["message_text"],
                    "auto_send",
                )
                await conv_repo.update_message_status(msg.id, "sent")
                await conv_repo.update_status(
                    payload["conversation_id"],
                    "WAITING_REPLY",
                    current_round=payload.get("round", 1),
                    last_message_at=datetime.now(timezone.utc),
                )
                status = "sent"
            except Exception as e:
                await conv_repo.update_message_status(msg.id, "failed", str(e))
                status = "failed"
        else:
            await conv_repo.update_status(payload["conversation_id"], "MESSAGE_DRAFTED")
            status = "drafted"

        await session.commit()
        return {"message_id": msg.id, "status": status}


@activity.defn
async def parse_candidate_reply_activity(reply_data: dict) -> dict:
    from services.agent_service.reply_parser_agent import parse_reply

    output = await parse_reply(
        candidate_snapshot_id=reply_data["candidate_snapshot_id"],
        raw_message=reply_data["message_text"],
        missing_info=reply_data.get("missing_info", []),
    )
    return output.model_dump()


@activity.defn
async def update_candidate_profile_and_rescreen_activity(payload: dict) -> dict:
    from services.agent_service.rescreening_agent import rescreen_candidate

    state = payload["state"]
    parsed = payload["parsed_reply"]

    async with async_session_factory() as session:
        profile_repo = ProfileRepository(session)
        screening_repo = ScreeningRepository(session)
        candidate_repo = CandidateRepository(session)
        conv_repo = ConversationRepository(session)
        wf_repo = WorkflowRepository(session)

        await profile_repo.save_supplemental(
            workflow_id=state["workflow_id"],
            candidate_snapshot_id=state["candidate_snapshot_id"],
            raw_message=parsed.get("raw_message", ""),
            extracted_fields=parsed.get("extracted_fields", {}),
            confidence=parsed.get("confidence", 0),
        )

        snap = await candidate_repo.get(state["candidate_snapshot_id"])
        original = {
            "display_name": snap.display_name,
            "skills": snap.skills,
            "experience_summary": snap.experience_summary,
        }
        merged = {**original, **parsed.get("extracted_fields", {})}
        await profile_repo.upsert_merged_profile(
            state["workflow_id"], state["candidate_snapshot_id"], merged
        )

        wf = await wf_repo.get(state["workflow_id"])
        screening = await screening_repo.get_latest_for_candidate(
            state["workflow_id"], state["candidate_snapshot_id"]
        )
        old_score = float(screening.total_score) if screening and screening.total_score else 0

        rescreen = await rescreen_candidate(
            candidate_snapshot_id=state["candidate_snapshot_id"],
            job_description=wf.config.get("job", {}).get("description", "") if wf else "",
            original_profile=original,
            supplemental_fields=parsed.get("extracted_fields", {}),
            old_score=old_score,
            missing_info=state.get("missing_info", []),
        )

        from packages.schemas.screening import ScreeningOutput

        await screening_repo.save_result(
            state["workflow_id"],
            wf.job_id if wf else None,
            ScreeningOutput(
                candidate_snapshot_id=state["candidate_snapshot_id"],
                total_score=rescreen.new_score,
                level=rescreen.level,
                suggested_action=rescreen.decision,
                missing_info=rescreen.remaining_missing_info,
            ),
            round_num=2,
        )

        new_status = "RESCREENED"
        if rescreen.decision == "recommend_to_hr":
            new_status = "READY_FOR_HR"
        elif rescreen.decision == "reject":
            new_status = "REJECTED"
        elif rescreen.decision == "ask_followup":
            new_status = "FOLLOW_UP_REQUIRED"

        await conv_repo.update_status(state["conversation_id"], new_status)
        await session.commit()

        state["round"] = state.get("round", 0) + 1
        state["decision"] = rescreen.decision
        state["latest_score"] = rescreen.new_score
        state["level"] = rescreen.level
        state["missing_info"] = [m.model_dump() for m in rescreen.remaining_missing_info]
        state["status"] = new_status
        return state


@activity.defn
async def mark_no_reply_or_followup_activity(state_data: dict) -> dict:
    async with async_session_factory() as session:
        conv_repo = ConversationRepository(session)
        if state_data.get("no_reply_count", 0) >= 1:
            await conv_repo.update_status(state_data["conversation_id"], "NO_REPLY")
            state_data["status"] = "NO_REPLY"
            state_data["decision"] = "complete"
        else:
            state_data["no_reply_count"] = state_data.get("no_reply_count", 0) + 1
        await session.commit()
    return state_data


@activity.defn
async def generate_initial_report_activity(workflow_id: str) -> dict:
    async with async_session_factory() as session:
        screening_repo = ScreeningRepository(session)
        candidate_repo = CandidateRepository(session)
        results = await screening_repo.list_by_workflow(workflow_id)

        recommended = []
        for r in results:
            if r.level == "recommend":
                snap = await candidate_repo.get(r.candidate_snapshot_id)
                recommended.append({
                    "candidate_snapshot_id": r.candidate_snapshot_id,
                    "display_name": snap.display_name if snap else None,
                    "score": float(r.total_score) if r.total_score else 0,
                })

        return {
            "workflow_id": workflow_id,
            "recommended_count": len(recommended),
            "recommended": recommended,
        }


@activity.defn
async def update_workflow_status_activity(payload: dict) -> None:
    async with async_session_factory() as session:
        repo = WorkflowRepository(session)
        await repo.update_status(
            payload["workflow_id"],
            payload["status"],
            fetch_task_id=payload.get("fetch_task_id"),
            shortlist_id=payload.get("shortlist_id"),
            error_message=payload.get("error_message"),
        )
        await session.commit()
