"""Email notifications."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import List, Optional

from .config import get_settings
from .models import MovieShowtimes, Showtime

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self):
        self.settings = get_settings()

    def send_email(self, subject: str, body: str, html: Optional[str] = None) -> bool:
        s = self.settings
        if not s.email_configured():
            log.warning("Email not configured; skipping send. Set CINEBOT_SMTP_* in .env")
            return False
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = s.smtp_user
        msg["To"] = s.email_to
        msg.set_content(body)
        if html:
            msg.add_alternative(html, subtype="html")
        try:
            if s.smtp_use_tls and s.smtp_port == 465:
                with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=30) as server:
                    server.login(s.smtp_user, s.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as server:
                    server.ehlo()
                    if s.smtp_use_tls:
                        server.starttls()
                        server.ehlo()
                    server.login(s.smtp_user, s.smtp_password)
                    server.send_message(msg)
            log.info("Email sent: %s", subject)
            return True
        except Exception as e:
            log.error("Failed to send email: %s", e)
            return False

    @staticmethod
    def format_showtimes(ms: MovieShowtimes) -> str:
        lines = [f"Movie: {ms.movie.title}", f"Slug: {ms.movie.slug}"]
        if ms.showtimes:
            lines.append(f"Date: {ms.showtimes[0].date}")
        lines.append("")
        if not ms.showtimes:
            lines.append("No showtimes found.")
            return "\n".join(lines)
        by_cinema = {}
        for st in ms.showtimes:
            by_cinema.setdefault(st.cinema, []).append(st)
        for cinema, sts in by_cinema.items():
            lines.append(f"== {cinema} ==")
            by_fmt = {}
            for st in sts:
                by_fmt.setdefault(st.format_name or "Standard", []).append(st)
            for fmt, sts2 in by_fmt.items():
                for st in sts2:
                    status = "available" if st.available else "SOLD OUT"
                    seat_info = ""
                    if st.total_seats:
                        seat_info = f"  [seats {st.available_seats}/{st.total_seats} avail, {st.sold_seats} sold]"
                    lines.append(f"  {fmt}: {st.time}  ({status}){seat_info}")
            lines.append("")
        lines.append(f"Available: {ms.available_count}  Sold out: {ms.sold_out_count}")
        return "\n".join(lines)

    def notify_booking_open(self, movie, ms: Optional[MovieShowtimes] = None) -> bool:
        subject = f"[CineBot] Booking opened: {movie.title}"
        body = f"Booking is now open for '{movie.title}' on VOX Cinemas Egypt.\n\n"
        if ms:
            body += self.format_showtimes(ms) + "\n\n"
        body += f"Book: {movie.url}\n"
        html = None
        if ms and ms.showtimes:
            rows = "".join(
                f"<tr><td>{s.cinema}</td><td>{s.format_name}</td><td>{s.time}</td><td>{'Available' if s.available else 'Sold out'}</td></tr>"
                for s in ms.showtimes
            )
            html = (
                f"<h2>Booking opened: {movie.title}</h2>"
                f"<p><a href='{movie.url}'>Open on VOX</a></p>"
                f"<table border='1' cellpadding='4'><tr><th>Cinema</th><th>Format</th><th>Time</th><th>Status</th></tr>{rows}</table>"
            )
        return self.send_email(subject, body, html)

    def notify_available_tickets(self, movie, new_slots: List[Showtime]) -> bool:
        subject = f"[CineBot] Available tickets: {movie.title}"
        lines = [f"New available tickets for '{movie.title}':", ""]
        for s in new_slots:
            lines.append(f"- {s.cinema} | {s.format_name} | {s.time}")
            if s.booking_url:
                lines.append(f"  Book: {s.booking_url}")
        body = "\n".join(lines)
        html = "<br>".join(
            f"{s.cinema} | {s.format_name} | {s.time}" + (f" - <a href='{s.booking_url}'>Book</a>" if s.booking_url else "")
            for s in new_slots
        )
        return self.send_email(subject, body, f"<h2>{movie.title}</h2><p>{html}</p>")
