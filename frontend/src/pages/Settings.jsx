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
  const [riskAmount, setRiskAmount] = useState(settings.riskAmount ?? "");
  const [riskPct, setRiskPct] = useState(settings.riskPct ?? "");

  function handleSave(e) {
    e.preventDefault();
    onChange({
      riskEnabled,
      riskAmount: parseFloat(riskAmount) || null,
      riskPct: parseFloat(riskPct) || null,
    });
    showToast("Settings saved.");
  }

  return (
    <div>
      <form className="panel alert-form" style={{ maxWidth: 520, margin: "6px 0 20px" }} onSubmit={handleSave}>
        <h2 style={{ fontSize: 16, fontWeight: 600 }}>Risk-based order sizing</h2>
        <p className="hint">When this is on, opening Buy or Sell for a new order fills in a quantity worked out from your risk, using the stock's current price. You can still change it before placing the order.</p>
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
