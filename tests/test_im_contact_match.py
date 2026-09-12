from services.fetch_worker.im_contact_match import (
    build_im_contact_key,
    candidate_display_name,
    extract_person_name_from_text,
    im_match_label,
    is_likely_company_name,
    is_likely_person_name,
    match_contact_index,
    IMContactMatchFields,
    parse_age_from_text,
    parse_name_from_card,
    resolve_person_display_name,
    resolve_person_name,
)


def test_match_by_name_age_school():
    contacts = [
        (0, "张三 32岁 北京大学 销售经理"),
        (1, "李四 28岁 清华大学"),
    ]
    fields = IMContactMatchFields(display_name="张三", age="32", school="北京大学")
    idx, score, _ = match_contact_index(contacts, fields)
    assert idx == 0
    assert score >= 20


def test_no_match_wrong_title_only():
    contacts = [(0, "某科技公司 销售总监")]
    fields = IMContactMatchFields(display_name="张三", age="32", school="北京大学")
    idx, _, _ = match_contact_index(contacts, fields)
    assert idx is None


def test_build_key_name_age_school():
    key = build_im_contact_key("张三", age="32", school="北京大学")
    assert key == "张三|32岁|北京大学"


def test_parse_age():
    assert parse_age_from_text("张三 32岁 本科") == "32"


def test_company_name_not_person():
    assert is_likely_company_name("深圳科士达科技股份有限公司")
    assert not is_likely_person_name("深圳科士达科技股份有限公司")


def test_parse_name_skips_company():
    lines = [
        "深圳科士达科技股份有限公司",
        "王磊",
        "37岁",
        "西安交通大学",
    ]
    assert parse_name_from_card(lines) == "王磊"


def test_resolve_person_name_prefers_card():
    name = resolve_person_name(
        "王磊",
        "深圳科士达科技股份有限公司",
        lines=["深圳科士达科技股份有限公司", "王磊", "37岁"],
    )
    assert name == "王磊"


def test_match_by_surname_age_school():
    contacts = [(0, "王先生 37岁 西安交通大学 销售")]
    fields = IMContactMatchFields(display_name="王磊", age="37", school="西安交通大学")
    idx, score, _ = match_contact_index(contacts, fields)
    assert idx == 0
    assert score >= 12


def test_no_match_company_as_name():
    contacts = [(0, "王磊 37岁 西安交通大学")]
    fields = IMContactMatchFields(
        display_name="深圳科士达科技股份有限公司", age="37", school="西安交通大学"
    )
    idx, _, _ = match_contact_index(contacts, fields)
    assert idx is None


def test_extract_masked_name_from_liepin_card():
    card = "今日活跃 | 张** | 24岁 | 2年 | 本科 | 深圳 | 西班牙语"
    assert extract_person_name_from_text(card) == "张**"


def test_industry_word_not_person_name():
    assert not is_likely_person_name("医疗器械")
    assert not is_likely_person_name("西班牙语")
    lines = ["3日内活跃", "张**", "24岁", "医疗器械", "深圳某公司"]
    assert parse_name_from_card(lines) == "张**"


def test_resolve_display_name_from_card_text_metadata():
    class Snap:
        display_name = "医疗器械"
        raw_text = ""
        metadata_ = {
            "card_text": "今日活跃\n张**\n24岁\n本科\n深圳",
            "person_name": "医疗器械",
        }

    assert resolve_person_display_name(Snap()) == "张**"
    assert candidate_display_name(Snap()) == "张"


def test_hidden_placeholder_not_display_name():
    class Snap:
        display_name = "隐藏"
        raw_text = ""
        metadata_ = {
            "person_name": "隐藏",
            "card_text": "7日内活跃\n李**\n26岁\n江苏师范大学",
        }

    assert candidate_display_name(Snap()) == "李"
    assert not is_likely_person_name("隐藏")


def test_city_name_not_person():
    assert not is_likely_person_name("广东")
    assert not is_likely_person_name("武汉")

    class Snap:
        display_name = "广东"
        raw_text = ""
        metadata_ = {
            "person_name": "广东",
            "card_text": "今日活跃\n王**\n30岁\n本科\n深圳",
        }

    assert candidate_display_name(Snap()) == "王"


def test_match_masked_name_in_im_list():
    contacts = [(0, "莫** 26岁 江苏师范大学 销售")]
    fields = IMContactMatchFields(display_name="莫**", age="26", school="江苏师范大学")
    idx, score, _ = match_contact_index(contacts, fields)
    assert idx == 0
    assert score >= 12


def test_match_surname_only_without_stars_in_list():
    """IM 列表只显示「刘」或「刘 09:04」，不含 **。"""
    contacts = [(0, "刘 26岁 09:04")]
    fields = IMContactMatchFields(display_name="刘**", age="26")
    idx, score, _ = match_contact_index(contacts, fields)
    assert idx == 0
    assert score >= 12


def test_match_by_surname_and_initiated_time():
    from datetime import datetime, timedelta, timezone

    cn = timezone(timedelta(hours=8))
    initiated = datetime(2026, 6, 8, 9, 4, 26, tzinfo=cn)
    contacts = [
        (0, "王** 28岁 09:00"),
        (1, "刘 26岁 09:04 江苏师范大学"),
    ]
    fields = IMContactMatchFields(
        display_name="刘**",
        age="26",
        school="江苏师范大学",
        chat_initiated_at=initiated.isoformat(),
    )
    idx, score, _ = match_contact_index(contacts, fields)
    assert idx == 1
    assert score >= 20


def test_im_match_label_strips_mask():
    assert im_match_label("刘**") == "刘"
    assert im_match_label("王磊") == "王磊"
