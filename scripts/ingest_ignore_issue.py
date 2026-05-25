#!/usr/bin/env python3
"""Append ignore rules parsed from a GitHub issue body into ignore.txt.

Invoked by the ignore-commit workflow. Reads the issue body from the
ISSUE_BODY environment variable, extracts ``word:`` / ``link:`` /
``link-prefix:`` rules, and appends any that aren't already present to
ignore.txt. Writes a short summary to GITHUB_OUTPUT so the workflow knows
whether to commit and what to say when it closes the issue.

The issue body must contain the marker ``<!-- linkchecker-ignore -->`` or
nothing is changed (so ordinary issues are left alone).
"""
from __future__ import annotations

import os
import re
import sys

MARKER = "<!-- linkchecker-ignore -->"
IGNORE_FILE = os.environ.get("IGNORE_FILE", "ignore.txt")
RULE_RE = re.compile(r"^(word|link|link-prefix)\s*:\s*(\S.*?)\s*$", re.IGNORECASE)


def set_output(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    # Multi-line safe output using a heredoc delimiter.
    delim = "EOF_LC_" + name
    with open(out, "a", encoding="utf-8") as fh:
        fh.write(f"{name}<<{delim}\n{value}\n{delim}\n")


def existing_rules(path: str) -> set[str]:
    rules: set[str] = set()
    if not os.path.exists(path):
        return rules
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = RULE_RE.match(line)
            if m:
                rules.add(_norm(m.group(1), m.group(2)))
    return rules


def _norm(kind: str, value: str) -> str:
    kind = kind.lower().replace("_", "-")
    value = value.strip()
    if kind == "word":
        value = value.lower()
    return f"{kind}:{value}"


def parse_body(body: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for raw in body.splitlines():
        line = raw.strip().lstrip(">").strip()  # tolerate quoted lines
        m = RULE_RE.match(line)
        if m:
            found.append((m.group(1).lower().replace("_", "-"), m.group(2).strip()))
    return found


def main() -> int:
    body = os.environ.get("ISSUE_BODY", "") or ""
    issue_num = os.environ.get("ISSUE_NUMBER", "")

    if MARKER not in body:
        set_output("added", "0")
        set_output("message", "No LinkChecker ignore marker found; nothing to do.")
        print("Marker not present; skipping.")
        return 0

    rules = parse_body(body)
    if not rules:
        set_output("added", "0")
        set_output("message", "No valid `word:` / `link:` / `link-prefix:` lines were found in the issue body.")
        print("No rules parsed.")
        return 0

    have = existing_rules(IGNORE_FILE)
    to_add: list[tuple[str, str]] = []
    seen: set[str] = set()
    for kind, value in rules:
        norm = _norm(kind, value)
        if norm in have or norm in seen:
            continue
        seen.add(norm)
        to_add.append((kind, value))

    if not to_add:
        set_output("added", "0")
        set_output("message", "Those rules are already in `ignore.txt` — no changes needed.")
        print("All rules already present.")
        return 0

    header = f"\n# --- added from issue #{issue_num} ---\n" if issue_num else "\n"
    with open(IGNORE_FILE, "a", encoding="utf-8") as fh:
        fh.write(header)
        for kind, value in to_add:
            fh.write(f"{kind}: {value}\n")

    lines = "\n".join(f"- `{k}: {v}`" for k, v in to_add)
    msg = f"Added {len(to_add)} rule(s) to `ignore.txt`:\n{lines}\n\nThe report will refresh shortly."
    set_output("added", str(len(to_add)))
    set_output("message", msg)
    print(f"Added {len(to_add)} rule(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
