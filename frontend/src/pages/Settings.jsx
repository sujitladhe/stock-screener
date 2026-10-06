import { useState } from "react";
import { showToast } from "../toast";

function fmt2(n) {
  return Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtInt(n) {
  return Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}
function riskExampleText(amt, pct) {
  if (!(amt > 0) || !(pct > 0)) return "Enter both to see an example.";
  const price = 100;
  const riskPerShare = price * (pct / 100);
  const qty = Math.floor(amt / riskPerShare);
  return `Example: a ₹${price} stock → risk per share ₹${fmt2(riskPerShare)} → quantity ${fmtInt(qty)}.`;
}

export default function Settings({ settings, onChange }) {
  const [riskEnabled, setRiskEnabled] = useState(settings.riskEnabled);
  const [riskAmount, setRiskAmount]   = useState(settings.riskAmount ?? "");
  const [riskPct, setRiskPct]         = useState(settings.riskPct ?? "");

  // NEW (0004) — green candle threshold
  const [greenEnabled, setGreenEnabled]     = useState(settings.greenCandleThreshold != null);
  const [greenThreshold, setGreenThreshold] = useState(settings.greenCandleThreshold ?? "1.5");

  function handleSaveRisk(e) {
    e.preventDefault();
    onChange({
      riskEnabled,
      riskAmount: parseFloat(riskAmount) || null,
      riskPct: parseFloat(riskPct) || null,
    });
    showToast("Risk settings saved.");
  }

  function handleSaveGreen(e) {
    e.preventDefault();
    const threshold = greenEnabled ? (parseFloat(greenThreshold) || 1.5) : null;
    onChange({ greenCandleThreshold: threshold });
    showToast("Green candle settings saved.");
  }

  return (
    <div>
      {/* Risk-based order sizing */}
      <form className="panel alert-form" style={{ maxWidth: 520, margin: "6px 0 20px" }} onSubmit={handleSaveRisk}>
        <h2 style={{ fontSize: 16, fontWeight: 600 }}>Risk-based order sizing</h2>
        <p className="hint">
          When this is on, opening Buy or Sell for a new order fills in a quantity worked out from your risk,
          using the stock's current price. You can still change it before placing the order.
        </p>
        <label className="check">
          <input type="checkbox" checked={riskEnabled} onChange={(e) => setRiskEnabled(e.target.checked)} />
          <span>Automatically size new orders from my risk</span>
        </label>
        <div className="grid2">
          <label className="field">
            <span>Risk per trade (₹)</span>
            <input className="input num" inputMode="decimal" placeholder="12000" value={riskAmount} onChange={(e) => setRiskAmount(e.target.value)} />
          </label>
          <label className="field">
            <span>Default stoploss %</span>
            <input className="input num" inputMode="decimal" placeholder="2" value={riskPct} onChange={(e) => setRiskPct(e.target.value)} />
          </label>
        </div>
        <p className="hint">{riskExampleText(parseFloat(riskAmount), parseFloat(riskPct))}</p>
        <button type="submit" className="btn primary" style={{ alignSelf: "flex-start" }}>Save settings</button>
      </form>

      {/* NEW (0004) — green candle highlight on Live */}
      <form className="panel alert-form" style={{ maxWidth: 520, margin: "0 0 20px" }} onSubmit={handleSaveGreen}>
        <h2 style={{ fontSize: 16, fontWeight: 600 }}>Green candle highlight on Live</h2>
        <p className="hint">
          A stock that meets the screener condition AND has a green candle at least this big gets
          a green background on the Live table so you can spot it at a glance.
        </p>
        <label className="check">
          <input type="checkbox" checked={greenEnabled} onChange={(e) => setGreenEnabled(e.target.checked)} />
          <span>Highlight rows with a green candle large enough</span>
        </label>
        {greenEnabled && (
          <>
            <label className="field" style={{ maxWidth: 180 }}>
              <span>Minimum candle size (%)</span>
              <input
                className="input num"
                inputMode="decimal"
                placeholder="1.5"
                value={greenThreshold}
                onChange={(e) => setGreenThreshold(e.target.value)}
              />
            </label>
            {/* Live preview of what the highlight looks like */}
            <div
              style={{
                padding: "10px 12px",
                borderRadius: 8,
                background: "var(--up-soft)",
                fontSize: 13,
                display: "flex",
                alignItems: "center",
                gap: 10,
              }}
            >
              <span style={{ fontWeight: 600 }}>SBIN</span>
              <span
                style={{
                  padding: "1px 6px",
                  borderRadius: 5,
                  background: "var(--up-soft)",
                  color: "var(--up)",
                  fontSize: 11,
                  fontWeight: 600,
                  border: "1px solid var(--up)",
                }}
              >
                +{greenThreshold || "1.5"}%
              </span>
              <span className="muted small">preview of highlighted row</span>
            </div>
          </>
        )}
        <button type="submit" className="btn primary" style={{ alignSelf: "flex-start" }}>Save settings</button>
      </form>

      {/* Appearance */}
      <div className="panel alert-form" style={{ maxWidth: 520 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600 }}>Appearance</h2>
        <p className="hint">Screener remembers this choice and opens the same way next time.</p>
        <div className="seg inline" role="group" aria-label="Theme" style={{ alignSelf: "flex-start" }}>
          <button type="button" className={settings.theme === "light" ? "active" : ""} aria-pressed={settings.theme === "light"} onClick={() => onChange({ theme: "light" })}>Light</button>
          <button type="button" className={settings.theme === "dark" ? "active" : ""} aria-pressed={settings.theme === "dark"} onClick={() => onChange({ theme: "dark" })}>Dark</button>
          <button type="button" className={settings.theme === "system" ? "active" : ""} aria-pressed={settings.theme === "system"} onClick={() => onChange({ theme: "system" })}>Match device</button>
        </div>
      </div>
    </div>
  );
}
