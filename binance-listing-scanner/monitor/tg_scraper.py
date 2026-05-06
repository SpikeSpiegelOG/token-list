"""Telegram public-channel scraper that writes to local SQLite — no bot.

Uses Telethon as a USER client (not a bot). You give it API ID/Hash from
my.telegram.org and a list of public channel usernames. It joins (or just
listens to public channels without joining), persists every new message into
`tg_messages`, and extracts any token contract addresses it sees so the
dashboard can correlate TG calls with on-chain insider activity.

Why no bot?
  - You said no Telegram. This is the inverse: TG → your DB. You never
    interact with TG; you just consume its data.
  - A user-client can read public channels without anyone seeing you.
  - Dashboard surfaces alerts in your browser at localhost.

Run:
    python -m monitor.tg_scraper          # backfills last 200 + listens live
"""
from __future__ import annotations
import asyncio
import json
import re
import time

from telethon import TelegramClient, events

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from monitor import db  # noqa: E402

# Solana mint (base58 32–44), EVM (0x + 40 hex)
ADDR_RE = re.compile(
    r"\b(0x[a-fA-F0-9]{40}|[1-9A-HJ-NP-Za-km-z]{32,44})\b"
)

LEAK_KEYWORDS = (
    "binance", "listing", "spot", "alpha", "leaked", "early", "deployed",
    "sniper", "insider", "vote to list", "vtl",
)


def _extract_addresses(text: str) -> list[str]:
    if not text:
        return []
    candidates = ADDR_RE.findall(text)
    # dedupe preserving order, drop anything that looks like a tx hash (66 hex)
    seen, out = set(), []
    for c in candidates:
        if c in seen:
            continue
        if c.startswith("0x") and len(c) == 66:
            continue
        seen.add(c)
        out.append(c)
    return out


def _looks_like_leak(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in LEAK_KEYWORDS)


def _persist(channel: str, msg_id: int, sender: str, text: str, ts: int) -> None:
    addrs = _extract_addresses(text)
    with db.conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO tg_messages"
            "(channel, msg_id, sender, text, contains_token_address, "
            " extracted_addresses, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (channel, msg_id, sender, text, 1 if addrs else 0,
             json.dumps(addrs), ts),
        )
    if addrs and _looks_like_leak(text):
        db.add_alert(
            severity="WATCH", kind="tg_leak", subject=channel,
            message=f"[{channel}] possible leak: "
                    f"{(text or '')[:120].replace(chr(10), ' ')}",
            payload=json.dumps({"addresses": addrs, "msg_id": msg_id}),
        )


async def main() -> None:
    if not (config.TG_API_ID and config.TG_API_HASH and config.TG_CHANNELS):
        print("Set TG_API_ID, TG_API_HASH and TG_CHANNELS in .env. Aborting.")
        return
    db.init()
    session_file = config.DATA_DIR / config.TG_SESSION_NAME
    client = TelegramClient(str(session_file), config.TG_API_ID, config.TG_API_HASH)
    await client.start()
    print(f"Telethon connected. Watching: {', '.join(config.TG_CHANNELS)}")

    # Backfill last 200 messages per channel
    for ch in config.TG_CHANNELS:
        try:
            entity = await client.get_entity(ch)
            count = 0
            async for m in client.iter_messages(entity, limit=200):
                if not m.message:
                    continue
                _persist(ch, m.id,
                         getattr(m.sender, "username", "") or "",
                         m.message, int(m.date.timestamp()))
                count += 1
            print(f"  {ch}: backfilled {count}")
        except Exception as e:
            print(f"  {ch}: backfill err: {e}")

    @client.on(events.NewMessage(chats=config.TG_CHANNELS))
    async def on_msg(event):
        chat = await event.get_chat()
        sender = await event.get_sender()
        _persist(getattr(chat, "username", "") or str(chat.id),
                 event.message.id,
                 getattr(sender, "username", "") or "",
                 event.message.message or "",
                 int(event.message.date.timestamp()))

    print("Listening for live messages…")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
