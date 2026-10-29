"""CLI for CineBot."""
from __future__ import annotations

import logging
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .browser import BrowserFetcher, close_all_drivers, close_driver
from .config import get_settings, reset_settings
from .models import Movie
from .notifier import Notifier
from .exporter import export_csv, export_excel
from .scraper import VoxScraper
from .utils import setup_logging, safe_movie_query
from .watcher import watch_booking, watch_tickets

app = typer.Typer(help="CineBot - VOX Cinemas Egypt ticket watcher", no_args_is_help=True)
console = Console()


def _make_scraper() -> VoxScraper:
    return VoxScraper(BrowserFetcher())


def _print_movies(movies, title: str) -> None:
    table = Table(title=title)
    table.add_column("#", style="dim")
    table.add_column("Title")
    table.add_column("Rating")
    table.add_column("Language")
    table.add_column("Slug", style="dim")
    for i, m in enumerate(movies, 1):
        table.add_row(str(i), m.title, m.classification, m.language, m.slug)
    console.print(table)
    console.print(f"Total: {len(movies)}")


@app.command()
def movies(verbose: bool = False):
    """List now-showing movies."""
    setup_logging(verbose)
    scraper = _make_scraper()
    try:
        ms = scraper.now_showing()
        _print_movies(ms, "Now Showing - VOX Cinemas Egypt")
    finally:
        close_all_drivers()


@app.command()
def coming(verbose: bool = False):
    """List coming-soon movies."""
    setup_logging(verbose)
    scraper = _make_scraper()
    try:
        ms = scraper.coming_soon()
        _print_movies(ms, "Coming Soon - VOX Cinemas Egypt")
    finally:
        close_all_drivers()


@app.command()
def search(query: str, verbose: bool = False):
    """Search movies by name."""
    setup_logging(verbose)
    scraper = _make_scraper()
    try:
        ms = scraper.search_movies(safe_movie_query(query))
        _print_movies(ms, f"Search: {query}")
    finally:
        close_all_drivers()


@app.command()
def showtimes(
    movie: str,
    all_dates: bool = typer.Option(False, "--all-dates", "-a", help="Fetch showtimes for all available dates"),
    seats: bool = typer.Option(False, "--seats", "-s", help="Fetch seat availability (slow)"),
    export: Optional[str] = typer.Option(None, "--export", "-e", help="Export to file (.xlsx or .csv)"),
    verbose: bool = False,
):
    """Show showtimes for a movie."""
    setup_logging(verbose)
    scraper = _make_scraper()
    notifier = Notifier()
    try:
        m = scraper.find_movie(safe_movie_query(movie))
        if m is None:
            console.print(f"[red]Movie not found: {movie}[/red]")
            raise typer.Exit(1)
        if export:
            all_dates = True
            seats = True
        if all_dates:
            results = scraper.all_dates_showtimes(m, include_seats=seats)
            for ms in results:
                console.print(notifier.format_showtimes(ms))
                console.print()
            if export:
                if export.lower().endswith(".csv"):
                    export_csv(export, results)
                else:
                    export_excel(export, results)
                console.print(f"[green]Exported to {export}[/green]")
        else:
            ms = scraper.showtimes(m)
            if seats:
                scraper._fill_seats(ms)
            console.print(notifier.format_showtimes(ms))
            if export:
                if export.lower().endswith(".csv"):
                    export_csv(export, [ms])
                else:
                    export_excel(export, [ms])
                console.print(f"[green]Exported to {export}[/green]")
    finally:
        close_all_drivers()


@app.command()
def cinemas(verbose: bool = False):
    """List cinemas (derived)."""
    setup_logging(verbose)
    scraper = _make_scraper()
    try:
        cs = scraper.cinemas()
        for c in cs:
            console.print(c)
    finally:
        close_all_drivers()


