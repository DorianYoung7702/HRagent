"""追问回复 enrichment：回写候选表并判断是否要简历。"""

from pydantic_ai import Agent

from packages.agent_context import hr_agent_system_prefix
from packages.schemas.outreach import FollowupReplyEnrichmentOutput
from services.agent_service.llm import get_deepseek_model

ENRICHMENT_SYSTEM = hr_agent_system_prefix(
    extra_rules="""## 角色
招聘追问回复分析专家。

## 任务
1. 从候选人 IM 回复提取结构化字段（extracted_fields）
2. 判断哪些 missing_info 已回答（answered_fields）
3. 根据 HR 评判标准更新 updated_level：observe（证据充分可观察）/ followup（仍需补证）/ exclude（明确不满足）
4. need_resume_request：若关键信息口头确认但仍缺完整简历佐证，设为 true
5. summary_for_list：1-2 句供 HR 列表展示的补充说明
6. remaining_missing_info：仍未确认的项（格式同 missing_info）""",
)


def create_followup_reply_enrichment_agent() -> Agent[None, FollowupReplyEnrichmentOutput]:
    return Agent(
        get_deepseek_model(),
        output_type=FollowupReplyEnrichmentOutput,
        system_prompt=ENRICHMENT_SYSTEM,
    )


async def enrich_followup_reply(
    *,
    candidate_snapshot_id: str,
    raw_reply: str,
    missing_info: list[dict],
    screening_criteria: str,
    original_level: str,
    display_name: str | None = None,
) -> FollowupReplyEnrichmentOutput:
    agent = create_followup_reply_enrichment_agent()
    missing_text = "\n".join(
        f"- {m.get('field')}: {m.get('question')}" for m in (missing_info or [])[:8]
    )
    prompt = f"""## 候选人
ID: {candidate_snapshot_id}
姓名: {display_name or '未知'}
原 level: {original_level}

## HR 评判标准
{screening_criteria[:2000] or '（无）'}

## 原 missing_info
{missing_text or '无'}

## 候选人 IM 回复
{raw_reply[:3000]}

请分析并输出结构化结果。"""

    result = await agent.run(prompt)
    out = result.output
    out.candidate_snapshot_id = candidate_snapshot_id
    if out.updated_level not in ("observe", "followup", "exclude"):
        out.updated_level = original_level or "followup"
    return out
