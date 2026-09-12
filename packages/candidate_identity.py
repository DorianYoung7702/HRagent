"""Stable candidate identity helpers for de-duplicating LPT snapshots."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable
from typing import Any

_COUNT_LINE_RE = re.compile(r"(?m)^\s*\(\d+\)\s*$")
_QUICK_LOCATE_RE = re.compile(r"(?m)^\s*快速定位[:：]?\s*$")
_ACTIVE_TEXT_RE = re.compile(r"(?:今天|昨天|刚刚|近期|近\d+天)?活跃")
_SPACE_RE = re.compile(r"\s+")


def _norm(value: object) -> str:
    return _SPACE_RE.sub("", str(value or "")).strip().lower()


def _norm_display_name(value: object) -> str:
    name = _norm(value)
    if not name:
        return ""
    if "*" in name:
        return name[:1]
    for suffix in ("先生", "女士", "男士", "小姐"):
        if name.endswith(suffix) and len(name) <= 4:
            return name[:1]
    return name


def stable_resume_identity_text(raw_text: str | None) -> str:
    text = str(raw_text or "")
    marker = "查看大图"
    marker_pos = text.find(marker)
    if marker_pos >= 0:
        text = text[marker_pos:]
    text = _QUICK_LOCATE_RE.sub("", text)
    text = _COUNT_LINE_RE.sub("", text)
    text = _ACTIVE_TEXT_RE.sub("", text)
    return _SPACE_RE.sub("", text).strip()[:1600]


def candidate_identity_hash(
    *,
    display_name: str | None = None,
    raw_text: str | None = None,
    fallback_parts: Iterable[object] = (),
) -> str | None:
    name = _norm_display_name(display_name)
    stable_text = stable_resume_identity_text(raw_text)
    if stable_text:
        payload = f"{name}|{stable_text}"
        return "resume:" + hashlib.sha1(payload.encode("utf-8")).hexdigest()

    parts = [name, *(_norm(part) for part in fallback_parts)]
    if not name or not any(parts[1:]):
        return None
    payload = "|".join(parts)
    return "profile:" + hashlib.sha1(payload.encode("utf-8")).hexdigest()


def snapshot_identity_key(snapshot: Any, *, display_name: str | None = None) -> str | None:
    meta = getattr(snapshot, "metadata_", None)
    if not isinstance(meta, dict):
        meta = {}
    if meta.get("candidate_identity_key"):
        return str(meta["candidate_identity_key"])
    fallback_parts = (
        meta.get("card_age") or meta.get("age"),
        meta.get("card_school") or meta.get("school"),
        getattr(snapshot, "education", None),
        getattr(snapshot, "city", None),
        getattr(snapshot, "work_years", None),
    )
    return candidate_identity_hash(
        display_name=display_name or getattr(snapshot, "display_name", None),
        raw_text=getattr(snapshot, "raw_text", None),
        fallback_parts=fallback_parts,
    )


def candidate_item_identity_key(item: dict[str, Any]) -> str | None:
    if item.get("identity_key"):
        return str(item["identity_key"])
    meta = item.get("metadata") or {}
    if isinstance(meta, dict) and meta.get("candidate_identity_key"):
        return str(meta["candidate_identity_key"])
    return candidate_identity_hash(
        display_name=item.get("display_name"),
        raw_text=item.get("raw_text"),
        fallback_parts=(
            meta.get("card_age") or meta.get("age"),
            meta.get("card_school") or meta.get("school"),
            item.get("education"),
            item.get("city"),
            item.get("work_years"),
        ),
    )


def _coerce_score(value: object) -> float:
    try:
        return float(value) if value is not None else -1.0
    except (TypeError, ValueError):
        return -1.0


def dedupe_candidate_records(
    records: list[dict[str, Any]],
    *,
    identity_getter: Callable[[dict[str, Any]], str | None] = candidate_item_identity_key,
    score_getter: Callable[[dict[str, Any]], object] | None = None,
    captured_getter: Callable[[dict[str, Any]], object] | None = None,
    strip_identity_key: bool = True,
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    passthrough: list[dict[str, Any]] = []

    def rank(record: dict[str, Any]) -> tuple[float, str]:
        score = score_getter(record) if score_getter else (record.get("screening") or {}).get("total_score")
        captured = captured_getter(record) if captured_getter else record.get("captured_at")
        return (_coerce_score(score), str(captured or ""))

    for record in records:
        key = identity_getter(record)
        if not key:
            passthrough.append(dict(record))
            continue
        if key not in by_key:
            order.append(key)
            by_key[key] = dict(record)
        elif rank(record) > rank(by_key[key]):
            by_key[key] = dict(record)

    out = [by_key[key] for key in order] + passthrough
    if strip_identity_key:
        for record in out:
            record.pop("identity_key", None)
    return out
