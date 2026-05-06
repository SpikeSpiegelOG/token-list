"""Run the full pipeline: listings → pre-listing buyers → insider clustering."""
from . import binance_listings, prelisting_buyers, cluster


def main() -> None:
    print("[1/3] Fetching recent Binance memecoin listings…")
    binance_listings.main()
    print("[2/3] Collecting pre-listing buyers per listing…")
    prelisting_buyers.main()
    print("[3/3] Clustering wallets across listings…")
    cluster.main()
    print("Done. See data/insider_wallets.json")


if __name__ == "__main__":
    main()
