import { useState, useEffect } from "react";
import {
  getAlerts, createAlert, deleteAlert,
  getAlertHistory, clearAlertHistory,
} from "../api";
import { getNotificationPermission, requestNotificationPermission } from "../browserNotify";
import StockSearchInput from "../components/StockSearchInput";
import { useConfirm } from "../hooks/useConfirm";
import { showToast } from "../toast";

const METRIC_LABELS = { price: "Price", value: "Value (volume × price)" };
const DIRECTION_LABELS = { above: "rises to or above", below: "falls to or below" };
const ONE_CRORE = 10000000;

function formatAmount(metric, value) {
  return metric === "value" ? `₹${value} Cr` : `₹${value}`;
}
function scaleForSubmit(metric, rawInput) {
  const num = parseFloat(rawInput);
  return metric === "value" ? num * ONE_CRORE : num;
}
function displayThreshold(metric, storedValue) {
  return metric === "value" ? `${(storedValue / ONE_CRORE).toFixed(2)} Cr` : storedValue;
}

export default function Alerts({ refreshSignal }) {
  const [alerts, setAlerts] = useState([]);
  const [history, setHistory] = useState([]);
  const [notifPermission, setNotifPermission] = useState(getNotificationPermission());
  const [error, setError] = useState(null);
  const [confirm, confirmDialog] = useConfirm();

  const [symbol, setSymbol] = useState("");
  const [metric1, setMetric1] = useState("price");
  const [operator1, setOperator1] = useState("above");
  const [threshold1, setThreshold1] = useState("");
  const [hasCondition2, setHasCondition2] = useState(false);
  const [metric2, setMetric2] = useState("value");
  const [operator2, setOperator2] = useState("above");
  const [threshold2, setThreshold2] = useState("");
  const [combinator, setCombinator] = useState("AND");
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  function reloadAlerts() {
    getAlerts().then(setAlerts).catch((err) => setError(err.message));
  }
  function reloadHistory() {
    getAlertHistory().then(setHistory).catch((err) => setError(err.message));
  }

  useEffect(() => {
    reloadAlerts();
    reloadHistory();
  }, []);

  // A user_alert WS message means one just fired -- refetch both lists
  // so it disappears from "Your alerts" and appears in history live.
  useEffect(() => {
    if (!refreshSignal) return;
    reloadAlerts();
    reloadHistory();
  }, [refreshSignal]);

  async function handleEnableNotifications() {
    const result = await requestNotificationPermission();
    setNotifPermission(result);
  }

  async function handleCreate(e) {
    e.preventDefault();
    if (!symbol) {
      setError("Pick a stock first.");
      return;
    }
    if (!threshold1) {
      setError("Set a threshold for the first condition.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await createAlert({
        trading_symbol: symbol,
        condition_1_metric: metric1,
        condition_1_operator: operator1,
        condition_1_threshold: scaleForSubmit(metric1, threshold1),
        condition_2_metric: hasCondition2 ? metric2 : null,
        condition_2_operator: hasCondition2 ? operator2 : null,
        condition_2_threshold: hasCondition2 ? scaleForSubmit(metric2, threshold2) : null,
        combinator: hasCondition2 ? combinator : null,
        sound_enabled: soundEnabled,
      });
      showToast(`Alert for ${symbol} created.`);
      setSymbol("");
      setThreshold1("");
      setThreshold2("");
      setHasCondition2(false);
      reloadAlerts();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(alert) {
    const ok = await confirm("Delete this alert?", `The ${alert.trading_symbol} alert will be removed before it has a chance to trigger.`, "Delete alert", true);
    if (!ok) return;
    await deleteAlert(alert.id);
    showToast(`Alert for ${alert.trading_symbol} deleted.`);
    reloadAlerts();
  }

  async function handleClearHistory() {
    const ok = await confirm("Clear alert history?", "This can't be undone.", "Clear history", true);
    if (!ok) return;
    await clearAlertHistory();
    setHistory([]);
  }

  function conditionSummary(a) {
    let text = `${METRIC_LABELS[a.condition_1_metric]} ${DIRECTION_LABELS[a.condition_1_operator]} ${displayThreshold(a.condition_1_metric, a.condition_1_threshold)}`;
    if (a.condition_2_metric) {
      text += ` ${a.combinator} ${METRIC_LABELS[a.condition_2_metric]} ${DIRECTION_LABELS[a.condition_2_operator]} ${displayThreshold(a.condition_2_metric, a.condition_2_threshold)}`;
    }
    return text;
  }

  // Once an alert fires, the backend deactivates it permanently (it's
  // already in `history` by then) -- so only ever show the ones still
  // waiting to trigger here.
  const activeAlerts = alerts.filter((a) => a.is_active);

  return (
    <div>
      {notifPermission !== "granted" && notifPermission !== "unsupported" && (
        <div className="panel" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, padding: "10px 14px", marginBottom: 16, fontSize: 12, background: "var(--ink-soft)" }}>
          <span>Enable browser notifications to get alerts even when you're on a different tab.</span>
          <button type="button" className="btn sm" onClick={handleEnableNotifications}>
            {notifPermission === "denied" ? "Blocked — check browser settings" : "Enable notifications"}
          </button>
        </div>
      )}

      <form className="panel alert-form" style={{ margin: "6px 0 20px" }} onSubmit={handleCreate}>
        <h2 style={{ fontSize: 16, fontWeight: 600 }}>New alert</h2>
        <div className="field" style={{ maxWidth: 340 }}>
          <span>Stock</span>
          <StockSearchInput placeholder="Search for a stock" clearOnSelect={false} value={symbol} onSelect={setSymbol} />
        </div>

        <div className="field">
          <span>Tell me when</span>
          <div className="cond">
            <select className="select" value={metric1} onChange={(e) => setMetric1(e.target.value)}>
              <option value="price">Price</option>
              <option value="value">Value (volume × price)</option>
            </select>
            <select className="select" value={operator1} onChange={(e) => setOperator1(e.target.value)}>
              <option value="above">rises to or above</option>
              <option value="below">falls to or below</option>
            </select>
            <input className="input num" inputMode="decimal" placeholder="Amount" value={threshold1} onChange={(e) => setThreshold1(e.target.value)} />
            <span className="muted small">{metric1 === "value" ? "Cr" : "₹"}</span>
          </div>

          {hasCondition2 ? (
            <>
              <div className="seg inline" role="group" aria-label="Combine" style={{ alignSelf: "flex-start", marginTop: 10 }}>
                <button type="button" className={combinator === "AND" ? "active" : ""} onClick={() => setCombinator("AND")}>AND</button>
                <button type="button" className={combinator === "OR" ? "active" : ""} onClick={() => setCombinator("OR")}>OR</button>
              </div>
              <div className="cond" style={{ marginTop: 10 }}>
                <select className="select" value={metric2} onChange={(e) => setMetric2(e.target.value)}>
                  <option value="price">Price</option>
                  <option value="value">Value (volume × price)</option>
                </select>
                <select className="select" value={operator2} onChange={(e) => setOperator2(e.target.value)}>
                  <option value="above">rises to or above</option>
                  <option value="below">falls to or below</option>
                </select>
                <input className="input num" inputMode="decimal" placeholder="Amount" value={threshold2} onChange={(e) => setThreshold2(e.target.value)} />
                <span className="muted small">{metric2 === "value" ? "Cr" : "₹"}</span>
              </div>
              <button type="button" className="link" style={{ marginTop: 8 }} onClick={() => setHasCondition2(false)}>Remove second condition</button>
            </>
          ) : (
            <button type="button" className="link" style={{ marginTop: 8, alignSelf: "flex-start" }} onClick={() => setHasCondition2(true)}>Add a second condition</button>
          )}
        </div>

        <label className="check">
          <input type="checkbox" checked={soundEnabled} onChange={(e) => setSoundEnabled(e.target.checked)} />
          <span>Play a sound when it fires</span>
        </label>

        {error && <div className="err" role="alert">{error}</div>}

        <button type="submit" className="btn primary" disabled={submitting} style={{ alignSelf: "flex-start" }}>
          {submitting ? "Creating..." : "Create alert"}
        </button>
      </form>

      <h2 className="section-title" style={{ marginTop: 0 }}>Your alerts</h2>
      <p className="muted small" style={{ margin: "-4px 0 10px" }}>Waiting to trigger. The moment one fires, it moves to Alert history below.</p>
      {activeAlerts.length === 0 ? (
        <div className="panel empty"><b>No alerts yet.</b>Set one above and it will tell you the moment it fires.</div>
      ) : (
        <div className="panel">
          {activeAlerts.map((a) => (
            <div className="alert-row" key={a.id}>
              <div>
                <span className="sym">{a.trading_symbol}</span>
                <div className="sub" style={{ maxWidth: "none" }}>{conditionSummary(a)}</div>
              </div>
              <div className="grow" />
              <button type="button" className="btn sm danger" onClick={() => handleDelete(a)}>Delete</button>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", margin: "26px 0 10px" }}>
        <h2 className="section-title" style={{ margin: 0 }}>Alert history</h2>
        <div className="grow" />
        {history.length > 0 && <button type="button" className="btn sm" onClick={handleClearHistory}>Clear history</button>}
      </div>
      {history.length === 0 ? (
        <div className="panel empty"><b>Nothing has fired yet.</b></div>
      ) : (
        <div className="panel table-panel">
          <table className="tbl">
            <tbody>
              {history.map((h) => (
                <tr key={h.id}>
                  <td><span className="sym">{h.trading_symbol}</span></td>
                  <td>{h.condition_summary}</td>
                  <td className="r num">{h.price_at_trigger}</td>
                  <td className="r num">{new Date(h.triggered_at).toLocaleTimeString("en-IN", { hour12: false })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {confirmDialog}
    </div>
  );
}
