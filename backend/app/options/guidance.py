"""
guidance.py — the SIMPLE Guidance Engine: it reads the option chain as it is
(open interest, OI change and last traded price) and says whether the chain
looks Bullish / Mild Bullish / Neutral / Mild Bearish / Bearish, from the
option SELLER's point of view. No IV, no skew, no price-direction guessing.

Three readings, each votes -1 / 0 / +1 (only OTM strikes within +/-500 points of
spot, and only options with a real premium):

  1. WALLS       The biggest put-OI strike below spot (support) and the biggest
                 call-OI strike above spot (resistance). Spot closer to support
                 with resistance far away = room to go up = bullish; spot
                 pressed against resistance with support far away = bearish.
  2. POSITIONING OTM PCR (puts below spot / calls above spot), smoothed over the
                 last 5 minutes. High PCR = puts being written = bullish.
                 Its change since the open (09:30 reference) counts too.
  3. FRESH OI    Contracts added/removed in the last 30 minutes on OTM puts vs
                 OTM calls. Put OI growing faster than call OI (or call OI
                 being unwound) = bullish; the reverse = bearish.

Score = sum of the three votes (-3 .. +3):
      +3 BULLISH | +1/+2 MILD BULLISH | 0 NEUTRAL | -1/-2 MILD BEARISH | -3 BEARISH

The engine decides every 5 minutes (the router calls evaluate()); the fake-spike
scan is light and runs every minute (update_spikes()). Selling-opportunity cards
and the spike detector are unchanged. All tunable numbers are in CONSTANTS below.
"""

import logging
import math
from datetime import datetime, date, time as dtime, timedelta
from statistics import mean, median
from typing import Dict, List, Optional, Tuple

from app.options.history import HistoryStore, history, STRIKE_STEP

logger = logging.getLogger(__name__)

# ============================== CONSTANTS ===================================
EVAL_EVERY_MIN = 5            # full decision cadence (minutes)
SMOOTH_BUCKETS = 5            # 1-minute snapshots averaged for the PCR reading
FRESH_WINDOW_MIN = 30         # look-back for the fresh-OI reading (and the chain's OI-change %)
SPIKE_WINDOW_MIN = 10         # look-back for the fake-spike OI surge
OPEN_REF_TIME = dtime(9, 30)  # "since open" reference starts here; OI is still settling before

READ_RANGE_PTS = 500          # the three readings use OTM strikes within +/- this of spot
MIN_PREMIUM = 1.0             # ignore options with LTP below this (dead / untraded OI)
DECISION_RANGE_PTS = 1000     # range used by the selling-opportunity cards

# reading 1: walls
WALL_SKEW = 0.25              # (dist to resistance - dist to support) / (sum) beyond +-this votes

# reading 2: positioning
PCR_BULL, PCR_BEAR = 1.10, 0.90        # OTM PCR level
PCR_CHG_OPEN = 0.10                    # change since open beyond +-this

# reading 3: fresh OI
FRESH_MIN_PCT = 1.0           # total OI moved must be at least this % of OTM OI
FRESH_SHARE = 0.25            # (put change - call change) / (|put| + |call|) beyond +-this

CONFIRM_CYCLES = 1            # evaluations a NEW label must hold before it is adopted (1 = immediately)

OPP_APPEAR = 2                # cycles an opportunity must persist before it is shown
OPP_DISAPPEAR = 3             # cycles it must be missing before it is removed
SPIKE_APPEAR = 1              # spikes are time-sensitive: shown immediately
SPIKE_DISAPPEAR = 2
MAX_OPPS = 3                  # top opportunities shown

MIN_OI_FOR_CLASS = 20_000     # spike detector: ignore strikes with tiny open interest

# fake spike (all three must be true)
SPIKE_OTM_MIN_PTS = 200
SPIKE_OI_SURGE_PCT = 4.0
SPIKE_VOI_MIN = 0.6

# selling opportunities
MIN_SELL_DIST = 50
MIN_SELL_PREMIUM = 10.0       # never suggest selling an option trading below this (Rs)
CE_WALL_OI_MIN = 40_000
PE_WALL_OI_MIN = 50_000
VOI_MAX_FOR_SELL = 0.55
MIN_OPP_CONF = 55
# ============================================================================

BULLISH, MILD_BULLISH, NEUTRAL, MILD_BEARISH, BEARISH = (
    "BULLISH", "MILD BULLISH", "NEUTRAL", "MILD BEARISH", "BEARISH")
ALL_LABELS = (BULLISH, MILD_BULLISH, NEUTRAL, MILD_BEARISH, BEARISH)


# ---------------------------------------------------------------------------
# Chain readings
# ---------------------------------------------------------------------------

