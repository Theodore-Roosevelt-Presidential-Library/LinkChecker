"""Load the committed ignore list (ignore.txt).

The file lets you permanently suppress items from the report for everyone, at
generation time. Format — one rule per line, ``#`` starts a comment:

    word: rehumanize                       # never flag this spelling
    link: https://bsky.app/profile/...     # ignore this exact link
    link-prefix: https://www.youtube.com/  # ignore every link under this prefix

Bare lines with no prefix are treated as ``word:`` for convenience.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import config


@dataclass
class IgnoreRules:
    words: set[str] = field(default_factory=set)
    links: set[str] = field(default_factory=set)
    link_prefixes: list[str] = field(default_factory=list)

    def link_ignored(self, url: str) -> bool:
        if url in self.links:
            return True
        return any(url.startswith(p) for p in self.link_prefixes)

    def word_ignored(self, word: str) -> bool:
        return word.lower() in self.words


def _resolve(path: str) -> str:
    if os.path.isabs(path):
        return path
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, path)


def load_ignores() -> IgnoreRules:
    rules = IgnoreRules()
    path = _resolve(config.IGNORE_FILE)
    if not os.path.exists(path):
        return rules
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                kind, _, value = line.partition(":")
                kind = kind.strip().lower()
                value = value.strip()
            else:
                kind, value = "word", line
            if not value:
                continue
            if kind == "word":
                rules.words.add(value.lower())
            elif kind == "link":
                rules.links.add(value)
            elif kind in ("link-prefix", "link_prefix", "prefix"):
                rules.link_prefixes.append(value)
    total = len(rules.words) + len(rules.links) + len(rules.link_prefixes)
    if total:
        print(
            f"  loaded {total} ignore rule(s) from {os.path.basename(path)} "
            f"({len(rules.words)} words, {len(rules.links)} links, "
            f"{len(rules.link_prefixes)} prefixes)"
        )
    return rules
