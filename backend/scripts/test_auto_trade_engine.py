"""
scripts/test_auto_trade_engine.py — unit tests for the AUTO TRADE
decision logic (requirement 10), run against synthetic ticks/dates —
no database, no broker, no network, so it's safe to run anytime
(including outside market hours). Run it after deploying, and again
after any change to auto_trade_engine.py:

    cd backend
    python -m scripts.test_auto_trade_engine

Covers: volume condition, candle % condition (GREEN ONLY), AND / OR,
market-window + "valid till" cut-off, weekends, stale ticks, the
"minute not observed from its start" guard, the in-memory registry,
and the engine scheduler's trading-day maths.
"""

import sys
from datetime import datetime, time as dtime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app import auto_trade_registry
from app.auto_trade_engine import (
    AutoOrderState, CandleState, evaluate_auto_order, update_candle, ONE_CRORE,
)
from app import engine_scheduler

IST = ZoneInfo("Asia/Kolkata")

MONDAY = (2026, 9, 21)
SATURDAY = (2026, 9, 19)

_results = []


def check(name, condition):
    _results.append((name, bool(condition)))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}")


def ist(y, m, d, hh, mm, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=IST)


def order(volume_cr=None, candle_pct=None, combinator=None, valid_till=None):
    return AutoOrderState(
        order_id=1, client_id="AA0001", trading_symbol="SBIN",
        volume_threshold=None if volume_cr is None else volume_cr * ONE_CRORE,
        candle_pct_threshold=candle_pct,
        combinator=combinator,
        valid_till=valid_till,
    )


def candle(open_price=100.0, observed=True):
    return CandleState(
        minute=datetime(2026, 9, 21, 10, 0), open_price=open_price, observed_from_start=observed
    )


def fires(o, *, volume, ltp, c=None, now=None, tick_time=None):
    now = now or ist(*MONDAY, 10, 0, 30)
    tick_time = tick_time or now.replace(tzinfo=None)
    return evaluate_auto_order(
        o, current_minute_volume=volume, ltp=ltp,
        candle=c or candle(), tick_time=tick_time, now=now,
    ) is not None


def test_volume_only():
    print("Volume condition")
    o = order(volume_cr=6)
    check("exactly 6 Cr fires (>=, not >)", fires(o, volume=600_000, ltp=100.0))
    check("just under 6 Cr does not fire", not fires(o, volume=599_999, ltp=100.0))
    check("0.06 Cr (= 6 lakh) works as a small threshold",
          fires(order(volume_cr=0.06), volume=6_000, ltp=100.0))


def test_candle_only():
    print("Candle % condition")
    o = order(candle_pct=1.7)
    check("green candle at exactly 1.7% fires (float-safe)", fires(o, volume=1, ltp=101.7))
    check("green candle at 1.69% does not fire", not fires(o, volume=1, ltp=101.69))
    check("green candle above threshold fires", fires(o, volume=1, ltp=103.0))
    check("RED candle never fires, even for a -5% move", not fires(o, volume=1, ltp=95.0))
    check("flat candle does not fire", not fires(o, volume=1, ltp=100.0))


def test_combinators():
    print("AND / OR")
    both_and = order(volume_cr=6, candle_pct=1.7, combinator="AND")
    check("AND: volume ok + green candle ok -> fires",
          fires(both_and, volume=600_000, ltp=102.0))
    check("AND: volume ok but candle too small -> no", not fires(both_and, volume=600_000, ltp=100.5))
    check("AND: candle ok but volume too small -> no", not fires(both_and, volume=1000, ltp=102.0))
    check("AND: volume ok, candle big but RED -> no (the spec's SBIN example)",
          not fires(both_and, volume=600_000, ltp=97.0))

    both_or = order(volume_cr=6, candle_pct=1.7, combinator="OR")
    check("OR: only volume ok -> fires", fires(both_or, volume=600_000, ltp=100.5))
    check("OR: only green candle ok -> fires", fires(both_or, volume=1000, ltp=102.0))
    check("OR: neither -> no", not fires(both_or, volume=1000, ltp=100.5))
    check("OR: red big candle + low volume -> no", not fires(both_or, volume=1000, ltp=97.0))

    missing = order(volume_cr=6, candle_pct=1.7, combinator=None)
    check("missing combinator falls back to the stricter AND",
          not fires(missing, volume=600_000, ltp=100.5))


