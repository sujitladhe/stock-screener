"""
guidance.py — the STATEFUL Guidance Engine (a scoring engine, not a prediction
engine — every call can be traced back to a specific rule).

What changed compared with the old tick-by-tick version
-------------------------------------------------------
  * It now has MEMORY (app/options/history.py): every decision compares the
    latest 1-minute snapshot with snapshots from 5 / 10 / 15 minutes ago.
  * It decides only every 5 minutes (the router calls evaluate()); the fake
    spike scan is lighter and runs every minute (update_spikes()).
  * SMOOTHING   – PCR, IV, skew and max pain are averaged over the last
                  SMOOTH_BUCKETS one-minute snapshots, never a single reading.
  * HYSTERESIS  – the bias only changes after the new bias has been proposed
                  CONFIRM_CYCLES evaluations in a row, and a standing bias
                  needs a clearly weaker score (not just the threshold) to
                  be dropped.
  * CONFIRMED OPPORTUNITIES – a card appears only after it persisted for
                  OPP_APPEAR cycles and is removed only after it has been
                  missing for OPP_DISAPPEAR cycles.
  * OI CLASSIFICATION is per strike: option PRICE change vs OI change over the
                  look-back window (long buildup, short buildup, short
                  covering, long unwinding) — no more global "down day" guess.
  * IV uses a real Black-Scholes solve with the true time to expiry.
  * Fake spike = OI surge over the last ~10 minutes (not vs yesterday).

Scoring (same structure as the original design, range -5 .. +5):
  PCR            : +-1 (0.85 / 1.15), +-2 at extremes (0.70 / 1.30)
  IV skew        : +-1 (beyond +-1.5)
  OI class count : +-1
  Spot vs pain   : +-1 (with a small dead zone)
  ATM IV level   : flag only (no vote)
  Bias: score <= -3 Bearish, >= +3 Bullish, otherwise Neutral/Range.

All the tunable numbers are in the CONSTANTS block just below.
"""

import logging
import math
from datetime import datetime, date, time as dtime
from statistics import mean, median
from typing import Dict, List, Optional, Tuple

from app.options.history import HistoryStore, history, STRIKE_STEP

logger = logging.getLogger(__name__)

# ============================== CONSTANTS ===================================
DECISION_RANGE_PTS = 1000     # strikes within +/- this of spot are used for decisions
EVAL_EVERY_MIN = 5            # full decision cadence (minutes)
SMOOTH_BUCKETS = 5            # 1-minute snapshots averaged for PCR / IV / skew / pain
OI_WINDOW_MIN = 15            # look-back for per-strike OI classification
SPIKE_WINDOW_MIN = 10         # look-back for the fake-spike OI surge

CONFIRM_CYCLES = 2            # evaluations a NEW bias must hold before it is adopted
BIAS_ENTER = 3                # |score| needed to enter Bullish/Bearish
BIAS_STAY = 2                 # a standing Bullish/Bearish bias holds until |score| < this

OPP_APPEAR = 2                # cycles an opportunity must persist before it is shown
OPP_DISAPPEAR = 3             # cycles it must be missing before it is removed
SPIKE_APPEAR = 1              # spikes are time-sensitive: shown immediately
SPIKE_DISAPPEAR = 2
MAX_OPPS = 3                  # top opportunities shown

PCR_BEAR, PCR_BULL = 0.85, 1.15
PCR_STRONG_BEAR, PCR_STRONG_BULL = 0.70, 1.30
SKEW_THRESHOLD = 1.5
MAXPAIN_MARGIN = 50           # dead zone around max pain (points)
IV_HIGH, IV_LOW = 20.0, 11.0

# per-strike OI classification
OI_MIN_PCT = 1.0              # OI must change by at least this % in the window
PX_MIN_PCT = 1.0              # option price must change by at least this %
PX_MIN_ABS = 0.05             # ... and at least one tick
MIN_OI_FOR_CLASS = 20_000     # ignore strikes with tiny open interest
VOTE_MARGIN_MIN = 3           # OI-class vote needs a lead of at least this many rows
VOTE_MARGIN_PCT = 0.15        # ... or this share of all classified rows

