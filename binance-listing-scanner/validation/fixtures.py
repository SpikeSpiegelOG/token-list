"""Synthetic fixtures for offline validation of the cluster + facilitator logic.

Five fake "Binance memecoin listings" with:
  - Three real insider wallets (W_INSIDER_1/2/3) that appear in 3+ listings
  - One facilitator wallet (W_FACILITATOR) that 3 distinct team wallets paid
  - Random noise buyers and unrelated team transfers

If the cluster + facilitator code is correct, running them against this data
should surface W_INSIDER_1/2/3 as PRIMARY-tier insiders and W_FACILITATOR
as a FACILITATOR-tier wallet.
"""
from __future__ import annotations

# Anchor timestamps (Unix seconds)
T0 = 1_700_000_000   # rough Nov-2023 epoch reference
HOUR = 3600
DAY = 86400

# Wallets (lowercase EVM-style for consistency)
W_INSIDER_1   = "0x" + "1" * 40
W_INSIDER_2   = "0x" + "2" * 40
W_INSIDER_3   = "0x" + "3" * 40
W_NOISE_A     = "0x" + "a" * 40
W_NOISE_B     = "0x" + "b" * 40
W_NOISE_C     = "0x" + "c" * 40
W_NOISE_D     = "0x" + "d" * 40

# Team / deployer wallets for each listing
W_TEAM_PNUT   = "0x" + "f" * 40
W_TEAM_ACT    = "0x" + "e" * 40
W_TEAM_MEME3  = "0x" + "9" * 40
W_TEAM_MEME4  = "0x" + "8" * 40
W_TEAM_MEME5  = "0x" + "7" * 40

# Facilitator — paid by 3 distinct team wallets
W_FACILITATOR = "0x" + "fac" + "0" * 37

# Unrelated recipient (paid by only 1 team — should NOT be flagged)
W_UNRELATED_REC = "0x" + "bad" + "0" * 37


LISTINGS = [
    {
        "symbol": "PNUTX",
        "announced_at": T0 + 30 * DAY,
        "platforms": {"ethereum": "0x" + "111" + "0" * 37},
    },
    {
        "symbol": "ACTX",
        "announced_at": T0 + 35 * DAY,
        "platforms": {"ethereum": "0x" + "222" + "0" * 37},
    },
    {
        "symbol": "MEME3",
        "announced_at": T0 + 40 * DAY,
        "platforms": {"ethereum": "0x" + "333" + "0" * 37},
    },
    {
        "symbol": "MEME4",
        "announced_at": T0 + 45 * DAY,
        "platforms": {"ethereum": "0x" + "444" + "0" * 37},
    },
    {
        "symbol": "MEME5",
        "announced_at": T0 + 50 * DAY,
        "platforms": {"ethereum": "0x" + "555" + "0" * 37},
    },
]


def _buy(wallet: str, ts: int) -> dict:
    return {
        "wallet": wallet, "chain": "ethereum",
        "ts": ts, "amount": "1000000",
        "tx": f"0x{wallet[2:10]}{ts:x}",
    }


# Pre-listing buyers: W_INSIDER_1/2/3 appear in 3+ listings within their windows;
# noise wallets appear in only 0-1 listings each.
BUYERS = {
    "PNUTX": [
        _buy(W_INSIDER_1, T0 + 30 * DAY - 2 * HOUR),
        _buy(W_INSIDER_2, T0 + 30 * DAY - 4 * HOUR),
        _buy(W_NOISE_A,   T0 + 30 * DAY - 5 * HOUR),
    ],
    "ACTX": [
        _buy(W_INSIDER_1, T0 + 35 * DAY - 6 * HOUR),
        _buy(W_INSIDER_3, T0 + 35 * DAY - 3 * HOUR),
        _buy(W_NOISE_B,   T0 + 35 * DAY - 2 * HOUR),
    ],
    "MEME3": [
        _buy(W_INSIDER_2, T0 + 40 * DAY - 8 * HOUR),
        _buy(W_INSIDER_3, T0 + 40 * DAY - 4 * HOUR),
        _buy(W_NOISE_C,   T0 + 40 * DAY - 1 * HOUR),
    ],
    "MEME4": [
        _buy(W_INSIDER_1, T0 + 45 * DAY - 12 * HOUR),
        _buy(W_INSIDER_2, T0 + 45 * DAY - 6 * HOUR),
        _buy(W_INSIDER_3, T0 + 45 * DAY - 3 * HOUR),
        _buy(W_NOISE_D,   T0 + 45 * DAY - 2 * HOUR),
    ],
    "MEME5": [
        _buy(W_INSIDER_2, T0 + 50 * DAY - 8 * HOUR),
        _buy(W_NOISE_A,   T0 + 50 * DAY - 4 * HOUR),
    ],
}


# Stablecoin payments from team wallets — synthetic outflows for the
# facilitator_finder logic test. PNUTX, ACTX, MEME4 team wallets each pay
# W_FACILITATOR a $100k+ tranche. MEME3/MEME5 do not.
TEAM_PAYMENTS = {
    W_TEAM_PNUT: [
        {"to": W_FACILITATOR, "amount_usd": 100_000, "symbol": "USDC",
         "ts": T0 + 28 * DAY, "tx": "0xpay1", "from_team": W_TEAM_PNUT,
         "listing_symbol": "PNUTX", "chain": "ethereum"},
        {"to": W_UNRELATED_REC, "amount_usd": 70_000, "symbol": "USDT",
         "ts": T0 + 29 * DAY, "tx": "0xpay1b", "from_team": W_TEAM_PNUT,
         "listing_symbol": "PNUTX", "chain": "ethereum"},
    ],
    W_TEAM_ACT: [
        {"to": W_FACILITATOR, "amount_usd": 120_000, "symbol": "USDC",
         "ts": T0 + 33 * DAY, "tx": "0xpay2", "from_team": W_TEAM_ACT,
         "listing_symbol": "ACTX", "chain": "ethereum"},
    ],
    W_TEAM_MEME3: [],  # MEME3 team did not pay anyone
    W_TEAM_MEME4: [
        {"to": W_FACILITATOR, "amount_usd": 80_000, "symbol": "USDC",
         "ts": T0 + 43 * DAY, "tx": "0xpay3", "from_team": W_TEAM_MEME4,
         "listing_symbol": "MEME4", "chain": "ethereum"},
    ],
    W_TEAM_MEME5: [
        {"to": W_UNRELATED_REC, "amount_usd": 50_000, "symbol": "USDC",
         "ts": T0 + 48 * DAY, "tx": "0xpay4", "from_team": W_TEAM_MEME5,
         "listing_symbol": "MEME5", "chain": "ethereum"},
    ],
}


# Expected outcomes — used by validate_pipeline.py
EXPECTED_PRIMARY = {W_INSIDER_1, W_INSIDER_2, W_INSIDER_3}
EXPECTED_NOT_PRIMARY = {W_NOISE_A, W_NOISE_B, W_NOISE_C, W_NOISE_D}
EXPECTED_FACILITATORS = {W_FACILITATOR}
EXPECTED_NOT_FACILITATORS = {W_UNRELATED_REC}
