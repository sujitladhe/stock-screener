"""
engine_scheduler.py — runs the live tick engine ONLY inside the daily
market window, from inside the web app's own process. OPT-IN: it does
nothing unless ENGINE_SCHEDULER_ENABLED=true is set in .env (see
config.py / main.py). With it off (the default), the app behaves
exactly as before and root's cron start/stop keeps controlling
everything.

WHY THIS EXISTS
---------------
Requirement 10d says auto orders can be placed AFTER market hours. But
today the whole app — website included — is a single systemd service
that cron stops at 3:31 PM, so after that time nobody can even open
the page. Simply leaving the service running all the time isn't an
option either: the live engine would then connect to Ventura outside
market hours, and stray ticks on a non-trading day have already
polluted screener_daily_stats once (handoff Section 7).

So, with this enabled, the service can stay up all day and night (the
website and API always work, orders can be created any time), while
this module starts the engine at 9:14 AM and stops it at 3:31 PM on
trading days only — the same window and the same holiday list
(deploy/nse_holidays.txt) the cron setup used. It also restarts the
engine if it crashes mid-window, which the cron setup never did.
"""

import asyncio
import os
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Identical to the cron entries in the handoff (start 9:14, stop 15:31).
ENGINE_START = dtime(9, 14)
ENGINE_STOP = dtime(15, 31)

RESTART_DELAY_SECONDS = 10

HOLIDAY_FILE = os.path.join(os.path.dirname(__file__), "..", "deploy", "nse_holidays.txt")


def load_holidays(path: str = HOLIDAY_FILE) -> set:
    """
    Reads deploy/nse_holidays.txt (one YYYY-MM-DD per line, '#' comments
    allowed) fresh every time, so editing the file takes effect without
    restarting the service. A missing file means "no known holidays".
    """
    try:
        with open(path) as f:
            lines = [line.strip() for line in f]
    except OSError:
        return set()
    return {line for line in lines if line and not line.startswith("#")}


def is_trading_day(d: date, holidays: set = None) -> bool:
    if holidays is None:
        holidays = load_holidays()
    return d.weekday() < 5 and d.isoformat() not in holidays


def next_window(now: datetime, holidays: set = None):
    """
    Returns (start, stop) — timezone-aware IST datetimes — of the engine
    window to run next: today's if it hasn't ended yet, otherwise the
    next trading day's. `start` may already be in the past (the app was
    started mid-window), meaning "run right now".
    """
    if holidays is None:
        holidays = load_holidays()
    d = now.date()
    for _ in range(20):
        if is_trading_day(d, holidays):
            start = datetime.combine(d, ENGINE_START, tzinfo=IST)
            stop = datetime.combine(d, ENGINE_STOP, tzinfo=IST)
            if now < stop:
                return start, stop
        d += timedelta(days=1)
    raise RuntimeError("No trading day found in the next 20 days — check deploy/nse_holidays.txt.")


async def run_engine_on_schedule(on_alert=None, on_user_alert=None):
    # Imported here (not at module top) so this file's date logic can be
    # unit tested without pulling in websockets / SQLAlchemy.
    from app import ws_client

    while True:
        now = datetime.now(IST)
        try:
            start, stop = next_window(now)
        except RuntimeError as e:
            print(f"[engine_scheduler] {e} Retrying in an hour.")
            await asyncio.sleep(3600)
            continue

        if now < start:
            wait = (start - now).total_seconds()
            print(f"[engine_scheduler] Next engine window starts {start:%Y-%m-%d %H:%M} IST "
                  f"(in {wait / 3600:.1f} h). Sleeping.")
            await asyncio.sleep(wait)

        # Inside the window: run the engine until `stop`, restarting it
        # if it dies on its own.
        while True:
            remaining = (stop - datetime.now(IST)).total_seconds()
            if remaining <= 0:
                break

            print(f"[engine_scheduler] Starting live engine (window ends {stop:%H:%M} IST).")
            engine_task = asyncio.create_task(
                ws_client.run_engine(on_alert=on_alert, on_user_alert=on_user_alert)
            )
            try:
                done, _ = await asyncio.wait({engine_task}, timeout=remaining)
            except asyncio.CancelledError:
                # The whole app is shutting down — take the engine down with it.
                engine_task.cancel()
                raise

            if engine_task in done:
                # It ended by itself before the window closed — a crash.
                try:
                    exc = engine_task.exception()
                except asyncio.CancelledError:
                    exc = None
                print(f"[engine_scheduler] Live engine stopped unexpectedly ({exc!r}). "
                      f"Restarting in {RESTART_DELAY_SECONDS}s.")
                await asyncio.sleep(RESTART_DELAY_SECONDS)
                continue

            # Window over: stop the engine.
            print(f"[engine_scheduler] Market window over ({stop:%H:%M} IST). Stopping live engine.")
            engine_task.cancel()
            try:
                await engine_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"[engine_scheduler] Engine raised while stopping: {e!r}")
            break
