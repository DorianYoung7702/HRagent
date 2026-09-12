"""Per-workflow isolated Liepin browser profiles for concurrent screening."""

from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path

from services.fetch_worker.login_init import profile_dir_for, profile_has_cache

logger = logging.getLogger(__name__)

_clone_lock = threading.Lock()

DEFAULT_SOURCE_PROFILE = "hr_default"

# Skip heavy/volatile dirs when cloning login state.
_PROFILE_SKIP_NAMES = frozenset(
    {
        "Cache",
        "Code Cache",
        "GPUCache",
        "GrShaderCache",
        "ShaderCache",
        "Service Worker",
        "Crashpad",
        "BrowserMetrics",
        "DawnGraphiteCache",
        "DawnWebGPUCache",
        "GraphiteDawnCache",
        "Safe Browsing Network",
        "optimization_guide_hint_cache_store",
        "Segmentation Platform",
    }
)


def workflow_browser_profile_name(workflow_id: str) -> str:
    safe = "".join(ch for ch in workflow_id if ch.isalnum())[:16]
    return f"wf_{safe or 'task'}"


def _copy_profile_tree(source: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _ignore(_dir: str, names: list[str]) -> set[str]:
        return {name for name in names if name in _PROFILE_SKIP_NAMES}

    shutil.copytree(source, dest, ignore=_ignore, dirs_exist_ok=False)


def ensure_workflow_browser_profile(
    workflow_id: str,
    *,
    source_profile: str = DEFAULT_SOURCE_PROFILE,
    force_refresh: bool = False,
) -> str:
    """Return an isolated profile name for *workflow_id*, cloning login from *source_profile*.

    Each concurrent Liepin workflow gets its own Chromium user_data_dir so search/IM
    automation in one task cannot interfere with another task's pages.
    """
    profile_name = workflow_browser_profile_name(workflow_id)
    if profile_has_cache(profile_name) and not force_refresh:
        return profile_name

    if not profile_has_cache(source_profile):
        raise ValueError("请先完成猎聘登录（hr_default 无有效登录缓存）")

    source_dir = profile_dir_for(source_profile)
    dest_dir = profile_dir_for(profile_name)
    with _clone_lock:
        if profile_has_cache(profile_name) and not force_refresh:
            return profile_name
        logger.info(
            "Cloning Liepin browser profile %s -> %s for workflow %s",
            source_profile,
            profile_name,
            workflow_id,
        )
        _copy_profile_tree(source_dir, dest_dir)
    return profile_name


def cleanup_workflow_browser_profile(workflow_id: str) -> None:
    """Best-effort remove workflow-scoped profile directory."""
    root = profile_dir_for(workflow_browser_profile_name(workflow_id))
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
