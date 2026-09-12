from packages.schemas.screening import ResumeParseOutput, ScreeningDecisionOutput
from services.agent_service.screening_display import (
    build_screening_flag_map,
    format_screening_flag_text,
    parse_criteria_analysis_flags,
)


def test_parse_criteria_analysis_kv():
    flags = parse_criteria_analysis_flags("美签：有；西班牙语：有；销售：有")
    assert flags == {"美签": "有", "西班牙语": "有", "销售": "有"}


def test_format_from_criteria_not_hardcoded_legacy():
    text = format_screening_flag_text(
        criteria_analysis="电子类经验：无；拉美市场：有；工作年限：满足",
        legacy=ScreeningDecisionOutput(
            decision="排除",
            has_us_visa=False,
            has_spanish=True,
            has_sales=True,
        ),
    )
    assert "美签" not in text
    assert "电子类经验:无" in text
    assert "拉美市场:有" in text


def test_fallback_to_parse_output():
    parse = ResumeParseOutput(
        languages=["德语", "英语"],
        visa_info="持申根签，未提及美签",
        sales_info="5年B2B海外销售",
        education_abroad="未提及",
    )
    flags = build_screening_flag_map(parse=parse)
    assert flags["德语"] == "有"
    assert flags["签证"] == "有"
    assert flags["销售"] == "有"
    assert flags.get("留学") == "未提及"


def test_legacy_only_when_in_criteria():
    flags = build_screening_flag_map(
        legacy=ScreeningDecisionOutput(
            decision="排除",
            has_us_visa=False,
            has_spanish=True,
            has_sales=True,
            has_study_abroad=False,
        ),
        screening_criteria="必须有美签和西班牙语",
    )
    assert "美签" in flags
    assert "西班牙语" in flags
    assert "销售" not in flags
    assert "留学" not in flags
