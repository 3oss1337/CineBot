"""Scraping VOX Cinemas Egypt."""
from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup

from .browser import close_all_drivers
from .config import get_settings
from .models import Movie, MovieShowtimes, Showtime
from .utils import safe_movie_query

log = logging.getLogger(__name__)


class VoxScraper:
    def __init__(self, fetcher=None):
        self.settings = get_settings()
        if fetcher is None:
            from .http_fetcher import HttpFetcher
            fetcher = HttpFetcher()
        self.fetcher = fetcher
        self.base = self.settings.base_url.rstrip("/")
        self._lock = threading.Lock()

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

    def available_dates(self, movie: Movie) -> List[Tuple[str, str]]:
        """Return list of (label, YYYYMMDD) available for a movie."""
        url = f"{self.base}/movies/{movie.slug}#showtimes"
        html = self.fetcher.fetch(url)
        soup = BeautifulSoup(html, "html.parser")
        nav = soup.find(class_="date-filter")
        result: List[Tuple[str, str]] = []
        today_str = datetime.now().strftime("%Y%m%d")
        if nav is None:
            result.append(("Today", today_str))
            return result
        ol = nav.find("ol")
        if ol is None:
            result.append(("Today", today_str))
            return result
        for li in ol.find_all("li", recursive=False):
            span = li.find("span")
            a = li.find("a")
            if span is not None and a is None:
                label = span.get_text(strip=True)
                result.append((label if label else "Today", today_str))
                continue
            if a is not None:
                label = a.get_text(strip=True)
                href = a.get("href", "")
                parsed = urlparse(href)
                qs = parse_qs(parsed.query)
                dval = None
                if "d" in qs and qs["d"]:
                    dval = qs["d"][0]
                if not dval:
                    m = re.search(r"[?&]d=(\d{8})", href)
                    dval = m.group(1) if m else None
                if not dval:
                    dval = today_str
                result.append((label, dval))
        # de-dup by date
        seen = set()
        uniq = []
        for label, dval in result:
            if dval in seen:
                continue
            seen.add(dval)
            uniq.append((label, dval))
        return uniq

    def showtimes(self, movie: Movie, date_str: Optional[str] = None) -> MovieShowtimes:
        if date_str:
            url = f"{self.base}/movies/{movie.slug}?d={date_str}#showtimes"
        else:
            url = f"{self.base}/movies/{movie.slug}#showtimes"
            date_str = datetime.now().strftime("%Y%m%d")
        html = self.fetcher.fetch(url)
        soup = BeautifulSoup(html, "html.parser")
        ms = MovieShowtimes(movie=movie)
        dates_div = soup.find(class_="dates")
        if dates_div is None:
            dates_div = soup
        current_cinema = None
        for child in dates_div.children:
            if getattr(child, "name", None) == "h3":
                current_cinema = child.get_text(strip=True)
            elif getattr(child, "name", None) == "ol" and "showtimes" in (child.get("class") or []):
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
                                        date=date_str,
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
                                        date=date_str,
                                    )
                                )
        # de-dup
        uniq = []
        seen = set()
        for s in ms.showtimes:
            key = (s.cinema, s.format_name, s.time, s.available, s.session_id)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(s)
        ms.showtimes = uniq
        return ms

    def all_dates_showtimes(self, movie: Movie, include_seats: bool = False, favorite_rows: Optional[list] = None, max_workers: Optional[int] = None) -> List[MovieShowtimes]:
        if max_workers is None:
            max_workers = self.settings.pool_size
        dates = self.available_dates(movie)
        results: List[MovieShowtimes] = []

        def _work(label_date):
            label, dstr = label_date
            try:
                ms = self.showtimes(movie, dstr)
                if include_seats:
                    self._fill_seats(ms, favorite_rows=favorite_rows)
                return ms
            except Exception as e:
                log.warning("Failed showtimes for %s %s: %s", movie.slug, dstr, e)
                return MovieShowtimes(movie=movie)

        try:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futs = {ex.submit(_work, ld): ld for ld in dates}
                for f in as_completed(futs):
                    results.append(f.result())
        finally:
            close_all_drivers()
            from .http_fetcher import close_session
            close_session()
        # sort by date
        results.sort(key=lambda r: (r.showtimes[0].date if r.showtimes else "",))
        return results

    def _fill_seats(self, ms: MovieShowtimes, favorite_rows: Optional[list] = None) -> None:
        favorite_rows = favorite_rows or []
        def _one(st: Showtime) -> None:
            if not st.session_id or not st.booking_url:
                return
            try:
                info = self.seat_availability(st.session_id, favorite_rows=favorite_rows)
                st.total_seats = info["total"]
                st.available_seats = info["available"]
                st.sold_seats = info["sold"]
                st.row_seats = info["rows"]
                st.favorite_rows = favorite_rows
            except Exception as e:
                log.debug("Seat fetch failed for %s: %s", st.session_id, e)

        try:
            with ThreadPoolExecutor(max_workers=self.settings.pool_size) as ex:
                list(ex.map(_one, ms.showtimes))
        finally:
            close_all_drivers()
            from .http_fetcher import close_session
            close_session()

    def seat_availability(self, session_id: str, favorite_rows: Optional[list] = None) -> dict:
        favorite_rows = favorite_rows or []
        import time
        from curl_cffi import requests as cfr
        sess = None
        try:
            from .http_fetcher import get_session
            sess = get_session()
        except Exception:
            sess = cfr.Session(impersonate="chrome124")
        resp = sess.get(f"{self.base}/booking/{session_id}", timeout=20, allow_redirects=True)
        m = re.search(r"/booking/([^/]+)/", str(resp.url))
        if not m:
            raise RuntimeError("Could not resolve booking token")
        token_part = m.group(1)
        seats_url = f"{self.base}/booking/{token_part}/seats/processing"
        html = ""
        for attempt in range(6):
            r = sess.get(seats_url, timeout=20)
            html = r.text
            if 'class="seat' in html and html.count('class="seat') > 50:
                break
            time.sleep(1.5)
        soup = BeautifulSoup(html, "html.parser")
        seats = soup.find_all(class_="seat")
        total = avail = sold = 0
        row_data = {}
        for x in seats:
            cls = x.get("class", [])
            if "blank" in cls:
                continue
            row = x.get("data-row", "")
            if row not in row_data:
                row_data[row] = {"total": 0, "available": 0, "sold": 0}
            row_data[row]["total"] += 1
            total += 1
            if "sold" in cls:
                sold += 1
                row_data[row]["sold"] += 1
            else:
                avail += 1
                row_data[row]["available"] += 1
        return {
            "total": total,
            "available": avail,
            "sold": sold,
            "rows": row_data,
            "favorite_rows": favorite_rows,
        }

    def has_booking_open(self, movie: Movie) -> bool:
        try:
            ms = self.showtimes(movie)
            return len(ms.showtimes) > 0
        except Exception:
            return False

    def cinemas(self) -> List[str]:
        movies = self.now_showing()
        if not movies:
            return []
        ms = self.showtimes(movies[0])
        seen = []
        for s in ms.showtimes:
            if s.cinema not in seen:
                seen.append(s.cinema)
        return seen
