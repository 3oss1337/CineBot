"""Data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Movie:
    title: str
    slug: str
    classification: str = ""
    language: str = ""
    url: str = ""

    def match(self, query: str) -> bool:
        q = (query or "").strip().lower()
        if not q:
            return False
        slug_q = q.replace(" ", "-")
        return q in self.title.lower() or slug_q in self.slug.lower() or self.slug.lower() in slug_q


@dataclass
class Showtime:
    cinema: str
    format_name: str
    time: str
    date: str = ""
    booking_url: str = ""
    available: bool = True
    session_id: str = ""
    total_seats: int = 0
    available_seats: int = 0
    sold_seats: int = 0
    # row-level breakdown: {row_number: {"total": N, "available": M, "sold": K}}
    row_seats: dict = field(default_factory=dict)
    favorite_rows: list = field(default_factory=list)

@dataclass
class MovieShowtimes:
    movie: Movie
    showtimes: List[Showtime] = field(default_factory=list)

    @property
    def available_count(self) -> int:
        return sum(1 for s in self.showtimes if s.available)

    @property
    def sold_out_count(self) -> int:
        return sum(1 for s in self.showtimes if not s.available)
