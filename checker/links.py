"""Validate every unique link discovered during the crawl.

We try a HEAD request first (cheap), and fall back to a ranged GET when HEAD is
not supported (some servers return 405/501 for HEAD). Results are cached per
URL so a link referenced from 50 pages is only checked once.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

from . import config
from .crawl import Link, Page, is_internal
from .http_util import get_session


@dataclass
class LinkResult:
    url: str
    status: int | None = None
    ok: bool = False
    warn: bool = False          # reachable but suspicious (403/429/etc.)
    is_internal: bool = False
    error: str | None = None
    final_url: str | None = None  # after redirects, if different
    # Bot-protection service that answered instead of the real page, if any.
    shield: str | None = None
    # Set when the site refuses automated checks, so we can't tell if the
    # link works. These are kept out of Broken/Warnings.
    blocked: str | None = None
    # Pages that reference this link, with the anchor text used there.
    sources: list[tuple[str, str]] = field(default_factory=list)

    @property
    def category(self) -> str:
        if self.ok:
            return "ok"
        if self.blocked:
            return "blocked"
        if self.warn:
            return "warning"
        return "broken"


def _check_one(url: str) -> LinkResult:
    result = LinkResult(url=url, is_internal=is_internal(url))
    session = get_session()

    def record(resp: requests.Response) -> None:
        result.status = resp.status_code
        result.shield = shield_of(resp)
        final = str(resp.url)
        if final and final != url:
            result.final_url = final
        if resp.status_code in config.WARN_STATUSES:
            result.warn = True
            result.ok = False
        elif resp.status_code >= config.BROKEN_THRESHOLD:
            result.ok = False
        else:
            result.ok = True

    try:
        resp = session.head(
            url, timeout=config.REQUEST_TIMEOUT, allow_redirects=True
        )
        # Many servers mishandle HEAD -> retry with GET.
        if (resp.status_code in (403, 405, 406, 501) or resp.status_code >= 500
                or (resp.status_code == 404 and not result.is_internal)):
            resp = session.get(
                url,
                timeout=config.REQUEST_TIMEOUT,
                allow_redirects=True,
                stream=True,
                headers={"Range": "bytes=0-2047"},
            )
            resp.close()
        record(resp)
    except requests.RequestException as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.ok = False
    return result


# Response headers that mean a bot-protection service answered, not the site.
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


def collect_links(pages: dict[str, Page]) -> dict[str, list[tuple[str, str]]]:
    """Map each unique link URL -> list of (source_page_url, anchor_text)."""
    index: dict[str, list[tuple[str, str]]] = {}
    for page_url, page in pages.items():
        for link in page.links:
            scheme = urlparse(link.url).scheme.lower()
            if scheme not in ("http", "https"):
                continue
            index.setdefault(link.url, []).append((page_url, link.text))
    return index


def validate_links(pages: dict[str, Page]) -> list[LinkResult]:
    index = collect_links(pages)
    print(f"Validating {len(index)} unique links...")

    results: list[LinkResult] = []
    pool = ThreadPoolExecutor(max_workers=config.LINK_WORKERS)
    futures = {pool.submit(_check_one, url): url for url in index}
    done = 0
    try:
        for fut in as_completed(futures, timeout=config.LINK_PHASE_MINUTES * 60):
            res = fut.result()
            res.sources = sorted(set(index.get(res.url, [])))
            results.append(res)
            done += 1
            if done % 100 == 0 or done == len(index):
                print(f"  checked {done}/{len(index)} links")
    except FuturesTimeout:
        # Something is stuck. Report what's left instead of hanging the run.
        for fut, url in futures.items():
            if not fut.done():
                results.append(LinkResult(
                    url=url, is_internal=is_internal(url), warn=True,
                    error=f"Not checked: link phase hit its {config.LINK_PHASE_MINUTES}-minute limit",
                    sources=sorted(set(index.get(url, []))),
                ))
        print(f"  time limit reached; {len(index) - done} link(s) left unchecked")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    results = _recheck_transient(results)
    mark_blocked(results)

    broken = sum(1 for r in results if r.category == "broken")
    warn = sum(1 for r in results if r.category == "warning")
    blocked = sum(1 for r in results if r.category == "blocked")
    print(f"Link check complete: {broken} broken, {warn} warnings, "
          f"{blocked} on sites that block checkers.")
    return results


def _is_transient(r: LinkResult) -> bool:
    """Failures that are often a blip: connection errors, timeouts, 5xx, 429."""
    if r.ok:
        return False
    if r.status is None:
        return True  # ConnectionError / Timeout / SSLError
    return r.status >= 500 or r.status == 429


def _recheck_transient(results: list[LinkResult]) -> list[LinkResult]:
    """Re-test transient failures once more, slowly, before reporting them.

    A host that was down (or rate-limiting us) for a minute during the fast
    parallel pass otherwise shows up as dozens of "broken" links. This pass
    waits, then re-checks those URLs one host at a time with a polite pause.
    """
    todo = [r for r in results if _is_transient(r)]
    if not todo:
        return results
    print(f"Re-checking {len(todo)} transient failure(s) after "
          f"{config.RECHECK_DELAY:.0f}s pause...")
    time.sleep(config.RECHECK_DELAY)
    todo.sort(key=lambda r: urlparse(r.url).hostname or "")
    fixed = 0
    last_host = None
    for r in todo:
        host = urlparse(r.url).hostname
        if host == last_host:
            time.sleep(config.RECHECK_HOST_PAUSE)
        last_host = host
        again = _check_one(r.url)
        if again.ok or (again.status is not None and not _is_transient(again)):
            # Take the newer, more definitive answer.
            r.status, r.ok, r.warn = again.status, again.ok, again.warn
            r.error, r.final_url = again.error, again.final_url
            if again.ok:
                fixed += 1
    print(f"  {fixed} recovered on re-check; {len(todo) - fixed} still failing.")
    return results
