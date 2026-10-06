"""
ws_client.py — connects live_engine.py to Ventura's real WebSocket feed.

Changes in 0004:
  - save_alert() now accepts candle_pct and circuit_pct; returns (count, is_new).
  - When a stock fires for the first time today (is_new), its circuit % is
    fetched from Ventura's OHLCV API in a worker thread and stored in the row.
  - The screener broadcast payload now includes candle_pct and circuit_pct.
  - expire_daily_auto_orders() is called on engine start so "today only" orders
    from previous trading days are cancelled before loading the registry.
  - evaluate_auto_order() is called with prev_close so day_high_pct_limit works.
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
MARKET_OPEN_CUTOFF = dtime(9, 16, 0)

IST = ZoneInfo("Asia/Kolkata")

_background_tasks: set = set()


def now_ist() -> datetime:
    return datetime.now(IST)


def load_stock_states(db: Session, limit: int | None = None) -> dict:
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


def save_alert(
    db: Session,
    alert,
    instrument_id: int,
    candle_pct: float | None = None,
    circuit_pct: int | None = None,
) -> tuple[int, bool]:
    """
    Upserts the screener daily stat row.
    Returns (occurrence_count, is_new_today).
    is_new_today is True only for the very first alert for this stock today —
    the caller uses this to decide whether to fetch circuit limits from Ventura.
    """
    trade_date = alert.triggered_at.date()
    existing = (
        db.query(ScreenerDailyStat)
        .filter_by(instrument_id=instrument_id, trade_date=trade_date)
        .first()
    )
    is_new = existing is None

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
        existing.last_candle_pct = candle_pct
        # Only overwrite circuit_pct if we actually fetched a new value.
        if circuit_pct is not None:
            existing.last_circuit_pct = circuit_pct
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
            last_candle_pct=candle_pct,
            last_circuit_pct=circuit_pct,
        ))

    db.commit()
    # return occurrence_count, is_new
    return occurrence_count, is_new, (existing.last_circuit_pct if existing else None)


def _update_circuit_pct_in_db(db: Session, instrument_id: int, trade_date, circuit_pct: int) -> None:
    """Stores a freshly-fetched circuit % on the row created seconds ago by save_alert."""
    try:
        db.query(ScreenerDailyStat).filter_by(
            instrument_id=instrument_id, trade_date=trade_date
        ).update({"last_circuit_pct": circuit_pct})
        db.commit()
    except Exception as e:
        print(f"[ws_client] Could not persist circuit_pct={circuit_pct}: {e}")
        db.rollback()


async def run_engine(limit: int = None, on_alert=None, on_user_alert=None):
    db = SessionLocal()
    try:
        states = load_stock_states(db, limit=limit)
        print(f"Loaded {len(states)} stocks into memory.")

        alert_registry.load_all(SessionLocal)

        # --- Auto trade startup sequence ---
        try:
            recovered = auto_trade_service.recover_interrupted_orders()
            if recovered:
                print(f"[{now_ist()}] Marked {recovered} interrupted auto order(s) as Rejected.")
        except Exception as e:
            print(f"[{now_ist()}] Auto-trade recovery step failed: {e!r}")

        # NEW (0004): expire "today only" orders from previous trading days.
        try:
            expired = auto_trade_service.expire_daily_auto_orders()
            if expired:
                print(f"[{now_ist()}] Expired {expired} today-only auto order(s) from previous days.")
        except Exception as e:
            print(f"[{now_ist()}] Auto-trade daily expiry step failed: {e!r}")

        try:
            auto_trade_registry.load_all(SessionLocal)
        except Exception as e:
            print(f"[{now_ist()}] Could not load auto orders: {e!r}")
        try:
            await asyncio.to_thread(auto_trade_service.prewarm_sessions)
        except Exception as e:
            print(f"[{now_ist()}] Auto-trade session pre-warm failed: {e!r}")

        token_to_instrument_id = {
            inst.exchange_token: inst.id
            for inst in db.query(Instrument).filter(Instrument.exchange_token.in_(states.keys())).all()
        }

        is_startup_before_market_open = now_ist().time() < MARKET_OPEN_CUTOFF
        seen_tokens_this_run = set()

        while True:
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
    finally:
        db.close()


async def _print_heartbeat(states: dict, tick_counter: dict, interval_seconds: int = 60):
    while True:
        await asyncio.sleep(interval_seconds)

        ticks_since_last = tick_counter["count"]
        tick_counter["count"] = 0

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
            prev_close=state.prev_close,  # NEW (0004) — enables day_high_pct_limit check
        )
        if result is None:
            continue

        auto_trade_registry.remove_order(order_state.order_id)
        print(f"[{now_ist()}] AUTO TRADE TRIGGERED: order {order_state.order_id} "
              f"{order_state.trading_symbol} for client {order_state.client_id} — {result.details}")

        task = asyncio.create_task(_execute_auto_order_and_notify(order_state, result.details, on_user_alert))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


async def _execute_auto_order_and_notify(order_state, trigger_details: str, on_user_alert):
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
          f"broker_order_no={outcome.get('broker_order_no')}")

    if outcome.get("outcome") == "skipped":
        return

    if on_user_alert:
        try:
            await on_user_alert(order_state.client_id, {
                "type": "auto_trade",
                "outcome": outcome.get("outcome"),
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


async def _connect_and_listen(
    states, token_to_instrument_id, db,
    is_startup_before_market_open, seen_tokens_this_run,
    on_alert=None, on_user_alert=None,
):
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

        # Per-connection candle states for auto trade (and now candle_pct broadcast).
        # Reset on reconnect so mid-minute candles aren't trusted.
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
                    continue

                is_first_tick_of_day = (
                    is_startup_before_market_open
                    and tick.exchange_token not in seen_tokens_this_run
                )
                seen_tokens_this_run.add(tick.exchange_token)

                alert = process_tick(state, tick, is_first_tick_of_day=is_first_tick_of_day)

                if alert:
                    instrument_id = token_to_instrument_id.get(tick.exchange_token)

                    # --- Compute current-minute candle % (green candles only). ---
                    # We use the same candle_states dict that auto trade maintains.
                    # update_candle hasn't been called for this tick yet (that happens
                    # in _process_auto_trade below), so we look at the LAST completed
                    # state. For the very first tick in a minute the open equals LTP,
                    # giving 0% — acceptable; the tag appears from the second tick onward.
                    candle = candle_states.get(tick.exchange_token)
                    candle_pct = None
                    if (
                        candle
                        and candle.open_price
                        and candle.open_price > 0
                        and candle.observed_from_start
                        and tick.ltp > candle.open_price
                    ):
                        candle_pct = round(
                            (tick.ltp - candle.open_price) / candle.open_price * 100, 2
                        )

                    if instrument_id:
                        # occurrence_count, is_new = save_alert(
                        #     db, alert, instrument_id,
                        #     candle_pct=candle_pct,
                        #     circuit_pct=None,  # filled in asynchronously below if is_new
                        # )
                        occurrence_count, is_new, circuit_pct = save_alert(
                            db, alert, instrument_id, 
                            candle_pct=candle_pct
                        )


                        # Fetch circuit limits from Ventura for the first occurrence today.
                        # Run in a worker thread so the tick loop isn't blocked by the HTTP call.
                        # circuit_pct = None
                        if is_new and tick.prev_close and tick.prev_close > 0:
                            try:
                                circuit_pct = await asyncio.to_thread(
                                    ventura_client.fetch_circuit_pct,
                                    tick.exchange_token,
                                    tick.prev_close,
                                    settings.ventura_service_app_key,
                                    settings.ventura_service_client_id,
                                    auth_token,
                                )
                                if circuit_pct is not None:
                                    _update_circuit_pct_in_db(
                                        db, instrument_id,
                                        alert.triggered_at.date(),
                                        circuit_pct,
                                    )
                            except Exception as e:
                                print(f"[{now_ist()}] Circuit fetch failed for "
                                      f"{alert.trading_symbol}: {e}")

                        print(f"[{now_ist()}] ALERT: {alert.trading_symbol} — "
                              f"{alert.condition_matched} — {alert.multiple}x avg, "
                              f"value Rs.{alert.value:,.0f}, LTP {alert.ltp}, "
                              f"candle_pct={candle_pct}, circuit_pct={circuit_pct}")

                        if on_alert:
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
                                # NEW (0004)
                                "candle_pct": candle_pct,
                                "circuit_pct": circuit_pct,
                            })

                # --- User-defined alerts (requirement 9) ---
                alerts_for_symbol = alert_registry.get_alerts_for_symbol(state.trading_symbol)
                if alerts_for_symbol:
                    current_minute_volume = (
                        (state.latest_volume or 0) - (state.volume_at_minute_start or 0)
                    )
                    current_value = current_minute_volume * state.ltp
                    for alert_state in alerts_for_symbol:
                        fired = evaluate_alert(
                            alert_state,
                            current_price=state.ltp,
                            current_value=current_value,
                        )
                        if fired:
                            summary_parts = [
                                f"{alert_state.condition_1_metric} "
                                f"{alert_state.condition_1_operator} "
                                f"{alert_state.condition_1_threshold}"
                            ]
                            if alert_state.condition_2_metric:
                                summary_parts.append(
                                    f"{alert_state.combinator} "
                                    f"{alert_state.condition_2_metric} "
                                    f"{alert_state.condition_2_operator} "
                                    f"{alert_state.condition_2_threshold}"
                                )
                            condition_summary = " ".join(summary_parts)

                            print(f"[{now_ist()}] USER ALERT fired: "
                                  f"{state.trading_symbol} for client {alert_state.client_id}")

                            db.add(AlertHistoryEntry(
                                alert_id=alert_state.alert_id,
                                client_id=alert_state.client_id,
                                trading_symbol=state.trading_symbol,
                                triggered_at=tick.timestamp,
                                price_at_trigger=state.ltp,
                                value_at_trigger=current_value,
                                condition_summary=condition_summary,
                            ))

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

                # --- Auto trade (requirement 10) ---
                try:
                    _process_auto_trade(
                        state, tick, candle_states, is_first_tick_of_day, on_user_alert
                    )
                except Exception:
                    print(f"[{now_ist()}] AUTO TRADE evaluation error for "
                          f"{state.trading_symbol}:")
                    traceback.print_exc()
        finally:
            heartbeat_task.cancel()
