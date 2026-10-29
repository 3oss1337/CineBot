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
        # Prefer SendGrid HTTP API if configured
        if s.use_sendgrid():
            return self._send_sendgrid(s, subject, body, html)
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

    def send_telegram(self, text: str) -> bool:
        s = self.settings
        if not s.telegram_configured():
            log.warning("Telegram not configured; skipping.")
            return False
        import httpx

        url = f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage"
        # Telegram message limit 4096 chars
        if len(text) > 4000:
            text = text[:3990] + "\n…(truncated)"
        try:
            with httpx.Client(timeout=30) as client:
                r = client.post(url, json={
                    "chat_id": s.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                })
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code == 200 and data.get("ok"):
                log.info("Telegram message sent.")
                return True
            log.error("Telegram error %s: %s", r.status_code, r.text[:500])
            return False
        except Exception as e:
            log.error("Failed to send Telegram message: %s", e)
            return False

    def _send_sendgrid(self, s, subject: str, body: str, html: Optional[str]) -> bool:
        import httpx

        content = [{"type": "text/plain", "value": body}]
        if html:
            content.append({"type": "text/html", "value": html})
        payload = {
            "personalizations": [{"to": [{"email": s.email_to}]}],
            "from": {"email": s.sendgrid_from, "name": "CineBot"},
            "subject": subject,
            "content": content,
        }
        try:
            with httpx.Client(timeout=30) as client:
                r = client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    headers={
                        "Authorization": f"Bearer {s.sendgrid_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            if r.status_code in (200, 202):
                log.info("Email sent via SendGrid: %s", subject)
                return True
            log.error("SendGrid error %s: %s", r.status_code, r.text[:500])
            return False
        except Exception as e:
            log.error("Failed to send email via SendGrid: %s", e)
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
                    # Favorite rows highlight
                    if st.favorite_rows and st.row_seats:
                        lines.append("    * Favorite rows:")
                        for fr in st.favorite_rows:
                            rd = st.row_seats.get(fr, {})
                            if rd:
                                a = rd.get("available", 0)
                                t = rd.get("total", 0)
                                sold = rd.get("sold", 0)
                                icon = "[OK]" if a > 0 else "[FULL]"
                                lines.append(f"       Row {fr}: {a}/{t} available, {sold} sold {icon}")
                            else:
                                lines.append(f"       Row {fr}: no data")
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
        ok = True
        if self.settings.email_configured():
            ok = self.send_email(subject, body, html) and ok
        if self.settings.telegram_configured():
            tg_text = f"🎬 Booking OPEN: {movie.title}\n\n{self.format_showtimes(ms) if ms else ''}\n\nBook: {movie.url}"
            ok = self.send_telegram(tg_text) and ok
        return ok

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
        ok = True
        if self.settings.email_configured():
            ok = self.send_email(subject, body, f"<h2>{movie.title}</h2><p>{html}</p>") and ok
        if self.settings.telegram_configured():
            tg_lines = [f"🎟️ New tickets: {movie.title}", ""]
            for s in new_slots:
                tg_lines.append(f"- {s.cinema} | {s.format_name} | {s.time}")
                if s.booking_url:
                    tg_lines.append(f"  {s.booking_url}")
            ok = self.send_telegram("\n".join(tg_lines)) and ok
        return ok
