"""Spell-check the visible prose of each crawled page.

Approach (per the chosen "custom allow-list" strategy)
------------------------------------------------------
* Tokenize visible page text into candidate words.
* Discard things that are not ordinary prose words: numbers, acronyms,
  ALL-CAPS tokens, camelCase, URLs/emails, hyphen/possessive fragments, and
  anything in the project allow-list (custom_words.txt) or standard dictionary.
* What remains is "unknown". We split unknown words into two buckets:
    - "likely typos": the dictionary has a close, higher-frequency correction
      (these are the high-signal items worth fixing).
    - "unknown words": no obvious correction — usually proper nouns or jargon
      that should be added to the allow-list.
* Track which pages each flagged word appears on so editors can find them.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field

from spellchecker import SpellChecker

from . import config
from .crawl import Page

# A "word": letters with optional internal apostrophes/hyphens.
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*[A-Za-z]|[A-Za-z]")

# Tokens to ignore outright.
_HAS_DIGIT = re.compile(r"\d")
_CAMEL = re.compile(r"[a-z][A-Z]")


@dataclass
class SpellIssue:
    word: str
    suggestion: str | None
    count: int = 0
    pages: list[tuple[str, str]] = field(default_factory=list)  # (url, title)

    @property
    def likely_typo(self) -> bool:
        return bool(self.suggestion) and self.suggestion.lower() != self.word.lower()


def load_custom_words() -> set[str]:
    words: set[str] = set()
    path = config.CUSTOM_WORDS_FILE
    if not os.path.isabs(path):
        # resolve relative to repo root (parent of this package)
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo_root, path)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                words.add(line.lower())
        print(f"  loaded {len(words)} custom allow-list words from {os.path.basename(path)}")
    return words


def _strip_possessive(word: str) -> str:
    return re.sub(r"[’']s$", "", word)


def _is_ignorable(token: str) -> bool:
    if len(token) < config.MIN_WORD_LEN:
        return True
    if _HAS_DIGIT.search(token):
        return True
    if token.isupper():           # acronym, e.g. NARA, FAQ
        return True
    if _CAMEL.search(token):      # camelCase / mixedCase identifiers
        return True
    if token != token.lower() and token != token.capitalize():
        # weird mixed casing that isn't simple Title Case
        return True
    return False


def check_spelling(pages: dict[str, Page]) -> list[SpellIssue]:
    if not config.ENABLE_SPELLCHECK:
        print("Spell-check disabled.")
        return []

    print("Spell-checking page text...")
    spell = SpellChecker(distance=1)  # distance=1 keeps suggestions conservative
    custom = load_custom_words()
    if custom:
        spell.word_frequency.load_words(custom)

    # word -> {"count": int, "pages": {(url, title)}}
    agg: dict[str, dict] = defaultdict(lambda: {"count": 0, "pages": set()})

    for url, page in pages.items():
        if not page.text:
            continue
        title = page.title or url
        # Candidate words: lowercase for the unknown-check, but keep originals
        # so we can ignore acronyms / camelCase.
        candidates: list[str] = []
        for raw in WORD_RE.findall(page.text):
            token = _strip_possessive(raw)
            if "-" in token:
                # Check hyphen parts individually; skip if any part is short.
                parts = [p for p in token.split("-") if p]
                for p in parts:
                    if not _is_ignorable(p):
                        candidates.append(p)
                continue
            if _is_ignorable(token):
                continue
            candidates.append(token)

        if not candidates:
            continue

        lowered = [c.lower() for c in candidates]
        unknown = spell.unknown(lowered)
        for w in unknown:
            if w in custom:
                continue
            agg[w]["count"] += lowered.count(w)
            agg[w]["pages"].add((url, title))

    issues: list[SpellIssue] = []
    for word, data in agg.items():
        correction = spell.correction(word)
        suggestion = correction if correction and correction != word else None
        issues.append(
            SpellIssue(
                word=word,
                suggestion=suggestion,
                count=data["count"],
                pages=sorted(data["pages"]),
            )
        )

    # Likely typos first (have a suggested correction), then by frequency.
    issues.sort(key=lambda i: (not i.likely_typo, -i.count, i.word))
    typos = sum(1 for i in issues if i.likely_typo)
    print(f"Spell-check complete: {len(issues)} flagged words ({typos} likely typos).")
    return issues
