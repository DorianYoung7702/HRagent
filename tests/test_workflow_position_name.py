from apps.api.routes.workflows import _demo_create_from_body, _resolve_position_name
from packages.schemas.workflow import ConsoleStartRequest, LiepinLptDemoRequest


def test_resolve_position_name_prefers_homepage_field():
    body = ConsoleStartRequest(
        keywords="销售",
        chat_job_title="拉美中方销售",
        collect_parent_group="其他文件夹",
        preset_label="筛选需求卡片名",
    )
    assert _resolve_position_name(body) == "拉美中方销售"


def test_resolve_position_name_ignores_screening_text():
    body = ConsoleStartRequest(
        keywords="销售",
        screening_criteria="筛选偏好摘要：岗位为拉美中方销售\n岗位：不应采用此字段",
        preset_label="拉美中方销售",
    )
    assert _resolve_position_name(body) == "拉美中方销售"


def test_resolve_position_name_falls_back_to_preset_label():
    body = ConsoleStartRequest(
        keywords="销售",
        preset_label="深圳 ToB 大客户销售",
    )
    assert _resolve_position_name(body) == "深圳 ToB 大客户销售"


def test_demo_create_uses_position_name_for_workflow_name():
    body = LiepinLptDemoRequest(
        name="深圳 嵌入式开发",
        keywords="嵌入式",
        chat_job_title="12345",
    )
    created = _demo_create_from_body(body)
    assert created.name == "12345"
    assert created.job.title == "12345"
