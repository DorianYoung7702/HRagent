"""观察名单 IM 索要简历话术。"""

import logging

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior

from packages.agent_context import get_hr_company_name, hr_agent_system_prefix, hr_context_block
from packages.schemas.outreach import ResumeRequestOutput
from services.agent_service.llm import get_deepseek_model

logger = logging.getLogger(__name__)

RESUME_REQUEST_SYSTEM = hr_agent_system_prefix(
    extra_rules="""## 沟通场景
向已开聊的候选人简短索要完整简历。

## 输出格式
只输出一条可直接发送的 IM 私信正文，不要 JSON、不要引号、不要字段名、不要解释。

## 规则
1-2 句，礼貌专业，须表明【招聘方公司】身份与岗位意向，请求发送最新简历或附件，不超过 60 字。""",
)


def create_resume_request_agent() -> Agent[None, str]:
    return Agent(
        get_deepseek_model(),
        output_type=str,
        system_prompt=RESUME_REQUEST_SYSTEM,
    )


def fallback_resume_request_output(
    *,
    candidate_snapshot_id: str,
    display_name: str | None,
    job_title: str | None,
    reason: str = "rule_fallback",
) -> ResumeRequestOutput:
    company = get_hr_company_name()
    job = job_title or "相关岗位"
    greet = display_name or "您好"
    return ResumeRequestOutput(
        candidate_snapshot_id=candidate_snapshot_id,
        message_text=(
            f"{greet}，我是{company}的HR，正在招聘{job}，"
            f"方便发一份最新简历给我吗？谢谢！"
        ),
        reason=reason,
    )


def _normalize_message_text(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            import json

            data = json.loads(cleaned)
            if isinstance(data, dict) and data.get("message_text"):
                cleaned = str(data["message_text"]).strip()
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return cleaned.strip().strip('"').strip("'")


async def generate_resume_request_message(
    *,
    candidate_snapshot_id: str,
    display_name: str | None,
    current_title: str | None,
    job_title: str | None = None,
) -> ResumeRequestOutput:
    agent = create_resume_request_agent()
    prompt = f"""{hr_context_block(job_title=job_title)}

候选人: {display_name or '未知'} / {current_title or ''}
ID: {candidate_snapshot_id}
请生成索要简历的 IM 私信正文。"""

    message_text = ""
    try:
        result = await agent.run(prompt)
        message_text = _normalize_message_text(result.output)
    except (UnexpectedModelBehavior, ValidationError, ValueError) as exc:
        logger.warning(
            "resume_request_agent failed for %s, using fallback: %s",
            candidate_snapshot_id,
            exc,
        )

    if not message_text:
        return fallback_resume_request_output(
            candidate_snapshot_id=candidate_snapshot_id,
            display_name=display_name,
            job_title=job_title,
            reason="agent_fallback",
        )

    return ResumeRequestOutput(
        candidate_snapshot_id=candidate_snapshot_id,
        message_text=message_text[:120],
        reason="llm",
    )
