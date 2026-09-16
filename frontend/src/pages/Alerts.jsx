import { useState, useEffect } from "react";
import {
  getAlerts, createAlert, toggleAlert, deleteAlert,
  getAlertHistory, clearAlertHistory,
} from "../api";
import { getNotificationPermission, requestNotificationPermission } from "../browserNotify";
import StockSearchInput from "../components/StockSearchInput";

// 1 Crore = 1,00,00,000 = 10,000,000. Per an explicit product decision,
// the VALUE (Volume x Price) condition's threshold is entered in
// crores for convenience (e.g. "6" means 6 Cr) — raw rupee amounts for
// this metric are unwieldy to type (6 Cr = 60000000). The PRICE
// condition stays in plain rupees, since no NSE stock trades at
// "crores per share" — only Value gets this scaling.
const ONE_CRORE = 10000000;

const METRIC_LABELS = { price: "Price", value: "Value (Vol x Price)" };
const OPERATOR_LABELS = { above: ">= (crosses above)", below: "<= (crosses below)" };

function scaleThresholdForSubmit(metric, rawInput) {
  const num = parseFloat(rawInput);
  return metric === "value" ? num * ONE_CRORE : num;
}

function formatThresholdForDisplay(metric, storedValue) {
  if (metric === "value") {
    return `${(storedValue / ONE_CRORE).toFixed(2)} Cr`;
  }
  return storedValue;
}

