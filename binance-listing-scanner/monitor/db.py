"""SQLite schema for the local monitor.

Single file DB at config.DB_PATH. Designed for read-heavy dashboard +
infrequent writes from wallet/announcement/TG watchers.
"""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402

SCHEMA = """
CREATE TABLE IF NOT EXISTS insider_wallets (
    wallet TEXT PRIMARY KEY,
    hit_count INTEGER NOT NULL,
    chains TEXT NOT NULL,
    symbols TEXT NOT NULL,
    avg_lead_time_h REAL,
    notes TEXT,
    added_at INTEGER DEFAULT (strftime('%s', 'now'))
);

CREATE TABLE IF NOT EXISTS wallet_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet TEXT NOT NULL,
    chain TEXT NOT NULL,
    direction TEXT NOT NULL,            -- 'in' | 'out'
    counterparty TEXT,                  -- the other side (CEX label / contract)
    counterparty_label TEXT,            -- 'Binance: Hot Wallet 14' etc
    token_addr TEXT,
    token_symbol TEXT,
    amount TEXT,
    tx TEXT NOT NULL,
    ts INTEGER NOT NULL,
    UNIQUE(tx, wallet, direction)
);
CREATE INDEX IF NOT EXISTS idx_wallet_events_ts ON wallet_events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_wallet_events_wallet ON wallet_events(wallet);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    severity TEXT NOT NULL,             -- 'INFO' | 'WATCH' | 'ENTRY' | 'URGENT_EXIT'
    kind TEXT NOT NULL,                 -- 'cluster_buy' | 'binance_deposit' | 'announcement' | 'tg_leak'
    subject TEXT,                       -- token symbol or wallet
    message TEXT NOT NULL,
    payload TEXT,                       -- JSON blob
    ts INTEGER DEFAULT (strftime('%s', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts DESC);

CREATE TABLE IF NOT EXISTS binance_announcements (
    code TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    catalog_id INTEGER,
    release_date INTEGER NOT NULL,
    url TEXT,
    seen_at INTEGER DEFAULT (strftime('%s', 'now'))
);

CREATE TABLE IF NOT EXISTS tg_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    msg_id INTEGER NOT NULL,
    sender TEXT,
    text TEXT NOT NULL,
    contains_token_address INTEGER DEFAULT 0,
    extracted_addresses TEXT,           -- JSON list
    ts INTEGER NOT NULL,
    UNIQUE(channel, msg_id)
);
CREATE INDEX IF NOT EXISTS idx_tg_messages_ts ON tg_messages(ts DESC);
"""


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init() -> None:
    with conn() as c:
        c.executescript(SCHEMA)


def add_alert(severity: str, kind: str, subject: str, message: str, payload: str = "") -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO alerts(severity, kind, subject, message, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (severity, kind, subject, message, payload),
        )


if __name__ == "__main__":
    init()
    print(f"Initialized DB at {config.DB_PATH}")
