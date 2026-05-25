"""Crawl the site: gather pages, the links on each page, and visible text.

Strategy
--------
1. Seed the frontier from the XML sitemap(s) and the configured start URLs.
2. Breadth-first crawl every *internal* HTML page (any host ending in
   ROOT_DOMAIN), discovering new internal pages from anchor links as we go.
3. For each page record: the HTTP status, every outbound link (with the anchor
   text), and the visible body text (for spell checking).

Only HTML pages are fetched for crawling. Links that point at other resource
types (PDFs, images, external sites, mailto:, etc.) are still *recorded* so the
link validator can check them, but they are not themselves crawled.
"""
from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import config
from .http_util import get_session, polite_pause

# Path prefixes we never crawl (from robots.txt + obvious non-content areas).
ROBOTS_DISALLOW = ("/core/", "/profiles/", "/admin/", "/user/login", "/user/logout")

# Tags whose text content is not "prose" and should be ignored for spelling.
NON_TEXT_TAGS = (
    "script",
    "style",
    "noscript",
    "code",
    "pre",
    "svg",
    "head",
    "template",
)


@dataclass
class Link:
    url: str            # absolute, fragment-stripped
    text: str           # anchor text (trimmed)
    is_internal: bool


@dataclass
class Page:
    url: str
    status: int | None = None
    error: str | None = None
    content_type: str = ""
    title: str = ""
    links: list[Link] = field(default_factory=list)
    text: str = ""        # full visible text (HTML pages only)
    prose_text: str = ""  # prose for spell-check: no nav/header/footer/links


def normalize_url(url: str) -> str:
    """Strip fragments and trailing whitespace; leave query strings intact."""
    url, _frag = urldefrag(url.strip())
    return url


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def is_internal(url: str) -> bool:
    host = host_of(url)
    if not host:
        return False
    return host == config.ROOT_DOMAIN or host.endswith("." + config.ROOT_DOMAIN)


def is_http(url: str) -> bool:
    return urlparse(url).scheme in ("http", "https")


def is_crawlable(url: str) -> bool:
    """Can we crawl this URL as an HTML page?"""
    if not is_http(url) or not is_internal(url):
        return False
    path = urlparse(url).path.lower()
    if any(path.startswith(p) for p in ROBOTS_DISALLOW):
        return False
    # Skip obvious binary/document resources — they are validated as links,
    # not crawled for more links.
    if re.search(
        r"\.(pdf|jpe?g|png|gif|svg|webp|mp4|mp3|mov|avi|zip|docx?|xlsx?|pptx?|"
        r"csv|rss|ico|woff2?|ttf|eot|js|css)(\?|$)",
        path,
    ):
        return False
    return True


def fetch_sitemap_urls(sitemap_urls: list[str]) -> list[str]:
    """Recursively resolve sitemap (and sitemap-index) files into page URLs."""
    session = get_session()
    seen: set[str] = set()
    found: list[str] = []
    queue = list(sitemap_urls)

    while queue:
        sm = queue.pop()
        if sm in seen:
            continue
        seen.add(sm)
        try:
            resp = session.get(sm, timeout=config.REQUEST_TIMEOUT)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.content, "xml")
            # Nested sitemap index?
            for sitemap in soup.find_all("sitemap"):
                loc = sitemap.find("loc")
                if loc and loc.text.strip():
                    queue.append(loc.text.strip())
            for url in soup.find_all("url"):
                loc = url.find("loc")
                if loc and loc.text.strip():
                    found.append(normalize_url(loc.text.strip()))
        except requests.RequestException as exc:
            print(f"  ! sitemap fetch failed for {sm}: {exc}")
            continue
    return found


def extract_visible_text(soup: BeautifulSoup) -> str:
    for tag in soup(list(NON_TEXT_TAGS)):
        tag.decompose()
    body = soup.body or soup
    text = body.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text)


# Tags whose text is navigation/boilerplate (or link text) rather than prose.
# We drop these before extracting the text used for spell checking so that menu
# items, footers, and link anchors don't pollute the results with proper nouns.
PROSE_DROP_TAGS = ("nav", "header", "footer", "a", "aside", "form", "button")