# fake spike (all three must be true)
SPIKE_OTM_MIN_PTS = 200
SPIKE_OI_SURGE_PCT = 4.0
SPIKE_VOI_MIN = 0.6

# selling opportunities
MIN_SELL_DIST = 50
CE_WALL_OI_MIN = 40_000
PE_WALL_OI_MIN = 50_000
VOI_MAX_FOR_SELL = 0.55
MIN_OPP_CONF = 55
# ============================================================================

# ---------------------------------------------------------------------------
# Black-Scholes implied volatility (r = 0), solved by bisection
# ---------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_price(spot: float, strike: float, t: float, vol: float, is_call: bool) -> float:
    sd = vol * math.sqrt(t)
    if sd <= 0:
        return max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)
    d1 = (math.log(spot / strike) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    if is_call:
        return spot * _norm_cdf(d1) - strike * _norm_cdf(d2)
    return strike * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def implied_vol(price, spot, strike, t, is_call) -> Optional[float]:
    """Annualised IV in percent, or None if it cannot be solved sensibly."""
    if not price or price <= 0 or spot <= 0 or strike <= 0 or t <= 0:
        return None
    intrinsic = max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)
    if price < intrinsic - 1e-6:
        return None
    lo, hi = 0.01, 3.0
    if _bs_price(spot, strike, t, lo, is_call) > price:
        return None
    if _bs_price(spot, strike, t, hi, is_call) < price:
        return None
    for _ in range(50):
        mid = (lo + hi) / 2.0
        if _bs_price(spot, strike, t, mid, is_call) < price:
            lo = mid
        else:
            hi = mid
    return round(((lo + hi) / 2.0) * 100.0, 2)


def years_to_expiry(ts: datetime, expiry_iso: str) -> float:
    end = datetime.combine(date.fromisoformat(expiry_iso), dtime(15, 30))
    secs = max((end - ts).total_seconds(), 3600.0)   # never less than 1 hour
    return secs / (365.0 * 86400.0)


# ---------------------------------------------------------------------------
# Per-bucket metrics and smoothing
# ---------------------------------------------------------------------------

def compute_max_pain(strikes: dict) -> Optional[int]:
    keys = sorted(strikes.keys())
    if not keys:
        return None
    total_oi = sum((strikes[k].get("ce_oi") or 0) + (strikes[k].get("pe_oi") or 0) for k in keys)
    if total_oi <= 0:
        return None
    best, best_loss = None, None
    for target in keys:
        loss = 0
        for s in keys:
            e = strikes[s]
            if target > s:
                loss += (target - s) * (e.get("ce_oi") or 0)
            elif target < s:
                loss += (s - target) * (e.get("pe_oi") or 0)
        if best_loss is None or loss < best_loss:
            best_loss, best = loss, target
    return best


def _iv_of(entry: Optional[dict], side: str, spot: float, strike: int, t: float) -> Optional[float]:
    if not entry:
        return None
    return implied_vol(entry.get(f"{side}_ltp"), spot, strike, t, side == "ce")


def bucket_metrics(b: dict) -> dict:
    spot, strikes = b["spot"], b["strikes"]
    lo, hi = spot - DECISION_RANGE_PTS, spot + DECISION_RANGE_PTS
    ce_tot = pe_tot = 0
    for k, e in strikes.items():
        if lo <= k <= hi:
            ce_tot += e.get("ce_oi") or 0
            pe_tot += e.get("pe_oi") or 0
    pcr = (pe_tot / ce_tot) if ce_tot > 0 else None

    atm = int(round(spot / STRIKE_STEP) * STRIKE_STEP)
    t = years_to_expiry(b["ts"], b["expiry"])

    ivs = []
    atm_entry = strikes.get(atm)
    for side in ("ce", "pe"):
        v = _iv_of(atm_entry, side, spot, atm, t)
        if v is not None:
            ivs.append(v)
    atm_iv = (sum(ivs) / len(ivs)) if ivs else None

    skew = None
    for d in (150, 100, 50):
        pe_iv = _iv_of(strikes.get(atm - d), "pe", spot, atm - d, t)
        ce_iv = _iv_of(strikes.get(atm + d), "ce", spot, atm + d, t)
        if pe_iv is not None and ce_iv is not None:
            skew = pe_iv - ce_iv
            break

    return {"pcr": pcr, "max_pain": compute_max_pain(strikes), "atm_iv": atm_iv, "iv_skew": skew}


