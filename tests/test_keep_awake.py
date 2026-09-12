"""Tests for Windows keep-awake helper (no-op on other platforms)."""

from packages.keep_awake import acquire_keep_awake, keep_awake_session, release_keep_awake


def test_keep_awake_refcount():
    acquire_keep_awake("test-a")
    acquire_keep_awake("test-b")
    release_keep_awake("test-b")
    release_keep_awake("test-a")


def test_keep_awake_session_context():
    with keep_awake_session("ctx"):
        pass
