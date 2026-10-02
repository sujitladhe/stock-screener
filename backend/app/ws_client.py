"""
ws_client.py — connects live_engine.py's tested decision logic to
Ventura's real WebSocket feed. This is the "plumbing" layer; all the
actual decision-making lives in live_engine.py and is already unit
tested against synthetic data.

Auto-reconnect (per requirement 11a): if the connection drops, this
reconnects automatically with a short backoff, rather than requiring
anyone to manually restart the process.

IMPORTANT reconnect nuance: when we reconnect mid-day, the first tick
we see for each stock must NOT be treated as "first tick of the day"
(see live_engine.process_tick's is_first_tick_of_day parameter) — if
it were, we'd wrongly treat the stock's entire day-so-far cumulative
volume as "this minute" and fire a false massive alert. We only pass
is_first_tick_of_day=True on a fresh process start before 9:16 AM;
every reconnect after that treats the first tick as a normal baseline-
setting tick (current behavior when is_first_tick_of_day=False), which
safely "loses" only the partial current minute, not the whole day.

AUTO TRADE (requirement 10) is evaluated on the same ticks, after the
screener and user-alert logic — see _process_auto_trade below. It
places REAL orders, so it is built defensively: it is wrapped so that
no error inside it can ever stop the tick loop, and the actual broker
call runs in a worker thread so it never blocks tick processing.
"""

import asyncio
import json
import traceback
import urllib.parse
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import websockets
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Instrument, VolumeAverage, ScreenerDailyStat, AlertHistoryEntry, Alert
from app import ventura_client
from app import alert_registry
from app import auto_trade_registry
from app import auto_trade_service
from app.alert_engine import evaluate_alert
from app.auto_trade_engine import CandleState, update_candle, evaluate_auto_order
from app.live_engine import StockState, parse_tick, process_tick

WS_BASE_URL = "wss://easeapi-ws.venturasecurities.com/v1/easeapi_mktdata"

RECONNECT_DELAY_SECONDS = 5
MARKET_OPEN_CUTOFF = dtime(9, 16, 0)  # if we connect before this, treat first ticks as day-start

# CRITICAL: don't trust the server's system clock to be IST — a real
# test run caught this being wrong (EC2 defaults to UTC), which caused
# EVERY stock's first tick to be wrongly treated as "day start,"
# reading the stock's entire volume-so-far as "this one minute" and
# firing massive false alerts within seconds of connecting. All time-
# of-day logic in this file must use IST explicitly, never bare
# datetime.now().
IST = ZoneInfo("Asia/Kolkata")

# Strong references to in-flight auto-order tasks. asyncio only keeps a
# weak reference to a task, so without this a placement could in theory
# be garbage-collected halfway through.
_background_tasks: set = set()


def now_ist() -> datetime:
    return datetime.now(IST)


def load_stock_states(db: Session, limit: int | None = None) -> dict:
    """
    Loads every active, mapped NSE/EQ instrument WITH a computed
    average into memory as a StockState, keyed by exchange_token —
    this is the in-memory lookup table the architecture doc calls for,
    avoiding a DB query per tick.
    """
    query = (
        db.query(Instrument, VolumeAverage)
        .join(VolumeAverage, VolumeAverage.instrument_id == Instrument.id)
        .filter(
            Instrument.exchange == "NSE",
            Instrument.instrument_type == "EQ",
            Instrument.is_active == True,  # noqa: E712
        )
    )
    if limit:
        query = query.limit(limit)

    states = {}
    for instrument, avg in query.all():
        states[instrument.exchange_token] = StockState(
            exchange_token=instrument.exchange_token,
            trading_symbol=instrument.trading_symbol,
            avg_volume_per_min=avg.avg_volume_per_min,
        )
    return states