def smoothed_metrics(buckets: List[dict]) -> dict:
    ms = [bucket_metrics(b) for b in buckets]

    def avg(key, nd):
        vals = [m[key] for m in ms if m.get(key) is not None]
        return round(mean(vals), nd) if vals else None

    mp = [m["max_pain"] for m in ms if m.get("max_pain")]
    max_pain = int(round(median(mp) / STRIKE_STEP) * STRIKE_STEP) if mp else None
    return {
        "pcr": avg("pcr", 3), "atm_iv": avg("atm_iv", 2), "iv_skew": avg("iv_skew", 2),
        "max_pain": max_pain, "n": len(ms),
    }


# ---------------------------------------------------------------------------
# Per-strike OI classification (price change vs OI change over the window)
# ---------------------------------------------------------------------------
# (price direction, OI direction) -> (label, css class, direction vote)
_CE_MAP = {
    ("up", "up"):     ("BULL", "bull", +1),   # call buyers adding
    ("down", "up"):   ("TRAP", "trap", -1),   # call writers adding = resistance
    ("up", "down"):   ("SCOV", "scov", +1),   # call writers covering
    ("down", "down"): ("UWD",  "uwd",   0),   # call buyers leaving
}
_PE_MAP = {
    ("up", "up"):     ("BEAR", "bear", -1),   # put buyers adding
    ("down", "up"):   ("SUPT", "bull", +1),   # put writers adding = support
    ("up", "down"):   ("PCOV", "bear", -1),   # put writers covering
    ("down", "down"): ("UWD",  "uwd",   0),   # put buyers leaving
}


def classify_side(side, oi_now, oi_then, px_now, px_then) -> Optional[dict]:
    if oi_now is None or oi_then is None or oi_then <= 0 or oi_now < MIN_OI_FOR_CLASS:
        return None
    oi_chg_pct = (oi_now - oi_then) / oi_then * 100.0
    out = {"label": None, "css": None, "vote": 0,
           "oi_chg_pct": round(oi_chg_pct, 2), "px_chg_pct": None}
    if px_now is None or px_then is None or px_then <= 0:
        return out
    px_chg = px_now - px_then
    px_pct = px_chg / px_then * 100.0
    out["px_chg_pct"] = round(px_pct, 2)

    oi_dir = "up" if oi_chg_pct >= OI_MIN_PCT else "down" if oi_chg_pct <= -OI_MIN_PCT else None
    if abs(px_chg) >= PX_MIN_ABS and abs(px_pct) >= PX_MIN_PCT:
        px_dir = "up" if px_chg > 0 else "down"
    else:
        px_dir = None
    if oi_dir is None or px_dir is None:
        return out
    label, css, vote = (_CE_MAP if side == "ce" else _PE_MAP)[(px_dir, oi_dir)]
    out.update({"label": label, "css": css, "vote": vote})
    return out


def compute_strike_signals(new: dict, old: dict):
    """Returns ({strike: {"ce":..,"pe":..}}, bull_rows, bear_rows, classified_rows)."""
    out, bull, bear, classified = {}, 0, 0, 0
    spot = new["spot"]
    for strike, e in new["strikes"].items():
        if abs(strike - spot) > DECISION_RANGE_PTS:
            continue
        o = old["strikes"].get(strike)
        if not o:
            continue
        ce = classify_side("ce", e.get("ce_oi"), o.get("ce_oi"), e.get("ce_ltp"), o.get("ce_ltp"))
        pe = classify_side("pe", e.get("pe_oi"), o.get("pe_oi"), e.get("pe_ltp"), o.get("pe_ltp"))
        if ce or pe:
            out[strike] = {"ce": ce, "pe": pe}
        for c in (ce, pe):
            if c and c["label"]:
                classified += 1
                if c["vote"] > 0:
                    bull += 1
                elif c["vote"] < 0:
                    bear += 1
    return out, bull, bear, classified


# ---------------------------------------------------------------------------
# Fake spike detector
# ---------------------------------------------------------------------------