def extract_prose_text(soup: BeautifulSoup) -> str:
    """Visible prose for spell checking: no nav/header/footer/link/aside text."""
    clone = BeautifulSoup(str(soup), "lxml")
    for tag in clone(list(NON_TEXT_TAGS) + list(PROSE_DROP_TAGS)):
        tag.decompose()
    container = clone.find("main") or clone.body or clone
    text = container.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text)


def parse_page(url: str, html: bytes) -> tuple[str, str, str, list[Link]]:
    """Return (title, visible_text, prose_text, links) for an HTML document."""
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else ""

    links: list[Link] = []
    seen_on_page: set[str] = set()
    for a in soup.find_all("a", href=True):
        raw = a["href"].strip()
        if not raw:
            continue
        absolute = normalize_url(urljoin(url, raw))
        scheme = urlparse(absolute).scheme.lower()
        if scheme in config.SKIP_SCHEMES:
            continue
        if not absolute or absolute.startswith("#"):
            continue
        if absolute in seen_on_page:
            continue
        seen_on_page.add(absolute)
        links.append(
            Link(
                url=absolute,
                text=" ".join(a.get_text(strip=True).split())[:120],
                is_internal=is_internal(absolute),
            )
        )

    text = extract_visible_text(soup)
    prose = extract_prose_text(BeautifulSoup(html, "lxml"))
    return title, text, prose, links


def fetch_page(url: str) -> Page:
    session = get_session()
    page = Page(url=url)
    try:
        resp = session.get(
            url, timeout=config.REQUEST_TIMEOUT, allow_redirects=True
        )
        page.status = resp.status_code
        page.content_type = resp.headers.get("Content-Type", "").lower()
        # The URL may have redirected; record links relative to the final URL.
        final_url = normalize_url(str(resp.url))
        if resp.status_code == 200 and "html" in page.content_type:
            title, text, prose, links = parse_page(final_url, resp.content)
            page.title = title
            page.text = text
            page.prose_text = prose
            page.links = links
    except requests.RequestException as exc:
        page.error = f"{type(exc).__name__}: {exc}"
    return page


def crawl() -> dict[str, Page]:
    """Crawl the whole internal site. Returns {url: Page} for HTML pages."""
    print("Resolving sitemap(s)...")
    sitemap_pages = fetch_sitemap_urls(config.SITEMAP_URLS)
    print(f"  sitemap provided {len(sitemap_pages)} URLs")

    frontier: list[str] = []
    queued: set[str] = set()

    def enqueue(u: str) -> None:
        u = normalize_url(u)
        if u and u not in queued and is_crawlable(u):
            queued.add(u)
            frontier.append(u)

    for u in config.START_URLS:
        enqueue(u)
    for u in sitemap_pages:
        enqueue(u)

    pages: dict[str, Page] = {}
    lock = threading.Lock()

    print(f"Crawling (cap = {config.MAX_PAGES or 'unlimited'})...")
    with ThreadPoolExecutor(max_workers=config.CRAWL_WORKERS) as pool:
        while frontier:
            if config.MAX_PAGES and len(pages) >= config.MAX_PAGES:
                print(f"  reached page cap of {config.MAX_PAGES}")
                break

            # Take a batch from the frontier to fetch in parallel.
            remaining = (
                config.MAX_PAGES - len(pages) if config.MAX_PAGES else len(frontier)
            )
            batch = frontier[: min(len(frontier), max(1, remaining), config.CRAWL_WORKERS * 4)]
            del frontier[: len(batch)]

            futures = {pool.submit(fetch_page, u): u for u in batch}
            for fut in as_completed(futures):
                page = fut.result()
                with lock:
                    pages[page.url] = page
                # Discover new internal pages from this page's links.
                for link in page.links:
                    if link.is_internal:
                        enqueue(link.url)
                polite_pause(config.CRAWL_DELAY)

            print(f"  crawled {len(pages)} pages, {len(frontier)} queued")

    print(f"Crawl complete: {len(pages)} pages fetched.")
    return pages
