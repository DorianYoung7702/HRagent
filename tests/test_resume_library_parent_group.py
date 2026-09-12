from services.fetch_worker.resume_library_nav import _folder_cache_key
from services.fetch_worker.resume_library_row_match import ResumeLibraryMatchProfile


def test_profile_reads_direct_resume_library_folder_from_metadata():
    profile = ResumeLibraryMatchProfile.from_candidate(
        display_name="Candidate A",
        current_title="Sales",
        current_company=None,
        education="Bachelor",
        screening_level="observe",
        metadata={
            "resume_library_folder": "Latam Sales Shenzhen",
            "resume_library_decision": "observe",
        },
    )

    assert profile.parent_folder is None
    assert profile.folder == "Latam Sales Shenzhen"


def test_profile_falls_back_to_job_folder_not_decision_tags():
    profile = ResumeLibraryMatchProfile.from_candidate(
        display_name="Candidate B",
        current_title="Sales",
        current_company=None,
        education="Bachelor",
        screening_level="observe",
        metadata={},
        job_folder="薪酬绩效经理",
    )

    assert profile.folder == "薪酬绩效经理"
    assert profile.parent_folder is None


def test_folder_cache_key_uses_job_folder_only():
    assert _folder_cache_key(None, "Latam Sales Shenzhen") == "Latam Sales Shenzhen"
    assert _folder_cache_key("", "Latam Sales Shenzhen") == "Latam Sales Shenzhen"