def find_spikes(new: dict, old: dict, window_min: int) -> Dict[str, dict]:
    out = {}
    spot = new["spot"]
    for strike, e in new["strikes"].items():
        o = old["strikes"].get(strike)
        if not o:
            continue
        for side in ("ce", "pe"):
            dist = (strike - spot) if side == "ce" else (spot - strike)   # OTM distance
            if dist <= SPIKE_OTM_MIN_PTS:
                continue
            oi_now = e.get(f"{side}_oi") or 0
            oi_then = o.get(f"{side}_oi") or 0
            if oi_now < MIN_OI_FOR_CLASS or oi_then <= 0:
                continue
            chg = (oi_now - oi_then) / oi_then * 100.0
            if chg < SPIKE_OI_SURGE_PCT:
                continue
            vol = e.get(f"{side}_vol") or 0
            voi = vol / oi_now if oi_now > 0 else 0.0
            if voi <= SPIKE_VOI_MIN:
                continue
            ltp_now, ltp_then = e.get(f"{side}_ltp"), o.get(f"{side}_ltp")
            px_pct = None
            if ltp_now is not None and ltp_then and ltp_then > 0:
                px_pct = round((ltp_now - ltp_then) / ltp_then * 100.0, 2)
            out[f"SPIKE|{side}|{strike}"] = {
                "strike": int(strike), "type": side.upper(),
                "oi_chg_pct": round(chg, 2), "voi": round(voi, 2),
                "ltp": ltp_now, "dist_from_spot": int(dist),
                "px_chg_pct": px_pct, "window_min": window_min,
                "verdict": "Panic hedge / speculative bet - likely to unwind",
            }
    return out


def spike_card(spike: dict) -> Optional[dict]:
    """A spike becomes a SELL card only if the premium actually rose (it is elevated)."""
    px = spike.get("px_chg_pct")
    if px is None or px <= 0:
        return None
    conf = 60
    if spike["oi_chg_pct"] >= 8:
        conf += 5
    if spike["voi"] >= 0.9:
        conf += 5
    if spike["dist_from_spot"] >= 300:
        conf += 5
    conf = min(conf, 90)
    return {
        "type": f"SELL {spike['type']}", "strike": spike["strike"], "pe_strike": None,
        "confidence": conf, "is_spike": True,
        "reasons": [
            f"OI surged {spike['oi_chg_pct']:+.1f}% in {spike['window_min']} min (fresh positioning)",
            f"V/OI {spike['voi']:.2f}, premium up {px:.1f}% - now elevated",
            f"{spike['dist_from_spot']} pts OTM - weak directional justification",
            spike["verdict"],
        ],
    }


# ---------------------------------------------------------------------------
# Selling opportunities (Layer 2)
# ---------------------------------------------------------------------------

def _risk_label(conf: int) -> str:
    if conf >= 75:
        return "Low"
    if conf >= 62:
        return "Med"
    return "High"


def _walls(side: str, new: dict, sigs: dict) -> List[dict]:
    """Top-3 OTM open-interest walls on one side (CE above spot / PE below spot)."""
    spot = new["spot"]
    oi_min = CE_WALL_OI_MIN if side == "ce" else PE_WALL_OI_MIN
    cands = []
    for strike, e in new["strikes"].items():
        dist = (strike - spot) if side == "ce" else (spot - strike)
        if dist < MIN_SELL_DIST or dist > DECISION_RANGE_PTS:
            continue
        oi = e.get(f"{side}_oi") or 0
        if oi < oi_min:
            continue
        cands.append((oi, strike, dist, e))
    cands.sort(key=lambda c: (-c[0], c[1]))
    walls = []
    for rank, (oi, strike, dist, e) in enumerate(cands[:3], start=1):
        vol = e.get(f"{side}_vol")
        voi = (vol / oi) if (vol is not None and oi > 0) else None
        walls.append({
            "side": side, "strike": int(strike), "oi": int(oi), "dist": float(dist),
            "rank": rank, "voi": voi, "sig": (sigs.get(strike) or {}).get(side),
        })
    return walls


