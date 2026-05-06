"""Centralized config loaded from .env."""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DUNE_SIM_API_KEY = os.getenv("DUNE_SIM_API_KEY", "")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")

TG_API_ID = int(os.getenv("TG_API_ID", "0") or 0)
TG_API_HASH = os.getenv("TG_API_HASH", "")
TG_SESSION_NAME = os.getenv("TG_SESSION_NAME", "binance_alpha_scraper")
TG_CHANNELS = [c.strip() for c in os.getenv("TG_CHANNELS", "").split(",") if c.strip()]

LOOKBACK_LISTINGS = int(os.getenv("LOOKBACK_LISTINGS", "20"))
PRE_LISTING_WINDOW_HOURS = int(os.getenv("PRE_LISTING_WINDOW_HOURS", "72"))
MIN_LISTINGS_FOR_INSIDER = int(os.getenv("MIN_LISTINGS_FOR_INSIDER", "3"))

_db = os.getenv("DB_PATH", "./data/scanner.db")
DB_PATH = Path(_db) if Path(_db).is_absolute() else ROOT / _db.lstrip("./")
