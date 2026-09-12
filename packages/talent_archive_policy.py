"""Cross-workflow retention is an explicit deployment choice."""

import os


def talent_archive_enabled() -> bool:
    return os.environ.get("HRAGENT_TALENT_ARCHIVE_ENABLED", "0").lower() in {
        "1", "true", "yes",
    }
