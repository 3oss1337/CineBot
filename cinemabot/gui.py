"""Desktop GUI for CineBot (CustomTkinter)."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .browser import close_all_drivers
from .config import get_settings
from .models import Movie
from .notifier import Notifier
# from .scraper import VoxScraper  # now using cinemas.get_scraper
from .utils import safe_movie_query


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class CineBotGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("CineBot — VOX Cinemas Egypt")
        self.geometry("900x650")
        self.minsize(700, 500)

        self.scraper = None
        self.notifier = Notifier()
        self.settings = get_settings()
        self._watch_thread = None
        self._watch_stop = threading.Event()

        self._build_ui()

    def _build_ui(self):
        # Cinema selector at top
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=10, pady=(10, 0))
        ctk.CTkLabel(top, text="Cinema:").pack(side="left", padx=5)
        self.cinema_var = ctk.StringVar(value="vox")
        self.cinema_combo = ctk.CTkComboBox(top, values=["vox", "scene"], variable=self.cinema_var, width=120)
        self.cinema_combo.pack(side="left", padx=5)

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_movies = self.tabview.add("Movies")
        self.tab_coming = self.tabview.add("Coming Soon")
        self.tab_showtimes = self.tabview.add("Showtimes")
        self.tab_watch = self.tabview.add("Watch")
        self.tab_settings = self.tabview.add("Settings")

        self._build_movies_tab()
        self._build_coming_tab()
        self._build_showtimes_tab()
        self._build_watch_tab()
        self._build_settings_tab()

    # ---------- Movies tab ----------
    def _build_movies_tab(self):
        f = self.tab_movies
        btn = ctk.CTkButton(f, text="Refresh", command=self._load_movies)
        btn.pack(pady=5)
        self.movies_box = ctk.CTkTextbox(f, wrap="none")
        self.movies_box.pack(fill="both", expand=True, padx=5, pady=5)

    def _load_movies(self):
        self.movies_box.delete("1.0", "end")
        self.movies_box.insert("end", "Loading...\n")

        def work():
            try:
                
                from .cinemas import get_scraper
                scraper = get_scraper(self.cinema_var.get())
                try:
                    movies = scraper.now_showing()
                finally:
                    close_all_drivers()
                lines = [f"{i}. {m.title} ({m.classification}) — {m.language}" for i, m in enumerate(movies, 1)]
                self.after(0, lambda: self._set_text(self.movies_box, "\n".join(lines)))
            except Exception as e:
                self.after(0, lambda: self._set_text(self.movies_box, f"Error: {e}"))

        threading.Thread(target=work, daemon=True).start()

    # ---------- Coming Soon tab ----------
    def _build_coming_tab(self):
        f = self.tab_coming
        btn = ctk.CTkButton(f, text="Refresh", command=self._load_coming)
        btn.pack(pady=5)
        self.coming_box = ctk.CTkTextbox(f, wrap="none")
        self.coming_box.pack(fill="both", expand=True, padx=5, pady=5)

    def _load_coming(self):
        self.coming_box.delete("1.0", "end")
        self.coming_box.insert("end", "Loading...\n")

        def work():
            try:
                
                from .cinemas import get_scraper
                scraper = get_scraper(self.cinema_var.get())
                try:
                    movies = scraper.coming_soon()
                finally:
                    close_all_drivers()
                lines = [f"{i}. {m.title} ({m.classification})" for i, m in enumerate(movies, 1)]
                self.after(0, lambda: self._set_text(self.coming_box, "\n".join(lines)))
            except Exception as e:
                self.after(0, lambda: self._set_text(self.coming_box, f"Error: {e}"))

        threading.Thread(target=work, daemon=True).start()

    # ---------- Showtimes tab ----------
    def _build_showtimes_tab(self):
        f = self.tab_showtimes
        row = ctk.CTkFrame(f)
        row.pack(fill="x", padx=5, pady=5)
        ctk.CTkLabel(row, text="Movie:").pack(side="left", padx=5)
        self.st_entry = ctk.CTkEntry(row, width=250)
        self.st_entry.pack(side="left", padx=5)
        self.st_all_dates = ctk.CTkCheckBox(row, text="All dates")
        self.st_all_dates.pack(side="left", padx=5)
        self.st_seats = ctk.CTkCheckBox(row, text="Seats")
        self.st_seats.pack(side="left", padx=5)
        ctk.CTkLabel(row, text="Fav rows:").pack(side="left", padx=5)
        self.st_fav = ctk.CTkEntry(row, width=80, placeholder_text="5,6,7")
        self.st_fav.pack(side="left", padx=5)
        ctk.CTkButton(row, text="Fetch", command=self._fetch_showtimes).pack(side="left", padx=5)
        ctk.CTkButton(row, text="Export Excel", command=self._export_showtimes).pack(side="left", padx=5)

        self.st_box = ctk.CTkTextbox(f, wrap="none")
        self.st_box.pack(fill="both", expand=True, padx=5, pady=5)

    def _fetch_showtimes(self):
        movie = self.st_entry.get().strip()
        if not movie:
            messagebox.showwarning("CineBot", "Enter a movie name.")
            return
        self.st_box.delete("1.0", "end")
        self.st_box.insert("end", "Loading...\n")
        all_dates = bool(self.st_all_dates.get())
        seats = bool(self.st_seats.get())
        fav_text = self.st_fav.get().strip()
        fav = [r.strip() for r in fav_text.split(",") if r.strip().isdigit()] if fav_text else (self.settings.get_favorite_rows() if seats else None)

        def work():
            try:
                from .cinemas import get_scraper
                scraper = get_scraper(self.cinema_var.get())
                try:
                    m = scraper.find_movie(safe_movie_query(movie))
                    if m is None:
                        self.after(0, lambda: self._set_text(self.st_box, f"Movie not found: {movie}"))
                        return
                    if all_dates:
                        results = scraper.all_dates_showtimes(m, include_seats=seats, favorite_rows=fav if seats else None)
                        text = "\n\n".join(self.notifier.format_showtimes(ms) for ms in results)
                    else:
                        ms = scraper.showtimes(m)
                        if seats:
                            scraper._fill_seats(ms, favorite_rows=fav)
                        text = self.notifier.format_showtimes(ms)
                finally:
                    close_all_drivers()
                self.after(0, lambda: self._set_text(self.st_box, text))
            except Exception as e:
                self.after(0, lambda: self._set_text(self.st_box, f"Error: {e}"))

        threading.Thread(target=work, daemon=True).start()

    def _export_showtimes(self):
        movie = self.st_entry.get().strip()
        if not movie:
            messagebox.showwarning("CineBot", "Enter a movie name.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv")])
        if not path:
            return
        self.st_box.delete("1.0", "end")
        self.st_box.insert("end", "Exporting (this may take a while)...\n")

        def work():
            try:
                
                from .exporter import export_csv, export_excel
                from .cinemas import get_scraper
                scraper = get_scraper(self.cinema_var.get())
                try:
                    m = scraper.find_movie(safe_movie_query(movie))
                    if m is None:
                        self.after(0, lambda: self._set_text(self.st_box, f"Movie not found: {movie}"))
                        return
                    fav_text = self.st_fav.get().strip()
                    fav = [r.strip() for r in fav_text.split(",") if r.strip().isdigit()] if fav_text else (self.settings.get_favorite_rows() or None)
                    results = scraper.all_dates_showtimes(m, include_seats=True, favorite_rows=fav)
                finally:
                    close_all_drivers()
                if path.lower().endswith(".csv"):
                    export_csv(path, results)
                else:
                    export_excel(path, results)
                self.after(0, lambda: self._set_text(self.st_box, f"Exported to {path}"))
            except Exception as e:
                self.after(0, lambda: self._set_text(self.st_box, f"Error: {e}"))

        threading.Thread(target=work, daemon=True).start()

    # ---------- Watch tab ----------
    def _build_watch_tab(self):
        f = self.tab_watch
        row = ctk.CTkFrame(f)
        row.pack(fill="x", padx=5, pady=5)
        ctk.CTkLabel(row, text="Movie:").pack(side="left", padx=5)
        self.w_entry = ctk.CTkEntry(row, width=250)
        self.w_entry.pack(side="left", padx=5)
        self.w_mode = ctk.CTkComboBox(row, values=["booking", "tickets"], width=120)
        self.w_mode.set("booking")
        self.w_mode.pack(side="left", padx=5)
        ctk.CTkButton(row, text="Start", command=self._start_watch).pack(side="left", padx=5)
        ctk.CTkButton(row, text="Stop", command=self._stop_watch).pack(side="left", padx=5)

        self.watch_box = ctk.CTkTextbox(f, wrap="word")
        self.watch_box.pack(fill="both", expand=True, padx=5, pady=5)

    def _log_watch(self, msg: str):
        self.after(0, lambda: (self.watch_box.insert("end", msg + "\n"), self.watch_box.see("end")))

    def _start_watch(self):
        movie = self.w_entry.get().strip()
        if not movie:
            messagebox.showwarning("CineBot", "Enter a movie name.")
            return
        if self._watch_thread and self._watch_thread.is_alive():
            messagebox.showwarning("CineBot", "A watch is already running. Stop it first.")
            return
        self._watch_stop.clear()
        mode = self.w_mode.get()
        self._log_watch(f"Starting {mode} watch for: {movie}")

        def work():
            try:
                
                from .cinemas import get_scraper
                scraper = get_scraper(self.cinema_var.get())
                notifier = self.notifier
                m = scraper.find_movie(safe_movie_query(movie))
                if m is None:
                    self._log_watch(f"Movie not found: {movie}")
                    return
                if mode == "booking":
                    from .watcher import watch_booking
                    watch_booking(
                        scraper, notifier, movie,
                        interval=self.settings.poll_interval,
                        timeout=self.settings.watch_timeout,
                        on_found=lambda mm, ms: self._log_watch(f"BOOKING OPEN: {mm.title} ({len(ms.showtimes)} slots)"),
                        email=self.settings.email_configured() or self.settings.telegram_configured(),
                    )
                else:
                    from .watcher import watch_tickets
                    watch_tickets(
                        scraper, notifier, movie,
                        interval=self.settings.poll_interval,
                        timeout=self.settings.watch_timeout,
                        on_update=lambda mm, slots: self._log_watch(f"New tickets: {mm.title} ({len(slots)} slots)"),
                        email=self.settings.email_configured() or self.settings.telegram_configured(),
                        notify_initial=True,
                    )
                self._log_watch("Watch finished.")
            except Exception as e:
                self._log_watch(f"Error: {e}")
            finally:
                close_all_drivers()

        self._watch_thread = threading.Thread(target=work, daemon=True)
        self._watch_thread.start()

    def _stop_watch(self):
        self._watch_stop.set()
        self._log_watch("Stop requested (watch will end after current poll).")

    # ---------- Settings tab ----------
    def _build_settings_tab(self):
        f = self.tab_settings
        self.settings_box = ctk.CTkTextbox(f, wrap="word")
        self.settings_box.pack(fill="both", expand=True, padx=5, pady=5)
        btns = ctk.CTkFrame(f)
        btns.pack(fill="x", padx=5, pady=5)
        ctk.CTkButton(btns, text="Refresh status", command=self._refresh_settings).pack(side="left", padx=5)
        ctk.CTkButton(btns, text="Test Telegram", command=self._test_telegram).pack(side="left", padx=5)
        ctk.CTkButton(btns, text="Test Email", command=self._test_email).pack(side="left", padx=5)
        self._refresh_settings()

    def _refresh_settings(self):
        s = self.settings
        lines = [
            f"Base URL: {s.base_url}",
            f"Email configured: {s.email_configured()}",
            f"Telegram configured: {s.telegram_configured()}",
            f"Poll interval: {s.poll_interval}s",
            f"Headless: {s.headless}",
            f"Pool size: {s.pool_size}",
            "",
            "Configured via .env file in the app directory.",
        ]
        self._set_text(self.settings_box, "\n".join(lines))

    def _test_telegram(self):
        def work():
            ok = self.notifier.send_telegram("🤖 CineBot GUI test message.")
            self.after(0, lambda: messagebox.showinfo("CineBot", "Telegram test sent!" if ok else "Telegram test failed."))
        threading.Thread(target=work, daemon=True).start()

    def _test_email(self):
        def work():
            ok = self.notifier.send_email("[CineBot] GUI test", "Test email from CineBot GUI.")
            self.after(0, lambda: messagebox.showinfo("CineBot", "Email test sent!" if ok else "Email test failed (check .env)."))
        threading.Thread(target=work, daemon=True).start()

    # ---------- helpers ----------
    def _set_text(self, box, text: str):
        box.delete("1.0", "end")
        box.insert("end", text)


def main():
    app = CineBotGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
