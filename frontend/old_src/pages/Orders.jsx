import { useState, useEffect, useRef } from "react";
import { getOrders, cancelOrder } from "../api";
import { showToast } from "../toast";
import PlaceOrderModal from "../components/PlaceOrderModal";
import ModifyOrderModal from "../components/ModifyOrderModal";
import StockSearchInput from "../components/StockSearchInput";

const TERMINAL_STATUSES = new Set(["Executed", "Cancelled", "Rejected"]);
const REORDERABLE_STATUSES = new Set(["Cancelled", "Rejected"]);

// 1 Crore = 10,000,000. Auto-order volume thresholds are stored in RAW
// rupees; crores are purely a display convenience (principle #9).
const ONE_CRORE = 10000000;

// Order-source filter (requirement 10f), in the order the product
// decision listed them: Manual, Auto, All.
const SOURCE_OPTIONS = [
  { value: "manual", label: "Manual" },
  { value: "auto", label: "Auto" },
  { value: "all", label: "All" },
];

const STATUS_COLORS = {
  Pending: "var(--accent-loose)",
  Executed: "var(--positive)",
  Cancelled: "var(--text-muted)",
  Rejected: "var(--negative)",
  // Auto-trade states: Active = saved and watching, Triggering = being
  // sent to the broker at this very moment.
  Active: "var(--focus)",
  Triggering: "var(--accent-loose)",
};

// The backend stores order timestamps as naive datetimes that ALREADY
// hold Indian time (see models.py's now_ist_naive), e.g.
// "2026-09-21T09:16:04.123456". Feeding that string to `new Date()`
// would read it as the BROWSER's local time and then shift it, showing
// the wrong hour for anyone whose device isn't set to IST. So the
// digits are formatted as-is instead — they are already IST.
function formatIST(isoString) {
  if (!isoString) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})/.exec(isoString);
  if (!m) return isoString;
  return `${m[3]}/${m[2]}/${m[1]}, ${m[4]}:${m[5]}:${m[6]}`;
}

function formatCrores(rupees) {
  const cr = rupees / ONE_CRORE;
  return `${Number(cr.toFixed(4))} Cr`;
}

// "Value ≥ 6 Cr AND green candle ≥ 1.7% · till 09:30"
function describeAutoConditions(o) {
  const parts = [];
  if (o.auto_volume_threshold != null) parts.push(`Value ≥ ${formatCrores(o.auto_volume_threshold)}`);
  if (o.auto_candle_pct_threshold != null) parts.push(`green candle ≥ ${o.auto_candle_pct_threshold}%`);
  let text = parts.join(` ${o.auto_combinator || "AND"} `);
  if (o.auto_valid_till) text += ` · till ${o.auto_valid_till}`;
  return text;
}

// Current IST clock, independent of the viewer's device timezone.
function istNow() {
  const timeParts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).format(new Date());
  const weekday = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Kolkata", weekday: "short",
  }).format(new Date());
  return { hhmm: timeParts, weekday };
}

// One-line status hint for an auto order that is still waiting.
function activeHint(o) {
  const { hhmm, weekday } = istNow();
  if (weekday === "Sat" || weekday === "Sun") return "Market closed — checking resumes next trading day";
  if (hhmm < "09:15") return "Checking starts at 09:15";
  // With a "valid till" time the order stops firing after it; without
  // one it is watched until the 15:30 close.
  const windowClosed = o.auto_valid_till ? hhmm > o.auto_valid_till : hhmm >= "15:30";
  if (windowClosed) return "Window closed for today — checking resumes next trading day";
  return "Watching live";
}

