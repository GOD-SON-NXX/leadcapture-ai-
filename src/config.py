"""
LeadCapture AI — Configuration Module
Loads all settings from environment variables with sensible defaults.
No hardcoded secrets — everything comes from .env or environment.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # --- API Keys ---
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GOOGLE_PLACES_API_KEY: str = os.getenv("GOOGLE_PLACES_API_KEY", "")

    # --- Email (Resend) ---
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    EMAIL_FROM: str = os.getenv("EMAIL_FROM", "LeadCapture AI <noreply@example.com>")

    # --- Wise / Payment ---
    WISE_ACCOUNT_NAME: str = os.getenv("WISE_ACCOUNT_NAME", "Your Business")
    WISE_ACCOUNT_NUMBER: str = os.getenv("WISE_ACCOUNT_NUMBER", "")
    WISE_ROUTING_NUMBER: str = os.getenv("WISE_ROUTING_NUMBER", "")
    WISE_EMAIL: str = os.getenv("WISE_EMAIL", "")

    # --- App Config ---
    APP_NAME: str = os.getenv("APP_NAME", "LeadCapture AI")
    APP_URL: str = os.getenv("APP_URL", "http://localhost:8000")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/leadcapture.db")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "data/logs/app.log")

    # --- Pricing ---
    MONTHLY_PRICE: int = int(os.getenv("MONTHLY_PRICE", "97"))
    MONTHLY_PRICE_CURRENCY: str = os.getenv("MONTHLY_PRICE_CURRENCY", "USD")


settings = Settings()


def setup_logging() -> logging.Logger:
    """Configure logging to console and file."""
    log_dir = os.path.dirname(settings.LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("leadcapture")
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler
    try:
        file_handler = logging.FileHandler(settings.LOG_FILE)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning("Could not set up file logging: %s", e)

    return logger


logger = setup_logging()