def save_alert(db: Session, alert, instrument_id: int):
    """
    Upserts into screener_daily_stats: if this stock already has a row
    for today, increments occurrence_count and updates the "last"
    snapshot fields. Otherwise creates the first row for the day with
    occurrence_count=1. This is what keeps the table's size bounded —
    a stock triggering 20 times in one session is still just ONE row,
    not 20.

    Per an explicit product decision: individual occurrences are NOT
    logged one-per-row here (that would grow the table unboundedly) —
    the live browser feed shows every occurrence as it happens (an
    in-memory, frontend-only concern), but a page refresh only ever
    shows this row's latest snapshot, by design.
    """
    trade_date = alert.triggered_at.date()

    existing = (
        db.query(ScreenerDailyStat)
        .filter_by(instrument_id=instrument_id, trade_date=trade_date)
        .first()
    )

    if existing:
        existing.occurrence_count += 1
        existing.last_triggered_at = alert.triggered_at
        existing.last_current_minute_volume = alert.current_minute_volume
        existing.last_avg_volume_per_min = alert.avg_volume_per_min
        existing.last_multiple = alert.multiple
        existing.last_value = alert.value
        existing.last_ltp = alert.ltp
        existing.last_prev_close = alert.prev_close
        existing.last_condition_matched = alert.condition_matched
        occurrence_count = existing.occurrence_count
    else:
        occurrence_count = 1
        db.add(ScreenerDailyStat(
            instrument_id=instrument_id,
            trading_symbol=alert.trading_symbol,
            trade_date=trade_date,
            occurrence_count=1,
            first_triggered_at=alert.triggered_at,
            last_triggered_at=alert.triggered_at,
            last_current_minute_volume=alert.current_minute_volume,
            last_avg_volume_per_min=alert.avg_volume_per_min,
            last_multiple=alert.multiple,
            last_value=alert.value,
            last_ltp=alert.ltp,
            last_prev_close=alert.prev_close,
            last_condition_matched=alert.condition_matched,
        ))

    db.commit()
    return occurrence_count


async def run_engine(limit: int = None, on_alert=None, on_user_alert=None):
    """
    Main entry point: loads state, connects, processes ticks forever,
    reconnecting automatically on any disconnect.

    on_alert: an optional async callback, called with a dict of
    SCREENER alert details every time one fires — broadcast to every
    connected browser (shared feed).

    on_user_alert: an optional async callback, called with
    (client_id, dict of alert details) every time a PERSONAL user
    alert fires — delivered ONLY to that specific user, never
    broadcast. The same callback also carries AUTO-TRADE results
    (message type "auto_trade") to the order's owner. Both callbacks
    exist rather than importing FastAPI/WebSocket code directly into
    this module, so the engine can still run standalone
    (scripts/run_live_engine.py) without a web-server dependency.
    """
    db = SessionLocal()
    try:
        states = load_stock_states(db, limit=limit)
        print(f"Loaded {len(states)} stocks into memory.")

        alert_registry.load_all(SessionLocal)

        # Auto trade start-up. Each step is isolated so that a problem
        # here can never stop the screener itself from starting.
        try:
            recovered = auto_trade_service.recover_interrupted_orders()
            if recovered:
                print(f"[{now_ist()}] Marked {recovered} interrupted auto order(s) as Rejected (unconfirmed).")
        except Exception as e:
            print(f"[{now_ist()}] Auto-trade recovery step failed: {e!r}")
        try:
            auto_trade_registry.load_all(SessionLocal)
        except Exception as e:
            print(f"[{now_ist()}] Could not load auto orders: {e!r}")
        try:
            # Blocking (network logins), so run it off the event loop.
            await asyncio.to_thread(auto_trade_service.prewarm_sessions)
        except Exception as e:
            print(f"[{now_ist()}] Auto-trade session pre-warm failed: {e!r}")

        token_to_instrument_id = {
            inst.exchange_token: inst.id
            for inst in db.query(Instrument).filter(Instrument.exchange_token.in_(states.keys())).all()
        }

        is_startup_before_market_open = now_ist().time() < MARKET_OPEN_CUTOFF
        seen_tokens_this_run = set()  # tracks which stocks we've received at least one tick for, THIS process run

        while True:  # reconnect loop
            try:
                await _connect_and_listen(
                    states, token_to_instrument_id, db,
                    is_startup_before_market_open, seen_tokens_this_run,
                    on_alert=on_alert,
                    on_user_alert=on_user_alert,
                )
            except (websockets.exceptions.ConnectionClosed, ConnectionError, OSError) as e:
                print(f"[{now_ist()}] Connection lost ({e}). Reconnecting in {RECONNECT_DELAY_SECONDS}s...")
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)
            # After the FIRST connection attempt, a reconnect should never treat a
            # stock's first-seen tick as day-start, even if the process itself
            # started before market open — seen_tokens_this_run already prevents
            # this correctly (a token only gets the day-start treatment once, on
            # its true first tick of the whole run).
    finally:
        db.close()


