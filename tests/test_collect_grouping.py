from services.fetch_worker.collect_grouping import (
    CollectGroupConfig,
    build_collect_metadata_patch,
    infer_ui_target,
)


def test_collect_group_path_records_job_folder_only():
    group = CollectGroupConfig(parent_name="Latam Sales Shenzhen")

    patch = build_collect_metadata_patch("observe", group)

    assert "resume_library_parent_folder" not in patch
    assert patch["resume_library_folder"] == "Latam Sales Shenzhen"
    assert patch["resume_library_path"] == ["Latam Sales Shenzhen"]
    assert patch["resume_library_decision"] == "observe"


def test_collect_group_path_stays_compatible_without_parent():
    patch = build_collect_metadata_patch("followup", CollectGroupConfig(parent_name=""))

    assert patch["resume_library_folder"] == ""
    assert patch["resume_library_path"] == []
    assert patch["resume_library_decision"] == "followup"


def test_collect_group_rejects_decision_labels_as_folder():
    group = CollectGroupConfig(parent_name="观察")
    assert group.folder_for_decision("observe") == ""
    assert build_collect_metadata_patch("observe", group)["resume_library_folder"] == ""
    assert build_collect_metadata_patch("observe", group)["resume_library_decision"] == "observe"


def test_resolve_collect_folder_tag_uses_parent_only():
    from services.fetch_worker.collect_grouping import resolve_collect_folder_tag

    assert (
        resolve_collect_folder_tag(
            parent_name="嵌入式",
            job_title="嵌入式软件工程师",
        )
        == "嵌入式"
    )
    assert resolve_collect_folder_tag(parent_name="", job_title="嵌入式软件工程师") == ""
    assert resolve_collect_folder_tag(parent_name="观察", job_title="嵌入式软件工程师") == ""


def test_ui_target_matches_folder_keyword_in_longer_label():
    decision = infer_ui_target(
        desired_label="嵌入式",
        visible_texts=[
            "Uncategorized candidates",
            "嵌入式软件工程师(3)",
            "observe(1)",
        ],
        action_context="collect_parent_group",
    )

    assert decision.action == "click"
    assert "嵌入式" in decision.target_text


def test_ui_target_agent_prefers_exact_or_counted_label():
    decision = infer_ui_target(
        desired_label="Latam Sales Shenzhen",
        visible_texts=[
            "Uncategorized candidates",
            "Add tag",
            "Latam Sales Shenzhen(3)",
            "observe(1)",
        ],
        action_context="collect_parent_group",
    )

    assert decision.action == "click"
    assert decision.target_text == "Latam Sales Shenzhen(3)"
    assert decision.confidence >= 0.9


def test_ui_target_agent_refuses_low_confidence_guess():
    decision = infer_ui_target(
        desired_label="Latam Sales Shenzhen",
        visible_texts=["Uncategorized candidates", "Add tag", "All favorites"],
        action_context="collect_parent_group",
    )

    assert decision.action == "no_action"
    assert decision.confidence < 0.7
