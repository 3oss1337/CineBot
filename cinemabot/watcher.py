"""Watchers / polling loops."""
from __future__ import annotations

import logging
import random
import time
from typing import Callable, List, Optional, Set

from .config import get_settings
from .models import Movie, MovieShowtimes, Showtime
from .notifier import Notifier
from .scraper import VoxScraper

log = logging.getLogger(__name__)


def _sleep_interval(base: int) -> None:
    # jitter +/- 10%
    jitter = base * 0.1
    time.sleep(max(1, base + random.uniform(-jitter, jitter)))


def watch_booking(
    scraper: VoxScraper,
    notifier: Notifier,
    query: str,
    interval: Optional[int] = None,
    timeout: int = 0,
    on_found: Optional[Callable[[Movie, MovieShowtimes], None]] = None,
    email: bool = True,
) -> Optional[MovieShowtimes]:
    """Poll until booking opens for an upcoming movie."""
    settings = get_settings()
    interval = interval or settings.poll_interval
    timeout = timeout if timeout else settings.watch_timeout
    deadline = time.time() + timeout if timeout > 0 else None

    log.info("Watching for booking to open: %r (interval %ds)", query, interval)
    movie: Optional[Movie] = None
    # Resolve movie initially (may be in coming soon)
    while True:
        if deadline and time.time() > deadline:
            log.info("Timed out waiting for booking.")
            return None
        try:
            movie = scraper.find_movie(query)
        except Exception as e:
            log.warning("Lookup error: %s", e)
            movie = None
        if movie is not None:
            # check if booking open
            try:
                ms = scraper.showtimes(movie)
            except Exception as e:
                log.warning("Showtimes error: %s", e)
                ms = None
            if ms and ms.showtimes:
                log.info("Booking OPEN for %s (%d slots)", movie.title, len(ms.showtimes))
                if email and settings.email_configured():
                    notifier.notify_booking_open(movie, ms)
                if on_found:
                    on_found(movie, ms)
                return ms
            log.info("Found '%s' but no showtimes yet. Waiting...", movie.title)
        else:
            log.info("Movie %r not listed yet. Waiting...", query)
        _sleep_interval(interval)


def watch_tickets(
    scraper: VoxScraper,
    notifier: Notifier,
    query: str,
    interval: Optional[int] = None,
    timeout: int = 0,
    email: bool = True,
    notify_initial: bool = False,
    on_update: Optional[Callable[[Movie, List[Showtime]], None]] = None,
) -> None:
    """Poll a now-showing movie for newly available tickets."""
    settings = get_settings()
    interval = interval or settings.poll_interval
    timeout = timeout if timeout else settings.watch_timeout
    deadline = time.time() + timeout if timeout > 0 else None

    movie = scraper.find_movie(query)
    if movie is None:
        # try coming soon too
        movie = scraper.find_movie(query)
    if movie is None:
        raise ValueError(f"Movie not found: {query!r}")

    log.info("Watching tickets for %s (interval %ds)", movie.title, interval)
    known_available: Set[str] = set()
    baseline_done = False

    while True:
        if deadline and time.time() > deadline:
            log.info("Timed out.")
            return
        try:
            ms = scraper.showtimes(movie)
        except Exception as e:
            log.warning("Showtimes error: %s", e)
            _sleep_interval(interval)
            continue

        current_available = [s for s in ms.showtimes if s.available]
        current_ids = {s.session_id or f"{s.cinema}|{s.format_name}|{s.time}" for s in current_available}

        if not baseline_done:
            known_available = set(current_ids)
            baseline_done = True
            log.info(
                "Baseline: %d available / %d total showtimes",
                len(current_available),
                len(ms.showtimes),
            )
            if notify_initial and current_available and email and settings.email_configured():
                notifier.notify_available_tickets(movie, current_available)
                if on_update:
                    on_update(movie, current_available)
            # Print summary
            print(notifier.format_showtimes(ms) if hasattr(notifier, "format_showtimes") else "")
        else:
            new_ids = current_ids - known_available
            if new_ids:
                new_slots = [s for s in current_available if (s.session_id or f"{s.cinema}|{s.format_name}|{s.time}") in new_ids]
                log.info("NEW available tickets: %d", len(new_slots))
                for s in new_slots:
                    log.info("  %s | %s | %s", s.cinema, s.format_name, s.time)
                if email and settings.email_configured():
                    notifier.notify_available_tickets(movie, new_slots)
                if on_update:
                    on_update(movie, new_slots)
                known_available |= new_ids
            else:
                log.debug("No new available tickets. available=%d", len(current_available))

        _sleep_interval(interval)
