"""Central configuration for the trlibrary.com link & spelling checker.

Most settings can be overridden with environment variables so the GitHub
Action can tune behaviour without code changes.
"""
from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


# The site we crawl. Any host ending in ROOT_DOMAIN is treated as "internal"
# and will be crawled (this covers all *.trlibrary.com subdomains).
ROOT_DOMAIN = os.environ.get("ROOT_DOMAIN", "trlibrary.com").lower().strip()

# Where the crawl begins. The sitemap is the primary seed; the homepage is a
# fallback so we still work if the sitemap ever disappears.
START_URLS = [
    u.strip()
    for u in os.environ.get(
        "START_URLS",
        "https://www.trlibrary.com/",
    ).split(",")
    if u.strip()
]

SITEMAP_URLS = [
    u.strip()
    for u in os.environ.get(
        "SITEMAP_URLS",
        "https://www.trlibrary.com/sitemap.xml",
    ).split(",")
    if u.strip()
]

# Safety cap on how many internal pages we crawl. 0 means "no cap".
# The live site is ~700 pages, so 5000 gives generous headroom.
MAX_PAGES = _int("MAX_PAGES", 5000)

# Concurrency.
CRAWL_WORKERS = _int("CRAWL_WORKERS", 12)
LINK_WORKERS = _int("LINK_WORKERS", 24)

# Network behaviour.
REQUEST_TIMEOUT = _float("REQUEST_TIMEOUT", 20.0)
CRAWL_DELAY = _float("CRAWL_DELAY", 0.0)  # politeness pause between page fetches
MAX_RETRIES = _int("MAX_RETRIES", 2)

USER_AGENT = os.environ.get(
    "USER_AGENT",
    "TRL-LinkChecker/1.0 (+https://github.com/Theodore-Roosevelt-Presidential-Library/LinkChecker)",
)

# HTTP status codes we treat as "broken" when validating links.
# Anything >= 400 is flagged. 401/403 are often bot-protection, so they are
# reported in a separate "warning" bucket rather than hard failures.
BROKEN_THRESHOLD = 400
WARN_STATUSES = {401, 403, 429}

# URL schemes we skip when validating links (not real HTTP resources).
SKIP_SCHEMES = {"mailto", "tel", "javascript", "data", "ftp", "sms", "file"}

# Output locations (relative to repo root).
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "public")
DATA_FILENAME = "results.json"
HTML_FILENAME = "index.html"

# Repo slug + branch are used to build the "edit ignore.txt on GitHub" deep
# link shown in the report's Ignored panel. Override via env if the repo moves.
REPO_SLUG = os.environ.get(
    "REPO_SLUG", "Theodore-Roosevelt-Presidential-Library/LinkChecker"
)
REPO_BRANCH = os.environ.get("REPO_BRANCH", "main")

# Items listed in this file are suppressed from the report at generation time
# (for everyone). See ignore.txt for the format.
IGNORE_FILE = os.environ.get("IGNORE_FILE", "ignore.txt")

# Spell-check tuning.
ENABLE_SPELLCHECK = os.environ.get("ENABLE_SPELLCHECK", "1").strip() not in {"0", "false", "False", ""}
# Words shorter than this are ignored by the spell checker.
MIN_WORD_LEN = _int("MIN_WORD_LEN", 4)
CUSTOM_WORDS_FILE = os.environ.get("CUSTOM_WORDS_FILE", "custom_words.txt")

# Pages whose URL path matches any of these substrings are NOT spell-checked.
# Video pages embed YouTube titles/descriptions full of names and jargon that
# generate overwhelming false-positive noise. Links on these pages are still
# validated — we just skip the prose. (Links ARE still checked on every page.)
SPELLCHECK_EXCLUDE_PATTERNS = [
    p.strip()
    for p in os.environ.get(
        "SPELLCHECK_EXCLUDE_PATTERNS",
        "/video/,/videos/,/playlist,/watch",
    ).split(",")
    if p.strip()
]

# Only flag words that appear in genuine lower-case form. Title-case and
# ALL-CAPS tokens are treated as proper nouns / acronyms and skipped. This is
# the single biggest lever for cutting proper-name false positives. Set to 0
# to also check capitalized words (much noisier).
SPELLCHECK_LOWERCASE_ONLY = os.environ.get(
    "SPELLCHECK_LOWERCASE_ONLY", "1"
).strip() not in {"0", "false", "False", ""}
