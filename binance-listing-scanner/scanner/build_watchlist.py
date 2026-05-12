"""Run the full pipeline:
  1. Listings → 2. Pre-listing buyers → 3. PRIMARY clustering →
  4. Load to DB → 5. EXPANDED cluster (funding lineage) →
  6. BINANCE_2NDARY (wallets funded from Binance + sniper behavior) →
  7. FACILITATOR (wallets receiving recurring team-wallet stables)
"""
from . import binance_listings, prelisting_buyers, cluster
from . import cluster_expansion, binance_secondary
from monitor import load_insiders
from qualification import facilitator_finder


def main() -> None:
    print("[1/7] Fetching recent Binance memecoin listings…")
    binance_listings.main()
    print("[2/7] Collecting pre-listing buyers per listing…")
    prelisting_buyers.main()
    print("[3/7] Clustering wallets across listings (PRIMARY tier)…")
    cluster.main()
    print("[4/7] Loading PRIMARY insiders into DB…")
    load_insiders.main()
    print("[5/7] Expanding cluster via funding lineage (EXPANDED tier)…")
    cluster_expansion.main()
    print("[6/7] Scanning Binance hot-wallet outflows (BINANCE_2NDARY tier)…")
    binance_secondary.main()
    print("[7/7] Detecting facilitator wallets (FACILITATOR tier)…")
    facilitator_finder.main()
    print("Done. See data/insider_wallets.json, data/facilitators.json, and "
          "the SQLite insider_wallets table.")


if __name__ == "__main__":
    main()
