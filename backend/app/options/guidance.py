"""
Rule-based Guidance Engine — Python port of the JS engine in options-dashboard.html.

Scoring:
  PCR          : −2 / −1 / 0 / +1 / +2
  IV Skew      : −1 / 0 / +1
  OI Class     : −1 / 0 / +1   (bear votes vs bull votes)
  Spot vs Pain : −1 / 0 / +1
  ─────────────────────────────
  Range: −5 … +5

Bias table:
  ≤ −4 → BEARISH       84 %
  −3   → BEARISH        76 %
  −2   → MILD BEARISH   65 %
  −1   → MILD BEARISH   57 %
   0   → NEUTRAL        50 %
  +1   → MILD BULLISH   57 %
  +2   → MILD BULLISH   65 %
  +3   → BULLISH        76 %
  ≥ +4 → BULLISH        84 %
"""

import math
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Spike detection thresholds
# ---------------------------------------------------------------------------
SPIKE_OTM_MIN_PTS    = 180    # min distance from spot (₹)
SPIKE_OI_SURGE_PCT   = 3.5    # OI change % threshold
SPIKE_VOI_MIN        = 0.5    # V/OI ratio threshold

# Opportunity filters
CE_OI_MIN_FOR_SELL   = 40_000
PE_OI_MIN_FOR_SELL   = 50_000
VOI_MAX_FOR_SELL     = 0.55   # V/OI < this → liquidity not being absorbed by smart money

BIAS_TABLE = {
    -5: ("BEARISH",      84),
    -4: ("BEARISH",      84),
    -3: ("BEARISH",      76),
    -2: ("MILD BEARISH", 65),
    -1: ("MILD BEARISH", 57),
     0: ("NEUTRAL",      50),
     1: ("MILD BULLISH", 57),
     2: ("MILD BULLISH", 65),
     3: ("BULLISH",      76),
     4: ("BULLISH",      84),
     5: ("BULLISH",      84),
}


# ---------------------------------------------------------------------------
# OI classification (same 4-case logic as the HTML mockup)
# ---------------------------------------------------------------------------

def _classify_ce(oi_chg_pct: float, is_down_day: bool) -> Optional[Dict]:
    if abs(oi_chg_pct) < 0.4:
        return None
    if is_down_day:
        return {"label": "TRAP", "css": "trap"} if oi_chg_pct > 0 else {"label": "UWD", "css": "uwd"}
    else:
        return {"label": "BULL", "css": "bull"} if oi_chg_pct > 0 else {"label": "UWD", "css": "uwd"}


def _classify_pe(oi_chg_pct: float, is_down_day: bool) -> Optional[Dict]:
    if abs(oi_chg_pct) < 0.4:
        return None
    if is_down_day:
        return {"label": "BEAR", "css": "bear"} if oi_chg_pct > 0 else {"label": "SCOV", "css": "scov"}
    else:
        return {"label": "SCOV", "css": "scov"} if oi_chg_pct > 0 else {"label": "UWD", "css": "uwd"}


# ---------------------------------------------------------------------------
# ATM IV approximation (simplified Black-Scholes)
# Used only when live Greeks are not available from the stream.
# ---------------------------------------------------------------------------

def _approx_iv(option_price: float, spot: float, strike: float,
               t_days: float, option_type: str = "CE") -> float:
    """
    Brenner-Subrahmanyam approximation.
    Returns annualised IV in percent (e.g. 14.5 for 14.5%).
    """
    if spot <= 0 or t_days <= 0 or option_price <= 0:
        return 0.0
    T = t_days / 365.0
    try:
        iv = (option_price / spot) * math.sqrt(2 * math.pi / T)
        return round(iv * 100, 2)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

