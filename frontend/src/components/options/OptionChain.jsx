/**
 * OptionChain — 9-column option chain table.
 * Columns: CE Signal | CE OI bar | CE Vol+VOI | CE LTP | STRIKE | PE LTP | PE Vol+VOI | PE OI bar | PE Signal
 *
 * Props: { chainData, guidance, classifyCe, classifyPe }
 */

import { useMemo } from "react";

const STRIKE_STEP = 50;

function OIBar({ oi, maxOI, side }) {
  const pct = maxOI > 0 ? (oi / maxOI) * 100 : 0;
  return (
    <div className="opt-oi-wrap">
      <span className="opt-oi-num">{fmtOI(oi)}</span>
      <div className={`opt-oi-bar opt-oi-bar--${side}`} style={{ "--pct": `${pct}%` }} />
    </div>
  );
}

function SignalBadge({ cls, label }) {
  if (!cls || !label) return <span className="opt-sig opt-sig--empty">—</span>;
  return <span className={`opt-sig opt-sig--${cls}`}>{label}</span>;
}

function fmtOI(v) {
  if (!v) return "—";
  if (v >= 1_00_00_000) return `${(v / 1_00_00_000).toFixed(1)}Cr`;
  if (v >= 1_00_000)    return `${(v / 1_00_000).toFixed(1)}L`;
  if (v >= 1_000)       return `${(v / 1_000).toFixed(0)}K`;
  return String(v);
}

function fmtLTP(v) {
  if (!v) return "—";
  return v.toFixed(2);
}

function fmtVOI(v) {
  if (v == null) return null;
  return v.toFixed(2);
}

export default function OptionChain({ chainData, guidance, classifyCe, classifyPe }) {
  const { strikes = {}, atm = 0 } = chainData;

  // Determine if it's a down day from guidance
  const isDownDay = guidance?.is_down_day ?? false;

  // Highlighted strikes from guidance
  const highlightedStrikes = useMemo(() => {
    const set = new Set();
    (guidance?.opportunities || []).forEach(op => {
      if (op.strike) set.add(op.strike);
      if (op.pe_strike) set.add(op.pe_strike);
    });
    (guidance?.spike_alerts || []).forEach(a => set.add(a.strike));
    return set;
  }, [guidance]);

  // Sorted strikes
  const sortedStrikes = useMemo(
    () => Object.keys(strikes).map(Number).sort((a, b) => b - a),
    [strikes]
  );

  // Max OI for bar scale
  const maxCeOI = useMemo(
    () => Math.max(...sortedStrikes.map(s => strikes[s]?.ce?.oi || 0), 1),
    [sortedStrikes, strikes]
  );
  const maxPeOI = useMemo(
    () => Math.max(...sortedStrikes.map(s => strikes[s]?.pe?.oi || 0), 1),
    [sortedStrikes, strikes]
  );

  if (sortedStrikes.length === 0) {
    return (
      <div className="opt-chain-empty">
        Waiting for option chain data…
      </div>
    );
  }

  return (
    <div className="opt-chain-wrap">
      {/* Column header */}
      <div className="opt-chain-hdr opt-crow">
        <span>CE Signal</span>
        <span>CE OI</span>
        <span>Vol / V:OI</span>
        <span>CE LTP</span>
        <span className="opt-strike-col">STRIKE</span>
        <span>PE LTP</span>
        <span>Vol / V:OI</span>
        <span>PE OI</span>
        <span>PE Signal</span>
      </div>

      {/* Rows */}
      <div className="opt-chain-body">
        {sortedStrikes.map(strike => {
          const ce = strikes[strike]?.ce;
          const pe = strikes[strike]?.pe;

          const ceClass   = ce ? classifyCe(ce.oi_chg_pct || 0, isDownDay) : null;
          const peClass   = pe ? classifyPe(pe.oi_chg_pct || 0, isDownDay) : null;

          const isAtm     = strike === atm;
          const isHlt     = highlightedStrikes.has(strike);

          // Spike detection on this row
          const ceSurge = ce && Math.abs(ce.oi_chg_pct || 0) >= 3.5 && (ce.voi || 0) > 0.5;
          const peSurge = pe && Math.abs(pe.oi_chg_pct || 0) >= 3.5 && (pe.voi || 0) > 0.5;

          return (
            <div
              key={strike}
              className={[
                "opt-crow",
                isAtm  ? "opt-crow--atm"  : "",
                isHlt  ? "opt-crow--hlt"  : "",
              ].filter(Boolean).join(" ")}
            >
              {/* CE Signal */}
              <span className="opt-cell opt-cell--signal">
                {ceSurge && <span className="opt-spike-badge" title="OI spike">⚡</span>}
                <SignalBadge cls={ceClass?.css} label={ceClass?.label} />
                {ce?.oi_chg_pct != null && (
                  <span className={`opt-oi-chg ${ce.oi_chg_pct >= 0 ? "up" : "dn"}`}>
                    {ce.oi_chg_pct > 0 ? "+" : ""}{ce.oi_chg_pct?.toFixed(1)}%
                  </span>
                )}
              </span>

              {/* CE OI bar */}
              <span className="opt-cell opt-cell--oi">
                <OIBar oi={ce?.oi || 0} maxOI={maxCeOI} side="ce" />
              </span>

              {/* CE Vol + VOI */}
              <span className="opt-cell opt-cell--vol">
                <span>{fmtOI(ce?.volume)}</span>
                {ce?.voi != null && (
                  <span className={`opt-voi ${ce.voi > 0.5 ? "opt-voi--hot" : ""}`}>
                    V:OI {fmtVOI(ce.voi)}
                  </span>
                )}
              </span>

              {/* CE LTP */}
              <span className="opt-cell opt-cell--ltp opt-cell--ce-ltp">
                {fmtLTP(ce?.ltp)}
              </span>

              {/* STRIKE */}
              <span className={`opt-cell opt-strike-col ${isAtm ? "opt-atm-label" : ""}`}>
                {strike}
                {isAtm && <span className="opt-atm-tag">ATM</span>}
              </span>

              {/* PE LTP */}
              <span className="opt-cell opt-cell--ltp opt-cell--pe-ltp">
                {fmtLTP(pe?.ltp)}
              </span>

              {/* PE Vol + VOI */}
              <span className="opt-cell opt-cell--vol">
                <span>{fmtOI(pe?.volume)}</span>
                {pe?.voi != null && (
                  <span className={`opt-voi ${pe.voi > 0.5 ? "opt-voi--hot" : ""}`}>
                    V:OI {fmtVOI(pe.voi)}
                  </span>
                )}
              </span>

              {/* PE OI bar */}
              <span className="opt-cell opt-cell--oi">
                <OIBar oi={pe?.oi || 0} maxOI={maxPeOI} side="pe" />
              </span>

              {/* PE Signal */}
              <span className="opt-cell opt-cell--signal">
                {peSurge && <span className="opt-spike-badge" title="OI spike">⚡</span>}
                <SignalBadge cls={peClass?.css} label={peClass?.label} />
                {pe?.oi_chg_pct != null && (
                  <span className={`opt-oi-chg ${pe.oi_chg_pct >= 0 ? "up" : "dn"}`}>
                    {pe.oi_chg_pct > 0 ? "+" : ""}{pe.oi_chg_pct?.toFixed(1)}%
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
