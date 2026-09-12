from datetime import timedelta
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from packages.schemas.workflow import CandidateConversationInput, OutreachConfig
    from services.workflow_worker.activities import (
        create_conversation_state_activity,
        generate_outreach_message_activity,
        mark_no_reply_or_followup_activity,
        parse_candidate_reply_activity,
        send_or_draft_platform_message_activity,
        update_candidate_profile_and_rescreen_activity,
    )


@workflow.defn
class CandidateConversationWorkflow:
    def __init__(self) -> None:
        self.reply_received = False
        self.latest_reply: dict[str, Any] | None = None

    @workflow.signal
    async def candidate_reply_received(self, message: dict) -> None:
        self.reply_received = True
        self.latest_reply = message

    @workflow.query
    def get_conversation_state(self) -> dict:
        return {
            "reply_received": self.reply_received,
            "latest_reply": self.latest_reply,
        }

    @workflow.run
    async def run(self, input_data: CandidateConversationInput | dict) -> dict:
        if isinstance(input_data, dict):
            input_data = CandidateConversationInput(
                workflow_id=input_data["workflow_id"],
                candidate_snapshot_id=input_data["candidate_snapshot_id"],
                screening_result=input_data["screening_result"],
                outreach_config=OutreachConfig(**input_data["outreach_config"]),
            )
        outreach: OutreachConfig = input_data.outreach_config

        state = await workflow.execute_activity(
            create_conversation_state_activity,
            input_data.model_dump(),
            start_to_close_timeout=timedelta(minutes=2),
        )
        state["screening_result"] = input_data.screening_result

        while state.get("round", 0) < outreach.max_rounds:
            message = await workflow.execute_activity(
                generate_outreach_message_activity,
                state,
                start_to_close_timeout=timedelta(minutes=3),
            )

            send_result = await workflow.execute_activity(
                send_or_draft_platform_message_activity,
                {
                    "conversation_id": state["conversation_id"],
                    "candidate_snapshot_id": state["candidate_snapshot_id"],
                    "message_text": message["message_text"],
                    "round": message["round"],
                    "send_mode": outreach.send_mode,
                },
                start_to_close_timeout=timedelta(minutes=5),
            )

            if outreach.send_mode == "draft_first" and state.get("round", 0) == 0:
                return {
                    "status": "drafted",
                    "message": message,
                    "send_result": send_result,
                }

            self.reply_received = False
            self.latest_reply = None

            try:
                await workflow.wait_condition(
                    lambda: self.reply_received,
                    timeout=timedelta(days=outreach.reply_timeout_days),
                )
            except TimeoutError:
                state = await workflow.execute_activity(
                    mark_no_reply_or_followup_activity,
                    state,
                    start_to_close_timeout=timedelta(minutes=2),
                )
                if state.get("decision") == "complete":
                    return {"status": "no_reply", "state": state}
                continue

            if not self.reply_received or not self.latest_reply:
                state = await workflow.execute_activity(
                    mark_no_reply_or_followup_activity,
                    state,
                    start_to_close_timeout=timedelta(minutes=2),
                )
                continue

            parsed = await workflow.execute_activity(
                parse_candidate_reply_activity,
                {
                    **self.latest_reply,
                    "missing_info": state.get("missing_info", []),
                },
                start_to_close_timeout=timedelta(minutes=3),
            )
            parsed["raw_message"] = self.latest_reply.get("message_text", "")

            state = await workflow.execute_activity(
                update_candidate_profile_and_rescreen_activity,
                {"state": state, "parsed_reply": parsed},
                start_to_close_timeout=timedelta(minutes=5),
            )

            if state.get("decision") in ("recommend_to_hr", "reject", "complete"):
                return {"status": state.get("decision"), "state": state}

        return {"status": "max_rounds_reached", "state": state}
