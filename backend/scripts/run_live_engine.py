"""
scripts/run_live_engine.py — runs the live screener engine.

RUN (small test batch first — recommended before the full universe):
    cd backend
    python -m scripts.run_live_engine --limit 20

RUN (full universe, all ~2,655 stocks):
    python -m scripts.run_live_engine

Only run during market hours (9:15 AM - 3:30 PM IST, weekdays) —
outside these hours there's no live data, so nothing will happen.

Like the historical averages job, this should run inside tmux (or a
proper process manager like systemd, later) so it survives your SSH
session disconnecting — see the tmux instructions from earlier in this
project for the same pattern.
"""

import argparse
import asyncio

from app.ws_client import run_engine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Only track this many stocks (for testing)")
    args = parser.parse_args()

    asyncio.run(run_engine(limit=args.limit))


if __name__ == "__main__":
    main()