export default function Alerts({ onNavigateLive, refreshSignal }) {
  const [alerts, setAlerts] = useState([]);
  const [history, setHistory] = useState([]);
  const [notifPermission, setNotifPermission] = useState(getNotificationPermission());
  const [error, setError] = useState(null);

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

  // Refetch whenever App.jsx signals a new alert fired — this is what
  // makes the page update live instead of only on manual refresh.
  useEffect(() => {
    if (refreshSignal === undefined || refreshSignal === 0) return;
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
        condition_1_threshold: scaleThresholdForSubmit(metric1, threshold1),
        condition_2_metric: hasCondition2 ? metric2 : null,
        condition_2_operator: hasCondition2 ? operator2 : null,
        condition_2_threshold: hasCondition2 ? scaleThresholdForSubmit(metric2, threshold2) : null,
        combinator: hasCondition2 ? combinator : null,
        sound_enabled: soundEnabled,
      });
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

  async function handleToggle(alertId) {
    await toggleAlert(alertId);
    reloadAlerts();
  }

  async function handleDelete(alertId) {
    if (!window.confirm("Delete this alert?")) return;
    await deleteAlert(alertId);
    reloadAlerts();
  }

  async function handleClearHistory() {
    if (!window.confirm("Clear all alert history? This can't be undone.")) return;
    await clearAlertHistory();
    setHistory([]);
  }

  function conditionSummary(a) {
    let text = `${METRIC_LABELS[a.condition_1_metric]} ${OPERATOR_LABELS[a.condition_1_operator]} ${formatThresholdForDisplay(a.condition_1_metric, a.condition_1_threshold)}`;
    if (a.condition_2_metric) {
      text += ` ${a.combinator} ${METRIC_LABELS[a.condition_2_metric]} ${OPERATOR_LABELS[a.condition_2_operator]} ${formatThresholdForDisplay(a.condition_2_metric, a.condition_2_threshold)}`;
    }
    return text;
  }

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <nav style={styles.nav}>
          <span style={styles.navLink} onClick={onNavigateLive}>Live</span>
          <span style={styles.navActive}>Alerts</span>
        </nav>
      </header>

      {notifPermission !== "granted" && notifPermission !== "unsupported" && (
        <div style={styles.notifBanner}>
          <span>Enable browser notifications to get alerts even when you're on a different tab.</span>
          <button onClick={handleEnableNotifications}>
            {notifPermission === "denied" ? "Blocked - check browser settings" : "Enable notifications"}
          </button>
        </div>
      )}

      <form style={styles.createCard} onSubmit={handleCreate}>
        <div style={styles.cardTitle}>Create alert</div>

        <StockSearchInput
          placeholder="Search for a stock..."
          onSelect={setSymbol}
        />
        {symbol && <div style={styles.selectedSymbol}>Selected: <strong>{symbol}</strong></div>}

        <div style={styles.conditionRow}>
          <select value={metric1} onChange={(e) => setMetric1(e.target.value)}>
            <option value="price">Price</option>
            <option value="value">Value (Vol x Price)</option>
          </select>
          <select value={operator1} onChange={(e) => setOperator1(e.target.value)}>
            <option value="above">{">= crosses above"}</option>
            <option value="below">{"<= crosses below"}</option>
          </select>
          <input
            type="number"
            step="any"
            placeholder={metric1 === "value" ? "Threshold (Cr)" : "Threshold (Rs)"}
            value={threshold1}
            onChange={(e) => setThreshold1(e.target.value)}
            style={styles.thresholdInput}
          />
        </div>
        {metric1 === "value" && threshold1 && (
          <div style={styles.hint}>= {"\u20b9"}{scaleThresholdForSubmit("value", threshold1).toLocaleString("en-IN")}</div>
        )}

        {!hasCondition2 ? (
          <button type="button" style={styles.linkBtn} onClick={() => setHasCondition2(true)}>
            + Add second condition
          </button>
        ) : (
          <>
            <div style={styles.combinatorRow}>
              <select value={combinator} onChange={(e) => setCombinator(e.target.value)}>
                <option value="AND">AND</option>
                <option value="OR">OR</option>
              </select>
              <button type="button" style={styles.linkBtn} onClick={() => setHasCondition2(false)}>
                Remove second condition
              </button>
            </div>
            <div style={styles.conditionRow}>
              <select value={metric2} onChange={(e) => setMetric2(e.target.value)}>
                <option value="price">Price</option>
                <option value="value">Value (Vol x Price)</option>
              </select>
              <select value={operator2} onChange={(e) => setOperator2(e.target.value)}>
                <option value="above">{">= crosses above"}</option>
                <option value="below">{"<= crosses below"}</option>
              </select>
              <input
                type="number"
                step="any"
                placeholder={metric2 === "value" ? "Threshold (Cr)" : "Threshold (Rs)"}
                value={threshold2}
                onChange={(e) => setThreshold2(e.target.value)}
                style={styles.thresholdInput}
              />
            </div>
            {metric2 === "value" && threshold2 && (
              <div style={styles.hint}>= {"\u20b9"}{scaleThresholdForSubmit("value", threshold2).toLocaleString("en-IN")}</div>
            )}
          </>
        )}

        <label style={styles.checkboxRow}>
          <input type="checkbox" checked={soundEnabled} onChange={(e) => setSoundEnabled(e.target.checked)} />
          Play sound when this alert fires
        </label>

        {error && <div style={styles.error}>{error}</div>}

        <button type="submit" disabled={submitting} style={styles.submitBtn}>
          {submitting ? "Creating..." : "Create alert"}
        </button>
      </form>

      <div style={styles.cardTitle}>Your alerts</div>
      {alerts.length === 0 ? (
        <p style={styles.muted}>No alerts yet.</p>
      ) : (
        alerts.map((a) => (
          <div key={a.id} style={styles.alertRow}>
            <div>
              <div style={styles.alertSymbol}>
                {a.trading_symbol} {!a.is_active && <span style={styles.inactiveTag}>fired / paused</span>}
              </div>
              <div style={styles.alertCondition}>{conditionSummary(a)}</div>
            </div>
            <div style={styles.alertActions}>
              <button style={styles.smallBtn} onClick={() => handleToggle(a.id)}>
                {a.is_active ? "Pause" : "Resume"}
              </button>
              <button style={styles.smallBtn} onClick={() => handleDelete(a.id)}>Delete</button>
            </div>
          </div>
        ))
      )}

      <div style={styles.historyHead}>
        <span style={styles.cardTitle}>Alert history</span>
        {history.length > 0 && (
          <button style={styles.smallBtn} onClick={handleClearHistory}>Clear history</button>
        )}
      </div>
      {history.length === 0 ? (
        <p style={styles.muted}>No alerts have triggered yet.</p>
      ) : (
        <table style={styles.table}>
          <tbody>
            {history.map((h) => (
              <tr key={h.id}>
                <td style={styles.tdLeft}>{h.trading_symbol}</td>
                <td style={styles.tdLeft}>{h.condition_summary}</td>
                <td style={styles.tdRight} className="mono">{h.price_at_trigger}</td>
                <td style={styles.tdRight} className="mono">
                  {new Date(h.triggered_at).toLocaleTimeString("en-IN", { hour12: false })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

const styles = {
  page: { padding: "20px 24px", maxWidth: 700, margin: "0 auto" },
  header: {
    display: "flex", alignItems: "center", gap: 16, marginBottom: 20,
    paddingBottom: 16, borderBottom: "1px solid var(--border)",
  },
  nav: { display: "flex", gap: 16, fontSize: 13 },
  navActive: { color: "var(--text)", fontWeight: 500, borderBottom: "2px solid var(--focus)", paddingBottom: 2 },
  navLink: { color: "var(--text-muted)", cursor: "pointer", paddingBottom: 2 },
  notifBanner: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    background: "rgba(91,140,255,0.1)", border: "1px solid rgba(91,140,255,0.3)",
    borderRadius: 8, padding: "10px 14px", marginBottom: 16, fontSize: 12, gap: 10,
  },
  createCard: {
    background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8,
    padding: 16, marginBottom: 20, display: "flex", flexDirection: "column", gap: 10,
  },
  cardTitle: { fontSize: 13, fontWeight: 600, marginBottom: 4 },
  selectedSymbol: { fontSize: 12, color: "var(--text-muted)" },
  conditionRow: { display: "flex", gap: 8 },
  thresholdInput: { flex: 1 },
  hint: { fontSize: 11, color: "var(--text-muted)", marginTop: -6 },
  combinatorRow: { display: "flex", alignItems: "center", gap: 10 },
  linkBtn: {
    background: "none", border: "none", color: "var(--focus)", fontSize: 12,
    padding: 0, textAlign: "left", cursor: "pointer", width: "fit-content",
  },
  checkboxRow: { display: "flex", alignItems: "center", gap: 8, fontSize: 13 },
  error: {
    fontSize: 12, color: "var(--negative)", background: "rgba(255, 92, 92, 0.1)",
    border: "1px solid rgba(255, 92, 92, 0.3)", borderRadius: 6, padding: "8px 12px",
  },
  submitBtn: { background: "var(--focus)", borderColor: "var(--focus)", color: "#fff", marginTop: 4 },
  muted: { color: "var(--text-muted)", fontSize: 13, marginBottom: 20 },
  alertRow: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8,
    padding: "12px 14px", marginBottom: 8,
  },
  alertSymbol: { fontSize: 13, fontWeight: 600 },
  inactiveTag: { fontSize: 10, color: "var(--text-muted)", fontWeight: 400, marginLeft: 6 },
  alertCondition: { fontSize: 12, color: "var(--text-muted)", marginTop: 2 },
  alertActions: { display: "flex", gap: 6 },
  smallBtn: { fontSize: 11, padding: "5px 9px" },
  historyHead: { display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 24, marginBottom: 8 },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 12 },
  tdLeft: { textAlign: "left", padding: "7px 4px", borderBottom: "1px solid var(--border)" },
  tdRight: { textAlign: "right", padding: "7px 4px", borderBottom: "1px solid var(--border)" },
};
