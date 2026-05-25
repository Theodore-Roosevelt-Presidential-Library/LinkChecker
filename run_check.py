#!/usr/bin/env python3
"""Entry point: crawl trlibrary.com, validate links, spell-check, write report.

Usage:
    python run_check.py                 # full run, defaults from checker/config.py
    MAX_PAGES=25 python run_check.py     # quick smoke test on 25 pages
    ENABLE_SPELLCHECK=0 python run_check.py   # skip spell check

All tuning is via environment variables (see checker/config.py).
"""
from __future__ import annotations

import sys
import time

from checker import config
from checker.crawl import crawl
from checker.ignores import load_ignores
from checker.links import validate_links
from checker.report import write_report
from checker.spell import check_spelling


def main() -> int:
    start = time.time()
    print("=" * 60)
    print(f"trlibrary LinkChecker — scope *.{config.ROOT_DOMAIN}")
    print("=" * 60)

    pages = crawl()
    if not pages:
        print("ERROR: no pages were crawled. Aborting.", file=sys.stderr)
        return 1

    link_results = validate_links(pages)
    spell_issues = check_spelling(pages)

    # Apply the committed ignore list (suppresses items for everyone).
    print("Applying ignore rules...")
    rules = load_ignores()
    before_links, before_words = len(link_results), len(spell_issues)
    link_results = [r for r in link_results if not rules.link_ignored(r.url)]
    spell_issues = [i for i in spell_issues if not rules.word_ignored(i.word)]
    dropped = (before_links - len(link_results)) + (before_words - len(spell_issues))
    if dropped:
        print(f"  suppressed {dropped} item(s) via {config.IGNORE_FILE}")

    write_report(len(pages), link_results, spell_issues)

    broken = sum(1 for r in link_results if r.category == "broken")
    typos = sum(1 for i in spell_issues if i.likely_typo)
    elapsed = time.time() - start
    print("=" * 60)
    print(f"Done in {elapsed:.0f}s — {len(pages)} pages, "
          f"{broken} broken links, {typos} likely typos.")
    print("=" * 60)
    # Always exit 0 so the Pages deploy still runs even when issues are found.
    return 0


if __name__ == "__main__":
    sys.exit(main())
