"""Config-driven cinema scraper — add new cinemas via YAML files in cinemas/ directory."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import CinemaScraper
from ..http_fetcher import HttpFetcher
from ..models import Movie, MovieShowtimes, Showtime
from ..utils import safe_movie_query

log = logging.getLogger(__name__)


class ConfigDrivenScraper(CinemaScraper):
    """A cinema scraper driven by a YAML config file.

    Config schema (all fields optional except name and base_url):
        name: "My Cinema"
        base_url: "https://example.com"
        movies_url: "/"                    # page listing movies
        movie_link_pattern: "movie-details/([^\"']+)\.html"
        title_selector: "h1"               # CSS selector for title on detail page
        title_regex: "^(\\d+\\+|PG|G)\\s*(.*)$"  # rating prefix extraction
        language_label: "Language:"
        coming_soon_text: "no showtimes"    # text indicating no showtimes
        date_pattern: "LoadShowtimes\\('([^']+)'\\)"  # regex for date tabs
        date_format: "%d-%m-%Y"            # strptime format for dates
        showtimes_url_template: "{base_url}/movie-details/{slug}.html?business_day={date}&ajax=1"
        showtime_link_pattern: 'href="(https?://[^"]*showtime-[^"]+)"'
        showtime_time_pattern: ">([^<]+)</a>"
        format_selector: "span"             # CSS selector for format name
        format_class_prefix: "ex_"          # class prefix for format spans
    """

    def __init__(self, config: dict, fetcher=None):
        self.config = config
        self.name = config.get("name", "Unknown Cinema")
        self.base_url = config.get("base_url", "").rstrip("/")
        host = self.base_url.replace("https://", "").replace("http://", "").split("/")[0]
        super().__init__(fetcher=fetcher or HttpFetcher(allowed_host=host))
        self._movies_cache = None

    def _cfg(self, key, default=None):
        return self.config.get(key, default)

    def _movie_links(self) -> List[str]:
        url = self.base_url + self._cfg("movies_url", "/")
        html = self.fetcher.fetch(url)
        pattern = self._cfg("movie_link_pattern", r"movie-details/([^\"]+)\.html")
        slugs = set(re.findall(pattern, html))
        return sorted(slugs)

    def _parse_movie(self, slug: str) -> tuple:
        url = self.base_url + "/" + self._cfg("movie_url_template", "movie-details/{slug}.html").format(slug=slug)
        html = self.fetcher.fetch(url)
        soup = BeautifulSoup(html, "html.parser")
        title_sel = self._cfg("title_selector", "h1")
        el = soup.select_one(title_sel)
        raw_title = el.get_text(strip=True) if el else slug
        rating = ""
        title = raw_title
        title_regex = self._cfg("title_regex")
        if title_regex:
            m = re.match(title_regex, raw_title)
            if m:
                rating = m.group(1)
                title = m.group(2).strip() or slug.replace("-", " ").title()
        language = ""
        label = self._cfg("language_label", "Language:")
        text = soup.get_text("\n", strip=True)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if line.lower().startswith(label.lower().rstrip(":")):
                if i + 1 < len(lines):
                    language = lines[i + 1]
                break
        coming_text = self._cfg("coming_soon_text", "no showtimes")
        has_showtimes = coming_text.lower() not in html.lower()
        # also check date tabs
        date_pat = (self._cfg("date_pattern") or "").strip()
        if date_pat:
            dates = re.findall(date_pat, html)
            has_showtimes = has_showtimes or len(dates) > 0
        return Movie(title=title, slug=slug, classification=rating, language=language, url=url), has_showtimes

    def now_showing(self) -> List[Movie]:
        movies = []
        for slug in self._movie_links():
            try:
                movie, has_st = self._parse_movie(slug)
                if has_st:
                    movies.append(movie)
            except Exception as e:
                log.warning("Failed to parse %s: %s", slug, e)
        return movies

    def coming_soon(self) -> List[Movie]:
        movies = []
        for slug in self._movie_links():
            try:
                movie, has_st = self._parse_movie(slug)
                if not has_st:
                    movies.append(movie)
            except Exception as e:
                log.warning("Failed to parse %s: %s", slug, e)
        return movies

    def available_dates(self, movie: Movie) -> List[Tuple[str, str]]:
        url = movie.url
        html = self.fetcher.fetch(url)
        date_pat = (self._cfg("date_pattern") or "").strip()
        date_fmt = self._cfg("date_format", "%d-%m-%Y")
        result = []
        seen = set()
        if date_pat:
            for d in re.findall(date_pat, html):
                try:
                    dt = datetime.strptime(d, date_fmt)
                    dstr = dt.strftime("%Y%m%d")
                except ValueError:
                    dstr = d
                if dstr in seen:
                    continue
                seen.add(dstr)
                today = datetime.now().strftime("%Y%m%d")
                label = "Today" if dstr == today else dt.strftime("%a %d %b")
                result.append((label, dstr))
        if not result:
            today = datetime.now().strftime("%Y%m%d")
            result.append(("Today", today))
        return result

    def showtimes(self, movie: Movie, date_str: Optional[str] = None) -> MovieShowtimes:
        if date_str:
            try:
                dt = datetime.strptime(date_str, "%Y%m%d")
                date_param = dt.strftime(self._cfg("date_format", "%d-%m-%Y"))
            except ValueError:
                date_param = date_str
        else:
            date_param = datetime.now().strftime(self._cfg("date_format", "%d-%m-%Y"))
            date_str = datetime.now().strftime("%Y%m%d")

        template = self._cfg("showtimes_url_template", "{base_url}/movie-details/{slug}.html?business_day={date}&ajax=1")
        url = template.format(base_url=self.base_url, slug=movie.slug, date=date_param)
        try:
            html = self.fetcher.fetch(url)
        except Exception:
            html = ""
        ms = MovieShowtimes(movie=movie)
        soup = BeautifulSoup(html, "html.parser")

        link_pat = self._cfg("showtime_link_pattern", r'href="(https?://[^"]*showtime-[^"]+)"')
        time_pat = self._cfg("showtime_time_pattern", r">([^<]+)</a>")
        fmt_prefix = self._cfg("format_class_prefix", "ex_")

        # Find format blocks (divs with "content" in class)
        for fmt_block in soup.find_all("div"):
            cls = fmt_block.get("class", [])
            if not cls or not any("content" in c for c in cls):
                continue
            # format name from span with ex_ prefix
            fmt_name = "Standard"
            for span in fmt_block.find_all("span"):
                sp_cls = span.get("class", [])
                if any(c.startswith(fmt_prefix) for c in sp_cls):
                    fmt_name = span.get_text(strip=True)
                    break
            cinema = self.name
            # branch
            branch_el = fmt_block.find_previous(class_=lambda c: c and "branch" in " ".join(c) if isinstance(c, list) else False)
            # simpler: find branch in parent
            parent = fmt_block.find_parent(class_=lambda c: c and "program_item" in " ".join(c) if isinstance(c, list) else False)
            if parent:
                branch_el = parent.find(class_=lambda c: c and "branch" in " ".join(c) if isinstance(c, list) else False)
                if branch_el:
                    cinema = branch_el.get_text(strip=True)
            for a in fmt_block.find_all("a"):
                href = a.get("href", "")
                if not href or "showtime" not in href.lower():
                    continue
                time_txt = a.get_text(strip=True)
                ms.showtimes.append(Showtime(
                    cinema=cinema,
                    format_name=fmt_name,
                    time=time_txt,
                    booking_url=href,
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

    def all_dates_showtimes(self, movie, include_seats=False, favorite_rows=None, max_workers=None):
        dates = self.available_dates(movie)
        results = []
        for item in dates:
            dstr = item[1] if isinstance(item, tuple) else item
            try:
                ms = self.showtimes(movie, dstr)
                results.append(ms)
            except Exception as e:
                log.warning("Failed showtimes for %s %s: %s", movie.slug, dstr, e)
                results.append(MovieShowtimes(movie=movie))
        return results

    def seat_availability(self, session_id, favorite_rows=None):
        return {"total": 0, "available": 0, "sold": 0, "rows": {}, "favorite_rows": favorite_rows or []}

    def has_booking_open(self, movie):
        try:
            ms = self.showtimes(movie)
            return len(ms.showtimes) > 0
        except Exception:
            return False

    def cinemas(self):
        return [self.name]

    def find_movie(self, query):
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