@app.command()
def watch(
    movie: str,
    interval: Optional[int] = typer.Option(None, "--interval", "-i", help="Poll interval seconds"),
    timeout: Optional[int] = typer.Option(None, "--timeout", "-t", help="Max seconds (0=forever)"),
    no_email: bool = typer.Option(False, "--no-email", help="Disable email notifications"),
    once: bool = typer.Option(False, "--once", help="Single check, do not loop"),
    verbose: bool = False,
):
    """Watch an upcoming movie until booking opens, then notify."""
    setup_logging(verbose)
    settings = get_settings()
    if interval is None:
        interval = settings.poll_interval
    if timeout is None:
        timeout = settings.watch_timeout

    scraper = _make_scraper()
    notifier = Notifier()
    try:
        if once:
            m = scraper.find_movie(safe_movie_query(movie))
            if m is None:
                console.print(f"[yellow]Not listed yet: {movie}[/yellow]")
                return
            ms = scraper.showtimes(m)
            console.print(notifier.format_showtimes(ms))
            if ms.showtimes:
                console.print("[green]Booking is OPEN.[/green]")
                if not no_email and settings.email_configured():
                    notifier.notify_booking_open(m, ms)
            else:
                console.print("[yellow]No showtimes yet.[/yellow]")
            return
        watch_booking(
            scraper,
            notifier,
            safe_movie_query(movie),
            interval=interval,
            timeout=timeout,
            email=(not no_email),
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped by user.[/yellow]")
    finally:
        close_all_drivers()


@app.command()
def tickets(
    movie: str,
    interval: Optional[int] = typer.Option(None, "--interval", "-i", help="Poll interval seconds"),
    timeout: Optional[int] = typer.Option(None, "--timeout", "-t", help="Max seconds (0=forever)"),
    no_email: bool = typer.Option(False, "--no-email", help="Disable email notifications"),
    notify_initial: bool = typer.Option(False, "--notify-initial", help="Email current available tickets on first run"),
    once: bool = typer.Option(False, "--once", help="Single check, do not loop"),
    verbose: bool = False,
):
    """Watch a now-showing movie for newly available tickets."""
    setup_logging(verbose)
    settings = get_settings()
    if interval is None:
        interval = settings.poll_interval
    if timeout is None:
        timeout = settings.watch_timeout

    scraper = _make_scraper()
    notifier = Notifier()
    try:
        if once:
            m = scraper.find_movie(safe_movie_query(movie))
            if m is None:
                console.print(f"[red]Movie not found: {movie}[/red]")
                raise typer.Exit(1)
            ms = scraper.showtimes(m)
            console.print(notifier.format_showtimes(ms))
            return
        watch_tickets(
            scraper,
            notifier,
            safe_movie_query(movie),
            interval=interval,
            timeout=timeout,
            email=(not no_email),
            notify_initial=notify_initial,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped by user.[/yellow]")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    finally:
        close_all_drivers()


@app.command(name="test-email")
def test_email(verbose: bool = False):
    """Send a test email to verify SMTP configuration."""
    setup_logging(verbose)
    notifier = Notifier()
    settings = get_settings()
    if not settings.email_configured():
        console.print("[red]Email not configured. Fill CINEBOT_SMTP_* in .env first.[/red]")
        console.print("Copy .env.example to .env and set SMTP_USER, SMTP_PASSWORD, EMAIL_TO.")
        raise typer.Exit(1)
    console.print(f"Sending test email to {settings.email_to} via {settings.smtp_host}:{settings.smtp_port} ...")
    ok = notifier.send_email(
        subject="[CineBot] Test email",
        body="This is a test email from CineBot. If you received this, email notifications are working.",
        html="<h2>CineBot test</h2><p>Email notifications are working.</p>",
    )
    if ok:
        console.print("[green]Test email sent successfully.[/green]")
    else:
        console.print("[red]Failed to send. Check credentials and SMTP settings.[/red]")
        raise typer.Exit(1)


@app.command(name="test-telegram")
def test_telegram(verbose: bool = False):
    """Send a test Telegram message to verify bot configuration."""
    setup_logging(verbose)
    notifier = Notifier()
    settings = get_settings()
    if not settings.telegram_configured():
        console.print("[red]Telegram not configured. Set CINEBOT_TELEGRAM_BOT_TOKEN and CINEBOT_TELEGRAM_CHAT_ID in .env.[/red]")
        console.print("1. Create a bot via @BotFather on Telegram -> get token.")
        console.print("2. Send any message to your bot, then open:")
        console.print("   https://api.telegram.org/bot<TOKEN>/getUpdates  to find your chat_id.")
        raise typer.Exit(1)
    console.print(f"Sending test message to chat {settings.telegram_chat_id} ...")
    ok = notifier.send_telegram("🤖 <b>CineBot test</b>\n\nTelegram notifications are working.")
    if ok:
        console.print("[green]Test message sent successfully.[/green]")
    else:
        console.print("[red]Failed to send. Check token and chat_id.[/red]")
        raise typer.Exit(1)


@app.command()
def config(verbose: bool = False):
    """Show configuration status (secrets redacted)."""
    setup_logging(verbose)
    s = get_settings()
    console.print(f"Base URL: {s.base_url}")
    console.print(f"SMTP host: {s.smtp_host}:{s.smtp_port} TLS={s.smtp_use_tls}")
    console.print(f"SMTP user: {s.smtp_user or '(not set)'}")
    console.print(f"Email to: {s.email_to or '(not set)'}")
    console.print(f"Email configured: {s.email_configured()}")
    console.print(f"Telegram configured: {s.telegram_configured()}")
    console.print(f"Poll interval: {s.poll_interval}s")
    console.print(f"Headless: {s.headless}")
    console.print(f"Pool size: {s.pool_size}")


if __name__ == "__main__":
    app()
