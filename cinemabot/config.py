"""Configuration loaded from environment / .env (never hardcoded secrets)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

# Load .env from project root or CWD
for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
    if candidate.exists():
        load_dotenv(candidate, override=False)
        break
else:
    load_dotenv(override=False)


class Settings(BaseModel):
    smtp_host: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    email_to: Optional[str] = None
    smtp_use_tls: bool = True

    poll_interval: int = Field(default=60, ge=5, le=3600)
    watch_timeout: int = Field(default=0, ge=0)  # 0 = forever

    headless: bool = True
    chrome_binary: Optional[str] = None
    pool_size: int = Field(default=2, ge=1, le=8)

    base_url: str = "https://egy.voxcinemas.com"
    allowed_host: str = "egy.voxcinemas.com"

    @field_validator("smtp_port")
    @classmethod
    def _port(cls, v):
        return v

    @classmethod
    def from_env(cls) -> "Settings":
        def _bool(name: str, default: bool) -> bool:
            raw = os.getenv(name)
            if raw is None:
                return default
            return raw.strip().lower() in ("1", "true", "yes", "on")

        def _int(name: str, default: int) -> int:
            raw = os.getenv(name)
            if raw is None or not raw.strip():
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        return cls(
            smtp_host=os.getenv("CINEBOT_SMTP_HOST", "smtp.gmail.com"),
            smtp_port=_int("CINEBOT_SMTP_PORT", 587),
            smtp_user=os.getenv("CINEBOT_SMTP_USER") or None,
            smtp_password=os.getenv("CINEBOT_SMTP_PASSWORD") or None,
            email_to=os.getenv("CINEBOT_EMAIL_TO") or None,
            smtp_use_tls=_bool("CINEBOT_SMTP_USE_TLS", True),
            poll_interval=_int("CINEBOT_POLL_INTERVAL", 60),
            watch_timeout=_int("CINEBOT_WATCH_TIMEOUT", 0),
            headless=_bool("CINEBOT_HEADLESS", True),
            chrome_binary=os.getenv("CINEBOT_CHROME_BINARY") or None,
            pool_size=_int("CINEBOT_POOL_SIZE", 2),
        )

    def email_configured(self) -> bool:
        return bool(self.smtp_user and self.smtp_password and self.email_to)


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