def compute_max_pain(strikes: dict) -> Optional[int]:
    """Display only - max pain does not vote."""
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


def otm_strikes(b: dict) -> Tuple[List[int], List[int]]:
    """
    (call strikes above spot, put strikes below spot) within READ_RANGE_PTS that
    have OI and a real premium (LTP >= MIN_PREMIUM). Strikes are decided from the
    given bucket's own spot.
    """
    spot, strikes = b["spot"], b["strikes"]
    ces, pes = [], []
    for k, e in strikes.items():
        if spot < k <= spot + READ_RANGE_PTS:
            ltp = e.get("ce_ltp")
            if (e.get("ce_oi") or 0) > 0 and ltp is not None and ltp >= MIN_PREMIUM:
                ces.append(k)
        elif spot - READ_RANGE_PTS <= k < spot:
            ltp = e.get("pe_ltp")
            if (e.get("pe_oi") or 0) > 0 and ltp is not None and ltp >= MIN_PREMIUM:
                pes.append(k)
    return ces, pes


def otm_pcr(b: dict) -> Optional[float]:
    """OTM-only PCR: PE OI of OTM puts / CE OI of OTM calls. None if no OTM call OI."""
    ces, pes = otm_strikes(b)
    ce_oi = sum(b["strikes"][k].get("ce_oi") or 0 for k in ces)
    pe_oi = sum(b["strikes"][k].get("pe_oi") or 0 for k in pes)
    return (pe_oi / ce_oi) if ce_oi > 0 else None


def oi_walls(b: dict) -> Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]]]:
    """((support strike, its PE OI), (resistance strike, its CE OI)); the biggest OI wins,
    ties go to the strike nearest spot."""
    spot, strikes = b["spot"], b["strikes"]
    ces, pes = otm_strikes(b)
    sup = res = None
    if pes:
        k = max(pes, key=lambda s: (strikes[s].get("pe_oi") or 0, -abs(spot - s)))
        sup = (k, int(strikes[k].get("pe_oi") or 0))
    if ces:
        k = max(ces, key=lambda s: (strikes[s].get("ce_oi") or 0, -abs(s - spot)))
        res = (k, int(strikes[k].get("ce_oi") or 0))
    return sup, res


def fresh_oi(new: dict, old: dict) -> Optional[dict]:
    """OI added(+)/removed(-) on OTM puts and OTM calls between `old` and `new`."""
    ces, pes = otm_strikes(new)
    put_chg = call_chg = base = 0
    for k in pes:
        o = old["strikes"].get(k)
        if o and o.get("pe_oi") is not None:
            put_chg += (new["strikes"][k].get("pe_oi") or 0) - o["pe_oi"]
            base += o["pe_oi"]
    for k in ces:
        o = old["strikes"].get(k)
        if o and o.get("ce_oi") is not None:
            call_chg += (new["strikes"][k].get("ce_oi") or 0) - o["ce_oi"]
            base += o["ce_oi"]
    if base <= 0:
        return None
    moved = abs(put_chg) + abs(call_chg)
    return {"put_chg": int(put_chg), "call_chg": int(call_chg), "base": int(base),
            "moved_pct": moved / base * 100.0,
            "share": ((put_chg - call_chg) / moved) if moved > 0 else 0.0}


def strike_oi_changes(new: dict, old: dict) -> dict:
    """Per-strike OI % change for the option-chain table (no buy/sell labels)."""
    out = {}
    spot = new["spot"]
    for strike, e in new["strikes"].items():
        if abs(strike - spot) > DECISION_RANGE_PTS:
            continue
        o = old["strikes"].get(strike)
        if not o:
            continue
        row = {}
        for side in ("ce", "pe"):
            a, b0 = e.get(f"{side}_oi"), o.get(f"{side}_oi")
            if a is None or not b0 or b0 <= 0:
                row[side] = None
            else:
                row[side] = {"label": None, "css": None, "vote": 0,
                             "oi_chg_pct": round((a - b0) / b0 * 100.0, 2)}
        if row["ce"] or row["pe"]:
            out[strike] = row
    return out


def label_for(score: int) -> str:
    if score >= 3:
        return BULLISH
    if score >= 1:
        return MILD_BULLISH
    if score <= -3:
        return BEARISH
    if score <= -1:
        return MILD_BEARISH
    return NEUTRAL


def bias_confidence(score: int) -> int:
    """How many of the three readings point the same way, as a percentage."""
    return 50 if score == 0 else int(round(abs(score) / 3.0 * 100))


