from pydantic_ai import Agent

from packages.schemas.outreach import ReplyParserOutput
from services.agent_service.llm import get_deepseek_model

REPLY_PARSER_PROMPT = """你是招聘信息提取专家。将候选人的自然语言回复解析为结构化字段。

规则：
1. extracted_fields: 从回复中提取的所有有价值信息（键值对）
2. answered_fields: 已明确回答的字段名列表
3. remaining_missing_fields: 仍然缺失的字段名列表
4. candidate_intent: interested / not_interested / unclear
5. confidence: 0-1 解析置信度
6. suggested_next_action: ask_followup / recommend_to_hr / reject / wait

不要编造回复中没有的信息。"""


def create_reply_parser_agent() -> Agent[None, ReplyParserOutput]:
    return Agent(
        get_deepseek_model(),
        output_type=ReplyParserOutput,
        system_prompt=REPLY_PARSER_PROMPT,
    )


async def parse_reply(
    candidate_snapshot_id: str,
    raw_message: str,
    missing_info: list[dict],
    conversation_history: list[str] | None = None,
) -> ReplyParserOutput:
    agent = create_reply_parser_agent()
    missing_text = "\n".join(f"- {m.get('field')}: {m.get('question')}" for m in missing_info)
    history_text = "\n".join(conversation_history or [])

    prompt = f"""## 候选人 ID
{candidate_snapshot_id}

## 待确认信息
{missing_text or '无'}

## 对话历史
{history_text or '无'}

## 候选人最新回复
{raw_message}
"""
    result = await agent.run(prompt)
    output = result.output
    output.candidate_snapshot_id = candidate_snapshot_id
    return output
