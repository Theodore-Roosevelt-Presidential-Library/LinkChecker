"""Load the committed ignore list (ignore.txt).

The file lets you permanently suppress items from the report for everyone, at
generation time. Format — one rule per line, ``#`` starts a comment:

    word: rehumanize                       # never flag this spelling
    link: https://bsky.app/profile/...     # ignore this exact link
    link-prefix: https://www.youtube.com/  # ignore every link under this prefix
    link-host: newspapers.com              # ignore every link on this host (+subdomains)
    page-pattern: /video/                  # ignore links found on pages whose URL
                                           # contains this (e.g. YouTube descriptions)

Bare lines with no prefix are treated as ``word:`` for convenience.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import config


@dataclass
class IgnoreRules:
    words: set[str] = field(default_factory=set)
    links: set[str] = field(default_factory=set)
    link_prefixes: list[str] = field(default_factory=list)
    link_hosts: set[str] = field(default_factory=set)
    page_patterns: list[str] = field(default_factory=list)

    def link_ignored(self, url: str) -> bool:
        if url in self.links:
            return True
        if any(url.startswith(p) for p in self.link_prefixes):
            return True
        if self.link_hosts:
            host = (urlparse(url).hostname or "").lower()
            for h in self.link_hosts:
                if host == h or host.endswith("." + h):
                    return True
        return False

    def page_ignored(self, page_url: str) -> bool:
        """True if links *found on* this page should be ignored."""
        low = page_url.lower()
        return any(pat in low for pat in self.page_patterns)

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
            elif kind in ("link-host", "link_host", "host"):
                rules.link_hosts.add(value.lower().lstrip(".").removeprefix("www."))
            elif kind in ("page-pattern", "page_pattern", "page", "page-prefix"):
                rules.page_patterns.append(value.lower())
    total = (len(rules.words) + len(rules.links) + len(rules.link_prefixes)
             + len(rules.link_hosts) + len(rules.page_patterns))
    if total:
        print(
            f"  loaded {total} ignore rule(s) from {os.path.basename(path)} "
            f"({len(rules.words)} words, {len(rules.links)} links, "
            f"{len(rules.link_prefixes)} prefixes, {len(rules.link_hosts)} hosts, "
            f"{len(rules.page_patterns)} page patterns)"
        )
    return rules
