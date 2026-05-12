"""Run the full pipeline:
  1. Listings → 2. Pre-listing buyers → 3. PRIMARY clustering →
  4. Load to DB → 5. EXPANDED cluster (funding lineage) →
  6. BINANCE_2NDARY (wallets funded from Binance + sniper behavior)
"""
from . import binance_listings, prelisting_buyers, cluster
from . import cluster_expansion, binance_secondary
from monitor import load_insiders


def main() -> None:
    print("[1/6] Fetching recent Binance memecoin listings…")
    binance_listings.main()
    print("[2/6] Collecting pre-listing buyers per listing…")
    prelisting_buyers.main()
    print("[3/6] Clustering wallets across listings (PRIMARY tier)…")
    cluster.main()
    print("[4/6] Loading PRIMARY insiders into DB…")
    load_insiders.main()
    print("[5/6] Expanding cluster via funding lineage (EXPANDED tier)…")
    cluster_expansion.main()
    print("[6/6] Scanning Binance hot-wallet outflows (BINANCE_2NDARY tier)…")
    binance_secondary.main()
    print("Done. See data/insider_wallets.json and the SQLite insider_wallets table.")


if __name__ == "__main__":
    main()
