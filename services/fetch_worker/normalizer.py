from packages.schemas.candidate import CandidateCard, CandidateSnapshotData


def normalize_card_to_snapshot(
    card: CandidateCard,
    detail: dict | None,
    workflow_id: str,
    platform: str,
) -> CandidateSnapshotData:
    if detail:
        return CandidateSnapshotData(
            workflow_id=workflow_id,
            platform=platform,
            source_candidate_id=card.source_candidate_id or detail.get("source_candidate_id"),
            source_url=card.source_url,
            display_name=detail.get("display_name") or card.display_name,
            current_title=detail.get("current_title") or card.current_title,
            current_company=detail.get("current_company") or card.current_company,
            work_years=detail.get("work_years") or card.work_years,
            education=detail.get("education") or card.education,
            city=detail.get("city") or card.city,
            skills=detail.get("skills") or card.skills,
            summary=detail.get("summary") or card.summary,
            experience_summary=detail.get("experience_summary"),
            project_summary=detail.get("project_summary"),
            raw_text=detail.get("raw_text", ""),
            extraction_confidence=detail.get("extraction_confidence", 0.0),
            missing_fields=detail.get("missing_fields", []),
            template_type=detail.get("template_type", "liepin_resume_detail_v2"),
        )

    return CandidateSnapshotData(
        workflow_id=workflow_id,
        platform=platform,
        source_candidate_id=card.source_candidate_id,
        source_url=card.source_url,
        display_name=card.display_name,
        current_title=card.current_title,
        current_company=card.current_company,
        work_years=card.work_years,
        education=card.education,
        city=card.city,
        skills=card.skills,
        summary=card.summary,
        raw_text="",
        extraction_confidence=0.3,
        missing_fields=["experience_summary", "project_summary", "raw_text"],
    )