def _fmt_qty(n: float) -> str:
    sign = "-" if n < 0 else "+"
    n = abs(n)
    if n >= 1_00_000:
        return f"{sign}{n / 1_00_000:.1f}L"
    if n >= 1_000:
        return f"{sign}{n / 1_000:.0f}K"
    return f"{sign}{n:.0f}"


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
    if spike.get("ltp") is None or spike["ltp"] < MIN_SELL_PREMIUM:
        return None                       # premium too small to be worth selling
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
            f"V/OI {spike['voi']:.2f}, premium up {px:.1f}% - now Rs {spike['ltp']:.2f}",
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
        ltp = e.get(f"{side}_ltp")
        if ltp is None or ltp < MIN_SELL_PREMIUM:
            continue                      # not enough premium to be worth selling
        cands.append((oi, strike, dist, e))
    cands.sort(key=lambda c: (-c[0], c[1]))
    walls = []
    for rank, (oi, strike, dist, e) in enumerate(cands[:3], start=1):
        vol = e.get(f"{side}_vol")
        voi = (vol / oi) if (vol is not None and oi > 0) else None
        walls.append({
            "side": side, "strike": int(strike), "oi": int(oi), "dist": float(dist),
            "rank": rank, "voi": voi, "sig": (sigs.get(strike) or {}).get(side),
            "ltp": float(e.get(f"{side}_ltp")),
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
    reasons.append(f"Premium to earn: Rs {wall['ltp']:.2f}")
    if strength >= 3:
        conf += 5
    return {"conf": min(conf, 95), "reasons": reasons}


def build_opportunities(bias: str, score: int, new: dict, sigs: dict) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    strength = abs(score)

    if bias in ("BEARISH", "MILD BEARISH"):
        for w in _walls("ce", new, sigs):
            r = _score_wall(w, strength)
            if r and r["conf"] >= MIN_OPP_CONF:
                out[f"SELL CE|{w['strike']}"] = {
                    "type": "SELL CE", "strike": w["strike"], "pe_strike": None,
                    "confidence": r["conf"], "reasons": r["reasons"], "is_spike": False,
                }
    elif bias in ("BULLISH", "MILD BULLISH"):
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


class GuidanceEngine:
    def __init__(self, store: HistoryStore):
        self.store = store
        self.bias = NEUTRAL
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
        self._open_pcr: Optional[Tuple[date, float]] = None      # (day, OTM PCR near the open)
        self.result: dict = self._warming("Waiting for market data...", None)

    # ----- state helpers ----------------------------------------------------
    def reset_for_new_day(self) -> None:
        self.bias, self.bias_since = NEUTRAL, None
        self.pending, self.pending_count = None, 0
        for t in (self.opp_tracker, self.spike_tracker, self.spike_opp_tracker):
            t.clear()
        self._regular_out, self._spike_out, self._spike_opp_out = [], [], []
        self.last_metrics = None
        self._open_pcr = None
        self.result = self._warming("New trading day - collecting data...", None)

    def restore(self, bias, pending, pending_count, since) -> None:
        """Re-applies the last saved decision after a server restart."""
        if bias in ALL_LABELS:
            self.bias = bias
        self.pending = pending if pending in ALL_LABELS else None
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
            "readings": None,
        }

    def _pcr_at_open(self, now_ts: datetime) -> Optional[float]:
        """Average OTM PCR over the first SMOOTH_BUCKETS buckets at/after OPEN_REF_TIME."""
        day = now_ts.date()
        if self._open_pcr and self._open_pcr[0] == day:
            return self._open_pcr[1]
        start = datetime.combine(day, OPEN_REF_TIME)
        ref = [b for b in self.store.buckets if b["ts"] >= start and b["ts"].date() == day]
        if len(ref) < SMOOTH_BUCKETS:
            return None
        vals = [v for v in (otm_pcr(b) for b in ref[:SMOOTH_BUCKETS]) if v is not None]
        if not vals:
            return None
        self._open_pcr = (day, round(mean(vals), 3))
        return self._open_pcr[1]

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

        pair = self.store.lookback(new, FRESH_WINDOW_MIN)
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

        spot = new["spot"]
        signals: List[dict] = []
        score = 0

        # 1) WALLS - where is spot between the biggest put wall and the biggest call wall?
        sup, res_ = oi_walls(new)
        wall_dir = 0
        if sup and res_:
            d_sup, d_res = spot - sup[0], res_[0] - spot
            tot = d_sup + d_res
            r = (d_res - d_sup) / tot if tot > 0 else 0.0
            if r >= WALL_SKEW:
                v, note = 1, f"Spot {d_sup:.0f} pts above support, {d_res:.0f} below resistance - room to rise"
            elif r <= -WALL_SKEW:
                v, note = -1, f"Spot {d_res:.0f} pts under resistance, {d_sup:.0f} above support - capped"
            else:
                v, note = 0, f"Spot mid-range ({d_sup:.0f} pts from support, {d_res:.0f} from resistance)"
            val = f"Sup {sup[0]} ({_fmt_qty(sup[1])[1:]}) / Res {res_[0]} ({_fmt_qty(res_[1])[1:]})"
            wall_dir = v
        else:
            v, note, val = 0, "No OTM OI walls found yet", "-"
        score += v
        signals.append(_sig("OI Walls", v, val, note))

        # 2) POSITIONING - OTM PCR level and its change since the open
        recent = [otm_pcr(b) for b in self.store.recent(SMOOTH_BUCKETS)]
        recent = [x for x in recent if x is not None]
        pcr = round(mean(recent), 3) if recent else None
        pcr_open = self._pcr_at_open(new["ts"])
        pcr_chg = round(pcr - pcr_open, 3) if (pcr is not None and pcr_open is not None) else None
        if pcr is None:
            v, note, val = 0, "No OTM OI data yet", "-"
        else:
            lvl = 1 if pcr >= PCR_BULL else -1 if pcr <= PCR_BEAR else 0
            chg = 0 if pcr_chg is None else (1 if pcr_chg >= PCR_CHG_OPEN else -1 if pcr_chg <= -PCR_CHG_OPEN else 0)
            v = max(-1, min(1, lvl + chg))
            lvl_txt = "puts heavier than calls" if lvl > 0 else "calls heavier than puts" if lvl < 0 else "balanced"
            chg_txt = ("open reference not ready" if pcr_chg is None
                       else f"{pcr_chg:+.2f} since open")
            note = f"{lvl_txt}; {chg_txt}"
            val = f"{pcr:.2f}"
        score += v
        signals.append(_sig("OTM PCR", v, val, note))

        # 3) FRESH OI - who added contracts in the last window?
        fr = fresh_oi(new, old)
        if new["ts"].time() < OPEN_REF_TIME:
            v, note, val = 0, "OI still settling before 09:30 - not voting yet", "-"
        elif fr is None:
            v, note, val = 0, "No OTM OI data yet", "-"
        else:
            val = f"Puts {_fmt_qty(fr['put_chg'])} / Calls {_fmt_qty(fr['call_chg'])}"
            if fr["moved_pct"] < FRESH_MIN_PCT:
                v, note = 0, f"Little change ({fr['moved_pct']:.1f}% of OTM OI in {win} min)"
            elif fr["share"] >= FRESH_SHARE:
                v, note = 1, f"Puts gaining on calls in {win} min (put OI building or call OI unwinding)"
            elif fr["share"] <= -FRESH_SHARE:
                v, note = -1, f"Calls gaining on puts in {win} min (call OI building or put OI unwinding)"
            else:
                v, note = 0, f"Both sides moving together in {win} min"
        score += v
        signals.append(_sig("Fresh OI", v, val, note))

        # info only: max pain does not vote
        mp = compute_max_pain(new["strikes"])
        signals.append(_sig("Max Pain", 0, str(mp) if mp else "-", "Info only - does not vote"))

        proposed = label_for(score)
        changed = self._update_bias(proposed, new["ts"])
        if changed:
            self.opp_tracker.clear()      # old-side cards must not linger after a flip

        sigs = strike_oi_changes(new, old)
        readings = {
            "support": sup[0] if sup else None, "resistance": res_[0] if res_ else None,
            "pcr": pcr, "pcr_open": pcr_open, "pcr_chg_open": pcr_chg,
            "fresh_put_chg": fr["put_chg"] if fr else None,
            "fresh_call_chg": fr["call_chg"] if fr else None,
        }
        out = {
            "warming_up": False, "message": None,
            "score": score, "raw_bias": proposed, "bias": self.bias,
            "confidence": bias_confidence(score),
            "pending_bias": self.pending, "pending_count": self.pending_count,
            "confirm_cycles": CONFIRM_CYCLES,
            "bias_since": self.bias_since.isoformat() if self.bias_since else None,
            "spot": spot, "expiry": new["expiry"],
            "pcr": pcr, "max_pain": mp, "iv_skew": None, "atm_iv": None, "expected_move": None,
            "signals": signals, "flags": [],
            "strike_signals": {str(k): v for k, v in sigs.items()},
            "opportunities": [], "spike_alerts": [],
            "evaluated_at": new["ts"].isoformat(),
            "window_min": win,
            "history_minutes": self.store.minutes_of_data(),
            "readings": readings,
        }
        self.result = out
        self.last_metrics = {"spot": spot, "pcr": pcr, "max_pain": mp}

        self._regular_out = self.opp_tracker.update(
            build_opportunities(self.bias, score, new, sigs))
        self._refresh_spikes(new)
        self._compose()
        return out


# One shared engine for the whole app.
engine = GuidanceEngine(history)
