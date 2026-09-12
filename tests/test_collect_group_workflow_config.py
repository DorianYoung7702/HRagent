from apps.api.routes.workflows import _demo_create_from_body
from packages.schemas.workflow import ConsoleStartRequest, LiepinLptDemoRequest


def test_console_start_carries_collect_parent_group_to_fetch_config():
    body = ConsoleStartRequest(
        keywords="sales",
        collect_parent_group="Latam Sales Shenzhen",
        collect_only=True,
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
        collect_parent_group=body.collect_parent_group,
    )

    created = _demo_create_from_body(demo_req)

    assert created.fetch.collect_only is True
    assert created.fetch.collect_parent_group == "Latam Sales Shenzhen"
