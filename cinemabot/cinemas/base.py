"""Base class for cinema scrapers. All cinema adapters implement this interface."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from ..models import Movie, MovieShowtimes

log = logging.getLogger(__name__)


class CinemaScraper(ABC):
    """Abstract base class for cinema scrapers.

    To add a new cinema, subclass this and implement all abstract methods,
    then register it in cinemas/registry.py (or add a YAML config).
    """

    name: str = "Unknown"
    base_url: str = ""

    def __init__(self, fetcher=None):
        self.fetcher = fetcher
        if self.fetcher is None:
            from ..http_fetcher import HttpFetcher
            # Default allowed host derived from base_url
            host = self.base_url.replace("https://", "").replace("http://", "").split("/")[0]
            self.fetcher = HttpFetcher(allowed_host=host)

    @abstractmethod
    def now_showing(self) -> List[Movie]:
        ...

    @abstractmethod
    def coming_soon(self) -> List[Movie]:
        ...

    def search_movies(self, query: str) -> List[Movie]:
        from ..utils import safe_movie_query
        q = safe_movie_query(query)
        results = []
        seen = set()
        for m in self.now_showing() + self.coming_soon():
            if m.match(q) and m.slug not in seen:
                seen.add(m.slug)
                results.append(m)
        return results

    def find_movie(self, query: str) -> Optional[Movie]:
        from ..utils import safe_movie_query
        q = safe_movie_query(query)
        candidates = self.now_showing() + self.coming_soon()
        for m in candidates:
            if m.slug.lower() == q.lower().replace(" ", "-") or m.title.lower() == q.lower():
                return m
        matches = [m for m in candidates if m.match(q)]
        if len(matches) == 1:
            return matches[0]
        if matches:
            for m in matches:
                if m in self.now_showing():
                    return m
            return matches[0]
        return None

    @abstractmethod
    def available_dates(self, movie: Movie) -> List[Tuple[str, str]]:
        """Return list of (label, date_str) or (label, date_str, original)."""
        ...

    @abstractmethod
    def showtimes(self, movie: Movie, date_str: Optional[str] = None) -> MovieShowtimes:
        ...

    def all_dates_showtimes(self, movie, include_seats=False, favorite_rows=None, max_workers=None):
        dates = self.available_dates(movie)
        results = []
        for item in dates:
            dstr = item[1] if isinstance(item, tuple) else item
            try:
                ms = self.showtimes(movie, dstr)
                if include_seats:
                    self._fill_seats(ms, favorite_rows=favorite_rows)
                results.append(ms)
            except Exception as e:
                log.warning("Failed showtimes for %s %s: %s", movie.slug, dstr, e)
                results.append(MovieShowtimes(movie=movie))
        return results

    def _fill_seats(self, ms, favorite_rows=None):
        pass  # override in subclasses that support seats

    def seat_availability(self, session_id: str, favorite_rows=None) -> dict:
        return {"total": 0, "available": 0, "sold": 0, "rows": {}, "favorite_rows": favorite_rows or []}

    def has_booking_open(self, movie: Movie) -> bool:
        try:
            ms = self.showtimes(movie)
            return len(ms.showtimes) > 0
        except Exception:
            return False

    def cinemas(self) -> List[str]:
        return [self.name]
