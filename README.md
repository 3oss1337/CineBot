# CineBot

Fast, secure Python bot for **VOX Cinemas Egypt** and **Scene Cinemas Egypt**.

## Features

- **List movies** — now-showing and coming-soon for VOX and Scene Cinemas.
- **Showtimes** — per cinema, format, and date with available vs sold-out status.
- **Seat availability** — total/available/sold seats per showtime, including favorite row tracking.
- **Multi-date export** — fetch all available dates and export to Excel (`.xlsx`) or CSV.
- **Watch for booking** — poll an upcoming movie and get notified when booking opens.
- **Watch for tickets** — poll for newly available tickets and get notified.
- **Favorite rows** — mark your preferred rows; get alerts when seats open up.
- **Notifications** — console, email (SMTP/SendGrid), and Telegram.
- **Interactive Telegram bot** — chat with CineBot to query movies and set watches.
- **Desktop GUI** — CustomTkinter app with 5 tabs.
- **Multi-cinema** — supports VOX and Scene; extensible via YAML config or Python adapter.
- **Universal scraper** — ConfigDrivenScraper lets you add any cinema via YAML (no code).
- **100% browser-free** — uses curl_cffi (TLS impersonation) instead of Selenium. No Chrome needed.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Favorite rows (optional)
```
CINEBOT_FAVORITE_ROWS=5,6,7
```

## Telegram bot

Try the live bot: **[@cinebot_alerts_bot](https://t.me/cinebot_alerts_bot)** on Telegram.

Or run your own:
```bash
python -m cinemabot telegram
```

Commands in chat:
- `/movies` — now showing
- `/coming` — coming soon
- `/search <name>` — find a movie
- `/showtimes <name>` — showtimes today
- `/dates <name>` — all available dates
- `/seats <name>` — showtimes + seat counts (slow)
- `/cinema vox|scene` — switch cinema
- `/watch <name>` — notify when booking opens
- `/tickets <name>` — notify on new available tickets
- `/stop` — cancel active watches
- `/help` — show commands

## Usage (CLI)

```bash
# List movies
python -m cinemabot movies
python -m cinemabot movies --cinema scene
python -m cinemabot coming
python -m cinemabot search "Dune"

# Showtimes
python -m cinemabot showtimes "Clayface"
python -m cinemabot showtimes "Clayface" --all-dates
python -m cinemabot showtimes "Clayface" --seats
python -m cinemabot showtimes "Clayface" --seats --favorite-rows 5,6,7
python -m cinemabot showtimes "Clayface" --seats --export showtimes.xlsx

# Multi-cinema
python -m cinemabot movies --cinema scene
python -m cinemabot showtimes "Clayface" --cinema scene
python -m cinemabot cinemas   # list available cinemas

# Watch for booking to open
python -m cinemabot watch "The Odyssey" --interval 60
python -m cinemabot watch "The Odyssey" --once

# Watch for newly available tickets
python -m cinemabot tickets "Clayface" --interval 30 --notify-initial

# Config & testing
python -m cinemabot config
python -m cinemabot test-telegram
python -m cinemabot test-email

# Desktop GUI
python -m cinemabot gui
```

## Desktop GUI

Launch with `python -m cinemabot gui`. Five tabs:
- **Movies** — now showing list
- **Coming Soon** — upcoming movies
- **Showtimes** — fetch showtimes, all dates, seats, export to Excel, favorite rows
- **Watch** — start/stop watching for booking or tickets
- **Settings** — config status, test Telegram/Email

Cinema selector dropdown at the top switches between VOX and Scene.

## Adding a new cinema (universal approach)

CineBot supports two ways to add a cinema:

1. **Code adapter** (for complex sites): Create `cinemabot/cinemas/<name>.py` implementing `CinemaScraper`.
2. **YAML config** (for simple sites): Create `cinemas/<name>.yaml` with CSS selectors and URL patterns. See `cinemas/_template.yaml.example` for the schema.

Available cinemas are auto-discovered at startup. No core code changes needed.

## Security notes

- Secrets only via environment / `.env` (gitignored). Never committed.
- All URLs validated to the allowed host (SSRF protection).
- Movie inputs sanitized; no shell execution.
- SMTP uses TLS; passwords never logged.
- No browser required (curl_cffi handles Akamai-protected pages).

## Performance

- **100% browser-free** — uses curl_cffi (TLS fingerprint impersonation).
- ~1-2s per page fetch (was 3-5s with headless Chrome).
- Thread pool for batch showtime fetching.
- ~40-60 MB RAM, ~0% CPU when idle.
- Suitable for 24/7 operation.

## Build executable

```bash
pip install -r requirements.txt
python -m PyInstaller --noconfirm --windowed --name CineBot CineBot.py
# Output: dist/CineBot/CineBot.exe (run the whole dist/CineBot folder)
```

## 24/7 operation

For permanent ticket watching, use the CLI (headless, no GUI):
```bash
python -m cinemabot tickets "Clayface" --interval 30
```

Auto-start on boot (Windows Task Scheduler):
- Trigger: At log on
- Action: `python.exe -m cinemabot tickets "Clayface" --interval 30`
- Start in: project directory
- Enable "restart on failure"

Or run the interactive Telegram bot for phone-based control:
```bash
python -m cinemabot telegram
```
