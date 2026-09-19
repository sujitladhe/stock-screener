import { useState, useEffect } from "react";
import { getOrders, cancelOrder } from "../api";
import PlaceOrderModal from "../components/PlaceOrderModal";
import ModifyOrderModal from "../components/ModifyOrderModal";
import StockSearchInput from "../components/StockSearchInput";

const TERMINAL_STATUSES = new Set(["Executed", "Cancelled", "Rejected"]);

const STATUS_COLORS = {
  Pending: "var(--accent-loose)",
  Executed: "var(--positive)",
  Cancelled: "var(--text-muted)",
  Rejected: "var(--negative)",
};

export default function Orders({ onNavigateLive }) {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [newOrderSymbol, setNewOrderSymbol] = useState(null);
  const [modifyingOrder, setModifyingOrder] = useState(null);
  const [cancellingId, setCancellingId] = useState(null);

  function reload() {
    setLoading(true);
    getOrders()
      .then(setOrders)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(reload, []);

  async function handleCancel(order) {
    if (!window.confirm(`Cancel order #${order.broker_order_no || order.id} for ${order.trading_symbol}?`)) return;
    setCancellingId(order.id);
    setError(null);
    try {
      await cancelOrder(order.id);
      reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setCancellingId(null);
    }
  }

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <nav style={styles.nav}>
          <span style={styles.navLink} onClick={onNavigateLive}>Live</span>
          <span style={styles.navActive}>Orders</span>
        </nav>
      </header>

      <div style={styles.newOrderCard}>
        <div style={styles.cardTitle}>Place a new order</div>
        <StockSearchInput
          placeholder="Search for a stock to trade..."
          onSelect={setNewOrderSymbol}
        />
      </div>

      {error && <div style={styles.error}>{error}</div>}

      {loading ? (
        <p style={styles.muted}>Loading...</p>
      ) : orders.length === 0 ? (
        <p style={styles.muted}>No orders placed yet.</p>
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
              <th style={styles.th}>Placed</th>
              <th style={styles.th}></th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td style={styles.tdLeft}>{o.trading_symbol}</td>
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
                  {o.broker_message && (
                    <div style={styles.brokerMsg} title={o.broker_message}>{o.broker_message}</div>
                  )}
                </td>
                <td style={styles.tdLeft} className="mono">
                  {new Date(o.placed_at).toLocaleString("en-IN", { hour12: false })}
                </td>
                <td style={styles.tdRight}>
                  {!TERMINAL_STATUSES.has(o.status) && (
                    <div style={styles.actions}>
                      {o.status === "Pending" && (
                        <button style={styles.smallBtn} onClick={() => setModifyingOrder(o)}>Modify</button>
                      )}
                      <button
                        style={styles.smallBtnDanger}
                        onClick={() => handleCancel(o)}
                        disabled={cancellingId === o.id}
                      >
                        {cancellingId === o.id ? "..." : "Cancel"}
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {newOrderSymbol && (
        <PlaceOrderModal
          symbol={newOrderSymbol}
          onClose={() => setNewOrderSymbol(null)}
          onPlaced={reload}
        />
      )}

      {modifyingOrder && (
        <ModifyOrderModal
          order={modifyingOrder}
          onClose={() => setModifyingOrder(null)}
          onModified={reload}
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
  newOrderCard: {
    background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8,
    padding: 16, marginBottom: 20, display: "flex", flexDirection: "column", gap: 10,
  },
  cardTitle: { fontSize: 13, fontWeight: 600 },
  error: {
    fontSize: 12, color: "var(--negative)", background: "rgba(255, 92, 92, 0.1)",
    border: "1px solid rgba(255, 92, 92, 0.3)", borderRadius: 6, padding: "8px 12px", marginBottom: 16,
  },
  muted: { color: "var(--text-muted)", fontSize: 13 },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th: { textAlign: "left", padding: "8px 10px", borderBottom: "1px solid var(--border)", fontWeight: 500, color: "var(--text-muted)" },
  thRight: { textAlign: "right", padding: "8px 10px", borderBottom: "1px solid var(--border)", fontWeight: 500, color: "var(--text-muted)" },
  tdLeft: { textAlign: "left", padding: "9px 10px", borderBottom: "1px solid var(--border)" },
  tdRight: { textAlign: "right", padding: "9px 10px", borderBottom: "1px solid var(--border)" },
  brokerMsg: { fontSize: 10, color: "var(--text-muted)", maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  actions: { display: "flex", gap: 6, justifyContent: "flex-end" },
  smallBtn: { fontSize: 11, padding: "5px 9px" },
  smallBtnDanger: { fontSize: 11, padding: "5px 9px", color: "var(--negative)", borderColor: "rgba(255,92,92,0.4)" },
};
