"""Outreach / IM send policy helpers for workflow config."""

from __future__ import annotations

from typing import Any, Mapping


def workflow_im_review_required(config: Mapping[str, Any] | None) -> bool:
    """When True, all automatic IM sends are blocked until HR confirms drafts."""
    if not config:
        return False
    outreach = config.get("outreach") or {}
    if not isinstance(outreach, dict):
        return False
    return bool(outreach.get("im_review_required"))