def test_window_and_validity():
    print("Market window / valid-till")
    o = order(volume_cr=6)
    kw = dict(volume=600_000, ltp=100.0)
    check("before 09:15 -> no", not fires(o, now=ist(*MONDAY, 9, 14, 59), **kw))
    check("09:15:00 -> yes", fires(o, now=ist(*MONDAY, 9, 15, 0), **kw))
    check("15:29:59 -> yes", fires(o, now=ist(*MONDAY, 15, 29, 59), **kw))
    check("15:30:00 -> no", not fires(o, now=ist(*MONDAY, 15, 30, 0), **kw))
    check("Saturday -> no", not fires(o, now=ist(*SATURDAY, 10, 0, 0), **kw))

    v = order(volume_cr=6, valid_till=dtime(9, 30))
    check("valid till 09:30: at 09:29:59 fires", fires(v, now=ist(*MONDAY, 9, 29, 59), **kw))
    check("valid till 09:30: at 09:30:00 fires", fires(v, now=ist(*MONDAY, 9, 30, 0), **kw))
    check("valid till 09:30: at 09:30:01 STILL fires (whole minute is valid)",
          fires(v, now=ist(*MONDAY, 9, 30, 1), **kw))
    check("valid till 09:30: at 09:30:59 still fires", fires(v, now=ist(*MONDAY, 9, 30, 59), **kw))
    check("valid till 09:30: held from 09:31:00", not fires(v, now=ist(*MONDAY, 9, 31, 0), **kw))
    check("valid till 09:30: held at 09:31:30", not fires(v, now=ist(*MONDAY, 9, 31, 30), **kw))
    check("no valid-till: still fires in the afternoon", fires(o, now=ist(*MONDAY, 14, 0, 0), **kw))


def test_data_quality_guards():
    print("Data-quality guards")
    o = order(volume_cr=6)
    kw = dict(volume=600_000, ltp=100.0)
    check("stale tick from another day -> no",
          not fires(o, tick_time=datetime(2026, 9, 18, 15, 29, 0), **kw))
    check("minute not observed from its start -> no",
          not fires(o, c=candle(observed=False), **kw))
    check("zero/absent candle open -> no", not fires(o, c=candle(open_price=0.0), **kw))
    check("negative current-minute volume -> no", not fires(o, volume=-5, ltp=100.0))
    check("order with no conditions is inert",
          not fires(order(), volume=600_000, ltp=100.0))


def test_candle_tracker():
    print("Candle tracker")
    c = CandleState()
    m1 = datetime(2026, 9, 21, 10, 0)
    m2 = datetime(2026, 9, 21, 10, 1)

    update_candle(c, m1, 100.0, is_first_tick_of_day=False)
    check("first tick after a reconnect: open captured but NOT trusted",
          c.open_price == 100.0 and c.observed_from_start is False)

    update_candle(c, m1, 105.0)
    check("later tick in same minute keeps the open", c.open_price == 100.0)

    update_candle(c, m2, 106.0)
    check("new minute: open resets and IS trusted",
          c.open_price == 106.0 and c.observed_from_start is True and c.minute == m2)

    update_candle(c, m1, 50.0)
    check("an older out-of-order tick never rewinds the candle",
          c.open_price == 106.0 and c.minute == m2)

    c2 = CandleState()
    update_candle(c2, m1, 100.0, is_first_tick_of_day=True)
    check("pre-open startup: first tick of the day IS trusted", c2.observed_from_start is True)


