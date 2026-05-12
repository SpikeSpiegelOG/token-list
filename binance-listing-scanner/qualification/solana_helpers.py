"""Solana lineage helpers — the Solana equivalents of the EVM functions in
facilitator_finder.py. Uses Helius RPC + enhanced txn API.

Concepts mapped EVM → Solana:
  - Contract creator → mint deployer (signer of the createMint instruction)
  - Early ERC-20 holders → first `getTokenLargestAccounts` snapshot, mapped
    from token accounts back to their owner wallets
  - Stablecoin outflows → enhanced txn `tokenTransfers` filtered to USDC/USDT
"""
from __future__ import annotations
import time
from typing import Any

import requests

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402

# Solana stablecoin mints
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
STABLE_MINTS = {USDC_MINT, USDT_MINT}

# Mints corresponding to wrapped tokens / blue chips to ignore as "first swap"
BLUE_CHIP_MINTS = {
    "So11111111111111111111111111111111111111112",  # wSOL
    USDC_MINT, USDT_MINT,
}

# Known Solana CEX deposit programs / addresses to exclude as recipients
SOL_EXCLUDE = {
    # Binance Solana
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
    # System program
    "11111111111111111111111111111111",
    # SPL token program (txns to this aren't transfers between EOAs)
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
}


def _helius_url(method: str) -> str:
    return f"https://api.helius.xyz/v0/{method}?api-key={config.HELIUS_API_KEY}"


def _helius_rpc(payload: dict) -> dict:
    """Plain Solana RPC via Helius."""
    r = requests.post(
        f"https://mainnet.helius-rpc.com/?api-key={config.HELIUS_API_KEY}",
        json=payload, timeout=20,
    )
    r.raise_for_status()
    return r.json()


def solana_deployer(mint: str) -> str | None:
    """Find the wallet that created the mint (signer of the first txn)."""
    # Use getSignaturesForAddress with `until` to fetch oldest signatures
    res = _helius_rpc({
        "jsonrpc": "2.0", "id": 1,
        "method": "getSignaturesForAddress",
        "params": [mint, {"limit": 1000}],
    })
    sigs = res.get("result") or []
    if not sigs:
        return None
    # Oldest signature is the last in the returned list (Solana returns desc)
    oldest = sigs[-1]
    tx_res = _helius_rpc({
        "jsonrpc": "2.0", "id": 1,
        "method": "getTransaction",
        "params": [oldest["signature"],
                   {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
    })
    tx = tx_res.get("result") or {}
    signers = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
    for s in signers:
        if isinstance(s, dict) and s.get("signer"):
            return s.get("pubkey")
    return None


def solana_team_holders(mint: str, limit: int = 20) -> list[str]:
    """Resolve top token accounts → owner wallets. Excludes known CEX wallets."""
    res = _helius_rpc({
        "jsonrpc": "2.0", "id": 1,
        "method": "getTokenLargestAccounts",
        "params": [mint],
    })
    accounts = (res.get("result") or {}).get("value") or []
    owners = []
    for a in accounts[:limit]:
        ata = a.get("address")
        if not ata:
            continue
        # Resolve token account → owner
        owner_res = _helius_rpc({
            "jsonrpc": "2.0", "id": 1,
            "method": "getAccountInfo",
            "params": [ata, {"encoding": "jsonParsed"}],
        })
        info = (owner_res.get("result") or {}).get("value") or {}
        parsed = info.get("data", {}).get("parsed", {}).get("info", {})
        owner = parsed.get("owner")
        if owner and owner not in SOL_EXCLUDE and owner not in owners:
            owners.append(owner)
        time.sleep(0.05)
    return owners


def solana_stable_outflows(wallet: str, before_ts: int,
                           window_days: int = 60) -> list[dict]:
    """Pull stablecoin (USDC/USDT) outflows from a Solana wallet via Helius
    enhanced transactions API.

    Returns dicts compatible with the EVM version:
      {to, amount_usd, symbol, ts, tx, from_team}
    """
    since = before_ts - window_days * 86400
    base = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
    out: list[dict] = []
    before_sig = None
    pages = 0

    while pages < 30:
        params = {"api-key": config.HELIUS_API_KEY, "limit": 100,
                  "type": "TRANSFER"}
        if before_sig:
            params["before"] = before_sig
        r = requests.get(base, params=params, timeout=20)
        if r.status_code != 200:
            break
        batch = r.json()
        if not batch:
            break
        stop = False
        for tx in batch:
            ts = tx.get("timestamp", 0)
            if ts > before_ts:
                continue
            if ts < since:
                stop = True
                break
            for tt in tx.get("tokenTransfers", []):
                mint = tt.get("mint")
                if mint not in STABLE_MINTS:
                    continue
                if tt.get("fromUserAccount") != wallet:
                    continue
                to = tt.get("toUserAccount")
                if not to or to in SOL_EXCLUDE:
                    continue
                # tokenAmount in Solana enhanced API is already human-readable
                amount = float(tt.get("tokenAmount", 0))
                if amount < 50_000:
                    continue
                out.append({
                    "to": to,
                    "amount_usd": amount,
                    "symbol": "USDC" if mint == USDC_MINT else "USDT",
                    "ts": ts,
                    "tx": tx.get("signature", ""),
                    "from_team": wallet,
                })
        before_sig = batch[-1].get("signature") if batch else None
        if stop or not before_sig:
            break
        pages += 1
        time.sleep(0.15)
    return out


def solana_first_swap_after(wallet: str, after_ts: int) -> dict | None:
    """For Binance-secondary detection on Solana: find the wallet's first
    SWAP-type tx after `after_ts`.
    """
    base = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
    r = requests.get(base, params={
        "api-key": config.HELIUS_API_KEY, "limit": 100, "type": "SWAP",
    }, timeout=15)
    if r.status_code != 200:
        return None
    # Iterate from oldest (end of array) forward
    for tx in reversed(r.json() or []):
        ts = tx.get("timestamp", 0)
        if ts < after_ts:
            continue
        # Find token received (toUserAccount == wallet, mint != stables)
        for tt in tx.get("tokenTransfers", []):
            if tt.get("toUserAccount") != wallet:
                continue
            mint = tt.get("mint")
            if mint in BLUE_CHIP_MINTS:
                continue
            return {
                "ts": ts,
                "symbol": mint[:6] if mint else "",
                "token": mint,
                "tx": tx.get("signature", ""),
                "is_blue_chip": False,
            }
    return None


def solana_wallet_age_days(wallet: str) -> int:
    """Days since the wallet's first observed signature."""
    res = _helius_rpc({
        "jsonrpc": "2.0", "id": 1,
        "method": "getSignaturesForAddress",
        "params": [wallet, {"limit": 1000}],
    })
    sigs = res.get("result") or []
    if not sigs:
        return 9999
    oldest_ts = sigs[-1].get("blockTime") or 0
    if not oldest_ts:
        return 9999
    return (int(time.time()) - oldest_ts) // 86400
