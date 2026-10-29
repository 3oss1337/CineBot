"""Scraping VOX Cinemas Egypt."""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .browser import BrowserFetcher
from .config import get_settings
from .models import Movie, MovieShowtimes, Showtime
from .utils import safe_movie_query

log = logging.getLogger(__name__)


class VoxScraper:
    def __init__(self, fetcher: Optional[BrowserFetcher] = None):
        self.settings = get_settings()
        self.fetcher = fetcher or BrowserFetcher()
        self.base = self.settings.base_url.rstrip("/")

    def _abs(self, href: str) -> str:
        return urljoin(self.base + "/", href)

    def _parse_movie_cards(self, soup: BeautifulSoup) -> List[Movie]:
        movies: List[Movie] = []
        seen = set()
        for art in soup.find_all("article", class_="movie-summary"):
            slug = art.get("data-slug") or art.get("data-identifier") or ""
            title = art.get("data-title") or ""
            if not title:
                h = art.find(["h2", "h3", "h4"])
                title = h.get_text(strip=True) if h else ""
            if not slug or not title or slug in seen:
                continue
            seen.add(slug)
            cls_el = art.find(class_=re.compile(r"classification"))
            classification = cls_el.get_text(strip=True) if cls_el else ""
            lang_el = art.find(class_="language")
            language = ""
            if lang_el:
                language = lang_el.get_text(" ", strip=True).replace("Language:", "").strip()
            movies.append(
                Movie(
                    title=title,
                    slug=slug,
                    classification=classification,
                    language=language,
                    url=f"{self.base}/movies/{slug}",
                )
            )
        return movies

    def now_showing(self) -> List[Movie]:
        url = f"{self.base}/movies/whatson"
        html = self.fetcher.fetch(url)
        soup = BeautifulSoup(html, "html.parser")
        return self._parse_movie_cards(soup)
    def coming_soon(self) -> List[Movie]:
        url = f"{self.base}/movies/comingsoon"
        html = self.fetcher.fetch(url)
        soup = BeautifulSoup(html, "html.parser")
        return self._parse_movie_cards(soup)
    def search_movies(self, query: str) -> List[Movie]:
        q = safe_movie_query(query)
        # VOX has a search page; fall back to filtering now_showing + coming_soon
        results: List[Movie] = []
        seen = set()
        for m in self.now_showing() + self.coming_soon():
            if m.match(q) and m.slug not in seen:
                seen.add(m.slug)
                results.append(m)
        return results

    def find_movie(self, query: str) -> Optional[Movie]:
        q = safe_movie_query(query)
        candidates = self.now_showing() + self.coming_soon()
        # exact slug/title first
        for m in candidates:
            if m.slug.lower() == q.lower().replace(" ", "-") or m.title.lower() == q.lower():
                return m
        matches = [m for m in candidates if m.match(q)]
        if len(matches) == 1:
            return matches[0]
        if matches:
            # prefer now showing
            for m in matches:
                if m in self.now_showing():
                    return m
            return matches[0]
        return None

    def showtimes(self, movie: Movie) -> MovieShowtimes:
        url = f"{self.base}/movies/{movie.slug}#showtimes"
        html = self.fetcher.fetch(url)
        soup = BeautifulSoup(html, "html.parser")
        ms = MovieShowtimes(movie=movie)
        # iterate cinema headings + following showtimes        current_cinema = None
        # The structure: .dates has h3 (cinema) then ol.showtimes
        dates_div = soup.find(class_="dates")
        if dates_div is None:
            # maybe showtimes under a different container; search all h3+ol
            dates_div = soup
        for child in dates_div.children:
            if getattr(child, "name", None) == "h3":
                current_cinema = child.get_text(strip=True)
            elif getattr(child, "name", None) == "ol" and "showtimes" in (child.get("class") or []):
                # format groups are li with strong + ol
                for fmt_li in child.find_all("li", recursive=False):
                    strong = fmt_li.find("strong")
                    fmt_name = strong.get_text(strip=True) if strong else ""
                    for ol in fmt_li.find_all("ol"):
                        for li in ol.find_all("li", recursive=False):
                            a = li.find("a", class_="showtime")
                            span = li.find("span", class_="showtime")
                            sid = li.get("data-id", "")
                            if a is not None:
                                time_txt = a.get_text(strip=True)
                                href = a.get("href", "")
                                ms.showtimes.append(
                                    Showtime(
                                        cinema=current_cinema or "Unknown",
                                        format_name=fmt_name,
                                        time=time_txt,
                                        booking_url=self._abs(href) if href else "",
                                        available=True,
                                        session_id=sid,
                                    )
                                )
                            elif span is not None:
                                time_txt = span.get_text(strip=True)
                                ms.showtimes.append(
                                    Showtime(
                                        cinema=current_cinema or "Unknown",
                                        format_name=fmt_name,
                                        time=time_txt,
                                        booking_url="",
                                        available=False,
                                        session_id=sid,
                                    )
                                )
        # de-dup identical
        uniq = []
        seen = set()
        for s in ms.showtimes:
            key = (s.cinema, s.format_name, s.time, s.available)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(s)
        ms.showtimes = uniq
        return ms

    def showtimes_for_slug(self, slug: str) -> MovieShowtimes:
        movie = Movie(title=slug, slug=slug, url=f"{self.base}/movies/{slug}")
        return self.showtimes(movie)

    def batch_showtimes(self, movies: List[Movie], max_workers: Optional[int] = None) -> List[MovieShowtimes]:
        if max_workers is None:
            max_workers = get_settings().pool_size
        results: List[MovieShowtimes] = []

        def _work(m: Movie) -> MovieShowtimes:
            try:
                return self.showtimes(m)
            except Exception as e:
                log.warning("Failed showtimes for %s: %s", m.slug, e)
                return MovieShowtimes(movie=m)

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(_work, m): m for m in movies}
            for f in as_completed(futs):
                results.append(f.result())
        return results

    def has_booking_open(self, movie: Movie) -> bool:
        """True if movie now appears in whatson with showtimes."""
        try:
            ms = self.showtimes(movie)
            return len(ms.showtimes) > 0
        except Exception:
            return False

    def cinemas(self) -> List[str]:
        # Derive cinema list from a popular movie's showtimes
        movies = self.now_showing()
        if not movies:
            return []
        ms = self.showtimes(movies[0])
        seen = []
        for s in ms.showtimes:
            if s.cinema not in seen:
                seen.append(s.cinema)
        return seen
