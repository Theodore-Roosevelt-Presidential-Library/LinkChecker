# LinkChecker

Automated **broken-link and spelling checker** for the Theodore Roosevelt
Presidential Library website (`*.trlibrary.com`).

Every week it crawls the whole site, validates every link, scans page text for
spelling errors, and publishes an interactive report to **GitHub Pages** with
links back to the exact pages that need correction.

## What it does

1. **Crawls** the site starting from `sitemap.xml` and the homepage, following
   internal links across every `*.trlibrary.com` subdomain.
2. **Validates every link** (internal and external) with a HEAD request,
   falling back to GET. Anything returning a 4xx/5xx or a connection error is
   flagged as **broken**; 401/403/429 responses are reported as **warnings**
   (usually bot-protection rather than a real break).
3. **Spell-checks** the visible text of each page against a standard English
   dictionary plus a project allow-list (`custom_words.txt`). Results are split
   into **likely typos** (a close correction exists) and **unknown words**
   (probably names/jargon to add to the allow-list).
4. **Publishes a report** (`public/index.html`) showing every issue grouped by
   the page it appears on, with clickable links back to those pages.

## Where the report lives

Once GitHub Pages is enabled (see below), the latest report is at:

```
https://theodore-roosevelt-presidential-library.github.io/LinkChecker/
```

The raw machine-readable data is alongside it at `results.json`.

## Schedule

The scan runs automatically **every Sunday night** (Monday 04:00 UTC) via the
`.github/workflows/link-check.yml` GitHub Action. You can also trigger it
anytime from the repo's **Actions → Weekly link & spelling check → Run
workflow** button.

## One-time setup

This repo is ready to go; the only manual step is enabling Pages:

1. In GitHub, open **Settings → Pages**.
2. Under **Build and deployment → Source**, choose **GitHub Actions**.

That's it. The next workflow run will publish the report.

## Reducing spelling false positives

Names, places, and jargon (e.g. *Sagamore*, *Medora*, donor surnames, video
titles) will show up under **unknown words** the first time. To stop a word
being flagged, add it (one per line) to [`custom_words.txt`](custom_words.txt)
and commit — the change triggers a fresh run automatically.

## Running it locally

```bash
pip install -r requirements.txt

# Full run (writes the report to ./public/)
python run_check.py

# Quick smoke test on just 25 pages
MAX_PAGES=25 python run_check.py

# Skip the spell check
ENABLE_SPELLCHECK=0 python run_check.py
```

Then open `public/index.html` in a browser.

## Configuration

All settings are environment variables (defaults in
[`checker/config.py`](checker/config.py)):

| Variable | Default | Meaning |
|---|---|---|
| `MAX_PAGES` | `5000` | Cap on pages crawled. `0` = unlimited. |
| `CRAWL_WORKERS` | `12` | Parallel page fetchers. |
| `LINK_WORKERS` | `24` | Parallel link validators. |
| `REQUEST_TIMEOUT` | `20` | Per-request timeout (seconds). |
| `ENABLE_SPELLCHECK` | `1` | Set `0` to skip spell checking. |
| `ROOT_DOMAIN` | `trlibrary.com` | Domain treated as internal. |
| `SITEMAP_URLS` | `https://www.trlibrary.com/sitemap.xml` | Comma-separated sitemap seeds. |

## Project layout

```
checker/
  config.py     # all tunable settings
  crawl.py      # sitemap + BFS crawler, link/text extraction
  links.py      # link validation (HEAD/GET, threaded, cached)
  spell.py      # dictionary spell check + allow-list
  report.py     # HTML dashboard + JSON output
  http_util.py  # shared requests session
run_check.py    # entry point
custom_words.txt  # spelling allow-list (grow this over time)
.github/workflows/link-check.yml  # weekly scan + Pages deploy
```
