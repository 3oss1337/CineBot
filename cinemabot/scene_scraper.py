"""Scene Cinemas (Egypt) scraper."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .http_fetcher import HttpFetcher
from .models import Movie, MovieShowtimes, Showtime
from .utils import safe_movie_query

log = logging.getLogger(__name__)

BASE = "https://cfc.scenecinemas.com"


class SceneScraper:
    """Scraper for Scene Cinemas Egypt (cfc.scenecinemas.com)."""

    def __init__(self, fetcher=None):
        self.fetcher = fetcher or HttpFetcher(allowed_host="cfc.scenecinemas.com")
        self.base = BASE

    def _abs(self, href: str) -> str:
        return urljoin(self.base + "/", href)

    def _slug_from_url(self, url: str) -> str:
        m = re.search(r"movie-details/([^/]+)\.html", url)
        return m.group(1) if m else ""

    def _title_from_slug(self, slug: str) -> str:
        return slug.replace("-", " ").replace("_", " ").title()

    def _parse_movie_details(self, slug: str) -> Movie:
        url = f"{self.base}/movie-details/{slug}.html"
        html = self.fetcher.fetch(url)
        soup = BeautifulSoup(html, "html.parser")
        # title from h1 (format: "18+Clayface" or "Clayface")
        h1 = soup.find("h1")
        raw_title = h1.get_text(strip=True) if h1 else slug
        # extract rating prefix
        rating = ""
        title = raw_title
        m = re.match(r"^(\d+\+|PG|R\d+|G|U)\s*(.*)$", raw_title)
        if m:
            rating = m.group(1)
            title = m.group(2).strip() or self._title_from_slug(slug)
        # language
        language = ""
        text = soup.get_text("\n", strip=True)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if line.lower().startswith("language"):
                if i + 1 < len(lines):
                    language = lines[i + 1]
                break
        # check if has showtimes: movie details page has date tabs for now-showing movies
        dates = re.findall(r"LoadShowtimes\('([^']+)'\)", html)
        has_showtimes = len(dates) > 0
        return Movie(title=title, slug=slug, classification=rating, language=language, url=url), has_showtimes

    def _movie_links(self) -> List[str]:
        html = self.fetcher.fetch(f"{self.base}/")
        slugs = set(re.findall(r"movie-details/([^\"']+)\.html", html))
        return sorted(slugs)

    def now_showing(self) -> List[Movie]:
        movies = []
        for slug in self._movie_links():
            try:
                movie, has_st = self._parse_movie_details(slug)
                if has_st:
                    movies.append(movie)
            except Exception as e:
                log.warning("Failed to parse %s: %s", slug, e)
        return movies

    def coming_soon(self) -> List[Movie]:
        movies = []
        for slug in self._movie_links():
            try:
                movie, has_st = self._parse_movie_details(slug)
                if not has_st:
                    movies.append(movie)
            except Exception as e:
                log.warning("Failed to parse %s: %s", slug, e)
        return movies

    def search_movies(self, query: str) -> List[Movie]:
        q = safe_movie_query(query)
        results = []
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
        url = f"{self.base}/movie-details/{movie.slug}.html"
        html = self.fetcher.fetch(url)
        dates = re.findall(r"LoadShowtimes\('([^']+)'\)", html)
        result = []
        seen = set()
        for d in dates:
            # convert DD-MM-YYYY to YYYYMMDD
            try:
                dt = datetime.strptime(d, "%d-%m-%Y")
                dstr = dt.strftime("%Y%m%d")
            except ValueError:
                dstr = d
            if dstr in seen:
                continue
            seen.add(dstr)
            # label
            today = datetime.now().strftime("%Y%m%d")
            if dstr == today:
                label = "Today"
            else:
                label = dt.strftime("%a %d %b")
            result.append((label, dstr, d))  # d is original DD-MM-YYYY
        if not result:
            today = datetime.now().strftime("%Y%m%d")
            result.append(("Today", today, datetime.now().strftime("%d-%m-%Y")))
        return result

    def showtimes(self, movie: Movie, date_str: Optional[str] = None) -> MovieShowtimes:
        # date_str is YYYYMMDD; convert to DD-MM-YYYY for Scene
        if date_str:
            try:
                dt = datetime.strptime(date_str, "%Y%m%d")
                biz_day = dt.strftime("%d-%m-%Y")
            except ValueError:
                biz_day = date_str
        else:
            biz_day = datetime.now().strftime("%d-%m-%Y")
            date_str = datetime.now().strftime("%Y%m%d")

        url = f"{self.base}/movie-details/{movie.slug}.html?business_day={biz_day}&ajax=1"
        html = self.fetcher.fetch(url)
        ms = MovieShowtimes(movie=movie)
        soup = BeautifulSoup(html, "html.parser")

        # Parse showtimes: branch + format + times
        # Structure: .program_item > .branch (cinema) + .showtimes > .ex_imax_content > .ex_imax (format) + ul > li > a (time + href)
        for item in soup.find_all(class_="program_item"):
            branch_el = item.find(class_="branch")
            cinema = branch_el.get_text(strip=True) if branch_el else "Scene Cinema"
            # remove icon text
            cinema = cinema.replace("\uf5eb", "").strip() if "\uf5eb" in cinema else cinema
            showtimes_div = item.find(class_="showtimes")
            if not showtimes_div:
                continue
            # Scene uses various format containers: ex_imax_content, ex_stand_content, etc.
            for fmt_block in showtimes_div.find_all("div"):
                if not fmt_block.get("class") or not any("content" in c for c in fmt_block.get("class", [])):
                    continue
                # find format name from span with class starting with ex_
                fmt_el = fmt_block.find(class_=lambda c: c and any(x.startswith("ex_") and x != "ex_imax_content" and x != "ex_stand_content" for x in (c if isinstance(c, list) else [c])))
                if not fmt_el:
                    # try any span with ex_ class
                    for span in fmt_block.find_all("span"):
                        sp_classes = span.get("class", [])
                        if any("ex_" in c for c in sp_classes):
                            fmt_el = span
                            break
                fmt_name = fmt_el.get_text(strip=True) if fmt_el else "Standard"
                for li in fmt_block.find_all("li"):
                    a = li.find("a")
                    if a:
                        time_txt = a.get_text(strip=True)
                        href = a.get("href", "")
                        ms.showtimes.append(Showtime(
                            cinema=cinema,
                            format_name=fmt_name,
                            time=time_txt,
                            booking_url=self._abs(href) if href else "",
                            available=True,
                            session_id="",
                            date=date_str,
                        ))
        # de-dup
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

    def all_dates_showtimes(self, movie: Movie, include_seats: bool = False, favorite_rows=None, max_workers=None) -> List[MovieShowtimes]:
        dates = self.available_dates(movie)
        results = []
        for label, dstr, orig in dates:
            try:
                ms = self.showtimes(movie, dstr)
                results.append(ms)
            except Exception as e:
                log.warning("Failed showtimes for %s %s: %s", movie.slug, dstr, e)
                results.append(MovieShowtimes(movie=movie))
        return results

    def seat_availability(self, session_id: str, favorite_rows=None) -> dict:
        # Scene Cinemas booking is currently under maintenance
        return {"total": 0, "available": 0, "sold": 0, "rows": {}, "favorite_rows": favorite_rows or []}

    def has_booking_open(self, movie: Movie) -> bool:
        try:
            ms = self.showtimes(movie)
            return len(ms.showtimes) > 0
        except Exception:
            return False

    def cinemas(self) -> List[str]:
        return ["Scene Cinema - Cairo Festival City"]

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
