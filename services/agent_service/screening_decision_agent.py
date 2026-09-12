"""判定 Agent：基于解析结果与 HR 评判标准，输出观察/追问/排除。"""

from __future__ import annotations

import logging

from pydantic_ai import Agent

from packages.schemas.screening import ResumeParseOutput, ScreeningDecisionOutput
from packages.settings import get_settings
from services.agent_service.agent_errors import AgentInferenceError
from services.agent_service.llm import get_deepseek_model
from packages.screening_defaults import DEFAULT_SCREENING_CRITERIA

logger = logging.getLogger(__name__)


def build_decision_system_prompt(screening_criteria: str = "") -> str:
    criteria = (screening_criteria or "").strip() or DEFAULT_SCREENING_CRITERIA
    return f"""你是招聘判定助手。根据「简历解析结果」与「HR 评判标准」做出初筛决定。

## HR 评判标准（必须严格遵循）
{criteria}

## 输出要求
- decision：观察 | 追问 | 排除（必填）
- fit_score：0-100 的综合匹配分（必填）。必须根据硬性条件、相关经验深度、项目真实性、加分项和信息缺口综合给分，不能按 decision 固定给分。
- score_rationale：解释 fit_score 的主要加分与扣分依据（必填）。
- criteria_analysis：对照 HR 标准逐条分析（必填），格式建议「维度：有/无/未提及」，多条用分号分隔，维度名与 HR 标准一致
- reason：一句话判定理由（必填，说明为何做出该决定）
- followup_question：decision=追问时填写
- has_us_visa / has_spanish / has_sales / has_study_abroad：根据解析结果填写布尔值

你不重复写简历总结，专注判定与理由。"""


def create_decision_agent(
    model_name: str | None = None,
    screening_criteria: str = "",
) -> Agent[None, ScreeningDecisionOutput]:
    model = get_deepseek_model(model_name) if model_name else get_deepseek_model()
    prompt = build_decision_system_prompt(screening_criteria)
    return Agent(model, output_type=ScreeningDecisionOutput, system_prompt=prompt)


def validate_decision_output(output: ScreeningDecisionOutput) -> ScreeningDecisionOutput:
    if output.decision not in ("观察", "追问", "排除"):
        raise AgentInferenceError(f"判定 Agent 返回非法 decision: {output.decision}")
    if output.fit_score is None:
        raise AgentInferenceError("判定 Agent 未返回综合匹配分 (fit_score)")
    if not (output.score_rationale or "").strip():
        raise AgentInferenceError("判定 Agent 未返回评分依据 (score_rationale)")
    if not (output.reason or "").strip():
        raise AgentInferenceError("判定 Agent 未返回判定理由 (reason)")
    if not (output.criteria_analysis or "").strip():
        raise AgentInferenceError("判定 Agent 未返回标准对照分析 (criteria_analysis)")
    if output.decision == "追问" and not (output.followup_question or "").strip():
        raise AgentInferenceError("判定为追问但未返回 followup_question")
    return output


async def decide_candidate(
    parse: ResumeParseOutput,
    resume_text: str,
    screening_criteria: str = "",
) -> ScreeningDecisionOutput:
    criteria = (screening_criteria or "").strip() or DEFAULT_SCREENING_CRITERIA
    prompt = f"""## HR 评判标准
{criteria}

## 简历解析结果
- 总结：{parse.resume_summary}
- 要点：{'; '.join(parse.highlights)}
- 语言：{', '.join(parse.languages) or '未提及'}
- 签证：{parse.visa_info}
- 销售：{parse.sales_info}
- 留学：{parse.education_abroad}
- 解析说明：{parse.parse_notes}

## 简历原文（供核对）
{(resume_text or '')[:4000]}
"""
    model_name = get_settings().deepseek_model
    try:
        agent = create_decision_agent(model_name, screening_criteria=criteria)
        result = await agent.run(prompt)
        return validate_decision_output(result.output)
    except AgentInferenceError:
        raise
    except Exception as e:
        logger.warning("Decision AI failed model=%s: %s", model_name, e)
        raise AgentInferenceError(f"判定 Agent 失败 ({model_name}): {e}") from e
