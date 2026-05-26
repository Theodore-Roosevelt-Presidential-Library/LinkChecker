"""Render the results into a self-contained HTML dashboard + JSON dump.

The HTML page embeds the full results as JSON and renders the tables in the
browser, which keeps the Python simple and makes live search / tab switching /
ignore handling trivial. The page has no external dependencies.

Ignoring items
--------------
* Permanent (everyone): items listed in ignore.txt are filtered out *before*
  this module runs, so they never reach the page.
* Browser-local (you): every item has an "Ignore" button that hides it via
  localStorage and remembers the choice across weekly runs. The "Ignored" tab
  lists those, lets you restore them, and exports ready-to-paste ignore.txt
  lines plus a deep link to edit ignore.txt on GitHub (to make them permanent).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from . import config
from .links import LinkResult
from .spell import SpellIssue


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
        "broken_links": [_link_dict(r) for r in sorted(broken, key=lambda x: (not x.is_internal, x.url))],
        "warning_links": [_link_dict(r) for r in sorted(warnings, key=lambda x: x.url)],
        "spelling_typos": [_spell_dict(i) for i in typos],
        "spelling_unknown": [_spell_dict(i) for i in unknown],
    }


def _link_dict(r: LinkResult) -> dict:
    return {
        "url": r.url,
        "status": r.status,
        "error": r.error,
        "internal": r.is_internal,
        "final_url": r.final_url,
        "sources": [{"page": p, "text": t} for p, t in r.sources],
    }


def _spell_dict(i: SpellIssue) -> dict:
    return {
        "word": i.word,
        "suggestion": i.suggestion,
        "count": i.count,
        "pages": [{"url": u, "title": t} for u, t in i.pages],
    }


# --------------------------------------------------------------------------- #
# Static front-end
# --------------------------------------------------------------------------- #

_CSS = """
*{box-sizing:border-box}
:root{
  --bg:#eef1f4; --panel:#ffffff; --ink:#1a2230; --muted:#6b7685; --line:#e3e8ee;
  --brand:#0b3d2e; --brand2:#14694f; --red:#d12f2f; --redbg:#fdecec;
  --amber:#b6791a; --amberbg:#fdf4e3; --green:#1d7a45; --greenbg:#e9f6ee;
  --blue:#1f5fd6; --chip:#eef2f7;
}
html,body{margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,
Arial,sans-serif;background:var(--bg);color:var(--ink);line-height:1.55;
-webkit-font-smoothing:antialiased}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px}
header{background:linear-gradient(135deg,var(--brand),var(--brand2));color:#fff}
header .wrap{padding:30px 20px 26px}
header h1{margin:0;font-size:23px;letter-spacing:.2px}
header .sub{margin-top:6px;opacity:.85;font-size:13.5px}
.headline{margin:18px 0 0;font-size:15.5px;font-weight:600}
.headline.ok{color:#bdf0d3}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:14px;margin:-26px 0 4px;position:relative;z-index:2}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;
padding:16px 14px;text-align:center;box-shadow:0 1px 3px rgba(20,30,50,.05)}
.card .n{font-size:30px;font-weight:750;line-height:1}
.card .l{font-size:11.5px;color:var(--muted);text-transform:uppercase;
letter-spacing:.06em;margin-top:7px;font-weight:600}
.card.bad .n{color:var(--red)} .card.warn .n{color:var(--amber)}
.card.good .n{color:var(--green)}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:26px 0 0;position:sticky;top:0;
background:var(--bg);padding:10px 0;z-index:5;border-bottom:1px solid var(--line)}
.tab{border:1px solid var(--line);background:var(--panel);border-radius:999px;
padding:8px 15px;font-size:14px;cursor:pointer;color:var(--ink);font-weight:600;
display:flex;align-items:center;gap:8px;transition:.12s}
.tab:hover{border-color:#c7d0db}
.tab.active{background:var(--brand);color:#fff;border-color:var(--brand)}
.tab .pill{font-size:12px;font-weight:700;background:var(--chip);color:var(--ink);
border-radius:999px;padding:1px 8px;min-width:20px;text-align:center}
.tab.active .pill{background:rgba(255,255,255,.22);color:#fff}
.tab .pill.red{background:var(--redbg);color:var(--red)}
.tab .pill.amber{background:var(--amberbg);color:var(--amber)}
.tab.active .pill.red,.tab.active .pill.amber{background:rgba(255,255,255,.22);color:#fff}
.toolbar{display:flex;align-items:center;gap:12px;margin:18px 0 12px;flex-wrap:wrap}
.search{flex:1;min-width:220px;position:relative}
.search input{width:100%;padding:11px 14px 11px 38px;border:1px solid var(--line);
border-radius:10px;font-size:14px;background:var(--panel)}
.search input:focus{outline:none;border-color:var(--brand2);
box-shadow:0 0 0 3px rgba(20,105,79,.12)}
.search svg{position:absolute;left:12px;top:11px;opacity:.45}
.note{font-size:13px;color:var(--muted);margin:0 0 14px}
.panel{display:none} .panel.active{display:block;padding-bottom:60px}
.item{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:14px 16px;margin-bottom:10px;display:flex;gap:12px;align-items:flex-start}
.item-main{flex:1;min-width:0}
.item .row1{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.tag{font-size:11px;font-weight:700;padding:2px 9px;border-radius:999px;
white-space:nowrap}
.tag.red{background:var(--redbg);color:var(--red)}
.tag.amber{background:var(--amberbg);color:var(--amber)}
.tag.gray{background:var(--chip);color:var(--muted)}
.urlcode{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;
word-break:break-all;color:var(--ink)}
.urlcode a{color:var(--blue);text-decoration:none}
.urlcode a:hover{text-decoration:underline}
.word{font-size:17px;font-weight:700}
.arrow{color:var(--muted)} .sugg{color:var(--green);font-weight:700}
.meta{font-size:12.5px;color:var(--muted);margin-top:2px}
.errmsg{font-size:12.5px;color:var(--red);margin-top:5px;
font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
word-break:break-word;overflow-wrap:anywhere;line-height:1.45}
.tag{max-width:100%;overflow-wrap:anywhere}
.sources{margin-top:9px;border-top:1px dashed var(--line);padding-top:9px}
.sources summary{cursor:pointer;font-size:13px;color:var(--brand2);font-weight:600;
list-style:none}
.sources summary::-webkit-details-marker{display:none}
.sources summary::before{content:"\\25b8 ";color:var(--muted)}
.sources[open] summary::before{content:"\\25be "}
.srclist{margin:8px 0 2px;padding:0;list-style:none}
.srclist li{padding:3px 0;font-size:13px}
.srclist a{color:var(--blue);text-decoration:none;word-break:break-all}
.srclist a:hover{text-decoration:underline}
.btn{flex:none;border:1px solid var(--line);background:var(--panel);
border-radius:8px;padding:6px 11px;font-size:12.5px;font-weight:600;cursor:pointer;
color:var(--muted);white-space:nowrap;transition:.12s}
.btn:hover{border-color:#c7d0db;color:var(--ink);background:#f8fafc}
.btn.restore{color:var(--brand2)}
.empty{background:var(--panel);border:1px dashed var(--line);border-radius:12px;
padding:40px 20px;text-align:center;color:var(--muted)}
.empty.good{color:var(--green);border-color:#bfe6cd;background:var(--greenbg)}
.hidden{display:none!important}
.permabox{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:16px;margin-bottom:14px}
.permabox h3{margin:0 0 6px;font-size:14.5px}
.permabox p{margin:0 0 10px;font-size:13px;color:var(--muted)}
.permabox textarea{width:100%;min-height:84px;font-family:ui-monospace,Menlo,
monospace;font-size:12.5px;border:1px solid var(--line);border-radius:8px;
padding:9px;resize:vertical;background:#fbfcfd;color:var(--ink)}
.permabox .actions{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.permabox a.gh{display:inline-flex;align-items:center;gap:6px;background:var(--brand);
color:#fff;border-radius:8px;padding:7px 13px;font-size:13px;font-weight:600;
text-decoration:none}
footer{color:var(--muted);font-size:12.5px;padding:24px 0 50px;text-align:center}
footer a{color:var(--blue)}
@media (max-width:560px){.card .n{font-size:24px}header h1{font-size:20px}}
"""

_JS = r"""
const DATA = JSON.parse(document.getElementById('payload').textContent);
const STORE_KEY = 'lc_ignored_v1';
const IGNORE_MARKER = '<!-- linkchecker-ignore -->';

function commitViaIssue(){
  const ig = loadIgnored();
  const entries = Object.values(ig);
  if(!entries.length) return;
  const lines = entries.map(v => (v.kind==='link'?'link: ':'word: ')+v.value).join('\n');
  const title = '[linkchecker] ignore request';
  const body = IGNORE_MARKER + '\n\nAdd these rules to ignore.txt (a bot will commit them, then close this issue):\n\n'
    + lines + '\n';
  const url = REPO_ISSUE_URL + '?title=' + encodeURIComponent(title)
    + '&labels=' + encodeURIComponent('ignore-request')
    + '&body=' + encodeURIComponent(body);
  window.open(url, '_blank', 'noopener');
}
const esc = s => (s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;',
  '>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function loadIgnored(){
  try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; }
  catch(e){ return {}; }
}
function saveIgnored(o){
  try { localStorage.setItem(STORE_KEY, JSON.stringify(o)); } catch(e){}
}
const keyOf = (kind, value) => kind + '::' + (kind === 'word' ? value.toLowerCase() : value);

function ignore(kind, value){
  const ig = loadIgnored();
  ig[keyOf(kind, value)] = {kind, value, at: Date.now()};
  saveIgnored(ig); renderAll();
}
function unignore(key){
  const ig = loadIgnored(); delete ig[key]; saveIgnored(ig); renderAll();
}

function sources(list, label){
  if(!list || !list.length) return '';
  const items = list.map(s => {
    const url = s.page || s.url; const t = s.title ? ' — '+esc(s.title) : '';
    return `<li><a href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a>${t}</li>`;
  }).join('');
  const n = list.length;
  return `<details class="sources"><summary>${label||'Found on'} ${n} page${n>1?'s':''}</summary>
    <ul class="srclist">${items}</ul></details>`;
}

function linkItem(r){
  let label, errBlock = '';
  if(r.error){
    const short = (r.error.split(/[:(]/)[0] || 'Error').trim().slice(0, 28);
    label = esc(short || 'Error');
    errBlock = `<div class="errmsg">${esc(r.error)}</div>`;
  } else {
    label = r.status!=null ? r.status : '—';
  }
  const tagcls = r.error ? 'red' : (r.status>=400 ? 'red' : 'amber');
  const scope = r.internal ? 'internal' : 'external';
  const search = (r.url+' '+(r.error||r.status||'')+' '+(r.sources||[]).map(s=>s.page).join(' ')).toLowerCase();
  const redir = r.final_url ? `<div class="meta">→ redirects to ${esc(r.final_url)}</div>` : '';
  return `<div class="item" data-s="${esc(search)}">
    <div class="item-main">
      <div class="row1">
        <span class="tag ${tagcls}">${label}</span>
        <span class="tag gray">${scope}</span>
        <span class="urlcode"><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.url)}</a></span>
      </div>${errBlock}${redir}${sources(r.sources)}
    </div>
    <button class="btn" data-ignore-kind="link" data-ignore-value="${esc(r.url)}">Ignore</button>
  </div>`;
}

function spellItem(i){
  const sugg = i.suggestion
    ? `<span class="arrow">→</span> <span class="sugg">${esc(i.suggestion)}</span>` : '';
  const search = (i.word+' '+(i.suggestion||'')+' '+(i.pages||[]).map(p=>p.url).join(' ')).toLowerCase();
  return `<div class="item" data-s="${esc(search)}">
    <div class="item-main">
      <div class="row1">
        <span class="word">${esc(i.word)}</span> ${sugg}
        <span class="tag gray">${i.count}×</span>
      </div>${sources(i.pages, 'Appears on')}
    </div>
    <button class="btn" data-ignore-kind="word" data-ignore-value="${esc(i.word)}">Ignore</button>
  </div>`;
}

const CATS = {
  broken:   {data:DATA.broken_links,    kind:'link', render:linkItem,
             empty:'<div class="empty good">No broken links found. 🎉</div>'},
  typos:    {data:DATA.spelling_typos,  kind:'word', render:spellItem,
             empty:'<div class="empty good">No likely typos found.</div>'},
  warnings: {data:DATA.warning_links,   kind:'link', render:linkItem,
             empty:'<div class="empty">No link warnings.</div>'},
  unknown:  {data:DATA.spelling_unknown,kind:'word', render:spellItem,
             empty:'<div class="empty">No unknown words.</div>'},
};
const valOf = (cat, item) => CATS[cat].kind === 'link' ? item.url : item.word;

function activeItems(cat){
  const ig = loadIgnored(); const k = CATS[cat].kind;
  return CATS[cat].data.filter(it => !ig[keyOf(k, valOf(cat, it))]);
}

function renderCategory(cat){
  const c = CATS[cat]; const el = document.getElementById('panel-'+cat);
  const items = activeItems(cat);
  el.innerHTML = items.length ? items.map(c.render).join('') : c.empty;
  const pill = document.querySelector('.tab[data-tab="'+cat+'"] .pill');
  if(pill) pill.textContent = items.length;
  const card = document.getElementById('card-'+cat);
  if(card) card.textContent = items.length;
}

function renderIgnored(){
  const ig = loadIgnored();
  const entries = Object.entries(ig).sort((a,b)=>(b[1].at||0)-(a[1].at||0));
  const el = document.getElementById('panel-ignored');
  const pill = document.querySelector('.tab[data-tab="ignored"] .pill');
  if(pill) pill.textContent = entries.length;

  if(!entries.length){
    el.innerHTML = '<div class="empty">Nothing ignored yet. Use the <strong>Ignore</strong> button on any item to hide it here — it stays hidden in this browser across weekly runs.</div>';
    return;
  }
  const lines = entries.map(([k,v]) => (v.kind==='link'?'link: ':'word: ')+v.value).join('\n');
  const perma = `<div class="permabox">
    <h3>Make these permanent (shared with everyone)</h3>
    <p>Browser ignores live only on this device. To suppress these for everyone on every run, commit them to <code>ignore.txt</code>. The button below opens a pre-filled GitHub issue — just submit it, and a bot appends the rules, commits to main, and closes the issue. The report refreshes shortly after.</p>
    <textarea id="permatext" readonly>${esc(lines)}</textarea>
    <div class="actions">
      <button class="gh" id="commitbtn" style="border:none;cursor:pointer">Commit to ignore.txt ↗</button>
      <button class="btn" id="copybtn">Copy lines</button>
      <a class="gh" href="${REPO_EDIT_URL}" target="_blank" rel="noopener" style="background:var(--brand2)">Edit manually on GitHub ↗</a>
    </div>
  </div>`;
  const rows = entries.map(([k,v]) => `<div class="item">
      <div class="item-main"><div class="row1">
        <span class="tag gray">${v.kind}</span>
        <span class="${v.kind==='word'?'word':'urlcode'}">${esc(v.value)}</span>
      </div></div>
      <button class="btn restore" data-restore-key="${esc(k)}">Restore</button>
    </div>`).join('');
  el.innerHTML = perma + rows;

  const cb = document.getElementById('copybtn');
  if(cb) cb.addEventListener('click', () => {
    const ta = document.getElementById('permatext');
    ta.select();
    navigator.clipboard ? navigator.clipboard.writeText(ta.value) : document.execCommand('copy');
    cb.textContent = 'Copied ✓'; setTimeout(()=>cb.textContent='Copy lines', 1500);
  });
  const commit = document.getElementById('commitbtn');
  if(commit) commit.addEventListener('click', commitViaIssue);
}

function renderAll(){
  Object.keys(CATS).forEach(renderCategory);
  renderIgnored();
  filter();
}

function activate(key){
  document.querySelectorAll('.tab').forEach(t =>
    t.classList.toggle('active', t.dataset.tab===key));
  document.querySelectorAll('.panel').forEach(pl =>
    pl.classList.toggle('active', pl.id==='panel-'+key));
  const note = document.getElementById('note');
  if(note) note.textContent = NOTES[key] || '';
  filter();
}

function filter(){
  const q = document.getElementById('q').value.trim().toLowerCase();
  const panel = document.querySelector('.panel.active');
  if(!panel) return;
  let shown = 0, total = 0;
  panel.querySelectorAll('.item').forEach(it => {
    if(!it.dataset.s) return;       // skip the permabox-less rows w/o search data
    total++;
    const match = !q || it.dataset.s.includes(q);
    it.classList.toggle('hidden', !match); if(match) shown++;
  });
  const c = document.getElementById('count');
  if(c) c.textContent = total ? (q ? `${shown} of ${total} shown` : `${total} item${total!==1?'s':''}`) : '';
}

document.addEventListener('click', e => {
  const ib = e.target.closest('[data-ignore-kind]');
  if(ib){ ignore(ib.dataset.ignoreKind, ib.dataset.ignoreValue); return; }
  const rb = e.target.closest('[data-restore-key]');
  if(rb){ unignore(rb.dataset.restoreKey); return; }
});
document.querySelectorAll('.tab').forEach(t =>
  t.addEventListener('click', () => activate(t.dataset.tab)));
document.getElementById('q').addEventListener('input', filter);

renderAll();
const order = ['broken','typos','warnings','unknown'];
activate(order.find(k => activeItems(k).length) || 'broken');
"""


def render_html(payload: dict) -> str:
    s = payload["summary"]
    gen = payload["generated_at"]
    total = s["broken_links"] + s["spelling_likely_typos"]
    if total == 0:
        headline = '<p class="headline ok">All clear — no broken links or likely typos found.</p>'
    else:
        headline = (
            f'<p class="headline">{s["broken_links"]} broken link(s) and '
            f'{s["spelling_likely_typos"]} likely typo(s) need attention.</p>'
        )

    def card(card_id: str | None, n: int, label: str, cls: str = "") -> str:
        idattr = f' id="{card_id}"' if card_id else ""
        return (
            f'<div class="card {cls}"><div class="n"{idattr}>{n}</div>'
            f'<div class="l">{label}</div></div>'
        )

    cards = "".join(
        [
            card(None, s["pages_crawled"], "Pages crawled"),
            card(None, s["links_checked"], "Links checked"),
            card("card-broken", s["broken_links"], "Broken links", "bad" if s["broken_links"] else "good"),
            card("card-warnings", s["warning_links"], "Warnings", "warn" if s["warning_links"] else ""),
            card("card-typos", s["spelling_likely_typos"], "Likely typos", "bad" if s["spelling_likely_typos"] else "good"),
            card("card-unknown", s["spelling_unknown_words"], "Unknown words"),
        ]
    )

    def tab(key: str, label: str, count: int, cls: str) -> str:
        pill_cls = cls if count else ""
        return (
            f'<button class="tab" data-tab="{key}">{label}'
            f'<span class="pill {pill_cls}">{count}</span></button>'
        )

    tabs = "".join(
        [
            tab("broken", "Broken links", s["broken_links"], "red"),
            tab("typos", "Likely typos", s["spelling_likely_typos"], "red"),
            tab("warnings", "Warnings", s["warning_links"], "amber"),
            tab("unknown", "Unknown words", s["spelling_unknown_words"], "amber"),
            tab("ignored", "Ignored", 0, ""),
        ]
    )

    notes = {
        "broken": "HTTP 4xx/5xx responses or connection failures. Each item lists the page(s) where the link appears so it can be fixed at the source. Use Ignore to hide false positives.",
        "typos": "Lower-case words not in the dictionary that have a close, common correction. Highest-confidence items to fix. Use Ignore to dismiss a word.",
        "warnings": "Reachable but returned 401/403/429 — usually bot-protection or rate limiting (e.g. social media, donation forms) rather than a true break.",
        "unknown": "Not in the dictionary with no obvious correction — usually names, places, or jargon. Ignore or add genuine terms to custom_words.txt.",
        "ignored": "Items you've hidden in this browser. Restore any of them, or copy the lines into ignore.txt to suppress them permanently for everyone.",
    }
    panels = "".join(
        f'<div class="panel" id="panel-{k}"></div>'
        for k in ["broken", "typos", "warnings", "unknown", "ignored"]
    )

    repo_edit_url = (
        f"https://github.com/{config.REPO_SLUG}/edit/{config.REPO_BRANCH}/{config.IGNORE_FILE}"
    )
    repo_issue_new_url = f"https://github.com/{config.REPO_SLUG}/issues/new"

    payload_json = json.dumps(payload, ensure_ascii=False)
    note_json = json.dumps(notes)

    search_svg = (
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/>'
        '<line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>'
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>trlibrary.com — Link &amp; Spelling Report</title>
<style>{_CSS}</style></head><body>
<header><div class="wrap">
  <h1>trlibrary.com — Link &amp; Spelling Report</h1>
  <div class="sub">Generated {gen} · scope: *.{payload['root_domain']}</div>
  {headline}
</div></header>
<div class="wrap">
  <div class="cards">{cards}</div>
  <div class="tabs">{tabs}</div>
  <div class="toolbar">
    <div class="search">{search_svg}
      <input id="q" type="search" placeholder="Filter by URL, word, or page…" autocomplete="off">
    </div>
    <span id="count" class="meta"></span>
  </div>
  <p class="note" id="note"></p>
  {panels}
  <footer>
    Produced by the LinkChecker GitHub Action ·
    <a href="{config.DATA_FILENAME}">raw data ({config.DATA_FILENAME})</a>
  </footer>
</div>
<script type="application/json" id="payload">{payload_json}</script>
<script>
const NOTES = {note_json};
const REPO_EDIT_URL = {json.dumps(repo_edit_url)};
const REPO_ISSUE_URL = {json.dumps(repo_issue_new_url)};
{_JS}
</script>
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
        fh.write(render_html(payload))

    open(os.path.join(output_dir, ".nojekyll"), "w").close()
    print(f"Report written to {html_path}")
    return html_path, json_path
