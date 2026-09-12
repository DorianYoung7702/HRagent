"""Prevent Windows system sleep while automation runs (display may turn off)."""

from __future__ import annotations

import logging
import sys
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_refcount = 0

if sys.platform == "win32":
    import ctypes

    _ES_CONTINUOUS = 0x80000000
    _ES_SYSTEM_REQUIRED = 0x00000001
    _ES_AWAYMODE_REQUIRED = 0x00000040

    def _apply_state(active: bool) -> None:
        if active:
            flags = _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_AWAYMODE_REQUIRED
        else:
            flags = _ES_CONTINUOUS
        ctypes.windll.kernel32.SetThreadExecutionState(flags)

else:

    def _apply_state(active: bool) -> None:
        return


def acquire_keep_awake(reason: str = "") -> None:
    """Keep CPU awake; allow monitor off / screen lock."""
    global _refcount
    with _lock:
        _refcount += 1
        if _refcount == 1:
            _apply_state(True)
            if reason:
                logger.info("Keep-awake enabled: %s", reason)


def release_keep_awake(reason: str = "") -> None:
    global _refcount
    with _lock:
        if _refcount <= 0:
            return
        _refcount -= 1
        if _refcount == 0:
            _apply_state(False)
            if reason:
                logger.info("Keep-awake released: %s", reason)


class keep_awake_session:
    """Context manager for keep-awake refcounting."""

    def __init__(self, reason: str = "") -> None:
        self.reason = reason

    def __enter__(self) -> keep_awake_session:
        acquire_keep_awake(self.reason)
        return self

    def __exit__(self, *args: object) -> None:
        release_keep_awake(self.reason)
