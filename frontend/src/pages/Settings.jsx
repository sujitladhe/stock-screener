import { useState, useEffect } from "react";
import { showToast } from "../toast";
import { getScreenerSettings, updateScreenerSettings } from "../api";

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

// ── Screener Conditions panel ────────────────────────────────────────────────

function ScreenerConditionsPanel() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving]   = useState(false);
  const [c1Mult, setC1Mult]   = useState("");
  const [c1Val, setC1Val]     = useState("");
  const [c2Mult, setC2Mult]   = useState("");
  const [c2Val, setC2Val]     = useState("");

  useEffect(() => {
    getScreenerSettings()
      .then((s) => {
        setC1Mult(String(s.cond1_multiplier));
        setC1Val(String(s.cond1_min_value_cr));
        setC2Mult(String(s.cond2_multiplier));
        setC2Val(String(s.cond2_min_value_cr));
      })
      .catch(() => showToast("Could not load screener conditions.", "error"))
      .finally(() => setLoading(false));
  }, []);

  async function handleSave(e) {
    e.preventDefault();
    const payload = {
      cond1_multiplier: parseInt(c1Mult, 10),
      cond1_min_value_cr: parseFloat(c1Val),
      cond2_multiplier: parseInt(c2Mult, 10),
      cond2_min_value_cr: parseFloat(c2Val),
    };
    if (!payload.cond1_multiplier || !payload.cond1_min_value_cr ||
        !payload.cond2_multiplier || !payload.cond2_min_value_cr) {
      showToast("All four fields are required.", "error");
      return;
    }
    setSaving(true);
    try {
      await updateScreenerSettings(payload);
      showToast("Screener conditions saved. The engine picks them up within ~2 minutes.");
    } catch (err) {
      showToast(`Could not save: ${err.message}`, "error");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return (
    <div className="panel alert-form" style={{ maxWidth: 560, margin: "6px 0 20px" }}>
      <h2 style={{ fontSize: 16, fontWeight: 600 }}>Screener conditions</h2>
      <p className="muted small">Loading...</p>
    </div>
  );

  return (
    <form className="panel alert-form" style={{ maxWidth: 560, margin: "6px 0 20px" }} onSubmit={handleSave}>
      <h2 style={{ fontSize: 16, fontWeight: 600 }}>Screener conditions</h2>
      <p className="hint">
        A stock appears on Live when it meets <b>either</b> of these two conditions
        in the current minute. Changes apply to <b>all users</b> and take effect
        within ~2 minutes — no server restart needed.
      </p>

      {/* Condition 1 */}
      <div
        style={{
          padding: "14px",
          borderRadius: 10,
          border: "1px solid var(--line)",
          borderLeft: "3px solid var(--down)",
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        <span style={{ fontWeight: 600, fontSize: 13 }}>Condition 1 (stricter)</span>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span className="muted small">Volume &gt;</span>
          <input
            className="input num"
            type="number"
            min="1"
            step="1"
            value={c1Mult}
            onChange={(e) => setC1Mult(e.target.value)}
            style={{ width: 80 }}
            aria-label="Condition 1 multiplier"
          />
          <span className="muted small">× average</span>
          <span className="muted small" style={{ margin: "0 4px" }}>AND value &gt;</span>
          <input
            className="input num"
            type="number"
            min="0.1"
            step="0.5"
            value={c1Val}
            onChange={(e) => setC1Val(e.target.value)}
            style={{ width: 90 }}
            aria-label="Condition 1 minimum value in crores"
          />
          <span className="muted small">Cr</span>
        </div>
        {c1Mult && c1Val && (
          <p className="hint" style={{ margin: 0 }}>
            Volume &gt; {c1Mult}× avg/min <b>AND</b> value &gt; ₹{c1Val} Cr in the current minute.
          </p>
        )}
      </div>

      <div style={{ textAlign: "center", color: "var(--muted)", fontSize: 13, margin: "-4px 0" }}>OR</div>

      {/* Condition 2 */}
      <div
        style={{
          padding: "14px",
          borderRadius: 10,
          border: "1px solid var(--line)",
          borderLeft: "3px solid var(--mari)",
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        <span style={{ fontWeight: 600, fontSize: 13 }}>Condition 2 (more lenient)</span>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span className="muted small">Volume &gt;</span>
          <input
            className="input num"
            type="number"
            min="1"
            step="1"
            value={c2Mult}
            onChange={(e) => setC2Mult(e.target.value)}
            style={{ width: 80 }}
            aria-label="Condition 2 multiplier"
          />
          <span className="muted small">× average</span>
          <span className="muted small" style={{ margin: "0 4px" }}>AND value &gt;</span>
          <input
            className="input num"
            type="number"
            min="0.1"
            step="0.5"
            value={c2Val}
            onChange={(e) => setC2Val(e.target.value)}
            style={{ width: 90 }}
            aria-label="Condition 2 minimum value in crores"
          />
          <span className="muted small">Cr</span>
        </div>
        {c2Mult && c2Val && (
          <p className="hint" style={{ margin: 0 }}>
            Volume &gt; {c2Mult}× avg/min <b>AND</b> value &gt; ₹{c2Val} Cr in the current minute.
          </p>
        )}
      </div>

      <button type="submit" className="btn primary" style={{ alignSelf: "flex-start" }} disabled={saving}>
        {saving ? "Saving..." : "Save conditions"}
      </button>
    </form>
  );
}

// ── Main Settings page ───────────────────────────────────────────────────────

export default function Settings({ settings, onChange }) {
  const [riskEnabled, setRiskEnabled] = useState(settings.riskEnabled);
  const [riskAmount, setRiskAmount]   = useState(settings.riskAmount ?? "");
  const [riskPct, setRiskPct]         = useState(settings.riskPct ?? "");

  // Green candle threshold
  const [greenEnabled, setGreenEnabled]     = useState(settings.greenCandleThreshold != null);
  const [greenThreshold, setGreenThreshold] = useState(settings.greenCandleThreshold ?? "1.5");

  // Capital for delivery order sizing
  const [capital, setCapital] = useState(settings.capital ?? "");

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

  function handleSaveCapital(e) {
    e.preventDefault();
    const cap = parseFloat(capital) || null;
    onChange({ capital: cap });
    showToast("Capital setting saved.");
  }

  const capitalNum = parseFloat(capital);

  return (
    <div>
      {/* Screener conditions — fetched from backend */}
      <ScreenerConditionsPanel />

      {/* Risk-based order sizing */}
      <form className="panel alert-form" style={{ maxWidth: 520, margin: "0 0 20px" }} onSubmit={handleSaveRisk}>
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

      {/* Capital for delivery order sizing */}
      <form className="panel alert-form" style={{ maxWidth: 520, margin: "0 0 20px" }} onSubmit={handleSaveCapital}>
        <h2 style={{ fontSize: 16, fontWeight: 600 }}>Capital for delivery orders</h2>
        <p className="hint">
          When you switch to Delivery in an order window, quantity is automatically calculated as
          your capital divided by the stock's price. You can still edit it before placing the order.
        </p>
        <label className="field" style={{ maxWidth: 260 }}>
          <span>Total capital (₹)</span>
          <input
            className="input num"
            inputMode="decimal"
            placeholder="e.g. 100000"
            value={capital}
            onChange={(e) => setCapital(e.target.value)}
          />
        </label>
        {capitalNum > 0 && (
          <p className="hint">
            Example: at ₹100/share → {fmtInt(Math.floor(capitalNum / 100))} shares &nbsp;·&nbsp;
            at ₹500/share → {fmtInt(Math.floor(capitalNum / 500))} shares.
          </p>
        )}
        <button type="submit" className="btn primary" style={{ alignSelf: "flex-start" }}>Save settings</button>
      </form>

      {/* Green candle highlight on Live */}
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
