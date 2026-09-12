"""Tests for LPT search config and schemas."""

from packages.schemas.candidate import FetchInput
from packages.schemas.workflow import FetchConfig, LiepinLptDemoRequest, LiepinSearchConfig


def test_liepin_search_config_defaults():
    cfg = LiepinSearchConfig(mode="lpt_search")
    assert cfg.keywords == "西班牙语 美签 海外销售"
    assert cfg.city == "深圳"
    assert cfg.experience == "3-5年"


def test_fetch_input_lpt_mode():
    inp = FetchInput(
        workflow_id="wf_1",
        target_count=3,
        search=LiepinSearchConfig(mode="lpt_search"),
    )
    assert inp.search.mode == "lpt_search"
    assert inp.start_url == "https://lpt.liepin.com/search"


def test_liepin_demo_request():
    req = LiepinLptDemoRequest()
    assert req.target_count == 20
    assert "西班牙语" in req.keywords


def test_fetch_config_with_search():
    cfg = FetchConfig(
        target_count=3,
        search=LiepinSearchConfig(mode="lpt_search", auto_screen=True),
    )
    assert cfg.search.auto_screen is True


def test_job_title_vs_search_bar_context():
    from services.fetch_worker.lpt_search import _is_job_title_context, _is_search_bar_context

    assert _is_job_title_context("职位名称 请输入")
    assert _is_job_title_context("当前职位 销售经理")
    assert not _is_job_title_context("任意关键词 搜索内容")
    assert _is_search_bar_context("任意关键词 请输入")
    assert _is_search_bar_context("搜索栏 人才搜索")
