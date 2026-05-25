"""Shared HTTP helpers: a configured session and small retry wrapper."""
from __future__ import annotations

import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config

_local = threading.local()


def get_session() -> requests.Session:
    """Return a thread-local requests.Session with sane pooling/retries."""
    sess = getattr(_local, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update(
            {
                "User-Agent": config.USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        retry = Retry(
            total=config.MAX_RETRIES,
            backoff_factor=0.5,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=32, pool_maxsize=64)
        sess.mount("http://", adapter)
        sess.mount("https://", adapter)
        _local.session = sess
    return sess


def polite_pause(seconds: float) -> None:
    if seconds and seconds > 0:
        time.sleep(seconds)
