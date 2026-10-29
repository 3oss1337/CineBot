"""Utilities: validation, sanitization, logging."""
from __future__ import annotations

import logging
import re
from typing import Optional

BASE_HOST = "egy.voxcinemas.com"

# Slugs: lowercase letters, digits, hyphens
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")


def sanitize_slug(value: str) -> str:
    value = (value or "").strip().lower()
    # Allow turning a title into a slug-ish token for matching, but validate
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    if not value or not _SLUG_RE.match(value):
        raise ValueError(f"Invalid movie slug: {value!r}")
    return value


def safe_movie_query(value: str) -> str:
    """Normalize a user-provided movie name for matching (no injection)."""
    return re.sub(r"\s+", " ", (value or "").strip())[:120]


def validate_url(url: str, allowed_host: str = BASE_HOST) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http(s) URLs are allowed")
    if parsed.hostname != allowed_host:
        raise ValueError(f"URL host must be {allowed_host}")
    # strip fragments/query for fetching base pages? keep as is but ensure no weird
    return url


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy libs
    for noisy in ("selenium", "urllib3", "httpx", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def redact(value: Optional[str]) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return value[:2] + "****" + value[-2:]
