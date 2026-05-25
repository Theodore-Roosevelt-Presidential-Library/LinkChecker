"""Render the results into a self-contained HTML dashboard + JSON dump."""
from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone

from . import config
from .links import LinkResult
from .spell import SpellIssue


def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def _status_label(r: LinkResult) -> str:
    if r.error:
        return _esc(r.error)
    if r.status is not None:
        return str(r.status)
    return "—"


def build_payload(
    pages_count: int,
    link_results: list[LinkResult],
    spell_issues: list[SpellIssue],
    generated_at: str,
) -> dict:
    broken = [r for r in link_results if r.category == "broken"]
    warnings = [r for r in link_results if r.category == "warning"]
    typos = [i for i in spell_issues if i.likely_typo]
    unknown = [i for i in spell_issues if not i.likely_typo]

    return {
        "generated_at": generated_at,
        "root_domain": config.ROOT_DOMAIN,
        "summary": {
            "pages_crawled": pages_count,
            "links_checked": len(link_results),
            "broken_links": len(broken),
            "warning_links": len(warnings),
            "spelling_likely_typos": len(typos),
            "spelling_unknown_words": len(unknown),
        },
        "broken_links": [
            {
                "url": r.url,
                "status": r.status,
                "error": r.error,
                "internal": r.is_internal,
                "final_url": r.final_url,
                "sources": [{"page": p, "text": t} for p, t in r.sources],
            }
            for r in sorted(broken, key=lambda x: (not x.is_internal, x.url))
        ],
        "warning_links": [
            {
                "url": r.url,
                "status": r.status,
                "internal": r.is_internal,
                "sources": [{"page": p, "text": t} for p, t in r.sources],
            }
            for r in sorted(warnings, key=lambda x: x.url)
        ],
        "spelling": [
            {
                "word": i.word,
                "suggestion": i.suggestion,
                "likely_typo": i.likely_typo,
                "count": i.count,
                "pages": [{"url": u, "title": t} for u, t in i.pages],
            }
            for i in spell_issues
        ],
    }


# --------------------------------------------------------------------------- #
# HTML rendering
# --------------------------------------------------------------------------- #

