from pydantic_ai import Agent

from packages.agent_context import hr_agent_system_prefix, hr_context_block
from packages.schemas.outreach import OutreachMessageOutput
from services.agent_service.llm import get_deepseek_model

OUTREACH_SYSTEM_PROMPT = hr_agent_system_prefix(
    extra_rules="""## 沟通场景
给候选人发私信追问关键信息。

## 规则
1. 每轮最多问 2 个核心问题，语气自然、简洁
2. 第一轮：是否看机会 + 最关键能力缺口
3. 第二轮：项目规模/技术细节
4. 第三轮：薪资/到岗/面试时间
5. 称呼候选人姓名（如有）
6. 不要一次问超过 2 个问题
7. 中文撰写，100-200字为宜
8. 须使用【招聘方公司】身份，不得冒充其他公司""",
)


def create_outreach_agent() -> Agent[None, OutreachMessageOutput]:
    return Agent(
        get_deepseek_model(),
        output_type=OutreachMessageOutput,
        system_prompt=OUTREACH_SYSTEM_PROMPT,
    )


ROUND_GUIDANCE = {
    1: "第一轮：确认是否看机会 + 问最关键的能力缺口（最多2个问题）",
    2: "第二轮：追问项目规模、技术细节或性能优化经验（最多2个问题）",
    3: "第三轮：确认期望薪资范围和最快到岗时间（最多2个问题）",
}


async def generate_outreach_message(
    candidate_snapshot_id: str,
    display_name: str | None,
    current_title: str | None,
    matched_points: list[str],
    missing_info: list[dict],
    round_num: int,
    job_title: str | None = None,
) -> OutreachMessageOutput:
    agent = create_outreach_agent()
    guidance = ROUND_GUIDANCE.get(round_num, ROUND_GUIDANCE[3])
    missing_text = "\n".join(
        f"- {m.get('field')}: {m.get('question')} (importance: {m.get('importance')})"
        for m in missing_info[:3]
    )
    matched_text = "\n".join(f"- {p}" for p in matched_points[:3])

    prompt = f"""{hr_context_block(job_title=job_title)}

## 当前轮次
第 {round_num} 轮 — {guidance}

## 候选人
- ID: {candidate_snapshot_id}
- 姓名: {display_name or '未知'}
- 当前职位: {current_title or '未知'}

## 岗位
{job_title or '技术岗位'}

## 匹配亮点
{matched_text or '暂无'}

## 待追问信息
{missing_text or '无特定缺口，礼貌确认求职意向'}

请生成私信内容。"""

    result = await agent.run(prompt)
    output = result.output
    output.candidate_snapshot_id = candidate_snapshot_id
    output.round = round_num
    return output
