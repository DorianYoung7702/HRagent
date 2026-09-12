"""全局 Agent 共享身份：招聘方公司、HR 称谓等，所有对外话术必须一致。"""

from __future__ import annotations

from packages.settings import get_settings


def get_hr_company_name() -> str:
    name = (get_settings().hr_company_name or "").strip()
    return name or "招聘团队"


def hr_identity_line() -> str:
    return f"{get_hr_company_name()} HR"


def hr_agent_system_prefix(*, extra_rules: str = "") -> str:
    """拼接到各 Agent system prompt 开头。"""
    company = get_hr_company_name()
    block = f"""## 招聘方身份（全局固定，必须严格遵守）
- 你代表【{company}】招聘团队，对外自称「{company}的HR」或「我们{company}」。
- 严禁使用其他公司名称冒充招聘方，即使用户简历中出现其他公司也不得当作己方。
- 不得编造未提供的招聘方信息；岗位名称以本次任务给出的为准。"""
    if extra_rules.strip():
        block += f"\n{extra_rules.strip()}"
    return block


def hr_context_block(
    *,
    job_title: str | None = None,
    job_description: str | None = None,
) -> str:
    """注入到 user prompt 的招聘方上下文。"""
    company = get_hr_company_name()
    lines = [
        "## 招聘方",
        f"公司：{company}",
        f"沟通身份：{company} HR",
    ]
    if job_title and job_title.strip():
        lines.append(f"在招岗位：{job_title.strip()}")
    if job_description and job_description.strip():
        lines.append(f"岗位说明：{job_description.strip()[:600]}")
    return "\n".join(lines)
