"""
Configuration Module
=====================
Handles logging setup, API credentials loading, and application configuration.
Supports rotating log files with configurable size and backup count.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# ─── Constants ────────────────────────────────────────────────────────────────
FUTURES_TESTNET_URL = "https://testnet.binancefuture.com"  # Futures Testnet
SPOT_TESTNET_URL    = "https://testnet.binance.vision"     # Spot Test Network
PROD_BASE_URL       = "https://fapi.binance.com"           # Production Futures

# Backwards-compat alias
TESTNET_BASE_URL = FUTURES_TESTNET_URL

# ─── Logging configuration ────────────────────────────────────────────────────
LOGS_DIR = Path(__file__).parent.parent / "logs"
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 5
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds
REQUEST_TIMEOUT = 30    # seconds

# ─── Load Environment ──────────────────────────────────────────────────────────
load_dotenv()

LEVERAGE = int(os.environ.get("LEVERAGE", "5"))
RISK_PER_TRADE = float(os.environ.get("RISK_PER_TRADE", "0.01"))
AUTO_TRADE = os.environ.get("AUTO_TRADE", "true").lower() == "true"


def get_base_url() -> str:
    """Returns correct API base URL based on TESTNET flag."""
    if not is_testnet():
        return PROD_BASE_URL
    return FUTURES_TESTNET_URL

def _ensure_logs_dir() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

def _build_log_filename() -> Path:
    from datetime import date
    return LOGS_DIR / f"trading_bot_{date.today().isoformat()}.log"

def setup_logging(verbose: bool = False) -> None:
    """Configures application logging with optional debug verbosity."""
    _ensure_logs_dir()

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Remove any handlers added by previous calls (useful in tests / re-init)
    root_logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # ── Console Handler ──────────────────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # ── Rotating File Handler ────────────────────────────────────────────────
    file_handler = RotatingFileHandler(
        filename=_build_log_filename(),
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Silence noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("binance").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

# ─── API Credentials ──────────────────────────────────────────────────────────

def get_api_credentials() -> tuple[str, str]:
    """Loads API keys from environment."""
    api_key = os.getenv("BINANCE_API_KEY")
    secret_key = os.getenv("BINANCE_SECRET_KEY")

    if not api_key or not secret_key:
        raise EnvironmentError("Missing Binance API credentials in .env")

    return api_key.strip(), secret_key.strip()

def is_testnet() -> bool:
    return os.getenv("TESTNET", "true").lower() in ("true", "1", "yes")

# End of configuration module