def test_result_details():
    print("Trigger details text")
    o = order(volume_cr=6, candle_pct=1.7, combinator="AND")
    now = ist(*MONDAY, 10, 0, 30)
    res = evaluate_auto_order(
        o, current_minute_volume=700_000, ltp=102.0, candle=candle(),
        tick_time=now.replace(tzinfo=None), now=now,
    )
    check("details mention volume, green candle, AND and LTP",
          res is not None and "volume value 7.14 Cr" in res.details
          and "green candle +2.00%" in res.details and " AND " in res.details
          and "LTP 102" in res.details)
    if res:
        print(f"        -> {res.details}")


def test_registry():
    print("Registry")
    auto_trade_registry._registry.clear()

    def fake_order(order_id, symbol="SBIN"):
        return SimpleNamespace(
            id=order_id, client_id="AA0001", trading_symbol=symbol,
            auto_volume_threshold=60_000_000, auto_candle_pct_threshold=None,
            auto_combinator=None, auto_valid_till=None,
        )

    check("empty registry reports no orders", not auto_trade_registry.has_orders())
    auto_trade_registry.add_order(fake_order(1))
    auto_trade_registry.add_order(fake_order(1))  # idempotent
    auto_trade_registry.add_order(fake_order(2))
    auto_trade_registry.add_order(fake_order(3, "TCS"))
    check("re-adding the same order does not duplicate it",
          len(auto_trade_registry.get_orders_for_symbol("SBIN")) == 2)
    check("count() sees all three", auto_trade_registry.count() == 3)
    copy = auto_trade_registry.get_orders_for_symbol("SBIN")
    auto_trade_registry.remove_order(1)
    check("a returned list is a safe copy (unaffected by later removals)", len(copy) == 2)
    check("remove_order removes just that order",
          [s.order_id for s in auto_trade_registry.get_orders_for_symbol("SBIN")] == [2])
    auto_trade_registry.remove_order(3)
    check("symbol with no orders left is dropped", auto_trade_registry.get_orders_for_symbol("TCS") == [])
    auto_trade_registry.remove_order(2)
    check("fully empty again", not auto_trade_registry.has_orders())


def test_scheduler_dates():
    print("Engine scheduler date maths")
    holidays = {"2026-09-22"}  # pretend Tuesday is a holiday
    check("Monday is a trading day", engine_scheduler.is_trading_day(datetime(2026, 9, 21).date(), holidays))
    check("Saturday is not", not engine_scheduler.is_trading_day(datetime(2026, 9, 19).date(), holidays))
    check("a listed holiday is not", not engine_scheduler.is_trading_day(datetime(2026, 9, 22).date(), holidays))

    start, stop = engine_scheduler.next_window(ist(2026, 9, 21, 8, 0), holidays)
    check("Monday 08:00 -> today's window 09:14-15:31",
          (start.hour, start.minute, stop.hour, stop.minute) == (9, 14, 15, 31) and start.day == 21)

    start, stop = engine_scheduler.next_window(ist(2026, 9, 21, 12, 0), holidays)
    check("Monday noon -> today's window (already started: run now)",
          start.day == 21 and start < ist(2026, 9, 21, 12, 0) < stop)

    start, stop = engine_scheduler.next_window(ist(2026, 9, 21, 16, 0), holidays)
    check("Monday 16:00 -> skips holiday Tuesday, next is Wednesday", start.day == 23)

    start, _ = engine_scheduler.next_window(ist(2026, 9, 18, 16, 0), set())  # Friday evening
    check("Friday evening -> next Monday", start.day == 21)

    check("load_holidays copes with a missing file",
          engine_scheduler.load_holidays("/nonexistent/holidays.txt") == set())


def main():
    test_volume_only()
    test_candle_only()
    test_combinators()
    test_window_and_validity()
    test_data_quality_guards()
    test_candle_tracker()
    test_result_details()
    test_registry()
    test_scheduler_dates()

    failed = [name for name, ok in _results if not ok]
    print(f"\n{len(_results) - len(failed)}/{len(_results)} checks passed.")
    if failed:
        print("FAILED:")
        for name in failed:
            print(f"  - {name}")
        sys.exit(1)


if __name__ == "__main__":
    main()