export default function Orders({ onNavigateLive, refreshSignal }) {
  const [orders, setOrders] = useState([]);
  const [source, setSource] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [newOrderSymbol, setNewOrderSymbol] = useState(null);
  const [modifyingOrder, setModifyingOrder] = useState(null);
  const [reorderTarget, setReorderTarget] = useState(null);
  const [cancellingId, setCancellingId] = useState(null);

  // Guards against an older response landing after a newer one (e.g.
  // the dropdown switched twice quickly) and overwriting the list.
  const requestIdRef = useRef(0);
  // Always the CURRENT dropdown value, even when reload() is called from
  // a handler that was created before the user changed the dropdown.
  const sourceRef = useRef(source);
  sourceRef.current = source;

  function reload({ showSpinner = true } = {}) {
    const requestId = ++requestIdRef.current;
    if (showSpinner) setLoading(true);
    getOrders(sourceRef.current)
      .then((data) => {
        if (requestId !== requestIdRef.current) return;
        setOrders(data);
        setError(null);
      })
      .catch((err) => {
        if (requestId !== requestIdRef.current) return;
        setError(err.message);
      })
      .finally(() => {
        if (requestId === requestIdRef.current) setLoading(false);
      });
  }

  // Reload whenever the dropdown changes.
  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  // App.jsx bumps this when an auto order fires (placed or failed), so
  // the list updates live — quietly, without flashing "Loading...".
  useEffect(() => {
    if (refreshSignal === undefined || refreshSignal === 0) return;
    reload({ showSpinner: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal]);

  async function handleCancel(order) {
    const isWaitingAuto = order.source === "auto" && order.status === "Active";
    const question = isWaitingAuto
      ? `Cancel this auto order for ${order.trading_symbol}? It has not triggered yet, so nothing has been sent to the broker.`
      : `Cancel order #${order.broker_order_no || order.id} for ${order.trading_symbol}?`;
    if (!window.confirm(question)) return;
    setCancellingId(order.id);
    setError(null);
    try {
      await cancelOrder(order.id);
      showToast(
        isWaitingAuto
          ? `Auto order for ${order.trading_symbol} cancelled.`
          : `Order for ${order.trading_symbol} cancelled.`,
        "success"
      );
      reload({ showSpinner: false });
    } catch (err) {
      showToast(`Could not cancel order for ${order.trading_symbol}: ${err.message}`, "error");
      setError(err.message);
      reload({ showSpinner: false }); // the order's real status may have changed (e.g. it just triggered)
    } finally {
      setCancellingId(null);
    }
  }

  const emptyText = source === "all" ? "No orders placed yet." : `No ${source} orders placed yet.`;

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <nav style={styles.nav}>
          <span style={styles.navLink} onClick={onNavigateLive}>Live</span>
          <span style={styles.navActive}>Orders</span>
        </nav>
        <div style={styles.spacer} />
        <label style={styles.filterWrap}>
          <span style={styles.filterLabel}>Show</span>
          <select
            style={styles.filterSelect}
            value={source}
            onChange={(e) => setSource(e.target.value)}
            aria-label="Filter orders by how they were placed"
          >
            {SOURCE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </label>
      </header>

      <div style={styles.newOrderCard}>
        <div style={styles.cardTitle}>Place a new order</div>
        <StockSearchInput
          placeholder="Search for a stock to trade..."
          onSelect={setNewOrderSymbol}
        />
        <div style={styles.cardHint}>Choose "Auto trade" in the order window to place it automatically when a condition is met.</div>
      </div>

      {error && <div style={styles.error}>{error}</div>}

      {loading ? (
        <p style={styles.muted}>Loading...</p>
      ) : orders.length === 0 ? (
        <p style={styles.muted}>{emptyText}</p>
      ) : (
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Symbol</th>
              <th style={styles.th}>Side</th>
              <th style={styles.th}>Type</th>
              <th style={styles.thRight}>Qty</th>
              <th style={styles.thRight}>Price</th>
              <th style={styles.thRight}>Trigger</th>
              <th style={styles.th}>Status</th>
              <th style={styles.th}>Placed (IST)</th>
              <th style={styles.th}></th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => {
              const isAuto = o.source === "auto";
              return (
                <tr key={o.id}>
                  <td style={styles.tdLeft}>
                    <span style={styles.symbolLine}>
                      {o.trading_symbol}
                      {isAuto && <span style={styles.autoTag}>Auto</span>}
                    </span>
                    {isAuto && (
                      <div style={styles.subLine} title={describeAutoConditions(o)}>{describeAutoConditions(o)}</div>
                    )}
                  </td>
                  <td style={styles.tdLeft}>
                    <span style={{ color: o.transaction_type === "B" ? "var(--positive)" : "var(--negative)" }}>
                      {o.transaction_type === "B" ? "Buy" : "Sell"}
                    </span>
                  </td>
                  <td style={styles.tdLeft}>{o.order_type}</td>
                  <td style={styles.tdRight} className="mono">{o.quantity}</td>
                  <td style={styles.tdRight} className="mono">{o.price || "—"}</td>
                  <td style={styles.tdRight} className="mono">{o.trigger_price || "—"}</td>
                  <td style={styles.tdLeft}>
                    <span style={{ color: STATUS_COLORS[o.status] || "var(--text)" }}>{o.status}</span>
                    {isAuto && o.status === "Active" && (
                      <div style={styles.subLine}>{activeHint(o)}</div>
                    )}
                    {isAuto && o.triggered_at && (
                      <div style={styles.subLine} title={o.trigger_details || ""}>
                        Triggered {formatIST(o.triggered_at)}
                      </div>
                    )}
                    {o.broker_message && (
                      <div style={styles.brokerMsg} title={o.broker_message}>{o.broker_message}</div>
                    )}
                  </td>
                  <td style={styles.tdLeft} className="mono">{formatIST(o.placed_at)}</td>
                  <td style={styles.tdRight}>
                    <div style={styles.actions}>
                      {!TERMINAL_STATUSES.has(o.status) && o.status === "Pending" && (
                        <button style={styles.smallBtn} onClick={() => setModifyingOrder(o)}>Modify</button>
                      )}
                      {!TERMINAL_STATUSES.has(o.status) && o.status !== "Triggering" && (
                        <button
                          style={styles.smallBtnDanger}
                          onClick={() => handleCancel(o)}
                          disabled={cancellingId === o.id}
                        >
                          {cancellingId === o.id ? "..." : "Cancel"}
                        </button>
                      )}
                      {REORDERABLE_STATUSES.has(o.status) && (
                        <button style={styles.smallBtn} onClick={() => setReorderTarget(o)}>Reorder</button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {newOrderSymbol && (
        <PlaceOrderModal
          symbol={newOrderSymbol}
          onClose={() => setNewOrderSymbol(null)}
          onPlaced={() => reload({ showSpinner: false })}
        />
      )}

      {reorderTarget && (
        <PlaceOrderModal
          symbol={reorderTarget.trading_symbol}
          prefillOrder={reorderTarget}
          onClose={() => setReorderTarget(null)}
          onPlaced={() => reload({ showSpinner: false })}
        />
      )}

      {modifyingOrder && (
        <ModifyOrderModal
          order={modifyingOrder}
          onClose={() => setModifyingOrder(null)}
          onModified={() => reload({ showSpinner: false })}
        />
      )}
    </div>
  );
}

const styles = {
  page: { padding: "20px 24px", maxWidth: 1100, margin: "0 auto" },
  header: {
    display: "flex", alignItems: "center", gap: 16, marginBottom: 20,
    paddingBottom: 16, borderBottom: "1px solid var(--border)",
  },
  nav: { display: "flex", gap: 16, fontSize: 13 },
  navActive: { color: "var(--text)", fontWeight: 500, borderBottom: "2px solid var(--focus)", paddingBottom: 2 },
  navLink: { color: "var(--text-muted)", cursor: "pointer", paddingBottom: 2 },
  spacer: { flex: 1 },
  filterWrap: { display: "flex", alignItems: "center", gap: 8 },
  filterLabel: { fontSize: 12, color: "var(--text-muted)" },
  filterSelect: { padding: "7px 10px" },
  newOrderCard: {
    background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8,
    padding: 16, marginBottom: 20, display: "flex", flexDirection: "column", gap: 10,
  },
  cardTitle: { fontSize: 13, fontWeight: 600 },
  cardHint: { fontSize: 11, color: "var(--text-muted)" },
  error: {
    fontSize: 12, color: "var(--negative)", background: "rgba(255, 92, 92, 0.1)",
    border: "1px solid rgba(255, 92, 92, 0.3)", borderRadius: 6, padding: "8px 12px", marginBottom: 16,
  },
  muted: { color: "var(--text-muted)", fontSize: 13 },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th: { textAlign: "left", padding: "8px 10px", borderBottom: "1px solid var(--border)", fontWeight: 500, color: "var(--text-muted)" },
  thRight: { textAlign: "right", padding: "8px 10px", borderBottom: "1px solid var(--border)", fontWeight: 500, color: "var(--text-muted)" },
  tdLeft: { textAlign: "left", padding: "9px 10px", borderBottom: "1px solid var(--border)", verticalAlign: "top" },
  tdRight: { textAlign: "right", padding: "9px 10px", borderBottom: "1px solid var(--border)", verticalAlign: "top" },
  symbolLine: { display: "inline-flex", alignItems: "center", gap: 6 },
  autoTag: {
    fontSize: 10, color: "var(--accent-loose)", border: "1px solid var(--accent-loose)",
    borderRadius: 4, padding: "1px 5px",
  },
  subLine: { fontSize: 11, color: "var(--text-muted)", marginTop: 2, maxWidth: 240 },
  brokerMsg: { fontSize: 10, color: "var(--text-muted)", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  actions: { display: "flex", gap: 6, justifyContent: "flex-end", flexWrap: "wrap" },
  smallBtn: { fontSize: 11, padding: "5px 9px" },
  smallBtnDanger: { fontSize: 11, padding: "5px 9px", color: "var(--negative)", borderColor: "rgba(255,92,92,0.4)" },
};
