# -*- coding: utf-8 -*-
"""Copilot-safe pre-commit hook.

Rules:
- If code changed (bot/, comfy/, utils/, workflows/, config/, storage/, main.py, requirements.txt) -> docs/CHANGELOG_INTERNAL.md must be staged.
- For root meta-only commits (README.md, LICENSE, .gitignore, .gitattributes): allowed ONLY if docs/CHANGELOG_INTERNAL.md is staged in same commit.
- Block .md files outside docs/ (except README.md).
"""

from __future__ import annotations

import subprocess
import sys
from typing import List

ROOT_OK_FILES = {"README.md", "LICENSE", ".gitignore", ".gitattributes"}
CODE_PREFIXES = ("bot/", "comfy/", "utils/", "workflows/", "config/", "storage/")
CODE_FILES = ("main.py", "requirements.txt")
CHANGELOG = "docs/CHANGELOG_INTERNAL.md"


def _git(args: List[str]) -> str:
    p = subprocess.run(["git"] + args, capture_output=True, text=True)
    if p.returncode != 0:
        return ""
    return (p.stdout or "").strip()


def _fail(msg: str) -> None:
    sys.stderr.write("\n" + "=" * 60 + "\n")
    sys.stderr.write("BLOCK\n")
    sys.stderr.write("=" * 60 + "\n")
    sys.stderr.write(msg.rstrip() + "\n\n")
    raise SystemExit(1)


def main() -> int:
    out = _git(["diff", "--cached", "--name-only"])
    if not out:
        _fail("No files staged. Run: git add -A")

    files = [f.strip().replace("\\", "/") for f in out.splitlines() if f.strip()]
    if not files:
        _fail("No files staged. Run: git add -A")

    md_outside = [f for f in files if f.lower().endswith(".md") and not f.startswith("docs/") and f != "README.md"]
    if md_outside:
        _fail("Markdown files must live under docs/ (except README.md). Found: " + ", ".join(md_outside))

    code_changed = any((f in CODE_FILES) or any(f.startswith(pfx) for pfx in CODE_PREFIXES) for f in files)
    if code_changed and CHANGELOG not in files:
        _fail(f"Code changed but {CHANGELOG} is not staged. Add a changelog entry.")

    non_docs = [f for f in files if not f.startswith("docs/")]
    if non_docs and all(f in ROOT_OK_FILES for f in non_docs):
        if CHANGELOG in files:
            return 0
        _fail("Meta-only commit is blocked (README/LICENSE/.gitignore/.gitattributes). Add docs/CHANGELOG_INTERNAL.md in same commit.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
