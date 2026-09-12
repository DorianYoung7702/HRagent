import pytest

from services.fetch_worker.resume_library_nav import (
    _GET_LIST_PAGE_STATE_JS,
    _SCAN_MAIN_LIST_JS,
    _WAIT_MAIN_LIST_JS,
    _cache_folder_page_rows,
    _cache_resume_library_folder,
    _cache_resume_library_match,
    _can_reuse_current_folder,
    _cached_folder_page_rows,
    _cached_resume_library_folder,
    _cached_resume_library_match,
    _clear_resume_library_folder_cache,
    _clear_resume_library_match_cache,
    _clear_resume_library_page_rows_cache,
    _profile_cache_key,
    _scan_right_rows,
)
from services.fetch_worker.resume_library_row_match import (
    ResumeLibraryMatchProfile,
    ResumeLibraryRow,
)


class FakePage:
    def __init__(self, *, current: str = "1", ready: bool = True):
        self.current = current
        self.ready = ready

    async def evaluate(self, script, *_args):
        if script == _GET_LIST_PAGE_STATE_JS:
            return {"current": self.current}
        if script == _WAIT_MAIN_LIST_JS:
            return {"ready": self.ready, "rows": 3 if self.ready else 0}
        raise AssertionError("unexpected script")


class FakeScanPage:
    def __init__(self):
        self.current = "1"
        self.scan_calls = 0

    async def evaluate(self, script, *_args):
        if script == _GET_LIST_PAGE_STATE_JS:
            return {"current": self.current}
        if script == _SCAN_MAIN_LIST_JS:
            self.scan_calls += 1
            return [{"cells": ["stub"], "index": 0, "top": 12}]
        raise AssertionError("unexpected script")


def test_resume_library_folder_cache_helpers():
    page = FakePage()
    assert _cached_resume_library_folder(page) is None
    _cache_resume_library_folder(page, "observe")
    assert _cached_resume_library_folder(page) == "observe"
    _clear_resume_library_folder_cache(page)
    assert _cached_resume_library_folder(page) is None


@pytest.mark.asyncio
async def test_can_reuse_current_folder_only_on_first_ready_page():
    page = FakePage(current="1", ready=True)
    _cache_resume_library_folder(page, "observe")
    assert await _can_reuse_current_folder(page, "observe") is True

    page.current = "3"
    assert await _can_reuse_current_folder(page, "observe") is False

    page.current = "1"
    page.ready = False
    assert await _can_reuse_current_folder(page, "observe") is False

    page.ready = True
    assert await _can_reuse_current_folder(page, "followup") is False


def test_resume_library_profile_cache_key_is_stable_and_field_sensitive():
    first = ResumeLibraryMatchProfile(
        display_name="Zhang",
        surname="Z",
        age=30,
        education="本科",
        current_title="Dev",
        current_company="Acme",
        collect_time="2026-06-12",
        folder="observe",
    )
    same = ResumeLibraryMatchProfile(
        display_name=" Zhang ",
        surname="Z",
        age=30,
        education="本科",
        current_title="Dev",
        current_company=" Acme ",
        collect_time="2026-06-12",
        folder="observe",
    )
    changed = ResumeLibraryMatchProfile(
        display_name="Zhang",
        surname="Z",
        age=31,
        education="本科",
        current_title="Dev",
        current_company="Acme",
        collect_time="2026-06-12",
        folder="observe",
    )

    assert _profile_cache_key(first) == _profile_cache_key(same)
    assert _profile_cache_key(first) != _profile_cache_key(changed)


def test_resume_library_match_cache_round_trip_and_clear():
    profile = ResumeLibraryMatchProfile(
        display_name="Zhang",
        surname="Z",
        age=30,
        education="本科",
        current_company="Acme",
        folder="observe",
    )
    row = ResumeLibraryRow(
        name="Zhang",
        gender=None,
        age=30,
        education="本科",
        title=None,
        company="Acme",
        collect_time=None,
        raw_text="Zhang Acme",
        index=4,
    )

    _clear_resume_library_match_cache()
    assert _cached_resume_library_match(profile) is None

    _cache_resume_library_match(profile, page_no=3, row=row)
    hit = _cached_resume_library_match(profile)
    assert hit is not None
    assert hit["page_no"] == 3
    assert hit["row_index"] == 4

    _clear_resume_library_match_cache(profile)
    assert _cached_resume_library_match(profile) is None


def test_folder_page_rows_cache_is_scoped_by_page_folder_and_page_number():
    page = FakePage()
    row = ResumeLibraryRow(
        name="Zhang",
        gender=None,
        age=30,
        education="本科",
        title=None,
        company="Acme",
        collect_time=None,
        raw_text="Zhang Acme",
        index=0,
    )

    _clear_resume_library_page_rows_cache(page)
    assert _cached_folder_page_rows(page, "observe", 1) is None
    _cache_folder_page_rows(page, "observe", 1, [row])

    assert _cached_folder_page_rows(page, "observe", 1) == [row]
    assert _cached_folder_page_rows(page, "followup", 1) is None
    assert _cached_folder_page_rows(page, "observe", 2) is None

    _clear_resume_library_page_rows_cache(page, "observe")
    assert _cached_folder_page_rows(page, "observe", 1) is None


@pytest.mark.asyncio
async def test_scan_right_rows_reuses_folder_page_cache(monkeypatch):
    page = FakeScanPage()
    row = ResumeLibraryRow(
        name="Zhang",
        gender=None,
        age=30,
        education="本科",
        title=None,
        company="Acme",
        collect_time=None,
        raw_text="Zhang Acme",
        index=0,
    )

    def fake_parse_row_from_cells(*_args, **_kwargs):
        return row

    monkeypatch.setattr(
        "services.fetch_worker.resume_library_nav.parse_row_from_cells",
        fake_parse_row_from_cells,
    )
    _clear_resume_library_page_rows_cache(page)
    _cache_resume_library_folder(page, "observe")

    assert await _scan_right_rows(page) == [row]
    assert await _scan_right_rows(page) == [row]
    assert page.scan_calls == 1