def _score_wall(wall: dict, strength: int) -> Optional[dict]:
    """Confidence 0-95 for selling at this wall, or None if the wall is disqualified."""
    side = wall["side"]
    SIDE = side.upper()
    sig = wall["sig"] or {}
    label = sig.get("label")
    against = ("BULL", "SCOV") if side == "ce" else ("BEAR", "PCOV")
    wanted = "TRAP" if side == "ce" else "SUPT"
    if label in against:
        return None                       # the wall is being challenged
    voi = wall["voi"]
    if voi is not None and voi > VOI_MAX_FOR_SELL:
        return None                       # being absorbed / aggressively traded

    conf = 40
    reasons = []
    if wall["rank"] == 1:
        conf += 15
        reasons.append(f"Highest {SIDE} OI wall: {wall['oi']:,.0f}")
    else:
        conf += 8
        reasons.append(f"Top-3 {SIDE} OI wall: {wall['oi']:,.0f}")
    if label == wanted:
        conf += 15
        what = "writers adding resistance" if side == "ce" else "writers adding support"
        reasons.append(f"{SIDE} {label} - {what} (OI {sig.get('oi_chg_pct', 0):+.1f}%)")
    oi_chg = sig.get("oi_chg_pct")
    if oi_chg is not None and oi_chg <= -3:
        conf -= 10
        reasons.append(f"Wall weakening: OI {oi_chg:+.1f}%")
    if voi is not None:
        if voi < 0.35:
            conf += 10
            reasons.append(f"Low V/OI {voi:.2f} - not being absorbed")
        else:
            conf += 5
            reasons.append(f"V/OI {voi:.2f} - acceptable")
    if wall["dist"] >= 100:
        conf += 5
    if wall["dist"] >= 200:
        conf += 5
    reasons.append(f"Distance: {wall['dist']:.0f} pts from spot")
    if strength >= 4:
        conf += 5
    return {"conf": min(conf, 95), "reasons": reasons}


def build_opportunities(bias: str, score: int, new: dict, sigs: dict) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    strength = abs(score)

    if bias == "BEARISH":
        for w in _walls("ce", new, sigs):
            r = _score_wall(w, strength)
            if r and r["conf"] >= MIN_OPP_CONF:
                out[f"SELL CE|{w['strike']}"] = {
                    "type": "SELL CE", "strike": w["strike"], "pe_strike": None,
                    "confidence": r["conf"], "reasons": r["reasons"], "is_spike": False,
                }
    elif bias == "BULLISH":
        for w in _walls("pe", new, sigs):
            r = _score_wall(w, strength)
            if r and r["conf"] >= MIN_OPP_CONF:
                out[f"SELL PE|{w['strike']}"] = {
                    "type": "SELL PE", "strike": w["strike"], "pe_strike": None,
                    "confidence": r["conf"], "reasons": r["reasons"], "is_spike": False,
                }
    else:  # NEUTRAL: tightest CE-wall / PE-wall pair around spot
        ce_list = [(w, _score_wall(w, 0)) for w in _walls("ce", new, sigs)]
        pe_list = [(w, _score_wall(w, 0)) for w in _walls("pe", new, sigs)]
        ce_list = [(w, r) for w, r in ce_list if r]
        pe_list = [(w, r) for w, r in pe_list if r]
        best = None
        for cw, cr in ce_list:
            for pw, pr in pe_list:
                width = cw["strike"] - pw["strike"]
                conf = int(round((cr["conf"] + pr["conf"]) / 2))
                key = (width, -conf)
                if best is None or key < best[0]:
                    best = (key, cw, pw, conf, width)
        if best and best[3] >= MIN_OPP_CONF:
            _, cw, pw, conf, width = best
            out[f"STRANGLE|{cw['strike']}|{pw['strike']}"] = {
                "type": "STRANGLE", "strike": cw["strike"], "pe_strike": pw["strike"],
                "confidence": conf, "is_spike": False,
                "reasons": [
                    f"CE wall at {cw['strike']} ({cw['oi']:,.0f} OI)",
                    f"PE wall at {pw['strike']} ({pw['oi']:,.0f} OI)",
                    f"Tightest wall pair: {width} pts wide around spot",
                    "Neutral market - range-bound expected",
                ],
            }
    return out


# ---------------------------------------------------------------------------
# Sticky tracker: appear only after N cycles, disappear only after M cycles
# ---------------------------------------------------------------------------

