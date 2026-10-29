"""Interactive Telegram bot: chat with CineBot to query movies and set watches."""
from __future__ import annotations

import html as _html
import logging
import threading
import time
from typing import Optional

import httpx

from .config import get_settings
from .models import Movie
from .notifier import Notifier
from .scraper import VoxScraper
from .utils import safe_movie_query
from .watcher import watch_booking, watch_tickets

log = logging.getLogger(__name__)

HELP_TEXT = (
    "🎬 <b>CineBot</b> — VOX Cinemas Egypt\n\n"
    "Commands:\n"
    "/movies — now showing\n"
    "/coming — coming soon\n"
    "/search name — find a movie\n"
    "/showtimes name — showtimes today\n"
    "/dates name — all available dates\n"
    "/seats name — showtimes + seat counts (slow)\n"
    "/watch name — notify when booking opens\n"
    "/tickets name — notify on new available tickets\n"
    "/stop — cancel active watches\n"
    "/help — this message"
)


class TelegramBotRunner:
    def __init__(self):
        self.settings = get_settings()
        self.token = self.settings.telegram_bot_token
        self.base = f"https://api.telegram.org/bot{self.token}"
        self.offset = 0
        self._stop = threading.Event()
        self._active: dict = {}  # chat_id -> list of threads
        self._lock = threading.Lock()

    def _api(self, method: str, **kwargs) -> dict:
        try:
            with httpx.Client(timeout=40) as c:
                r = c.post(f"{self.base}/{method}", json=kwargs)
                return r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        except Exception as e:
            log.error("Telegram API error: %s", e)
            return {}

    def send(self, chat_id, text: str, parse_mode: str = "HTML") -> None:
        if len(text) > 4000:
            text = text[:3990] + "\n…(truncated)"
        self._api("sendMessage", chat_id=chat_id, text=text, parse_mode=parse_mode, disable_web_page_preview=True)

    def reply(self, chat_id, text: str) -> None:
        self.send(chat_id, text)

    def _handle(self, chat_id: int, text: str) -> None:
        text = (text or "").strip()
        if not text.startswith("/"):
            self.reply(chat_id, "Send /help for commands.")
            return
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/start", "/help"):
            self.reply(chat_id, HELP_TEXT)
            return
        if cmd == "/stop":
            self._cancel(chat_id)
            self.reply(chat_id, "Cancelled active watches.")
            return
        if cmd == "/movies":
            self._run(chat_id, self._cmd_movies)
            return
        if cmd == "/coming":
            self._run(chat_id, self._cmd_coming)
            return
        if cmd in ("/search", "/showtimes", "/dates", "/seats", "/watch", "/tickets"):
            if not arg:
                self.reply(chat_id, f"Usage: {cmd} <movie name>")
                return
            self._run(chat_id, lambda cid, a=arg, c=cmd: self._cmd_movie(cid, a, c))
            return
        self.reply(chat_id, "Unknown command. /help for list.")

    def _run(self, chat_id, fn) -> None:
        threading.Thread(target=fn, args=(chat_id,), daemon=True).start()

    def _cmd_movies(self, chat_id) -> None:
        self.reply(chat_id, "Fetching now showing…")
        try:
            from .browser import BrowserFetcher, close_all_drivers
            scraper = VoxScraper(BrowserFetcher())
            try:
                movies = scraper.now_showing()
            finally:
                close_all_drivers()
            if not movies:
                self.reply(chat_id, "No movies found.")
                return
            lines = ["🎬 <b>Now Showing</b>", ""]
            for m in movies[:40]:
                lines.append(f"• {_html.escape(m.title)} ({_html.escape(m.classification)})")
            if len(movies) > 40:
                lines.append(f"…and {len(movies)-40} more")
            self.reply(chat_id, "\n".join(lines))
        except Exception as e:
            log.exception("movies cmd failed")
            self.reply(chat_id, f"Error: {_html.escape(str(e))}")

    def _cmd_coming(self, chat_id) -> None:
        self.reply(chat_id, "Fetching coming soon…")
        try:
            from .browser import BrowserFetcher, close_all_drivers
            scraper = VoxScraper(BrowserFetcher())
            try:
                movies = scraper.coming_soon()
            finally:
                close_all_drivers()
            if not movies:
                self.reply(chat_id, "No upcoming movies.")
                return
            lines = ["🗓️ <b>Coming Soon</b>", ""]
            for m in movies[:40]:
                lines.append(f"• {_html.escape(m.title)}")
            if len(movies) > 40:
                lines.append(f"…and {len(movies)-40} more")
            self.reply(chat_id, "\n".join(lines))
        except Exception as e:
            log.exception("coming cmd failed")
            self.reply(chat_id, f"Error: {_html.escape(str(e))}")

    def _cmd_movie(self, chat_id, arg: str, cmd: str) -> None:
        from .browser import BrowserFetcher, close_all_drivers
        scraper = VoxScraper(BrowserFetcher())
        notifier = Notifier()
        try:
            movie = scraper.find_movie(safe_movie_query(arg))
            if movie is None:
                self.reply(chat_id, f"Movie not found: {arg}")
                return
            if cmd == "/search":
                self.reply(chat_id, f"Found: <b>{_html.escape(movie.title)}</b>\n{movie.url}")
                return
            if cmd == "/showtimes":
                self.reply(chat_id, f"Fetching showtimes for {_html.escape(movie.title)}…")
                ms = scraper.showtimes(movie)
                self.reply(chat_id, _html.escape(notifier.format_showtimes(ms)))
                return
            if cmd == "/dates":
                self.reply(chat_id, f"Fetching all dates for {_html.escape(movie.title)}…")
                results = scraper.all_dates_showtimes(movie, include_seats=False)
                for ms in results:
                    self.reply(chat_id, _html.escape(notifier.format_showtimes(ms)))
                return
            if cmd == "/seats":
                self.reply(chat_id, f"Fetching seats for {_html.escape(movie.title)} (slow)…")
                results = scraper.all_dates_showtimes(movie, include_seats=True)
                for ms in results:
                    self.reply(chat_id, _html.escape(notifier.format_showtimes(ms)))
                return
            if cmd == "/watch":
                self.reply(chat_id, f"Watching for booking to open: {movie.title}…")
                self._start_watch(chat_id, movie, scraper, notifier, mode="booking")
                return
            if cmd == "/tickets":
                self.reply(chat_id, f"Watching for new tickets: {movie.title}…")
                self._start_watch(chat_id, movie, scraper, notifier, mode="tickets")
                return
        except Exception as e:
            log.exception("movie cmd failed")
            self.reply(chat_id, f"Error: {_html.escape(str(e))}")
        finally:
            close_all_drivers()

    def _start_watch(self, chat_id, movie: Movie, scraper, notifier, mode: str) -> None:
        # run watcher in background thread; notify via telegram
        def _cb_found(m, ms):
            text = f"🎬 Booking OPEN: {_html.escape(m.title)}\n\n{_html.escape(notifier.format_showtimes(ms))}\n\n{m.url}"
            self.send(chat_id, text)

        def _cb_update(m, slots):
            lines = [f"🎟️ New tickets: {_html.escape(m.title)}", ""]
            for s in slots:
                lines.append(f"- {_html.escape(s.cinema)} | {_html.escape(s.format_name)} | {_html.escape(s.time)}")
                if s.booking_url:
                    lines.append(f"  {s.booking_url}")
            self.send(chat_id, "\n".join(lines))

        def _work():
            try:
                if mode == "booking":
                    watch_booking(
                        scraper, notifier, movie.title,
                        interval=self.settings.poll_interval,
                        timeout=self.settings.watch_timeout,
                        on_found=_cb_found, email=False,
                    )
                else:
                    watch_tickets(
                        scraper, notifier, movie.title,
                        interval=self.settings.poll_interval,
                        timeout=self.settings.watch_timeout,
                        on_update=_cb_update, email=False, notify_initial=True,
                    )
            except Exception as e:
                log.exception("watch failed")
                self.send(chat_id, f"Watch error: {_html.escape(str(e))}")
            finally:
                pass

        t = threading.Thread(target=_work, daemon=True)
        with self._lock:
            self._active.setdefault(chat_id, []).append(t)
        t.start()

    def _cancel(self, chat_id) -> None:
        # threads are daemon; just clear tracking. They'll exit on next poll/timeout.
        with self._lock:
            self._active.pop(chat_id, None)

    def run(self) -> None:
        log.info("Telegram bot polling started.")
        self.send  # noop
        # greet not needed
        while not self._stop.is_set():
            try:
                r = httpx.get(
                    f"{self.base}/getUpdates",
                    params={"offset": self.offset, "timeout": 25},
                    timeout=35,
                )
                data = r.json() if r.status_code == 200 else {}
                for upd in data.get("result", []):
                    self.offset = upd["update_id"] + 1
                    msg = upd.get("message") or upd.get("edited_message")
                    if not msg:
                        continue
                    chat_id = msg["chat"]["id"]
                    text = msg.get("text", "")
                    threading.Thread(target=self._handle, args=(chat_id, text), daemon=True).start()
            except Exception as e:
                log.warning("Poll error: %s", e)
                time.sleep(3)
        log.info("Telegram bot stopped.")

    def stop(self) -> None:
        self._stop.set()