async def _print_heartbeat(states: dict, tick_counter: dict, interval_seconds: int = 60):
    """
    Runs alongside the tick loop and periodically prints proof of life
    — total ticks received, and the stocks currently closest to
    triggering (by current-minute multiple of their average). This
    exists specifically so "no alerts yet" can be told apart from
    "silently not receiving any data" — a real gap noticed when a
    200-stock, 10-minute test produced no alerts and no way to tell
    which of those two situations it actually was.
    """
    while True:
        await asyncio.sleep(interval_seconds)

        ticks_since_last = tick_counter["count"]
        tick_counter["count"] = 0

        # Compute each tracked stock's current-minute multiple, for
        # any stock that has at least started a minute (current_minute
        # is set once the first tick arrives).
        live_multiples = []
        for state in states.values():
            if state.current_minute is None or state.latest_volume is None or state.volume_at_minute_start is None:
                continue
            current_minute_volume = state.latest_volume - state.volume_at_minute_start
            avg = float(state.avg_volume_per_min)
            if avg > 0:
                live_multiples.append((state.trading_symbol, current_minute_volume / avg))

        live_multiples.sort(key=lambda x: x[1], reverse=True)
        top5 = ", ".join(f"{sym} ({mult:.1f}x)" for sym, mult in live_multiples[:5])

        print(f"[{now_ist()}] Heartbeat: {ticks_since_last} ticks in last {interval_seconds}s, "
              f"{len(live_multiples)}/{len(states)} stocks with live data. "
              f"Closest to triggering: {top5 if top5 else '(none yet)'}. "
              f"Active auto orders: {auto_trade_registry.count()}")


def _process_auto_trade(state, tick, candle_states: dict, is_first_tick_of_day: bool, on_user_alert):
    """
    Auto-trade step for ONE tick (requirement 10). Synchronous and
    fast: it only updates the stock's candle tracker, and — if this
    stock has active auto orders — evaluates them. The slow part (the
    broker call) is handed to a background task, never awaited here.

    `state` is the stock's StockState AFTER process_tick has already
    processed this same tick, so state.ltp / latest_volume /
    volume_at_minute_start are current.
    """
    candle = candle_states.get(tick.exchange_token)
    if candle is None:
        candle = CandleState()
        candle_states[tick.exchange_token] = candle
    minute = tick.timestamp.replace(second=0, microsecond=0)
    update_candle(candle, minute, tick.ltp, is_first_tick_of_day)

    if not auto_trade_registry.has_orders():
        return
    orders = auto_trade_registry.get_orders_for_symbol(state.trading_symbol)
    if not orders:
        return

    if state.latest_volume is None or state.volume_at_minute_start is None:
        return
    current_minute_volume = state.latest_volume - state.volume_at_minute_start
    now = now_ist()

    for order_state in orders:
        result = evaluate_auto_order(
            order_state,
            current_minute_volume=current_minute_volume,
            ltp=state.ltp,
            candle=candle,
            tick_time=tick.timestamp,
            now=now,
        )
        if result is None:
            continue

        # Claim it in memory FIRST, synchronously, before any await:
        # the very next tick for this stock can't fire it a second time.
        auto_trade_registry.remove_order(order_state.order_id)
        print(f"[{now_ist()}] AUTO TRADE TRIGGERED: order {order_state.order_id} "
              f"{order_state.trading_symbol} for client {order_state.client_id} — {result.details}")

        task = asyncio.create_task(_execute_auto_order_and_notify(order_state, result.details, on_user_alert))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


