import { useState, useMemo } from "react";
import { placeOrder } from "../api";

const ORDER_TYPES = ["MKT", "LMT", "SL", "SLM"];
const PRODUCTS = [
  { value: "C", label: "C — CNC (delivery)" },
  { value: "I", label: "I — Intraday" },
  { value: "M", label: "M — Margin" },
  { value: "F", label: "F — Futures" },
];

/**
 * General order-entry modal — opened from a screener/watchlist row
 * (prefilled symbol + last-known LTP as the stoploss-calc reference
 * price) or from the Orders page's "New order" button (blank).
 *
 * Stoploss-based quantity (requirement 6d): entering a stoploss value
 * and percentage computes quantity as
 *   riskPerShare = referencePrice * (stoplossPercentage / 100)
 *   quantity = stoplossValue / riskPerShare
 * matching the worked example in the requirement doc (price 100,
 * stoploss% 2 -> risk/share 2, stoploss value 10,000 -> qty 5,000).
 * The computed value fills the quantity field but stays a normal,
 * editable input afterward — it's a starting point, not a lock.
 */
export default function PlaceOrderModal({ symbol, defaultReferencePrice, onClose, onPlaced }) {
  const [orderKind, setOrderKind] = useState("intraday");
  const [transactionType, setTransactionType] = useState("B");
  const [orderType, setOrderType] = useState("MKT");
  const [product, setProduct] = useState("I");
  const [validity, setValidity] = useState("DAY");
  const [price, setPrice] = useState(defaultReferencePrice ? String(defaultReferencePrice) : "");
  const [triggerPrice, setTriggerPrice] = useState("");
  const [quantity, setQuantity] = useState("");

  const [useStoplossCalc, setUseStoplossCalc] = useState(false);
  const [referencePrice, setReferencePrice] = useState(defaultReferencePrice ? String(defaultReferencePrice) : "");
  const [stoplossPercentage, setStoplossPercentage] = useState("");
  const [stoplossValue, setStoplossValue] = useState("");

  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const needsPrice = orderType === "LMT" || orderType === "SL";
  const needsTrigger = orderType === "SL" || orderType === "SLM";

  const calculatedQuantity = useMemo(() => {
    const refPrice = parseFloat(referencePrice);
    const pct = parseFloat(stoplossPercentage);
    const slValue = parseFloat(stoplossValue);
    if (!refPrice || !pct || !slValue) return null;
    const riskPerShare = refPrice * (pct / 100);
    if (riskPerShare <= 0) return null;
    return Math.floor(slValue / riskPerShare);
  }, [referencePrice, stoplossPercentage, stoplossValue]);

  function applyCalculatedQuantity() {
    if (calculatedQuantity) setQuantity(String(calculatedQuantity));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);

    const qty = parseInt(quantity, 10);
    if (!qty || qty <= 0) {
      setError("Enter a valid quantity (or calculate one from stoploss value).");
      return;
    }
    if (needsPrice && (!price || parseFloat(price) <= 0)) {
      setError("Enter a price for this order type.");
      return;
    }
    if (needsTrigger && (!triggerPrice || parseFloat(triggerPrice) <= 0)) {
      setError("Enter a trigger price for this order type.");
      return;
    }

    setSubmitting(true);
    try {
      await placeOrder({
        trading_symbol: symbol,
        order_kind: orderKind,
        transaction_type: transactionType,
        order_type: orderType,
        quantity: qty,
        product,
        price: needsPrice ? parseFloat(price) : 0,
        trigger_price: needsTrigger ? parseFloat(triggerPrice) : 0,
        validity,
        stoploss_percentage: useStoplossCalc && stoplossPercentage ? parseFloat(stoplossPercentage) : null,
        stoploss_value: useStoplossCalc && stoplossValue ? parseFloat(stoplossValue) : null,
      });
      if (onPlaced) onPlaced();
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={styles.overlay} onClick={onClose}>
      <form style={styles.modal} onClick={(e) => e.stopPropagation()} onSubmit={handleSubmit}>
        <h2 style={styles.title}>Place order — {symbol}</h2>

        <div style={styles.row}>
          <ToggleGroup value={transactionType} onChange={setTransactionType} options={[
            { value: "B", label: "Buy" },
            { value: "S", label: "Sell" },
          ]} />
          <ToggleGroup value={orderKind} onChange={setOrderKind} options={[
            { value: "intraday", label: "Intraday" },
            { value: "delivery", label: "Delivery" },
          ]} />
        </div>

        <label style={styles.field}>
          <span style={styles.label}>Order type</span>
          <select value={orderType} onChange={(e) => setOrderType(e.target.value)}>
            {ORDER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>

        <div style={styles.row}>
          {needsPrice && (
            <Field label="Price" type="number" step="any" value={price} onChange={setPrice} />
          )}
          {needsTrigger && (
            <Field label="Trigger price" type="number" step="any" value={triggerPrice} onChange={setTriggerPrice} />
          )}
        </div>

        <div style={styles.row}>
          <Field label="Quantity" type="number" value={quantity} onChange={setQuantity} />
          <label style={styles.field}>
            <span style={styles.label}>Product</span>
            <select value={product} onChange={(e) => setProduct(e.target.value)}>
              {PRODUCTS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </label>
        </div>

        <label style={styles.checkboxRow}>
          <input type="checkbox" checked={useStoplossCalc} onChange={(e) => setUseStoplossCalc(e.target.checked)} />
          Calculate quantity from a stoploss value
        </label>

        {useStoplossCalc && (
          <div style={styles.stoplossBox}>
            <div style={styles.row}>
              <Field label="Reference price" type="number" step="any" value={referencePrice} onChange={setReferencePrice} />
              <Field label="Stoploss %" type="number" step="any" value={stoplossPercentage} onChange={setStoplossPercentage} />
            </div>
            <Field label="Stoploss value (Rs)" type="number" step="any" value={stoplossValue} onChange={setStoplossValue} />
            {calculatedQuantity !== null ? (
              <div style={styles.calcRow}>
                <span style={styles.hint}>Computed quantity: <strong>{calculatedQuantity}</strong></span>
                <button type="button" style={styles.smallBtn} onClick={applyCalculatedQuantity}>Use this</button>
              </div>
            ) : (
              <span style={styles.hint}>Enter reference price, stoploss % and stoploss value to compute quantity.</span>
            )}
          </div>
        )}

        <label style={styles.field}>
          <span style={styles.label}>Validity</span>
          <select value={validity} onChange={(e) => setValidity(e.target.value)}>
            <option value="DAY">DAY</option>
            <option value="IOC">IOC</option>
          </select>
        </label>

        {error && <div style={styles.error}>{error}</div>}

        <button type="submit" disabled={submitting} style={{ ...styles.submitBtn, background: transactionType === "B" ? "var(--positive)" : "var(--negative)", borderColor: "transparent" }}>
          {submitting ? "Placing..." : `${transactionType === "B" ? "Buy" : "Sell"} ${symbol}`}
        </button>
        <button type="button" style={styles.closeBtn} onClick={onClose}>Cancel</button>
      </form>
    </div>
  );
}

function Field({ label, value, onChange, type = "text", step }) {
  return (
    <label style={styles.field}>
      <span style={styles.label}>{label}</span>
      <input
        type={type}
        step={step}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={styles.input}
      />
    </label>
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
    padding: 20, width: 360, display: "flex", flexDirection: "column", gap: 10,
    maxHeight: "90vh", overflowY: "auto",
  },
  title: { fontSize: 15, fontWeight: 600, margin: "0 0 4px 0" },
  row: { display: "flex", gap: 10 },
  field: { display: "flex", flexDirection: "column", gap: 4, flex: 1 },
  label: { fontSize: 12, color: "var(--text-muted)" },
  input: { width: "100%" },
  toggleGroup: { display: "flex", gap: 6, flex: 1 },
  toggleBtn: { flex: 1, padding: "8px 0", fontSize: 12, border: "1px solid" },
  checkboxRow: { display: "flex", alignItems: "center", gap: 8, fontSize: 12, marginTop: 2 },
  stoplossBox: {
    display: "flex", flexDirection: "column", gap: 8,
    background: "rgba(91,140,255,0.06)", border: "1px solid var(--border)",
    borderRadius: 8, padding: 10,
  },
  calcRow: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 },
  hint: { fontSize: 11, color: "var(--text-muted)" },
  smallBtn: { fontSize: 11, padding: "5px 9px" },
  error: {
    fontSize: 12, color: "var(--negative)", background: "rgba(255, 92, 92, 0.1)",
    border: "1px solid rgba(255, 92, 92, 0.3)", borderRadius: 6, padding: "6px 10px",
  },
  submitBtn: { color: "#fff", marginTop: 4 },
  closeBtn: { background: "none", border: "none", color: "var(--text-muted)", fontSize: 12, marginTop: 2 },
};