def run_engine(state: dict) -> dict:
    """
    Analyse the current option chain state and return a structured guidance result.

    Args:
        state: the dict from option_stream.get_snapshot()

    Returns:
        {
          score, bias, confidence,
          signals: [{name, vote, value, note}],
          opportunities: [{type, strike, confidence, reasons, risk, is_spike}],
          spike_alerts: [{strike, type, oi_chg_pct, voi, dist_from_spot}]
        }
    """
    strikes_data: Dict[int, Dict] = state.get("strikes", {})
    spot: float  = state.get("spot", 0.0)

    if not strikes_data or spot <= 0:
        return _empty_result()

    # --- PCR -----------------------------------------------------------
    total_ce_oi = sum(
        s["ce"]["oi"] for s in strikes_data.values() if s.get("ce") and s["ce"].get("oi")
    )
    total_pe_oi = sum(
        s["pe"]["oi"] for s in strikes_data.values() if s.get("pe") and s["pe"].get("oi")
    )
    pcr = round(total_pe_oi / total_ce_oi, 3) if total_ce_oi > 0 else 1.0

    score   = 0
    signals = []

    if pcr < 0.82:
        score -= 2; signals.append({"name": "PCR",      "vote": "bear", "value": f"{pcr:.2f}", "note": "Very low — bearish pressure"})
    elif pcr < 0.92:
        score -= 1; signals.append({"name": "PCR",      "vote": "bear", "value": f"{pcr:.2f}", "note": "Low PCR"})
    elif pcr > 1.18:
        score += 2; signals.append({"name": "PCR",      "vote": "bull", "value": f"{pcr:.2f}", "note": "Very high — bullish stance"})
    elif pcr > 1.08:
        score += 1; signals.append({"name": "PCR",      "vote": "bull", "value": f"{pcr:.2f}", "note": "High PCR"})
    else:
        signals.append(       {"name": "PCR",      "vote": "neut", "value": f"{pcr:.2f}", "note": "Neutral range"})

    # --- IV Skew -------------------------------------------------------
    # Use ATM ± 1 strike to estimate skew (OTM PE IV − OTM CE IV)
    atm      = round(spot / 50) * 50
    iv_skew  = _compute_iv_skew(strikes_data, spot, atm)
    iv_skew_s = f"{iv_skew:+.1f}"

    if iv_skew > 1.8:
        score -= 1; signals.append({"name": "IV Skew",  "vote": "bear", "value": iv_skew_s,   "note": "Puts expensive → bearish lean"})
    elif iv_skew < -1.8:
        score += 1; signals.append({"name": "IV Skew",  "vote": "bull", "value": iv_skew_s,   "note": "Calls expensive → bullish lean"})
    else:
        signals.append(       {"name": "IV Skew",  "vote": "neut", "value": iv_skew_s,   "note": "Balanced skew"})

    # --- OI Classification vote tally ----------------------------------
    is_down_day = _is_down_day(strikes_data, spot)
    bear_votes = bull_votes = 0

    for strike, side in strikes_data.items():
        ce = side.get("ce"); pe = side.get("pe")
        if ce:
            c = _classify_ce(ce.get("oi_chg_pct", 0), is_down_day)
            if c and c["css"] == "trap": bear_votes += 1
            if c and c["css"] == "bull": bull_votes += 1
        if pe:
            p = _classify_pe(pe.get("oi_chg_pct", 0), is_down_day)
            if p and p["css"] == "bear": bear_votes += 1
            if p and p["css"] == "scov": bull_votes += 1

    if bear_votes > bull_votes + 3:
        score -= 1; signals.append({"name": "OI Class",  "vote": "bear", "value": f"B{bear_votes}/U{bull_votes}", "note": "Trap/Bear OI dominates"})
    elif bull_votes > bear_votes + 3:
        score += 1; signals.append({"name": "OI Class",  "vote": "bull", "value": f"B{bear_votes}/U{bull_votes}", "note": "Bull/SCOV OI dominates"})
    else:
        signals.append(       {"name": "OI Class",  "vote": "neut", "value": f"B{bear_votes}/U{bull_votes}", "note": "Mixed"})

    # --- Spot vs Max Pain ----------------------------------------------
    max_pain = _compute_max_pain(strikes_data)
    if spot > max_pain + 80:
        score -= 1; signals.append({"name": "Max Pain",  "vote": "bear", "value": str(max_pain), "note": f"Spot {int(spot)} > Pain {max_pain}"})
    elif spot < max_pain - 80:
        score += 1; signals.append({"name": "Max Pain",  "vote": "bull", "value": str(max_pain), "note": f"Spot {int(spot)} < Pain {max_pain}"})
    else:
        signals.append(       {"name": "Max Pain",  "vote": "neut", "value": str(max_pain), "note": f"Spot near Pain {max_pain}"})

    # Clamp to ±5
    score = max(-5, min(5, score))
    bias, confidence = BIAS_TABLE.get(score, ("NEUTRAL", 50))

    # --- Opportunities -------------------------------------------------
    opportunities = _find_opportunities(strikes_data, spot, score)

    # --- Spike alerts --------------------------------------------------
    spike_alerts  = _find_spikes(strikes_data, spot)

    return {
        "score":        score,
        "bias":         bias,
        "confidence":   confidence,
        "pcr":          pcr,
        "max_pain":     max_pain,
        "iv_skew":      iv_skew,
        "is_down_day":  is_down_day,
        "signals":      signals,
        "opportunities": sorted(
            opportunities,
            key=lambda x: (0 if x.get("is_spike") else 1, -x["confidence"])
        ),
        "spike_alerts": spike_alerts,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_result() -> dict:
    return {
        "score": 0, "bias": "NEUTRAL", "confidence": 50,
        "pcr": 1.0, "max_pain": 0, "iv_skew": 0.0, "is_down_day": False,
        "signals": [], "opportunities": [], "spike_alerts": [],
    }


def _is_down_day(strikes_data: dict, spot: float) -> bool:
    """
    Simple heuristic: if total PE OI change is positive (puts being added)
    while CE OI change is negative → down day pressure.
    """
    ce_chg_sum = sum(
        s["ce"]["oi_chg_pct"] for s in strikes_data.values()
        if s.get("ce") and s["ce"].get("oi_chg_pct") is not None
    )
    pe_chg_sum = sum(
        s["pe"]["oi_chg_pct"] for s in strikes_data.values()
        if s.get("pe") and s["pe"].get("oi_chg_pct") is not None
    )
    return pe_chg_sum > 0 and ce_chg_sum < 0


def _compute_max_pain(strikes_data: dict) -> int:
    """
    Max Pain = strike where total option writer P&L is maximised
    (i.e. total buyer loss is maximised).
    """
    strikes = sorted(strikes_data.keys())
    min_loss = None
    max_pain_strike = strikes[0] if strikes else 0

    for target in strikes:
        loss = 0
        for s in strikes:
            ce = strikes_data[s].get("ce")
            pe = strikes_data[s].get("pe")
            ce_oi = ce["oi"] if ce else 0
            pe_oi = pe["oi"] if pe else 0
            # CE loss if target > strike
            if target > s:
                loss += (target - s) * ce_oi
            # PE loss if target < strike
            if target < s:
                loss += (s - target) * pe_oi
        if min_loss is None or loss < min_loss:
            min_loss = loss
            max_pain_strike = target

    return max_pain_strike


def _compute_iv_skew(strikes_data: dict, spot: float, atm: int) -> float:
    """
    IV Skew = OTM PE IV − OTM CE IV (one strike OTM each side).
    Uses Brenner-Subrahmanyam approximation.
    Positive value = put-heavy = bearish lean.
    """
    otm_pe_strike  = atm - 50    # one strike below ATM
    otm_ce_strike  = atm + 50    # one strike above ATM

    pe_side = strikes_data.get(otm_pe_strike, {}).get("pe")
    ce_side = strikes_data.get(otm_ce_strike, {}).get("ce")

    if not pe_side or not ce_side:
        # Try ATM itself
        pe_side = strikes_data.get(atm, {}).get("pe")
        ce_side = strikes_data.get(atm, {}).get("ce")

    if not pe_side or not ce_side:
        return 0.0

    pe_ltp = pe_side.get("ltp", 0)
    ce_ltp = ce_side.get("ltp", 0)

    # Rough days to expiry: use 7 as default if not available
    t_days = 7.0
    pe_iv = _approx_iv(pe_ltp, spot, otm_pe_strike, t_days, "PE")
    ce_iv = _approx_iv(ce_ltp, spot, otm_ce_strike, t_days, "CE")

    return round(pe_iv - ce_iv, 2)


def _find_opportunities(strikes_data: dict, spot: float, score: int) -> List[dict]:
    """
    Generate selling opportunity cards based on score direction.
    """
    ops: List[dict] = []
    atm  = round(spot / 50) * 50

    # CE selling: bearish (score <= -1) → look at strikes above spot
    if score <= -1:
        for strike in sorted(strikes_data.keys(), reverse=True):
            if strike <= spot:
                continue
            ce = strikes_data[strike].get("ce")
            if not ce:
                continue
            oi  = ce.get("oi", 0)
            voi = ce.get("voi", 0)
            oi_chg_pct = ce.get("oi_chg_pct", 0)
            if oi < CE_OI_MIN_FOR_SELL or voi > VOI_MAX_FOR_SELL:
                continue

            is_down = _is_down_day(strikes_data, spot)
            cls = _classify_ce(oi_chg_pct, is_down)
            reasons = []
            if cls and cls["css"] == "trap":
                reasons.append("CE TRAP — bears adding shorts")
            if oi > CE_OI_MIN_FOR_SELL:
                reasons.append(f"High OI wall: {oi:,.0f}")
            if voi < 0.35:
                reasons.append("Low V/OI — not being absorbed")
            dist = strike - spot
            reasons.append(f"Distance: ₹{dist:.0f} from spot")

            conf = _ce_sell_confidence(score, oi, voi, dist)
            ops.append({
                "type": "SELL CE", "strike": strike,
                "confidence": conf, "reasons": reasons,
                "risk": _risk_label(conf), "is_spike": False,
            })
            if len(ops) >= 2:
                break

    # PE selling: bullish (score >= 1) → look at strikes below spot
    if score >= 1:
        for strike in sorted(strikes_data.keys()):
            if strike >= spot:
                continue
            pe = strikes_data[strike].get("pe")
            if not pe:
                continue
            oi  = pe.get("oi", 0)
            voi = pe.get("voi", 0)
            if oi < PE_OI_MIN_FOR_SELL or voi > VOI_MAX_FOR_SELL:
                continue

            reasons = [
                f"Support wall: {oi:,.0f} OI",
                f"V/OI {voi:.2f} — low absorption",
                f"Distance: ₹{spot - strike:.0f} from spot",
            ]
            conf = _pe_sell_confidence(score, oi, voi, spot - strike)
            ops.append({
                "type": "SELL PE", "strike": strike,
                "confidence": conf, "reasons": reasons,
                "risk": _risk_label(conf), "is_spike": False,
            })
            if len(ops) >= 2:
                break

    # Strangle: neutral (score -1 to +1)
    if -1 <= score <= 1:
        ce_wall = _find_max_oi_wall(strikes_data, spot, "ce", above=True)
        pe_wall = _find_max_oi_wall(strikes_data, spot, "pe", above=False)
        if ce_wall and pe_wall:
            ops.append({
                "type": "STRANGLE",
                "strike": ce_wall,
                "pe_strike": pe_wall,
                "confidence": 58,
                "reasons": [
                    f"CE wall at {ce_wall} ({strikes_data[ce_wall]['ce']['oi']:,.0f} OI)",
                    f"PE wall at {pe_wall} ({strikes_data[pe_wall]['pe']['oi']:,.0f} OI)",
                    "Neutral market — range bound expected",
                    "Collect premium from both sides",
                ],
                "risk": "Med",
                "is_spike": False,
            })

    return ops


def _find_spikes(strikes_data: dict, spot: float) -> List[dict]:
    """Detect fake/unusual OI spikes — all 3 conditions must fire."""
    alerts = []
    for strike, side in strikes_data.items():
        dist = abs(strike - spot)
        if dist < SPIKE_OTM_MIN_PTS:
            continue
        for opt_type in ("ce", "pe"):
            data = side.get(opt_type)
            if not data:
                continue
            oi_chg = abs(data.get("oi_chg_pct", 0))
            voi    = data.get("voi", 0)
            if oi_chg >= SPIKE_OI_SURGE_PCT and voi > SPIKE_VOI_MIN:
                alerts.append({
                    "strike":        strike,
                    "type":          opt_type.upper(),
                    "oi_chg_pct":    data["oi_chg_pct"],
                    "voi":           voi,
                    "ltp":           data.get("ltp", 0),
                    "dist_from_spot": int(dist),
                })
    return sorted(alerts, key=lambda x: (-abs(x["oi_chg_pct"]), -x["voi"]))


# ---------------------------------------------------------------------------
# Confidence and risk scoring helpers
# ---------------------------------------------------------------------------

def _ce_sell_confidence(score: int, oi: int, voi: float, dist: float) -> int:
    base = 50 + abs(score) * 6
    if oi > 100_000: base += 8
    elif oi > 60_000: base += 4
    if voi < 0.25: base += 6
    elif voi < 0.4: base += 3
    if dist > 200: base += 5
    return min(base, 92)


def _pe_sell_confidence(score: int, oi: int, voi: float, dist: float) -> int:
    base = 50 + abs(score) * 6
    if oi > 120_000: base += 8
    elif oi > 70_000: base += 4
    if voi < 0.25: base += 6
    elif voi < 0.4: base += 3
    if dist > 200: base += 5
    return min(base, 92)


def _risk_label(conf: int) -> str:
    if conf >= 72: return "Low"
    if conf >= 58: return "Med"
    return "High"


def _find_max_oi_wall(strikes_data: dict, spot: float,
                      opt_type: str, above: bool) -> Optional[int]:
    """Find the strike with maximum OI in the given direction from spot."""
    best_strike = None
    best_oi = 0
    for strike, side in strikes_data.items():
        if above and strike <= spot:
            continue
        if not above and strike >= spot:
            continue
        data = side.get(opt_type)
        if data and data.get("oi", 0) > best_oi:
            best_oi = data["oi"]
            best_strike = strike
    return best_strike