async def _execute_auto_order_and_notify(order_state, trigger_details: str, on_user_alert):
    """
    Places the triggered order in a worker thread, then tells the
    order's owner (and only them) what happened — success or failure.
    """
    try:
        outcome = await asyncio.to_thread(
            auto_trade_service.execute_auto_order, order_state.order_id, trigger_details
        )
    except Exception as e:
        traceback.print_exc()
        outcome = {
            "outcome": "failed",
            "order_id": order_state.order_id,
            "client_id": order_state.client_id,
            "trading_symbol": order_state.trading_symbol,
            "message": f"Unexpected error while placing the order: {e}",
            "trigger_details": trigger_details,
        }

    print(f"[{now_ist()}] AUTO TRADE RESULT: order {order_state.order_id} "
          f"{order_state.trading_symbol} -> {outcome.get('outcome')} "
          f"({outcome.get('message')}) broker_order_no={outcome.get('broker_order_no')}")

    if outcome.get("outcome") == "skipped":
        return  # nothing was sent (e.g. cancelled at the same instant) — nothing to notify

    if on_user_alert:
        try:
            await on_user_alert(order_state.client_id, {
                "type": "auto_trade",
                "outcome": outcome.get("outcome"),          # "success" | "failed"
                "order_id": outcome.get("order_id"),
                "trading_symbol": outcome.get("trading_symbol"),
                "transaction_type": outcome.get("transaction_type"),
                "quantity": outcome.get("quantity"),
                "broker_order_no": outcome.get("broker_order_no"),
                "message": outcome.get("message"),
                "trigger_details": outcome.get("trigger_details"),
            })
        except Exception as e:
            print(f"[{now_ist()}] Could not deliver auto-trade notification: {e!r}")


