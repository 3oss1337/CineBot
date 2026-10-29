# CineBot

Fast, secure Python bot for **VOX Cinemas Egypt** (`egy.voxcinemas.com`).

Features:
- List now-showing and coming-soon movies.
- Show showtimes and availability (available vs sold out) per cinema/format.
- Watch an upcoming movie and get notified (console + email) the moment booking opens.
- Watch a movie for newly available tickets and get notified.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Requires Google Chrome installed (used headless for Akamai-protected pages).

## Configure email (optional)

```bash
copy .env.example .env
# edit .env with your SMTP credentials (Gmail App Password recommended)
```

## Usage

```bash
python -m cinemabot movies
python -m cinemabot coming
python -m cinemabot search "Dune"
python -m cinemabot showtimes "Clayface"
python -m cinemabot watch "The Odyssey" --interval 60
python -m cinemabot tickets "Clayface" --interval 30 --notify-initial
python -m cinemabot config
```

## Security notes

- Secrets only via environment / `.env` (gitignored). Never committed.
- All URLs validated to the allowed host (SSRF protection).
- Movie inputs sanitized; no shell execution.
- SMTP uses TLS; passwords never logged.
- Browser runs headless with image blocking for speed.

## Performance

- Reuses a single headless Chrome instance per thread.
- Connection/page-load strategy `eager`, images blocked.
- Thread pool for batch showtime fetching.
