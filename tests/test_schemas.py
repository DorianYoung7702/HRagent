from packages.schemas.candidate import CandidateSnapshotData, FetchInput
from packages.schemas.screening import MissingInfo, ScreeningOutput
from packages.schemas.workflow import RecruitingWorkflowCreate, FetchConfig, JobConfig


def test_fetch_input_defaults():
    inp = FetchInput(workflow_id="wf_1", start_url="https://example.com")
    assert inp.target_count == 50
    assert inp.platform == "liepin"


def test_screening_output():
    out = ScreeningOutput(
        candidate_snapshot_id="snap_1",
        total_score=76,
        level="backup",
        missing_info=[
            MissingInfo(field="availability", question="到岗时间?", importance="medium")
        ],
    )
    assert out.suggested_action == "ask_for_more_info"
    assert len(out.missing_info) == 1


def test_missing_info_defaults_importance():
    info = MissingInfo(field="us_visa", question="是否有有效美签？")
    assert info.importance == "high"


def test_workflow_create():
    body = RecruitingWorkflowCreate(
        name="Java 后端",
        start_url="https://h.liepin.com/search",
        job=JobConfig(job_id="j1", description="Java 工程师"),
        fetch=FetchConfig(target_count=10),
    )
    assert body.platform == "liepin"
    assert body.outreach.send_mode == "draft_first"


def test_candidate_snapshot_data():
    snap = CandidateSnapshotData(
        workflow_id="wf_1",
        platform="liepin",
        display_name="张三",
        raw_text="工作经历...",
    )
    assert snap.template_type == "liepin_resume_detail_v2"
