/**
 * OptionChain — 9-column option chain table.
 * Columns: CE Signal | CE OI bar | CE Vol+VOI | CE LTP | STRIKE | PE LTP | PE Vol+VOI | PE OI bar | PE Signal
 *
 * Prices / OI / volume are live. The signal badges and the OI-change % come
 * from the server engine (per-strike price-vs-OI change over the look-back
 * window) so they stay stable between 5-minute decisions.
 *
 * Props: { chainData, guidance }
 */

import { useMemo } from "react";

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

export default function OptionChain({ chainData, guidance }) {
  const { strikes = {}, atm = 0 } = chainData;
  const strikeSignals = guidance?.strikeSignals || {};

  const highlightedStrikes = useMemo(() => {
    const set = new Set();
    (guidance?.opportunities || []).forEach((op) => {
      if (op.strike) set.add(op.strike);
      if (op.pe_strike) set.add(op.pe_strike);
    });
    (guidance?.spikeAlerts || []).forEach((a) => set.add(a.strike));
    return set;
  }, [guidance]);

  const spikeKeys = useMemo(
    () => new Set((guidance?.spikeAlerts || []).map((a) => `${a.strike}-${a.type}`)),
    [guidance]
  );

  const sortedStrikes = useMemo(
    () => Object.keys(strikes).map(Number).sort((a, b) => b - a),
    [strikes]
  );

  const maxCeOI = useMemo(
    () => Math.max(...sortedStrikes.map((s) => strikes[s]?.ce?.oi || 0), 1),
    [sortedStrikes, strikes]
  );
  const maxPeOI = useMemo(
    () => Math.max(...sortedStrikes.map((s) => strikes[s]?.pe?.oi || 0), 1),
    [sortedStrikes, strikes]
  );

  if (sortedStrikes.length === 0) {
    return <div className="opt-chain-empty">Waiting for option chain data…</div>;
  }

  return (
    <div className="opt-chain-wrap">
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

      <div className="opt-chain-body">
        {sortedStrikes.map((strike) => {
          const ce = strikes[strike]?.ce;
          const pe = strikes[strike]?.pe;
          const ceSig = strikeSignals[strike]?.ce;
          const peSig = strikeSignals[strike]?.pe;

          const isAtm = strike === atm;
          const isHlt = highlightedStrikes.has(strike);
          const ceSpike = spikeKeys.has(`${strike}-CE`);
          const peSpike = spikeKeys.has(`${strike}-PE`);

          return (
            <div
              key={strike}
              className={["opt-crow", isAtm ? "opt-crow--atm" : "", isHlt ? "opt-crow--hlt" : ""]
                .filter(Boolean).join(" ")}
            >
              <span className="opt-cell opt-cell--signal">
                {ceSpike && <span className="opt-spike-badge" title="OI spike">⚡</span>}
                <SignalBadge cls={ceSig?.css} label={ceSig?.label} />
                {ceSig?.oi_chg_pct != null && (
                  <span className={`opt-oi-chg ${ceSig.oi_chg_pct >= 0 ? "up" : "dn"}`}>
                    {ceSig.oi_chg_pct > 0 ? "+" : ""}{ceSig.oi_chg_pct.toFixed(1)}%
                  </span>
                )}
              </span>

              <span className="opt-cell opt-cell--oi">
                <OIBar oi={ce?.oi || 0} maxOI={maxCeOI} side="ce" />
              </span>

              <span className="opt-cell opt-cell--vol">
                <span>{fmtOI(ce?.volume)}</span>
                {ce?.voi != null && (
                  <span className={`opt-voi ${ce.voi > 0.5 ? "opt-voi--hot" : ""}`}>
                    V:OI {fmtVOI(ce.voi)}
                  </span>
                )}
              </span>

              <span className="opt-cell opt-cell--ltp opt-cell--ce-ltp">{fmtLTP(ce?.ltp)}</span>

              <span className={`opt-cell opt-strike-col ${isAtm ? "opt-atm-label" : ""}`}>
                {strike}
                {isAtm && <span className="opt-atm-tag">ATM</span>}
              </span>

              <span className="opt-cell opt-cell--ltp opt-cell--pe-ltp">{fmtLTP(pe?.ltp)}</span>

              <span className="opt-cell opt-cell--vol">
                <span>{fmtOI(pe?.volume)}</span>
                {pe?.voi != null && (
                  <span className={`opt-voi ${pe.voi > 0.5 ? "opt-voi--hot" : ""}`}>
                    V:OI {fmtVOI(pe.voi)}
                  </span>
                )}
              </span>

              <span className="opt-cell opt-cell--oi">
                <OIBar oi={pe?.oi || 0} maxOI={maxPeOI} side="pe" />
              </span>

              <span className="opt-cell opt-cell--signal">
                {peSpike && <span className="opt-spike-badge" title="OI spike">⚡</span>}
                <SignalBadge cls={peSig?.css} label={peSig?.label} />
                {peSig?.oi_chg_pct != null && (
                  <span className={`opt-oi-chg ${peSig.oi_chg_pct >= 0 ? "up" : "dn"}`}>
                    {peSig.oi_chg_pct > 0 ? "+" : ""}{peSig.oi_chg_pct.toFixed(1)}%
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
