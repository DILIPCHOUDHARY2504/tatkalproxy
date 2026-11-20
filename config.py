"""
Tatkal Proxy - Central Configuration
Handles environment loading, schema validation, and security settings.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Set
from dotenv import load_dotenv

# Load .env from workspace root
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    # Project Identity
    APP_NAME: str = "Tatkal Proxy"
    APP_TAGLINE: str = "Premium Proxy Store"
    VERSION: str = "1.0.0"

    # Base paths
    BASE_DIR: Path = BASE_DIR
    UPLOADS_DIR: Path = BASE_DIR / "uploads"
    LOGS_DIR: Path = BASE_DIR / "logs"
    ASSETS_DIR: Path = BASE_DIR / "assets"

    # Telegram Bot
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()

    # Admin IDs (numeric Telegram user IDs)
    _raw_admin_ids: str = os.getenv("ADMIN_IDS", "").strip()
    ADMIN_IDS: Set[int] = {
        int(uid.strip())
        for uid in _raw_admin_ids.split(",")
        if uid.strip().isdigit()
    }

    # Manual UPI Payment Details
    UPI_ID: str = os.getenv("UPI_ID", "tatkalproxy@okaxis").strip()
    UPI_NAME: str = os.getenv("UPI_NAME", "Tatkal Proxy").strip()

    # Encryption Key (Fernet 32-byte key)
    # Default fallback provided only for development testing if not yet configured in .env
    ENCRYPTION_KEY: str = os.getenv(
        "ENCRYPTION_KEY", "uKz8h6w_xN3qJ8yD-Vb7F3z6Q2o0M8w4P5s1L7r4E2I="
    ).strip()

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///tatkalproxy.db").strip()

    # Environment & Webhook
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").lower()
    WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "http://localhost:8000").rstrip("/")
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8000"))
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "super_secret_telegram_webhook_token")
    PAYMENT_GATEWAY_WEBHOOK_SECRET: str = os.getenv(
        "PAYMENT_GATEWAY_WEBHOOK_SECRET", "super_secret_payment_gateway_hmac_secret"
    )

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

    # Special IP pattern (matches 103.x.x.x)
    SPECIAL_IP_PREFIX: str = "103."

    # Subscription reminder thresholds in hours
    REMINDER_24H_HOURS: int = 24
    REMINDER_1H_HOURS: int = 1

    @classmethod
    def is_admin(cls, user_id: int | None) -> bool:
        """Verify if a numeric Telegram user ID has admin authorization."""
        if not user_id:
            return False
        return int(user_id) in cls.ADMIN_IDS

    @classmethod
    def ensure_directories(cls) -> None:
        """Create necessary directories if they don't already exist."""
        cls.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        cls.ASSETS_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
