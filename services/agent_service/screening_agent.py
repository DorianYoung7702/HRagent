from pydantic_ai import Agent

from packages.schemas.screening import ScreeningOutput
from services.agent_service.llm import get_deepseek_model

SCREENING_SYSTEM_PROMPT = """你是一位资深技术招聘顾问。根据岗位描述(JD)和候选人简历快照，进行结构化初筛评估。

评分规则：
- total_score: 0-100 综合匹配分
- level: recommend (>=80) / backup (60-79) / reject (<60)
- matched_points: 列出匹配亮点（最多5条）
- gaps: 列出能力或信息缺口（最多5条）
- missing_info: 需要追问的关键信息，每项包含 field、question、importance(high/medium/low)
- suggested_action: ask_for_more_info / recommend_to_hr / reject

请客观评估，不要编造简历中没有的信息。"""


def create_screening_agent() -> Agent[None, ScreeningOutput]:
    return Agent(
        get_deepseek_model(),
        output_type=ScreeningOutput,
        system_prompt=SCREENING_SYSTEM_PROMPT,
    )


async def screen_candidate(
    job_description: str,
    candidate_snapshot_id: str,
    resume_text: str,
    candidate_fields: dict,
) -> ScreeningOutput:
    agent = create_screening_agent()
    prompt = f"""## 岗位描述
{job_description}

## 候选人 ID
{candidate_snapshot_id}

## 候选人结构化字段
{candidate_fields}

## 简历原文
{resume_text[:8000]}
"""
    result = await agent.run(prompt)
    output = result.output
    output.candidate_snapshot_id = candidate_snapshot_id
    return output
