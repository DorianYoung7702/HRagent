from packages.db.sqlite_guard import is_sqlite_locked_error


def test_is_sqlite_locked_error():
    assert is_sqlite_locked_error(Exception("database is locked"))
    assert is_sqlite_locked_error(Exception("database is busy"))
    assert not is_sqlite_locked_error(Exception("other error"))
