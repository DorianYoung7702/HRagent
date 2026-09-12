"""解析 Agent：阅读在线简历，输出总结与结构化解析要点。"""

from __future__ import annotations

import logging

from pydantic_ai import Agent

from packages.schemas.screening import ResumeParseOutput
from packages.settings import get_settings
from services.agent_service.agent_errors import AgentInferenceError
from services.agent_service.llm import get_deepseek_model

logger = logging.getLogger(__name__)

RESUME_PARSE_PROMPT = """你是简历解析助手。阅读在线简历原文，输出客观、不编造的结构化解析。

要求：
1. resume_summary：3-5 句概括候选人背景（姓名/职位/年限/城市/核心经历），必填
2. highlights：5-8 条关键事实要点（技能、语言、签证、销售、留学、行业等）
3. languages：简历体现的语言能力列表
4. visa_info：与美签/签证相关的原文要点，无则写「未提及」
5. sales_info：与销售/商务相关的要点，无则写「未提及」
6. education_abroad：与留学/海外就读相关的要点，无则写「未提及」
7. current_company：当前/最近一段工作经历的公司名，只写公司名（如「海康威视」「江门市梦霖卫浴有限公司」），不要职位、时间、职责描述；简历未写则留空
8. parse_notes：2-3 句说明你如何从简历得出上述结论（解析思路），必填
9. display_name、current_title、work_years、education、city、skills、experience_summary、project_summary：仅提取简历明确出现的信息；不明确时留空或空列表，不得根据文件名或常识补全

只做事实提取，不做录用决策。"""


def create_resume_parser_agent(model_name: str | None = None) -> Agent[None, ResumeParseOutput]:
    model = get_deepseek_model(model_name) if model_name else get_deepseek_model()
    return Agent(model, output_type=ResumeParseOutput, system_prompt=RESUME_PARSE_PROMPT)


def validate_parse_output(output: ResumeParseOutput) -> ResumeParseOutput:
    if not (output.resume_summary or "").strip():
        raise AgentInferenceError("解析 Agent 未返回简历总结 (resume_summary)")
    if not (output.parse_notes or "").strip():
        raise AgentInferenceError("解析 Agent 未返回解析说明 (parse_notes)")
    return output


async def parse_resume_online(
    candidate_snapshot_id: str,
    resume_text: str,
    candidate_fields: dict,
) -> ResumeParseOutput:
    prompt = f"""## 候选人 ID
{candidate_snapshot_id}

## 结构化字段（DOM 抽取）
{candidate_fields}

## 简历原文
{resume_text[:8000]}
"""
    model_name = get_settings().deepseek_model
    try:
        agent = create_resume_parser_agent(model_name)
        result = await agent.run(prompt)
        output = result.output
        output.candidate_snapshot_id = candidate_snapshot_id
        return validate_parse_output(output)
    except AgentInferenceError:
        raise
    except Exception as e:
        logger.warning("Resume parse AI failed model=%s: %s", model_name, e)
        raise AgentInferenceError(f"解析 Agent 失败 ({model_name}): {e}") from e