class StickyTracker:
    def __init__(self, appear: int, disappear: int):
        self.appear = appear
        self.disappear = disappear
        self.items: Dict[str, dict] = {}

    def clear(self) -> None:
        self.items.clear()

    def update(self, candidates: Dict[str, dict]) -> List[dict]:
        for key, data in candidates.items():
            it = self.items.get(key)
            if it is None:
                it = {"hits": 0, "misses": 0, "confirmed": False, "data": dict(data)}
                self.items[key] = it
            else:
                old_conf = it["data"].get("confidence")
                it["data"] = dict(data)
                if old_conf is not None and "confidence" in data:
                    it["data"]["confidence"] = int(round((old_conf + data["confidence"]) / 2))
            it["hits"] += 1
            it["misses"] = 0
            if it["hits"] >= self.appear:
                it["confirmed"] = True
        for key in list(self.items.keys()):
            if key in candidates:
                continue
            it = self.items[key]
            if not it["confirmed"]:
                del self.items[key]
                continue
            it["misses"] += 1
            if it["misses"] >= self.disappear:
                del self.items[key]
        return [
            {**it["data"], "fading": it["misses"] > 0, "cycles": it["hits"]}
            for it in self.items.values() if it["confirmed"]
        ]


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------

def _vote_str(v: int) -> str:
    return "bull" if v > 0 else "bear" if v < 0 else "neut"


def _sig(name: str, v: int, value: str, note: str) -> dict:
    return {"name": name, "vote": _vote_str(v), "value": value, "note": note}


def propose_bias(score: int, current: str) -> str:
    if current == "BEARISH" and score <= -BIAS_STAY:
        return "BEARISH"
    if current == "BULLISH" and score >= BIAS_STAY:
        return "BULLISH"
    if score <= -BIAS_ENTER:
        return "BEARISH"
    if score >= BIAS_ENTER:
        return "BULLISH"
    return "NEUTRAL"


def bias_confidence(bias: str, score: int) -> int:
    if bias == "BULLISH":
        return min(95, 40 + 10 * max(score, 0))
    if bias == "BEARISH":
        return min(95, 40 + 10 * max(-score, 0))
    return 50 + 5 * (2 - min(abs(score), 2))


