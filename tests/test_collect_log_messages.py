"""Ensure runtime collect/resume-library logs do not describe obsolete observe/followup folder clicks."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OBSOLETE_PATTERNS = (
    "点「观察」分组",
    "点「追问」分组",
    "追问/观察标签",
    "开聊/收藏/标签选择",
    "选分组后未找到",
    "收藏分组弹窗",
    "分组弹窗已打开",
    "未能选中简历库父分组",
    "收藏目标推断",
)

ALLOWED_IN_COMMENTS_ONLY = (
    "观察/追问仅作",
    "勿点",
    "观察/追问/候选",
)


def test_extract_popup_logs_no_obsolete_collect_folder_wording():
    source = (ROOT / "services/fetch_worker/extract_popup.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if any(p in line for p in ALLOWED_IN_COMMENTS_ONLY):
            continue
        for pattern in OBSOLETE_PATTERNS:
            assert pattern not in line, f"obsolete log wording {pattern!r} in: {line}"


def test_report_card_im_outreach_review_pending_is_success(capfd):
    from services.fetch_worker.extract_popup import _report_card_im_outreach

    _report_card_im_outreach(
        0,
        "追问",
        {"review_pending": True, "send": None, "action": "追问"},
    )
    out = capfd.readouterr().out
    assert "已完成开聊" in out
    assert "草稿待人工确认" in out
    assert "发送失败" not in out


def test_resume_library_nav_errors_use_job_folder_wording():
    source = (ROOT / "services/fetch_worker/resume_library_nav.py").read_text(encoding="utf-8")
    assert "未能选中简历库岗位文件夹" in source
    assert "未能选中简历库父分组" not in source