_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1f2933;--muted:#6b7280;--line:#e5e7eb;
--red:#c0392b;--redbg:#fdecea;--amber:#b7791f;--amberbg:#fef6e7;--green:#1e7e45;
--blue:#1d4ed8;--accent:#0b3d2e}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
Helvetica,Arial,sans-serif;background:var(--bg);color:var(--ink);line-height:1.5}
header{background:var(--accent);color:#fff;padding:28px 24px}
header h1{margin:0 0 4px;font-size:22px}
header p{margin:0;opacity:.85;font-size:14px}
main{max-width:1080px;margin:0 auto;padding:24px 16px 64px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:12px;margin:20px 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:16px;text-align:center}
.card .n{font-size:28px;font-weight:700}
.card .l{font-size:12px;color:var(--muted);text-transform:uppercase;
letter-spacing:.04em;margin-top:4px}
.card.bad .n{color:var(--red)} .card.warn .n{color:var(--amber)}
.card.ok .n{color:var(--green)}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;
margin-top:24px;overflow:hidden}
section>h2{margin:0;padding:14px 18px;border-bottom:1px solid var(--line);
font-size:16px;display:flex;align-items:center;gap:8px}
.badge{font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px}
.badge.red{background:var(--redbg);color:var(--red)}
.badge.amber{background:var(--amberbg);color:var(--amber)}
.badge.green{background:#e8f5ec;color:var(--green)}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:10px 14px;border-bottom:1px solid var(--line);
vertical-align:top}
th{background:#fafafa;font-size:12px;text-transform:uppercase;letter-spacing:.04em;
color:var(--muted)}
tr:last-child td{border-bottom:none}
code{background:#f3f4f6;padding:1px 5px;border-radius:4px;font-size:13px;
word-break:break-all}
a{color:var(--blue);text-decoration:none} a:hover{text-decoration:underline}
.status{font-weight:700} .status.broken{color:var(--red)}
.status.warning{color:var(--amber)}
.src{font-size:13px;color:var(--muted);margin-top:4px}
.src a{color:var(--blue)}
.sugg{color:var(--green);font-weight:600}
.empty{padding:28px;text-align:center;color:var(--muted)}
details summary{cursor:pointer;color:var(--muted);font-size:13px}
.note{font-size:13px;color:var(--muted);padding:10px 18px;background:#fafafa;
border-bottom:1px solid var(--line)}
footer{max-width:1080px;margin:0 auto;padding:0 16px 48px;color:var(--muted);
font-size:13px}
"""


def _render_sources(sources, limit=8) -> str:
    rows = []
    for item in sources[:limit]:
        page = item[0] if isinstance(item, tuple) else item
        rows.append(f'<div class="src">↳ <a href="{_esc(page)}" target="_blank" rel="noopener">{_esc(page)}</a></div>')
    if len(sources) > limit:
        rows.append(f'<div class="src">…and {len(sources) - limit} more page(s)</div>')
    return "".join(rows)


def _broken_table(results: list[LinkResult]) -> str:
    if not results:
        return '<div class="empty">No broken links found. 🎉</div>'
    rows = []
    for r in sorted(results, key=lambda x: (not x.is_internal, x.url)):
        scope = "internal" if r.is_internal else "external"
        rows.append(
            f"<tr><td><span class='status broken'>{_status_label(r)}</span></td>"
            f"<td><code>{_esc(r.url)}</code><div class='src'>{scope} link</div></td>"
            f"<td>{_render_sources(r.sources)}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Status</th><th>Broken URL</th>"
        "<th>Found on page(s)</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _warning_table(results: list[LinkResult]) -> str:
    if not results:
        return '<div class="empty">No warnings.</div>'
    rows = []
    for r in sorted(results, key=lambda x: x.url):
        rows.append(
            f"<tr><td><span class='status warning'>{_status_label(r)}</span></td>"
            f"<td><code>{_esc(r.url)}</code></td>"
            f"<td>{_render_sources(r.sources, limit=5)}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Status</th><th>URL</th>"
        "<th>Found on page(s)</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _spell_table(issues: list[SpellIssue]) -> str:
    if not issues:
        return '<div class="empty">No flagged words.</div>'
    rows = []
    for i in issues:
        sugg = f"<span class='sugg'>{_esc(i.suggestion)}</span>" if i.suggestion else "<span style='color:#9ca3af'>—</span>"
        rows.append(
            f"<tr><td><strong>{_esc(i.word)}</strong></td>"
            f"<td>{sugg}</td>"
            f"<td>{i.count}</td>"
            f"<td>{_render_sources(i.pages, limit=6)}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Word</th><th>Suggested</th><th>Times</th>"
        "<th>Found on page(s)</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_html(payload: dict, link_results, spell_issues) -> str:
    s = payload["summary"]
    broken = [r for r in link_results if r.category == "broken"]
    warnings = [r for r in link_results if r.category == "warning"]
    typos = [i for i in spell_issues if i.likely_typo]
    unknown = [i for i in spell_issues if not i.likely_typo]

    gen = payload["generated_at"]
    total_issues = s["broken_links"] + s["spelling_likely_typos"]
    headline = (
        "All clear — no broken links or likely typos found."
        if total_issues == 0
        else f"{s['broken_links']} broken link(s) and {s['spelling_likely_typos']} likely typo(s) need attention."
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>trlibrary.com — Link &amp; Spelling Report</title>
<style>{_CSS}</style></head><body>
<header>
  <h1>trlibrary.com — Link &amp; Spelling Report</h1>
  <p>Generated {_esc(gen)} · scope: *.{_esc(payload['root_domain'])}</p>
</header>
<main>
  <p style="font-size:15px;margin:4px 0 0">{_esc(headline)}</p>
  <div class="cards">
    <div class="card"><div class="n">{s['pages_crawled']}</div><div class="l">Pages crawled</div></div>
    <div class="card"><div class="n">{s['links_checked']}</div><div class="l">Links checked</div></div>
    <div class="card {'bad' if s['broken_links'] else 'ok'}"><div class="n">{s['broken_links']}</div><div class="l">Broken links</div></div>
    <div class="card {'warn' if s['warning_links'] else ''}"><div class="n">{s['warning_links']}</div><div class="l">Link warnings</div></div>
    <div class="card {'bad' if s['spelling_likely_typos'] else 'ok'}"><div class="n">{s['spelling_likely_typos']}</div><div class="l">Likely typos</div></div>
    <div class="card"><div class="n">{s['spelling_unknown_words']}</div><div class="l">Unknown words</div></div>
  </div>

  <section>
    <h2>Broken links <span class="badge red">{s['broken_links']}</span></h2>
    <div class="note">HTTP 4xx/5xx responses or connection failures. Each row lists the page(s) where the link appears so it can be fixed at the source.</div>
    {_broken_table(broken)}
  </section>

  <section>
    <h2>Likely spelling errors <span class="badge red">{len(typos)}</span></h2>
    <div class="note">Words not in the dictionary that have a close, common correction. Highest-confidence items to fix.</div>
    {_spell_table(typos)}
  </section>

  <section>
    <h2>Link warnings <span class="badge amber">{s['warning_links']}</span></h2>
    <div class="note">Reachable but returned 401/403/429 — often bot-protection or rate limiting rather than a true break. Worth a manual glance.</div>
    {_warning_table(warnings)}
  </section>

  <section>
    <h2>Unknown words <span class="badge amber">{len(unknown)}</span></h2>
    <div class="note">Not in the dictionary and no obvious correction — usually names, places, or jargon. Genuine terms can be added to <code>custom_words.txt</code> to silence them next run.</div>
    <details><summary>Show {len(unknown)} unknown word(s)</summary>{_spell_table(unknown)}</details>
  </section>
</main>
<footer>
  <p>Produced by the LinkChecker GitHub Action · raw data: <a href="{config.DATA_FILENAME}">{config.DATA_FILENAME}</a></p>
</footer>
</body></html>"""


def write_report(
    pages_count: int,
    link_results: list[LinkResult],
    spell_issues: list[SpellIssue],
    output_dir: str | None = None,
) -> tuple[str, str]:
    output_dir = output_dir or config.OUTPUT_DIR
    if not os.path.isabs(output_dir):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(repo_root, output_dir)
    os.makedirs(output_dir, exist_ok=True)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = build_payload(pages_count, link_results, spell_issues, generated_at)

    json_path = os.path.join(output_dir, config.DATA_FILENAME)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    html_path = os.path.join(output_dir, config.HTML_FILENAME)
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(render_html(payload, link_results, spell_issues))

    # add a .nojekyll so GitHub Pages serves files verbatim
    open(os.path.join(output_dir, ".nojekyll"), "w").close()

    print(f"Report written to {html_path}")
    return html_path, json_path