class GuidanceEngine:
    def __init__(self, store: HistoryStore):
        self.store = store
        self.bias = "NEUTRAL"
        self.bias_since: Optional[datetime] = None
        self.pending: Optional[str] = None
        self.pending_count = 0
        self.opp_tracker = StickyTracker(OPP_APPEAR, OPP_DISAPPEAR)
        self.spike_tracker = StickyTracker(SPIKE_APPEAR, SPIKE_DISAPPEAR)
        self.spike_opp_tracker = StickyTracker(SPIKE_APPEAR, SPIKE_DISAPPEAR)
        self._regular_out: List[dict] = []
        self._spike_out: List[dict] = []
        self._spike_opp_out: List[dict] = []
        self.last_metrics: Optional[dict] = None
        self.result: dict = self._warming("Waiting for market data...", None)

    # ----- state helpers ----------------------------------------------------
    def reset_for_new_day(self) -> None:
        self.bias, self.bias_since = "NEUTRAL", None
        self.pending, self.pending_count = None, 0
        for t in (self.opp_tracker, self.spike_tracker, self.spike_opp_tracker):
            t.clear()
        self._regular_out, self._spike_out, self._spike_opp_out = [], [], []
        self.last_metrics = None
        self.result = self._warming("New trading day - collecting data...", None)

    def restore(self, bias, pending, pending_count, since) -> None:
        """Re-applies the last saved decision after a server restart."""
        if bias in ("BULLISH", "BEARISH", "NEUTRAL"):
            self.bias = bias
        self.pending = pending
        self.pending_count = pending_count or 0
        self.bias_since = since

    def _warming(self, message: str, new: Optional[dict]) -> dict:
        return {
            "warming_up": True, "message": message,
            "score": 0, "raw_bias": self.bias, "bias": self.bias, "confidence": 0,
            "pending_bias": None, "pending_count": 0, "confirm_cycles": CONFIRM_CYCLES,
            "bias_since": None,
            "spot": new["spot"] if new else 0.0,
            "expiry": new["expiry"] if new else None,
            "pcr": None, "max_pain": None, "iv_skew": None, "atm_iv": None,
            "expected_move": None,
            "signals": [], "flags": [], "strike_signals": {},
            "opportunities": [], "spike_alerts": [],
            "evaluated_at": new["ts"].isoformat() if new else None,
            "window_min": None,
            "history_minutes": self.store.minutes_of_data(),
            "oi_votes": {"bull": 0, "bear": 0, "classified": 0},
        }

    def _update_bias(self, proposed: str, ts: datetime) -> bool:
        if self.bias_since is None:
            self.bias_since = ts
        if proposed == self.bias:
            self.pending, self.pending_count = None, 0
            return False
        if proposed == self.pending:
            self.pending_count += 1
        else:
            self.pending, self.pending_count = proposed, 1
        if self.pending_count >= CONFIRM_CYCLES:
            self.bias, self.bias_since = proposed, ts
            self.pending, self.pending_count = None, 0
            return True
        return False

    # ----- spike scan (cheap; runs every minute) ------------------------------
    def _refresh_spikes(self, new: dict) -> None:
        spikes, cards = {}, {}
        pair = self.store.lookback(new, SPIKE_WINDOW_MIN)
        if pair:
            old, win = pair
            spikes = find_spikes(new, old, win)
            for key, s in spikes.items():
                card = spike_card(s)
                if card:
                    cards[f"SPIKEOPP|{s['type']}|{s['strike']}"] = card
        self._spike_out = self.spike_tracker.update(spikes)
        self._spike_opp_out = self.spike_opp_tracker.update(cards)

    def _compose(self) -> None:
        res = self.result
        res["spike_alerts"] = list(self._spike_out)
        opps = [dict(o) for o in (self._regular_out + self._spike_opp_out)]
        for o in opps:
            o["risk"] = _risk_label(o["confidence"])
        opps.sort(key=lambda o: (0 if o.get("is_spike") else 1, -o["confidence"]))
        res["opportunities"] = opps[:MAX_OPPS]

    def update_spikes(self) -> Optional[dict]:
        new = self.store.latest()
        if new is None:
            return None
        self._refresh_spikes(new)
        self._compose()
        return self.result

    # ----- full decision (every 5 minutes) -------------------------------------
    def evaluate(self) -> dict:
        new = self.store.latest()
        if new is None or new["spot"] <= 0:
            self.result = self._warming("Waiting for the first market snapshot...", new)
            self._regular_out = []
            self.opp_tracker.clear()
            self._compose()
            return self.result

        pair = self.store.lookback(new, OI_WINDOW_MIN)
        if pair is None:
            self.result = self._warming(
                f"Collecting history ({self.store.minutes_of_data()} min so far) - "
                f"the first decision needs a few minutes of data.", new)
            self._regular_out = []
            self.opp_tracker.clear()
            self._refresh_spikes(new)
            self._compose()
            return self.result
        old, win = pair

        sm = smoothed_metrics(self.store.recent(SMOOTH_BUCKETS))
        sigs, bull, bear, classified = compute_strike_signals(new, old)
        spot = new["spot"]
        signals: List[dict] = []
        score = 0

        # 1) PCR
        pcr = sm["pcr"]
        if pcr is None:
            v, note = 0, "No OI data yet"
        elif pcr < PCR_STRONG_BEAR:
            v, note = -2, "Very low - heavy call writing, bearish"
        elif pcr < PCR_BEAR:
            v, note = -1, "Low PCR - bearish lean"
        elif pcr > PCR_STRONG_BULL:
            v, note = 2, "Very high - heavy put writing, bullish"
        elif pcr > PCR_BULL:
            v, note = 1, "High PCR - bullish lean"
        else:
            v, note = 0, "Neutral range"
        score += v
        signals.append(_sig("PCR", v, f"{pcr:.2f}" if pcr is not None else "-", note))

        # 2) IV skew
        skew = sm["iv_skew"]
        if skew is None:
            v, note = 0, "Not enough option prices"
        elif skew > SKEW_THRESHOLD:
            v, note = -1, "Puts expensive - bearish lean"
        elif skew < -SKEW_THRESHOLD:
            v, note = 1, "Calls expensive - bullish lean"
        else:
            v, note = 0, "Balanced skew"
        score += v
        signals.append(_sig("IV Skew", v, f"{skew:+.1f}" if skew is not None else "-", note))

        # 3) OI classification count (per strike, over the look-back window)
        net = bull - bear
        need = max(VOTE_MARGIN_MIN, int(VOTE_MARGIN_PCT * classified))
        if net <= -need:
            v, note = -1, "Trap / Bear / Put-cover rows dominate"
        elif net >= need:
            v, note = 1, "Bull / Scov / Support rows dominate"
        else:
            v, note = 0, f"Mixed ({win} min window)"
        score += v
        signals.append(_sig("OI Class", v, f"Bull {bull} / Bear {bear}", note))

        # 4) Spot vs max pain
        mp = sm["max_pain"]
        if mp is None:
            v, note, val = 0, "No OI data yet", "-"
        elif spot > mp + MAXPAIN_MARGIN:
            v, note, val = -1, f"Spot {int(spot)} above pain {mp} - pullback gravity", str(mp)
        elif spot < mp - MAXPAIN_MARGIN:
            v, note, val = 1, f"Spot {int(spot)} below pain {mp} - upward gravity", str(mp)
        else:
            v, note, val = 0, f"Spot near pain {mp}", str(mp)
        score += v
        signals.append(_sig("Max Pain", v, val, note))

        # 5) ATM IV level: a flag, not a vote
        atm_iv = sm["atm_iv"]
        flags = []
        if atm_iv is None:
            signals.append(_sig("ATM IV", 0, "-", "No option prices yet"))
        elif atm_iv > IV_HIGH:
            signals.append(_sig("ATM IV", 0, f"{atm_iv:.1f}%", "High - volatile, both sides risky"))
            flags.append({"label": "HIGH IV",
                          "note": f"ATM IV {atm_iv:.1f}% - premiums rich but moves can be large"})
        elif atm_iv < IV_LOW:
            signals.append(_sig("ATM IV", 0, f"{atm_iv:.1f}%", "Low - sideways likely, thin premium"))
            flags.append({"label": "LOW IV",
                          "note": f"ATM IV {atm_iv:.1f}% - sideways likely, premiums are thin"})
        else:
            signals.append(_sig("ATM IV", 0, f"{atm_iv:.1f}%", "Normal range"))

        score = max(-5, min(5, score))

        # hysteresis: raw proposal -> confirmed bias
        proposed = propose_bias(score, self.bias)
        changed = self._update_bias(proposed, new["ts"])
        if changed:
            self.opp_tracker.clear()      # old-side cards must not linger after a flip

        expected_move = None
        if atm_iv:
            expected_move = int(round(spot * (atm_iv / 100.0) * math.sqrt(1.0 / 252.0)))

        res = {
            "warming_up": False, "message": None,
            "score": score, "raw_bias": proposed, "bias": self.bias,
            "confidence": bias_confidence(self.bias, score),
            "pending_bias": self.pending, "pending_count": self.pending_count,
            "confirm_cycles": CONFIRM_CYCLES,
            "bias_since": self.bias_since.isoformat() if self.bias_since else None,
            "spot": spot, "expiry": new["expiry"],
            "pcr": pcr, "max_pain": mp, "iv_skew": skew, "atm_iv": atm_iv,
            "expected_move": expected_move,
            "signals": signals, "flags": flags,
            "strike_signals": {str(k): v for k, v in sigs.items()},
            "opportunities": [], "spike_alerts": [],
            "evaluated_at": new["ts"].isoformat(),
            "window_min": win,
            "history_minutes": self.store.minutes_of_data(),
            "oi_votes": {"bull": bull, "bear": bear, "classified": classified},
        }
        self.result = res
        self.last_metrics = {
            "spot": spot, "pcr": pcr, "max_pain": mp, "iv_skew": skew,
            "atm_iv": atm_iv, "expected_move": expected_move,
        }

        self._regular_out = self.opp_tracker.update(
            build_opportunities(self.bias, score, new, sigs))
        self._refresh_spikes(new)
        self._compose()
        return res


# One shared engine for the whole app.
engine = GuidanceEngine(history)
