"""Cinema factory - returns the right scraper for a given cinema name."""
from __future__ import annotations

from .scene_scraper import SceneScraper
from .scraper import VoxScraper

CINEMAS = {
    "vox": ("VOX Cinemas Egypt", VoxScraper),
    "scene": ("Scene Cinemas Egypt", SceneScraper),
}


def get_scraper(cinema: str = "vox", fetcher=None):
    cinema = (cinema or "vox").lower().strip()
    if cinema not in CINEMAS:
        raise ValueError(f"Unknown cinema: {cinema}. Available: {list(CINEMAS.keys())}")
    name, cls = CINEMAS[cinema]
    if fetcher is not None:
        return cls(fetcher)
    return cls()


def cinema_name(cinema: str) -> str:
    cinema = (cinema or "vox").lower().strip()
    return CINEMAS.get(cinema, ("Unknown", None))[0]


def available_cinemas() -> list:
    return list(CINEMAS.keys())
