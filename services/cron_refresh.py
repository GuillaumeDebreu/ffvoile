"""Daily cron job to refresh FFVoile job offers."""

import sys
from datetime import datetime
from scraping.scrape_offres import scrape_all_offers


def refresh_offers():
    """Re-scrape all offers from FFVoile and update the database."""
    print(f"[{datetime.now().isoformat()}] Starting daily offer refresh...")
    scrape_all_offers(max_detail_pages=None)
    print(f"[{datetime.now().isoformat()}] Refresh complete.")


if __name__ == "__main__":
    refresh_offers()
