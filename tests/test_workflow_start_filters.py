"""Ensure console start passes parsed LPT filters into fetch config."""

from apps.api.routes.workflows import _demo_create_from_body
from packages.schemas.workflow import (
    ConsoleStartRequest,
    LiepinLptDemoRequest,
    LptEducationFilters,
    LptOtherFilters,
)


def test_console_start_demo_request_carries_lpt_filters_to_fetch_config():
    body = ConsoleStartRequest(
        keywords="西班牙语 海外销售",
        cities=["深圳"],
        current_cities=["广州"],
        experience="3-5年",
        education=LptEducationFilters(degree="本科", school_tiers=["985", "211"]),
        other_filters=LptOtherFilters(activity="活跃", gender="男"),
        target_count=15,
        screening_criteria="必须会西班牙语",
    )

    demo_req = LiepinLptDemoRequest(
        name=body.name,
        keywords=body.keywords,
        city=body.city,
        cities=list(body.cities or []),
        current_cities=list(body.current_cities or []),
        experience=body.experience,
        education=body.education,
        other_filters=body.other_filters,
        target_count=body.target_count,
        job_id=body.job_id,
        job_description=body.job_description or body.search_requirement,
        screening_criteria=body.screening_criteria,
        chat_job_title=body.chat_job_title,
        min_score=body.min_score,
        top_k=body.top_k,
        collect_only=body.collect_only,
    )

    created = _demo_create_from_body(demo_req)
    search = created.fetch.search

    assert search.current_cities == ["广州"]
    assert search.cities == ["深圳"]
    assert search.education.degree == "本科"
    assert search.education.school_tiers == ["985", "211"]
    assert search.other_filters.activity == "活跃"
    assert search.other_filters.gender == "男"
