"""Spell-check the visible prose of each crawled page.

Precision-first approach (per the chosen "custom allow-list" strategy)
----------------------------------------------------------------------
False positives are the enemy here, so we are aggressive about *not* flagging
things that aren't ordinary lower-case English prose:

* Pages whose URL matches SPELLCHECK_EXCLUDE_PATTERNS (video/playlist pages)
  are skipped entirely — YouTube titles/descriptions are pure noise.
* We spell-check ``page.prose_text`` (nav/header/footer/link text already
  stripped during crawl), not the full page text.
* URLs, emails, and @handles are removed before tokenizing.
* Curly apostrophes are normalized so "wasn’t" matches "wasn't".
* By default only **all-lower-case** tokens are considered. Title-case and
  ALL-CAPS tokens are treated as proper nouns / acronyms and skipped — this
  removes the bulk of name-based false positives.
* Numbers, camelCase, allow-list words, and dictionary words are dropped.

Remaining unknowns are split into "likely typos" (a close correction exists)
and "unknown words" (probably names/jargon to add to the allow-list).
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field

from spellchecker import SpellChecker

from . import config
from .crawl import Page

# Remove URLs, emails and @handles before tokenizing.
_URL_RE = re.compile(r"https?://\S+|www\.\S+|\S+@\S+\.\S+|[@#]\w+", re.IGNORECASE)
# A "word": letters with optional internal apostrophes/hyphens.
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*[A-Za-z]|[A-Za-z]")
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


def _should_skip_page(url: str) -> bool:
    low = url.lower()
    return any(pat.lower() in low for pat in config.SPELLCHECK_EXCLUDE_PATTERNS)


def _normalize(text: str) -> str:
    # normalize curly punctuation, then strip URLs/emails/handles
    text = text.replace("’", "'").replace("‘", "'")
    return _URL_RE.sub(" ", text)


def _strip_possessive(word: str) -> str:
    return re.sub(r"'s$", "", word)


def _is_ignorable(token: str) -> bool:
    """True if the token should never be spell-checked."""
    if len(token) < config.MIN_WORD_LEN:
        return True
    if _HAS_DIGIT.search(token):
        return True
    if "'" in token and config.MIN_WORD_LEN > 0 and not token.replace("'", "").isalpha():
        return True
    if _CAMEL.search(token):           # camelCase / mixedCase identifiers
        return True
    if config.SPELLCHECK_LOWERCASE_ONLY:
        # Only genuine lower-case prose words are candidates.
        if token != token.lower():
            return True
    else:
        if token.isupper():            # acronym
            return True
        if token != token.lower() and token != token.capitalize():
            return True
    return False


def _candidate_words(text: str) -> list[str]:
    out: list[str] = []
    for raw in WORD_RE.findall(text):
        token = _strip_possessive(raw)
        if not token:
            continue
        if "-" in token:
            for part in token.split("-"):
                if part and not _is_ignorable(part):
                    out.append(part)
            continue
        if _is_ignorable(token):
            continue
        out.append(token)
    return out


def check_spelling(pages: dict[str, Page]) -> list[SpellIssue]:
    if not config.ENABLE_SPELLCHECK:
        print("Spell-check disabled.")
        return []

    print("Spell-checking page text...")
    spell = SpellChecker(distance=1)  # distance=1 keeps suggestions conservative
    custom = load_custom_words()
    if custom:
        spell.word_frequency.load_words(custom)

    agg: dict[str, dict] = defaultdict(lambda: {"count": 0, "pages": set()})
    skipped = 0

    for url, page in pages.items():
        source = page.prose_text or page.text
        if not source:
            continue
        if _should_skip_page(url):
            skipped += 1
            continue
        title = page.title or url
        candidates = _candidate_words(_normalize(source))
        if not candidates:
            continue
        lowered = [c.lower() for c in candidates]
        for w in spell.unknown(lowered):
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

    issues.sort(key=lambda i: (not i.likely_typo, -i.count, i.word))
    typos = sum(1 for i in issues if i.likely_typo)
    print(
        f"Spell-check complete: {len(issues)} flagged words "
        f"({typos} likely typos); skipped {skipped} excluded page(s)."
    )
    return issues
