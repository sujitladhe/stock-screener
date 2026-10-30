/**
 * MetricsStrip — top row of 7 stat cards.
 * Props: { metrics, guidance, isConnected }
 */

export default function MetricsStrip({ metrics, guidance, isConnected }) {
  if (!metrics) return (
    <div className="opt-metrics-strip">
      {Array.from({ length: 7 }, (_, i) => (
        <div key={i} className="opt-mc opt-mc--loading" />
      ))}
    </div>
  );

  const {
    spot, pcr, atmIv, ivSkew, expectedMove,
    totalCeOI, totalPeOI, maxCeStrike, maxPeStrike,
  } = metrics;

  const maxPain = guidance?.maxPain || 0;

  const pcrClass =
    pcr < 0.85 ? "opt-mc--dn" : pcr > 1.15 ? "opt-mc--up" : "";

  const skewClass =
    ivSkew > 1.5 ? "opt-mc--dn" : ivSkew < -1.5 ? "opt-mc--up" : "";

  function fmtOI(v) {
    if (!v) return "—";
    if (v >= 1_00_00_000) return `${(v / 1_00_00_000).toFixed(2)}Cr`;
    if (v >= 1_00_000)    return `${(v / 1_00_000).toFixed(1)}L`;
    return v.toLocaleString("en-IN");
  }

  const cards = [
    {
      label: "NIFTY SPOT",
      value: spot ? spot.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : "—",
      sub:   isConnected ? "● Live" : "○ Offline",
      cls:   isConnected ? "opt-mc--live" : "opt-mc--offline",
    },
    {
      label: "PCR",
      value: pcr.toFixed(3),
      sub:   pcr < 0.85 ? "Bearish" : pcr > 1.15 ? "Bullish" : "Neutral",
      cls:   pcrClass,
    },
    {
      label: "MAX PAIN",
      value: maxPain ? maxPain.toLocaleString("en-IN") : "—",
      sub:   maxPain && spot
        ? `Spot ${spot > maxPain ? "↑" : "↓"} ${Math.abs(spot - maxPain).toFixed(0)}pts`
        : "",
      cls: "",
    },
    {
      label: "ATM IV",
      value: atmIv ? `${atmIv}%` : "—",
      sub:   "Annualised",
      cls:   "",
    },
    {
      label: "IV SKEW",
      value: ivSkew ? `${ivSkew > 0 ? "+" : ""}${ivSkew}` : "—",
      sub:   ivSkew > 1.5 ? "Put-heavy" : ivSkew < -1.5 ? "Call-heavy" : "Balanced",
      cls:   skewClass,
    },
    {
      label: "EXPECTED MOVE",
      value: expectedMove ? `±${expectedMove}` : "—",
      sub:   "Daily (1-day)",
      cls:   "",
    },
    {
      label: "OI WALLS",
      value: maxCeStrike ? `${maxCeStrike} / ${maxPeStrike}` : "—",
      sub:   `${fmtOI(totalCeOI)} CE · ${fmtOI(totalPeOI)} PE`,
      cls:   "",
    },
  ];

  return (
    <div className="opt-metrics-strip">
      {cards.map((c) => (
        <div key={c.label} className={`opt-mc ${c.cls || ""}`}>
          <span className="opt-mc__label">{c.label}</span>
          <span className="opt-mc__value">{c.value}</span>
          {c.sub && <span className="opt-mc__sub">{c.sub}</span>}
        </div>
      ))}
    </div>
  );
}
