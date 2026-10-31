"""Cinema registry - auto-discovers available cinemas (code adapters + YAML configs)."""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Tuple

from .base import CinemaScraper

log = logging.getLogger(__name__)

# Code-based adapters
_CODE_ADAPTERS: Dict[str, Tuple[str, type]] = {}


def _register_code_adapters():
    global _CODE_ADAPTERS
    try:
        from .vox import VoxScraper
        _CODE_ADAPTERS["vox"] = ("VOX Cinemas Egypt", VoxScraper)
    except Exception as e:
        log.warning("Failed to load VoxScraper: %s", e)
    try:
        from .scene import SceneScraper
        _CODE_ADAPTERS["scene"] = ("Scene Cinemas Egypt", SceneScraper)
    except Exception as e:
        log.warning("Failed to load SceneScraper: %s", e)


_register_code_adapters()

# YAML config-based cinemas
_YAML_CINEMAS: Dict[str, dict] = {}
_YAML_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cinemas")


def _load_yaml_cinemas():
    global _YAML_CINEMAS
    if not os.path.isdir(_YAML_DIR):
        return
    try:
        import yaml
    except ImportError:
        return
    for fname in os.listdir(_YAML_DIR):
        if not fname.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(_YAML_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            if cfg and isinstance(cfg, dict) and "name" in cfg and "base_url" in cfg:
                key = cfg.get("key", fname.replace(".yaml", "").replace(".yml", ""))
                _YAML_CINEMAS[key] = cfg
        except Exception as e:
            log.warning("Failed to load cinema config %s: %s", fname, e)


_load_yaml_cinemas()


def available_cinemas() -> List[str]:
    return sorted(set(list(_CODE_ADAPTERS.keys()) + list(_YAML_CINEMAS.keys())))


def cinema_name(key: str) -> str:
    key = (key or "").lower().strip()
    if key in _CODE_ADAPTERS:
        return _CODE_ADAPTERS[key][0]
    if key in _YAML_CINEMAS:
        return _YAML_CINEMAS[key].get("name", key)
    return key


def get_scraper(cinema: str = "vox", fetcher=None):
    cinema = (cinema or "vox").lower().strip()
    if cinema in _CODE_ADAPTERS:
        name, cls = _CODE_ADAPTERS[cinema]
        if fetcher is not None:
            return cls(fetcher)
        return cls()
    if cinema in _YAML_CINEMAS:
        from .config_scraper import ConfigDrivenScraper
        return ConfigDrivenScraper(_YAML_CINEMAS[cinema], fetcher=fetcher)
    raise ValueError(f"Unknown cinema: {cinema}. Available: {available_cinemas()}")
