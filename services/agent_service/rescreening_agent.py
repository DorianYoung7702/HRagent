from pydantic_ai import Agent

from packages.schemas.screening import RescreeningOutput
from services.agent_service.llm import get_deepseek_model

RESCREENING_PROMPT = """你是招聘二次筛选专家。综合原始简历和候选人补充信息，重新评估匹配度。

规则：
1. 对比 old_score 和 new_score
2. level: recommend / backup / reject
3. decision: recommend_to_hr / ask_followup / reject / wait
4. reasons: 决策理由列表
5. remaining_missing_info: 仍需追问的信息

补充信息优先级高于简历中的模糊描述。"""


def create_rescreening_agent() -> Agent[None, RescreeningOutput]:
    return Agent(
        get_deepseek_model(),
        output_type=RescreeningOutput,
        system_prompt=RESCREENING_PROMPT,
    )


async def rescreen_candidate(
    candidate_snapshot_id: str,
    job_description: str,
    original_profile: dict,
    supplemental_fields: dict,
    old_score: float,
    missing_info: list[dict],
) -> RescreeningOutput:
    agent = create_rescreening_agent()
    prompt = f"""## 岗位描述
{job_description}

## 候选人 ID
{candidate_snapshot_id}

## 原始简历
{original_profile}

## 补充信息（来自私信回复）
{supplemental_fields}

## 初筛分数
{old_score}

## 原缺失信息
{missing_info}
"""
    result = await agent.run(prompt)
    output = result.output
    output.candidate_snapshot_id = candidate_snapshot_id
    output.old_score = old_score
    return output
