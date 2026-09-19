import { useState } from "react";
import { placeStoplossOrder } from "../api";
import { showToast } from "../toast";

// Same fix as PlaceOrderModal.jsx: product options are scoped to
// order kind, and changing kind auto-syncs product, rather than
// letting them drift out of sync (which caused a real Ventura
// rejection: "EXCH: Not Specified").
const PRODUCTS_BY_KIND = {
  delivery: [{ value: "C", label: "C — CNC (delivery)" }],
  intraday: [
    { value: "I", label: "I — Intraday" },
    { value: "M", label: "M — Margin" },
  ],
};

/**
 * Sets a stoploss (exit) order for a currently-held position.
 *
 * defaultTransactionType comes pre-selected from Positions.jsx, which
 * derives it from Ventura's confirmed, SIGNED `total_quantity` field
 * (negative = short position, needs a Buy to exit; positive = long,
 * needs a Sell). The dropdown stays editable rather than locked, so
 * this is a reliable default, not a forced choice — worth a glance
 * before submitting since real money is behind it either way.
 */
export default function StoplossModal({ position, defaultTransactionType, onClose, onPlaced }) {
  const [transactionType, setTransactionType] = useState(defaultTransactionType || "S");
  // total_quantity from the broker is SIGNED (negative for a short
  // position) -- an order's quantity must always be positive, so the
  // default here is the absolute value, not the raw signed number.
  const [quantity, setQuantity] = useState(
    position.quantity != null ? String(Math.abs(position.quantity)) : ""
  );
  const [orderType, setOrderType] = useState("SLM");
  const [triggerPrice, setTriggerPrice] = useState("");
  const [price, setPrice] = useState("");
  const [orderKind, setOrderKind] = useState("intraday");
  const [product, setProduct] = useState("I");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const productOptions = PRODUCTS_BY_KIND[orderKind];

  function handleOrderKindChange(kind) {
    setOrderKind(kind);
    setProduct(kind === "delivery" ? "C" : "I");
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);

    const qty = parseInt(quantity, 10);
    if (!qty || qty <= 0) {
      setError("Enter a valid quantity.");
      return;
    }
    if (!triggerPrice || parseFloat(triggerPrice) <= 0) {
      setError("Enter a trigger price.");
      return;
    }
    if (orderType === "SL" && (!price || parseFloat(price) <= 0)) {
      setError("Enter a price for an SL order (SLM doesn't need one).");
      return;
    }

    setSubmitting(true);
    try {
      await placeStoplossOrder({
        trading_symbol: position.symbol,
        transaction_type: transactionType,
        quantity: qty,
        order_type: orderType,
        trigger_price: parseFloat(triggerPrice),
        price: orderType === "SL" ? parseFloat(price) : 0,
        order_kind: orderKind,
        product,
      });
      showToast(`Stoploss order for ${position.symbol} placed successfully.`, "success");
      if (onPlaced) onPlaced();
      onClose();
    } catch (err) {
      showToast(`Stoploss order for ${position.symbol} failed: ${err.message}`, "error");
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={styles.overlay} onClick={onClose}>
      <form style={styles.modal} onClick={(e) => e.stopPropagation()} onSubmit={handleSubmit}>
        <h2 style={styles.title}>Set stoploss — {position.symbol}</h2>
        <p style={styles.subtitle}>Currently held: {position.quantity ?? "?"} @ {position.averagePrice ?? "?"}</p>

        <label style={styles.field}>
          <span style={styles.label}>Exit direction (pre-filled from your position, editable)</span>
          <select value={transactionType} onChange={(e) => setTransactionType(e.target.value)}>
            <option value="S">Sell (exits a long/buy position)</option>
            <option value="B">Buy (exits a short/sell position)</option>
          </select>
        </label>

        <div style={styles.row}>
          <label style={styles.field}>
            <span style={styles.label}>Order type</span>
            <select value={orderType} onChange={(e) => setOrderType(e.target.value)}>
              <option value="SLM">SLM — market on trigger</option>
              <option value="SL">SL — limit on trigger</option>
            </select>
          </label>
          <label style={styles.field}>
            <span style={styles.label}>Quantity</span>
            <input type="number" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          </label>
        </div>

        <div style={styles.row}>
          <label style={styles.field}>
            <span style={styles.label}>Trigger price</span>
            <input type="number" step="any" value={triggerPrice} onChange={(e) => setTriggerPrice(e.target.value)} />
          </label>
          {orderType === "SL" && (
            <label style={styles.field}>
              <span style={styles.label}>Limit price</span>
              <input type="number" step="any" value={price} onChange={(e) => setPrice(e.target.value)} />
            </label>
          )}
        </div>

        <div style={styles.row}>
          <label style={styles.field}>
            <span style={styles.label}>Order kind</span>
            <ToggleGroup value={orderKind} onChange={handleOrderKindChange} options={[
              { value: "intraday", label: "Intraday" },
              { value: "delivery", label: "Delivery" },
            ]} />
          </label>
          <label style={styles.field}>
            <span style={styles.label}>Product</span>
            <select value={product} onChange={(e) => setProduct(e.target.value)}>
              {productOptions.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </label>
        </div>

        {error && <div style={styles.error}>{error}</div>}

        <button type="submit" disabled={submitting} style={styles.submitBtn}>
          {submitting ? "Placing..." : "Place stoploss order"}
        </button>
        <button type="button" style={styles.closeBtn} onClick={onClose}>Cancel</button>
      </form>
    </div>
  );
}

function ToggleGroup({ value, onChange, options }) {
  return (
    <div style={styles.toggleGroup}>
      {options.map((opt) => (
        <button
          type="button"
          key={opt.value}
          onClick={() => onChange(opt.value)}
          style={{
            ...styles.toggleBtn,
            background: value === opt.value ? "var(--focus)" : "var(--surface)",
            color: value === opt.value ? "#fff" : "var(--text)",
            borderColor: value === opt.value ? "var(--focus)" : "var(--border)",
          }}
        >
          {opt.label}
        </button>
      ))}
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
    padding: 20, width: 380, display: "flex", flexDirection: "column", gap: 10,
    maxHeight: "90vh", overflowY: "auto",
  },
  title: { fontSize: 15, fontWeight: 600, margin: 0 },
  subtitle: { fontSize: 12, color: "var(--text-muted)", margin: "0 0 4px 0" },
  row: { display: "flex", gap: 10 },
  field: { display: "flex", flexDirection: "column", gap: 4, flex: 1 },
  label: { fontSize: 11, color: "var(--text-muted)" },
  toggleGroup: { display: "flex", gap: 4 },
  toggleBtn: { flex: 1, padding: "7px 0", fontSize: 11, border: "1px solid" },
  error: {
    fontSize: 12, color: "var(--negative)", background: "rgba(255, 92, 92, 0.1)",
    border: "1px solid rgba(255, 92, 92, 0.3)", borderRadius: 6, padding: "6px 10px",
  },
  submitBtn: { background: "var(--accent-strict)", borderColor: "var(--accent-strict)", color: "#fff", marginTop: 4 },
  closeBtn: { background: "none", border: "none", color: "var(--text-muted)", fontSize: 12, marginTop: 2 },
};