async def _connect_and_listen(states, token_to_instrument_id, db, is_startup_before_market_open, seen_tokens_this_run, on_alert=None, on_user_alert=None):
    token_data = ventura_client.login(
        app_key=settings.ventura_service_app_key,
        app_secret=settings.ventura_service_app_secret,
        client_id=settings.ventura_service_client_id,
        pin=settings.ventura_service_pin,
        totp_secret=settings.ventura_service_totp_secret,
    )
    auth_token = token_data["auth_token"]

    query = urllib.parse.urlencode({
        "app_key": settings.ventura_service_app_key,
        "client_id": settings.ventura_service_client_id,
        "authorization": auth_token,
    })
    url = f"{WS_BASE_URL}?{query}"

    print(f"[{now_ist()}] Connecting...")
    async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
        print(f"[{now_ist()}] Connected. Subscribing to {len(states)} stocks in batches...")

        # A real full-scale test confirmed Ventura's WebSocket rejects
        # (or the connection dies from) a single subscribe message
        # listing all ~2,655 tokens at once — it disconnected ~280ms
        # after every such attempt, consistently, which points to a
        # real undocumented limit rather than random network flakiness.
        # 200 tokens in one message was confirmed working in an earlier
        # test, so we batch conservatively below that, with a short
        # pause between batches, and log progress so a failure at some
        # cumulative count (rather than per-batch) is visible — that
        # would point to a total per-connection cap instead of a
        # per-message one, which would need a different fix (multiple
        # connections, as we did for Angel One).
        all_tokens = list(states.keys())
        batch_size = 150
        for i in range(0, len(all_tokens), batch_size):
            batch = all_tokens[i:i + batch_size]
            subscribe_msg = {"actions": ["nse:ltp"], "token": batch, "mode": "sub"}
            await ws.send(json.dumps(subscribe_msg))
            print(f"[{now_ist()}] Subscribed batch {i // batch_size + 1} "
                  f"({i + len(batch)}/{len(all_tokens)} tokens total)")
            await asyncio.sleep(0.3)

        print(f"[{now_ist()}] All batches sent.")

        tick_counter = {"count": 0}
        heartbeat_task = asyncio.create_task(_print_heartbeat(states, tick_counter))

        # Auto-trade candle trackers are per CONNECTION on purpose: after
        # a reconnect we may have missed ticks, so every stock's first
        # minute on the new connection is treated as "not observed from
        # its start" and skipped for auto trade (see auto_trade_engine).
        candle_states = {}

        try:
            async for raw_message in ws:
                try:
                    message = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue

                tick = parse_tick(message)
                if tick is None:
                    continue

                tick_counter["count"] += 1

                state = states.get(tick.exchange_token)
                if state is None:
                    continue  # a tick for a token we don't track (shouldn't normally happen)

                is_first_tick_of_day = (
                    is_startup_before_market_open
                    and tick.exchange_token not in seen_tokens_this_run
                )
                seen_tokens_this_run.add(tick.exchange_token)

                alert = process_tick(state, tick, is_first_tick_of_day=is_first_tick_of_day)
                if alert:
                    instrument_id = token_to_instrument_id.get(tick.exchange_token)
                    print(f"[{now_ist()}] ALERT: {alert.trading_symbol} — {alert.condition_matched} "
                          f"— {alert.multiple}x avg, value Rs.{alert.value:,.0f}, LTP {alert.ltp}")
                    if instrument_id:
                        occurrence_count = save_alert(db, alert, instrument_id)
                        if on_alert:
                            # Field names deliberately match GET /screener/today's
                            # response shape exactly (e.g. "last_triggered_at", not
                            # "triggered_at") — a real bug was caught where a mismatch
                            # here caused the frontend to lose fields on a live update.
                            await on_alert({
                                "trading_symbol": alert.trading_symbol,
                                "ltp": alert.ltp,
                                "multiple": float(alert.multiple),
                                "value": float(alert.value),
                                "current_minute_volume": alert.current_minute_volume,
                                "avg_volume_per_min": float(alert.avg_volume_per_min),
                                "prev_close": alert.prev_close,
                                "condition_matched": alert.condition_matched,
                                "occurrence_count": occurrence_count,
                                "last_triggered_at": alert.triggered_at.isoformat(),
                            })

                # User-defined alerts (requirement 9) — checked independently
                # of the screener's own conditions, using the SAME already-
                # updated state (state.ltp is current as of this tick).
                # NOTE: only stocks with a computed average are in `states`
                # at all (see load_stock_states) — a stock listed too
                # recently to have one yet won't be checked here. Given
                # averages run weekly across the whole universe, this only
                # affects a handful of brand-new listings, not a general gap.
                alerts_for_symbol = alert_registry.get_alerts_for_symbol(state.trading_symbol)
                if alerts_for_symbol:
                    current_minute_volume = state.latest_volume - state.volume_at_minute_start
                    current_value = current_minute_volume * state.ltp
                    for alert_state in alerts_for_symbol:
                        fired = evaluate_alert(alert_state, current_price=state.ltp, current_value=current_value)
                        if fired:
                            summary_parts = [f"{alert_state.condition_1_metric} {alert_state.condition_1_operator} {alert_state.condition_1_threshold}"]
                            if alert_state.condition_2_metric:
                                summary_parts.append(f"{alert_state.combinator} {alert_state.condition_2_metric} {alert_state.condition_2_operator} {alert_state.condition_2_threshold}")
                            condition_summary = " ".join(summary_parts)

                            print(f"[{now_ist()}] USER ALERT fired: {state.trading_symbol} for client {alert_state.client_id} — {condition_summary}")

                            db.add(AlertHistoryEntry(
                                alert_id=alert_state.alert_id,
                                client_id=alert_state.client_id,
                                trading_symbol=state.trading_symbol,
                                triggered_at=tick.timestamp,
                                price_at_trigger=state.ltp,
                                value_at_trigger=current_value,
                                condition_summary=condition_summary,
                            ))

                            # One-shot alerts, per an explicit product decision: once
                            # fired, deactivate permanently — both in the DB (so it
                            # shows as inactive/"fired" in the UI) and in the live
                            # in-memory registry (so it stops being checked on
                            # subsequent ticks immediately, not just after the next
                            # engine restart).
                            alert_row = db.query(Alert).filter_by(id=alert_state.alert_id).first()
                            if alert_row:
                                alert_row.is_active = False
                            db.commit()
                            alert_registry.remove_alert(alert_state.alert_id)

                            if on_user_alert:
                                await on_user_alert(alert_state.client_id, {
                                    "alert_id": alert_state.alert_id,
                                    "trading_symbol": state.trading_symbol,
                                    "ltp": state.ltp,
                                    "value": current_value,
                                    "condition_summary": condition_summary,
                                    "sound_enabled": alert_state.sound_enabled,
                                    "triggered_at": tick.timestamp.isoformat(),
                                })

                # Auto trade (requirement 10). Wrapped so that NO error in
                # here can ever kill the tick loop — an earlier bug in the
                # alert path did exactly that (see handoff Section 6), and
                # this path is not allowed to repeat it.
                try:
                    _process_auto_trade(state, tick, candle_states, is_first_tick_of_day, on_user_alert)
                except Exception:
                    print(f"[{now_ist()}] AUTO TRADE evaluation error for {state.trading_symbol}:")
                    traceback.print_exc()
        finally:
            heartbeat_task.cancel()
