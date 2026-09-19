import { useState } from "react";
import { modifyOrder } from "../api";
import { showToast } from "../toast";

const ORDER_TYPES = ["MKT", "LMT", "SL", "SLM"];

/**
 * Modifies a still-Pending order. Only Pending orders can reach this
 * modal — Orders.jsx only shows the "Modify" action for that status
 * (see orders.py's modify endpoint, which enforces the same rule
 * server-side too, not just in the UI).
 */
export default function ModifyOrderModal({ order, onClose, onModified }) {
  const [orderType, setOrderType] = useState(order.order_type);
  const [quantity, setQuantity] = useState(String(order.quantity));
  const [price, setPrice] = useState(order.price != null ? String(order.price) : "");
  const [triggerPrice, setTriggerPrice] = useState(order.trigger_price != null ? String(order.trigger_price) : "");
  const [validity, setValidity] = useState(order.validity);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const needsPrice = orderType === "LMT" || orderType === "SL";
  const needsTrigger = orderType === "SL" || orderType === "SLM";

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);

    const qty = parseInt(quantity, 10);
    if (!qty || qty <= 0) {
      setError("Enter a valid quantity.");
      return;
    }

    setSubmitting(true);
    try {
      await modifyOrder(order.id, {
        quantity: qty,
        order_type: orderType,
        price: needsPrice ? parseFloat(price) || 0 : 0,
        trigger_price: needsTrigger ? parseFloat(triggerPrice) || 0 : 0,
        validity,
      });
      showToast(`Order for ${order.trading_symbol} updated.`, "success");
      if (onModified) onModified();
      onClose();
    } catch (err) {
      showToast(`Could not modify order for ${order.trading_symbol}: ${err.message}`, "error");
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={styles.overlay} onClick={onClose}>
      <form style={styles.modal} onClick={(e) => e.stopPropagation()} onSubmit={handleSubmit}>
        <h2 style={styles.title}>Modify order — {order.trading_symbol}</h2>
        <p style={styles.subtitle}>
          {order.transaction_type === "B" ? "Buy" : "Sell"} · order #{order.broker_order_no || order.id}
        </p>

        <label style={styles.field}>
          <span style={styles.label}>Order type</span>
          <select value={orderType} onChange={(e) => setOrderType(e.target.value)}>
            {ORDER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>

        <div style={styles.row}>
          {needsPrice && (
            <label style={styles.field}>
              <span style={styles.label}>Price</span>
              <input type="number" step="any" value={price} onChange={(e) => setPrice(e.target.value)} />
            </label>
          )}
          {needsTrigger && (
            <label style={styles.field}>
              <span style={styles.label}>Trigger price</span>
              <input type="number" step="any" value={triggerPrice} onChange={(e) => setTriggerPrice(e.target.value)} />
            </label>
          )}
        </div>

        <div style={styles.row}>
          <label style={styles.field}>
            <span style={styles.label}>Quantity</span>
            <input type="number" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          </label>
          <label style={styles.field}>
            <span style={styles.label}>Validity</span>
            <select value={validity} onChange={(e) => setValidity(e.target.value)}>
              <option value="DAY">DAY</option>
              <option value="IOC">IOC</option>
            </select>
          </label>
        </div>

        {error && <div style={styles.error}>{error}</div>}

        <button type="submit" disabled={submitting} style={styles.submitBtn}>
          {submitting ? "Saving..." : "Save changes"}
        </button>
        <button type="button" style={styles.closeBtn} onClick={onClose}>Cancel</button>
      </form>
    </div>
  );
}

const styles = {
  overlay: {
    position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
    display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
  },
  modal: {
    background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10,
    padding: 20, width: 340, display: "flex", flexDirection: "column", gap: 10,
  },
  title: { fontSize: 15, fontWeight: 600, margin: 0 },
  subtitle: { fontSize: 12, color: "var(--text-muted)", margin: "0 0 4px 0" },
  row: { display: "flex", gap: 10 },
  field: { display: "flex", flexDirection: "column", gap: 4, flex: 1 },
  label: { fontSize: 12, color: "var(--text-muted)" },
  error: {
    fontSize: 12, color: "var(--negative)", background: "rgba(255, 92, 92, 0.1)",
    border: "1px solid rgba(255, 92, 92, 0.3)", borderRadius: 6, padding: "6px 10px",
  },
  submitBtn: { background: "var(--focus)", borderColor: "var(--focus)", color: "#fff", marginTop: 4 },
  closeBtn: { background: "none", border: "none", color: "var(--text-muted)", fontSize: 12, marginTop: 2 },
};
