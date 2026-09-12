"""Tests for IM chat adapter helpers."""

from services.fetch_worker.im_chat_adapter import build_im_contact_key
from services.fetch_worker.im_contact_match import IMContactMatchFields, match_contact_index


def test_build_im_contact_key_legacy_title():
    assert build_im_contact_key("张三", "销售经理") == "张三|销售经理"


def test_build_im_contact_key_name_age_school():
    assert build_im_contact_key("张三", age="32", school="北京大学") == "张三|32岁|北京大学"


def test_match_contact_index():
    contacts = [(0, "张三 32岁 北京大学 深圳"), (1, "李四 工程师")]
    fields = IMContactMatchFields(display_name="张三", age="32", school="北京大学")
    idx, _, _ = match_contact_index(contacts, fields)
    assert idx == 0
    miss, _, _ = match_contact_index(contacts, IMContactMatchFields(display_name="王五"))
    assert miss is None
