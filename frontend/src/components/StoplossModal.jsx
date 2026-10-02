import { useState } from "react";
import { placeStoplossOrder } from "../api";
import { showToast } from "../toast";
import { CloseIcon } from "../icons";
import { useDrawerMount } from "../hooks/useDrawerMount";

const PRODUCTS_BY_KIND = {
  delivery: [{ value: "C", label: "C — CNC (delivery)" }],
  intraday: [
    { value: "I", label: "I — Intraday" },
    { value: "M", label: "M — Margin" },
  ],
};

/**
 * Sets a stoploss (exit) order for a currently-held position.
 * defaultTransactionType is derived by Positions.jsx from the
 * broker's signed total_quantity (negative = short, needs a Buy to
 * exit). The dropdown stays editable rather than locked.
 */
export default function StoplossModal({ position, defaultTransactionType, onClose, onPlaced }) {
  const mounted = useDrawerMount();
  const [transactionType, setTransactionType] = useState(defaultTransactionType || "S");
  const [quantity, setQuantity] = useState(position.quantity != null ? String(Math.abs(position.quantity)) : "");
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
    <div className={`scrim${mounted ? " open" : ""}`} onClick={onClose}>
      <form className={`drawer${mounted ? " open" : ""}`} onClick={(e) => e.stopPropagation()} onSubmit={handleSubmit}>
        <div className="dr-head">
          <div>
            <h2 className="dr-title">Set stoploss</h2>
            <div className="muted small">{position.symbol}, holding {position.quantity ?? "?"} at {position.averagePrice ?? "?"}</div>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close" style={{ marginLeft: "auto" }}><CloseIcon size={18} /></button>
        </div>

        <div className="dr-body">
          <label className="field">
            <span>Exit direction (pre-filled from your position, editable)</span>
            <select className="select" value={transactionType} onChange={(e) => setTransactionType(e.target.value)}>
              <option value="S">Sell (exits a long/buy position)</option>
              <option value="B">Buy (exits a short/sell position)</option>
            </select>
          </label>

          <div className="grid2">
            <label className="field">
              <span>Order type</span>
              <select className="select" value={orderType} onChange={(e) => setOrderType(e.target.value)}>
                <option value="SLM">SLM — market on trigger</option>
                <option value="SL">SL — limit on trigger</option>
              </select>
            </label>
            <label className="field"><span>Quantity</span><input className="input num" type="number" value={quantity} onChange={(e) => setQuantity(e.target.value)} /></label>
          </div>

          <div className="grid2">
            <label className="field"><span>Trigger price</span><input className="input num" type="number" step="any" value={triggerPrice} onChange={(e) => setTriggerPrice(e.target.value)} /></label>
            {orderType === "SL" && (
              <label className="field"><span>Limit price</span><input className="input num" type="number" step="any" value={price} onChange={(e) => setPrice(e.target.value)} /></label>
            )}
          </div>

          <div className="grid2">
            <div className="seg" role="group" aria-label="Intraday or delivery">
              <button type="button" className={orderKind === "intraday" ? "active" : ""} onClick={() => handleOrderKindChange("intraday")}>Intraday</button>
              <button type="button" className={orderKind === "delivery" ? "active" : ""} onClick={() => handleOrderKindChange("delivery")}>Delivery</button>
            </div>
            <label className="field">
              <span>Product</span>
              <select className="select" value={product} onChange={(e) => setProduct(e.target.value)}>
                {productOptions.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
              </select>
            </label>
          </div>

          {error && <div className="err" role="alert">{error}</div>}
        </div>

        <div className="dr-foot">
          <button type="submit" className="btn wide primary" disabled={submitting}>{submitting ? "Placing..." : "Place stoploss order"}</button>
          <button type="button" className="link" style={{ alignSelf: "center" }} onClick={onClose}>Cancel</button>
        </div>
      </form>
    </div>
  );
}
