"""
scripts/sync_angel_mapping.py — run this to map our Ventura NSE/EQ
instruments to Angel One's symboltoken. Prints a summary including any
unmatched symbols, so we can review and handle exceptions to the
"-EQ suffix" pattern rather than silently losing stocks from the
screener.

RUN:
    cd backend
    python -m scripts.sync_angel_mapping
"""

from app.database import SessionLocal
from app.angel_symbol_mapping import sync_angel_symbol_mapping


def main():
    db = SessionLocal()
    try:
        print("Fetching Angel One's instrument master and matching against our instruments...")
        summary = sync_angel_symbol_mapping(db)

        print(f"\nTotal Ventura NSE/EQ instruments checked: {summary['total_checked']}")
        print(f"Matched to an Angel symboltoken: {summary['matched']}")
        print(f"UNMATCHED: {summary['unmatched_count']}")

        if summary["unmatched_symbols"]:
            print("\nUnmatched symbols (these won't get historical averages until resolved):")
            for symbol in summary["unmatched_symbols"][:50]:
                print(f"  - {symbol}")
            if len(summary["unmatched_symbols"]) > 50:
                print(f"  ... and {len(summary['unmatched_symbols']) - 50} more")
    finally:
        db.close()


if __name__ == "__main__":
    main()
