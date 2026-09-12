from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher


OBSERVE_LABELS = {"observe": "observe", "观察": "观察", "瑙傚療": "瑙傚療"}
FOLLOWUP_LABELS = {"followup": "followup", "追问": "追问", "杩介棶": "杩介棶"}
# 猎聘侧栏上的初筛标签；仅作平台 metadata，不再作为简历库导航目标。
DECISION_SIDEBAR_LABELS = frozenset({"observe", "followup", "观察", "追问", "候选"})
BLOCKED_TARGET_TOKENS = (
    "Uncategorized",
    "uncategorized",
    "Add tag",
    "add tag",
    "All favorites",
    "all favorites",
    "未分组",
    "增加标签",
    "添加标签",
    "新增标签",
    "全部收藏",
    "鏈垎缁",
    "澧炲姞",
    "娣诲姞",
    "鍏ㄩ儴",
)


def normalize_collect_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def strip_count_suffix(value: str) -> str:
    open_full = "\uFF08"
    close_full = "\uFF09"
    return re.sub(
        rf"[\({open_full}]\s*\d+\s*[\){close_full}]$",
        "",
        normalize_collect_text(value),
    ).strip()


def is_decision_sidebar_label(label: str) -> bool:
    raw = normalize_collect_text(label)
    if not raw:
        return False
    if raw in DECISION_SIDEBAR_LABELS:
        return True
    base = strip_count_suffix(raw)
    return base in DECISION_SIDEBAR_LABELS or base.lower() in DECISION_SIDEBAR_LABELS


def resolve_collect_folder_tag(
    *,
    parent_name: str | None = None,
    job_title: str | None = None,
) -> str:
    del job_title  # 收藏文件夹仅使用用户填写的关键词，不回退岗位全称
    folder = normalize_collect_text(parent_name)
    if folder and not is_decision_sidebar_label(folder):
        return folder
    return ""


def resolve_job_collect_folder_from_config(config: dict | None) -> str:
    cfg = config or {}
    search_intent = cfg.get("search_intent") or {}
    collect_group = cfg.get("collect_group") or {}
    return resolve_collect_folder_tag(
        parent_name=str(search_intent.get("collect_parent_group") or collect_group.get("parent_name") or ""),
    )


def canonical_decision_label(decision: str) -> str:
    raw = normalize_collect_text(decision)
    if raw in OBSERVE_LABELS:
        return OBSERVE_LABELS[raw]
    if raw in FOLLOWUP_LABELS:
        return FOLLOWUP_LABELS[raw]
    lowered = raw.lower()
    if lowered in OBSERVE_LABELS:
        return OBSERVE_LABELS[lowered]
    if lowered in FOLLOWUP_LABELS:
        return FOLLOWUP_LABELS[lowered]
    return raw


@dataclass(frozen=True)
class CollectGroupConfig:
    parent_name: str = ""
    observe_label: str = "observe"
    followup_label: str = "followup"

    @classmethod
    def from_values(
        cls,
        *,
        parent_name: str | None = None,
        observe_label: str | None = None,
        followup_label: str | None = None,
    ) -> "CollectGroupConfig":
        return cls(
            parent_name=normalize_collect_text(parent_name),
            observe_label=normalize_collect_text(observe_label) or "observe",
            followup_label=normalize_collect_text(followup_label) or "followup",
        )

    def child_label_for_decision(self, decision: str) -> str:
        canonical = canonical_decision_label(decision)
        if canonical in OBSERVE_LABELS.values():
            return self.observe_label
        if canonical in FOLLOWUP_LABELS.values():
            return self.followup_label
        return canonical

    def path_for_decision(self, decision: str) -> list[str]:
        folder = self.folder_for_decision(decision)
        return [folder] if folder else []

    def folder_for_decision(self, decision: str) -> str:
        folder = normalize_collect_text(self.parent_name)
        if folder and not is_decision_sidebar_label(folder):
            return folder
        return ""

    def collect_folder_tag(self, *, job_title: str | None = None) -> str:
        del job_title
        return resolve_collect_folder_tag(parent_name=self.parent_name)


def build_collect_metadata_patch(
    decision: str,
    group: CollectGroupConfig | None = None,
) -> dict[str, object]:
    cfg = group or CollectGroupConfig()
    decision_label = cfg.child_label_for_decision(decision)
    folder = cfg.folder_for_decision(decision)
    patch: dict[str, object] = {
        "resume_library_folder": folder,
        "resume_library_path": [folder] if folder else [],
        "resume_library_decision": decision_label,
    }
    return patch


@dataclass(frozen=True)
class UiTargetDecision:
    action: str
    target_text: str = ""
    confidence: float = 0.0
    reason: str = ""
    action_context: str = ""
    visible_texts: tuple[str, ...] = ()


def _is_blocked_target(text: str) -> bool:
    return any(token in text for token in BLOCKED_TARGET_TOKENS)


def _score_candidate(desired: str, candidate: str) -> tuple[float, str]:
    desired_clean = strip_count_suffix(desired)
    candidate_clean = normalize_collect_text(candidate)
    candidate_base = strip_count_suffix(candidate_clean)
    if not desired_clean or not candidate_clean or _is_blocked_target(candidate_clean):
        return 0.0, "blocked-or-empty"
    if candidate_clean == desired_clean:
        return 1.0, "exact"
    if candidate_base == desired_clean:
        return 0.96, "exact-with-count"
    if desired_clean in candidate_clean:
        return 0.88, "contains-desired"
    if candidate_base in desired_clean and len(candidate_base) >= 3:
        return 0.75, "candidate-contained"
    ratio = SequenceMatcher(None, desired_clean.lower(), candidate_base.lower()).ratio()
    return round(ratio * 0.82, 4), "fuzzy"


def infer_ui_target(
    *,
    desired_label: str,
    visible_texts: list[str] | tuple[str, ...],
    action_context: str,
    min_confidence: float = 0.7,
) -> UiTargetDecision:
    desired = normalize_collect_text(desired_label)
    normalized = tuple(
        text for text in (normalize_collect_text(item) for item in visible_texts) if text
    )
    best_text = ""
    best_score = 0.0
    best_reason = ""
    for text in normalized:
        score, reason = _score_candidate(desired, text)
        if score > best_score:
            best_text = text
            best_score = score
            best_reason = reason
    if best_score >= min_confidence:
        return UiTargetDecision(
            action="click",
            target_text=best_text,
            confidence=best_score,
            reason=best_reason,
            action_context=action_context,
            visible_texts=normalized,
        )
    return UiTargetDecision(
        action="no_action",
        target_text=best_text,
        confidence=best_score,
        reason=best_reason or "no-confident-target",
        action_context=action_context,
        visible_texts=normalized,
    )
