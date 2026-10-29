"""Browser automation (Selenium + Chrome) for Akamai-protected VOX site."""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .config import get_settings

log = logging.getLogger(__name__)

_local = threading.local()


def _build_options(settings) -> Options:
    opts = Options()
    if settings.headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--window-size=1280,800")
    opts.add_argument("--lang=en-US,en")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    # Speed: eager page load, block images
    opts.page_load_strategy = "eager"
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2,
    }
    opts.add_experimental_option("prefs", prefs)
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    if settings.chrome_binary:
        opts.binary_location = settings.chrome_binary
    return opts


def _create_driver(settings) -> webdriver.Chrome:
    opts = _build_options(settings)
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(30)
    driver.set_script_timeout(20)
    # Stealth: remove webdriver flag
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"},
        )
    except Exception:
        pass
    return driver


def get_driver() -> webdriver.Chrome:
    settings = get_settings()
    drv = getattr(_local, "driver", None)
    if drv is None:
        drv = _create_driver(settings)
        _local.driver = drv
    return drv


def close_driver() -> None:
    drv = getattr(_local, "driver", None)
    if drv is not None:
        try:
            drv.quit()
        except Exception:
            pass
        _local.driver = None


class BrowserFetcher:
    """Fetches pages as HTML using a thread-local Chrome instance."""

    def __init__(self):
        self.settings = get_settings()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((TimeoutException, WebDriverException, Exception)),
        reraise=True,
    )
    def fetch(self, url: str) -> str:
        from .utils import validate_url

        validate_url(url, self.settings.allowed_host)
        driver = get_driver()
        log.debug("Fetching %s", url)
        t0 = time.time()
        try:
            driver.get(url)
        except TimeoutException:
            # page may be partially loaded; try to grab source
            log.warning("Timeout loading %s; using partial source", url)
        # Wait a bit for dynamic content (Akamai challenge) to resolve
        # Poll readyState
        for _ in range(20):
            try:
                state = driver.execute_script("return document.readyState")
            except Exception:
                state = "complete"
            if state in ("interactive", "complete"):
                break
            time.sleep(0.25)
        # Extra small wait for JS-rendered showtimes
        time.sleep(0.8)
        html = driver.page_source
        elapsed = time.time() - t0
        log.debug("Fetched %s in %.2fs (%d bytes)", url, elapsed, len(html))
        if len(html) < 500:
            raise WebDriverException("Empty/partial page")
        return html

    def close(self) -> None:
        close_driver()
