"""Fast HTTP fetcher using curl_cffi (TLS fingerprint impersonation). No browser needed."""
from __future__ import annotations

import logging
import threading
from typing import Optional

from curl_cffi import requests as cfr

from .config import get_settings
from .utils import validate_url

log = logging.getLogger(__name__)

_local = threading.local()


def get_session() -> cfr.Session:
    sess = getattr(_local, "session", None)
    if sess is None:
        sess = cfr.Session(impersonate="chrome124")
        _local.session = sess
    return sess


def close_session() -> None:
    sess = getattr(_local, "session", None)
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass
        _local.session = None


class HttpFetcher:
    """Fast fetcher using curl_cffi. ~10-50x faster than headless Chrome."""

    def __init__(self, allowed_host: str = None):
        self.settings = get_settings()
        self.allowed_host = allowed_host or self.settings.allowed_host

    def fetch(self, url: str) -> str:
        validate_url(url, self.allowed_host)
        sess = get_session()
        log.debug("Fetching (http) %s", url)
        r = sess.get(url, timeout=20, allow_redirects=True)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code} for {url}")
        html = r.text
        if len(html) < 500:
            raise RuntimeError("Empty/partial page")
        return html

    def close(self) -> None:
        close_session()
