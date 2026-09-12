"""Check version-controlled release files; report paths, never matched secrets."""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIRS = {
    ".runtime", ".agents", ".codex", "deliverables", "node_modules", "build",
    "browser_profiles", "backups", "uploads", "runtime", "logs",
}
PRIVATE_EXTENSIONS = {
    ".db", ".sqlite", ".sqlite3", ".pem", ".key", ".pptx", ".docx", ".pdf",
    ".csv", ".xlsx", ".xls", ".har", ".jsonl", ".log", ".dump", ".bak",
}
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{24,}"),
    re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def inspect_file(name: str, raw: bytes) -> list[str]:
    path = PurePosixPath(name)
    reasons = []
    if any(p in PRIVATE_DIRS or p.startswith((".pytest", ".tmp")) for p in path.parts):
        reasons.append("private or generated directory")
    if path.suffix.lower() in PRIVATE_EXTENSIONS or path.name.endswith((".db-wal", ".db-shm")):
        reasons.append("private data or key file")
    if (".env" in path.name or path.name.endswith(".env")) and not path.name.endswith(".example"):
        reasons.append("live environment configuration")
    if path.parts[0] == "data" and name != "data/.gitkeep":
        reasons.append("runtime data")
    if name.startswith("apps/console-web/dist/"):
        reasons.append("generated frontend bundle")
    if path.name in {"Cookies", "Login Data", "Web Data", "license.cache"}:
        reasons.append("browser or activation cache")
    text = raw.decode("utf-8", errors="replace")
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        reasons.append("possible credential")
    return reasons


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", help="Inspect a Git tree instead of the index")
    args = parser.parse_args()
    if args.ref:
        names = subprocess.check_output(
            ["git", "ls-tree", "-rz", "--name-only", args.ref], cwd=ROOT
        )
    else:
        names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    failures = []
    count = 0
    for item in names.split(b"\0"):
        if not item:
            continue
        name = item.decode("utf-8")
        object_name = f"{args.ref}:{name}" if args.ref else f":{name}"
        raw = subprocess.check_output(["git", "show", object_name], cwd=ROOT)
        count += 1
        reasons = inspect_file(name, raw)
        if reasons:
            failures.append((name, reasons))
    for name, reasons in failures:
        print(f"FAIL {name}: {', '.join(reasons)}")
    print(f"Checked {count} files; {len(failures)} finding(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
