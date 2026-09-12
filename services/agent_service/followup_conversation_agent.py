"""追问对话编排 Agent：为 IM 中心生成简短追问话术。"""

from pydantic_ai import Agent

from packages.agent_context import get_hr_company_name, hr_agent_system_prefix, hr_context_block
from packages.schemas.outreach import FollowupConversationOutput
from services.agent_service.llm import get_deepseek_model

FOLLOWUP_SYSTEM = hr_agent_system_prefix(
    extra_rules="""## 沟通场景
在猎聘 IM 中与候选人简短沟通。

## 规则
1. 每次 1-2 句话，口语自然，不超过 120 字
2. 仅追问初筛已标记为「未满足/待确认」的缺口；标准对照里已标注「有」的项禁止重复追问
3. 若提供了「初筛追问点」原文，第 1 轮应原样使用或只做极轻量口语化，不得改问其他维度
4. 遵守 HR 评判标准，不编造简历没有的信息
5. 第 2 轮起可更直接；round>=2 时 auto_send_allowed 可为 true
6. action 通常为 draft_message；信息已足够时可 recommend_to_hr 或 wait_reply""",
)


def _canonical_followup_question(
    followup_question: str | None,
    missing_info: list[dict],
) -> str:
    text = (followup_question or "").strip()
    if text:
        return text
    if not missing_info:
        return ""
    first = missing_info[0]
    if isinstance(first, dict):
        return str(first.get("question") or "").strip()
    return str(getattr(first, "question", "") or "").strip()


def create_followup_conversation_agent() -> Agent[None, FollowupConversationOutput]:
    return Agent(
        get_deepseek_model(),
        output_type=FollowupConversationOutput,
        system_prompt=FOLLOWUP_SYSTEM,
    )


async def generate_followup_message(
    *,
    candidate_snapshot_id: str,
    display_name: str | None,
    current_title: str | None,
    missing_info: list[dict],
    screening_criteria: str,
    followup_question: str | None,
    conversation_history: list[str],
    round_num: int,
    job_title: str | None = None,
    job_description: str | None = None,
) -> FollowupConversationOutput:
    canonical_q = _canonical_followup_question(followup_question, missing_info)
    if round_num == 1 and canonical_q and not conversation_history:
        return FollowupConversationOutput(
            candidate_snapshot_id=candidate_snapshot_id,
            message_text=canonical_q,
            action="draft_message",
            reason="使用初筛【待追问】原文，避免 IM 与日志不一致",
            round=round_num,
            auto_send_allowed=False,
        )

    agent = create_followup_conversation_agent()
    missing_text = "\n".join(
        f"- {m.get('field')}: {m.get('question')}" for m in (missing_info or [])[:5]
    )
    history_text = "\n".join(f"- {h[:120]}" for h in conversation_history[-6:]) or "（无）"

    prompt = f"""{hr_context_block(job_title=job_title, job_description=job_description)}

## 轮次
第 {round_num} 轮

## 候选人
姓名: {display_name or '未知'}
职位: {current_title or '未知'}
ID: {candidate_snapshot_id}

## HR 评判标准
{screening_criteria[:2000] or '（无）'}

## 初筛追问点
{followup_question or '（见 missing_info）'}

## 待确认 missing_info
{missing_text or '无'}

## 已发消息历史
{history_text}

请输出下一条 IM 私信（message_text）及 action。"""

    result = await agent.run(prompt)
    out = result.output
    out.candidate_snapshot_id = candidate_snapshot_id
    out.round = round_num
    if round_num >= 2:
        out.auto_send_allowed = True
    if not out.message_text and out.action == "draft_message":
        company = get_hr_company_name()
        q = followup_question or (missing_info[0].get("question") if missing_info else "方便进一步沟通吗？")
        job = job_title or "相关岗位"
        greet = f"您好{('，' + display_name) if display_name else ''}"
        out.message_text = (
            f"{greet}！我是{company}的HR，看到您的背景与我们招聘的{job}较匹配，想进一步沟通。"
            f"{q}"
        )
    return out
