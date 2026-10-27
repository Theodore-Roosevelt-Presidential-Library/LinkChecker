"""Patch LinkChecker: recognise sites that block automated link checks.

Run from the LinkChecker repo root. Idempotent.
"""
import re

def sub(path, old, new, count=1):
    s = open(path).read()
    if new in s:
        return
    assert old in s, f"{path}: anchor not found:\n{old}"
    s = s.replace(old, new, count)
    open(path, "w").write(s)

# ---------------------------------------------------------------- links.py
p = "checker/links.py"
sub(p, """    final_url: str | None = None  # after redirects, if different
""", """    final_url: str | None = None  # after redirects, if different
    # Bot-protection service that answered instead of the real page, if any.
    shield: str | None = None
    # Set when the site refuses automated checks, so we can't tell if the
    # link works. These are kept out of Broken/Warnings.
    blocked: str | None = None
""")
sub(p, """    def category(self) -> str:
        if self.ok:
            return "ok"
""", """    def category(self) -> str:
        if self.ok:
            return "ok"
        if self.blocked:
            return "blocked"
""")
sub(p, """    def record(resp: requests.Response) -> None:
        result.status = resp.status_code
""", """    def record(resp: requests.Response) -> None:
        result.status = resp.status_code
        result.shield = shield_of(resp)
""")
# A few sites (e.g. Bluesky) answer HEAD with 404 but GET with 200.
sub(p, """        if resp.status_code in (403, 405, 406, 501) or resp.status_code >= 500:""",
"""        if (resp.status_code in (403, 405, 406, 501) or resp.status_code >= 500
                or (resp.status_code == 404 and not result.is_internal)):""")
sub(p, """def collect_links(""", '''# Response headers that mean a bot-protection service answered, not the site.
SHIELD_HEADERS = {
    "cf-mitigated": "Cloudflare",
    "x-datadome": "DataDome",
    "x-amzn-waf-action": "AWS WAF",
    "x-px-block": "PerimeterX",
}
BLOCK_STATUSES = {401, 403, 429}


def shield_of(resp: requests.Response) -> str | None:
    if resp.status_code < 400:
        return None
    for header, name in SHIELD_HEADERS.items():
        if header in resp.headers:
            return name
    if resp.headers.get("server", "").lower().startswith("datadome"):
        return "DataDome"
    return None


def mark_blocked(results: list[LinkResult]) -> None:
    """Flag outside links we can't check because the site blocks link checkers.

    We don't try to get around the block. A link counts as blocked when:
      * a bot-protection service (Cloudflare, DataDome, ...) answered, or
      * it returned 401/403/429 and the site's own homepage refuses us too.
    A 404 is never treated as blocked: the site answered, and the page is gone.
    """
    cands = [r for r in results
             if not r.ok and not r.is_internal
             and (r.shield or r.status in BLOCK_STATUSES)]
    if not cands:
        return
    hosts = sorted({urlparse(r.url).hostname for r in cands if not r.shield})
    homepage: dict[str, LinkResult] = {}
    if hosts:
        print(f"Checking {len(hosts)} site homepage(s) for bot blocking...")
        with ThreadPoolExecutor(max_workers=8) as pool:
            for host, res in zip(hosts, pool.map(
                    lambda h: _check_one(f"https://{h}/"), hosts)):
                homepage[host] = res
    for r in cands:
        if r.shield:
            r.blocked = f"{r.shield} bot protection"
            continue
        home = homepage.get(urlparse(r.url).hostname)
        if home and (home.shield or home.status in BLOCK_STATUSES):
            r.blocked = f"Site refuses automated checks (homepage returned {home.status})"
    n = sum(1 for r in cands if r.blocked)
    print(f"  {n} link(s) on {len({urlparse(r.url).hostname for r in cands if r.blocked})} "
          f"site(s) can't be checked automatically")


def collect_links(''')
sub(p, """    results = _recheck_transient(results)
""", """    results = _recheck_transient(results)
    mark_blocked(results)
""")
sub(p, """    warn = sum(1 for r in results if r.category == "warning")
    print(f"Link check complete: {broken} broken, {warn} warnings.")""",
"""    warn = sum(1 for r in results if r.category == "warning")
    blocked = sum(1 for r in results if r.category == "blocked")
    print(f"Link check complete: {broken} broken, {warn} warnings, "
          f"{blocked} on sites that block checkers.")""")

# ---------------------------------------------------------------- report.py
p = "checker/report.py"
sub(p, """    warnings = [r for r in link_results if r.category == "warning"]
""", """    warnings = [r for r in link_results if r.category == "warning"]
    blocked = [r for r in link_results if r.category == "blocked"]
""")
sub(p, """            "warning_links": len(warnings),
""", """            "warning_links": len(warnings),
            "blocked_links": len(blocked),
            "blocked_sites": len({urlparse(r.url).hostname for r in blocked}),
""")
sub(p, """        "warning_links": [_link_dict(r) for r in sorted(warnings, key=lambda x: x.url)],
""", """        "warning_links": [_link_dict(r) for r in sorted(warnings, key=lambda x: x.url)],
        "blocked_links": [_link_dict(r) for r in sorted(blocked, key=lambda x: x.url)],
""")
sub(p, """        "final_url": r.final_url,
""", """        "final_url": r.final_url,
        "blocked": r.blocked,
""")
sub(p, """from datetime import datetime, timezone
""", """from datetime import datetime, timezone
from urllib.parse import urlparse
""")
# show the reason on each item
sub(p, """  const redir = r.final_url ?""", """  if(r.blocked){ label = r.status!=null ? r.status : 'Blocked'; errBlock = `<div class="meta">${esc(r.blocked)}. Open it in a browser to confirm it still works.</div>`; }
  const redir = r.final_url ?""")
sub(p, """  warnings: {data:DATA.warning_links,   kind:'link', render:linkItem,
             empty:'<div class="empty">No link warnings.</div>'},
""", """  warnings: {data:DATA.warning_links,   kind:'link', render:linkItem,
             empty:'<div class="empty">No link warnings.</div>'},
  blocked:  {data:DATA.blocked_links||[], kind:'link', render:linkItem,
             empty:'<div class="empty">No sites blocked the checker.</div>'},
""")
sub(p, """            tab("unknown", "Unknown words", s["spelling_unknown_words"], "amber"),
""", """            tab("unknown", "Unknown words", s["spelling_unknown_words"], "amber"),
            tab("blocked", "Blocked sites", s.get("blocked_links", 0), ""),
""")
sub(p, """        "ignored": "Items you've hidden""", """        "blocked": "Outside sites that refuse automated link checkers (news sites, the Library of Congress and others use bot protection). The checker can't tell whether these links work, so they are kept out of Broken and Warnings. Spot-check them in a browser now and then.",
        "ignored": "Items you've hidden""")
sub(p, """        for k in ["broken", "typos", "warnings", "unknown", "ignored"]""",
    """        for k in ["broken", "typos", "warnings", "unknown", "blocked", "ignored"]""")
print("patched")
