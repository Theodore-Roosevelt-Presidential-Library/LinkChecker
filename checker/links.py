"""Validate every unique link discovered during the crawl.

We try a HEAD request first (cheap), and fall back to a ranged GET when HEAD is
not supported (some servers return 405/501 for HEAD). Results are cached per
URL so a link referenced from 50 pages is only checked once.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
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
    # Pages that reference this link, with the anchor text used there.
    sources: list[tuple[str, str]] = field(default_factory=list)

    @property
    def category(self) -> str:
        if self.ok:
            return "ok"
        if self.warn:
            return "warning"
        return "broken"


def _check_one(url: str) -> LinkResult:
    result = LinkResult(url=url, is_internal=is_internal(url))
    session = get_session()

    def record(resp: requests.Response) -> None:
        result.status = resp.status_code
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
        if resp.status_code in (403, 405, 406, 501) or resp.status_code >= 500:
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
    with ThreadPoolExecutor(max_workers=config.LINK_WORKERS) as pool:
        futures = {pool.submit(_check_one, url): url for url in index}
        done = 0
        for fut in as_completed(futures):
            res = fut.result()
            res.sources = sorted(set(index.get(res.url, [])))
            results.append(res)
            done += 1
            if done % 100 == 0 or done == len(index):
                print(f"  checked {done}/{len(index)} links")

    broken = sum(1 for r in results if r.category == "broken")
    warn = sum(1 for r in results if r.category == "warning")
    print(f"Link check complete: {broken} broken, {warn} warnings.")
    return results
