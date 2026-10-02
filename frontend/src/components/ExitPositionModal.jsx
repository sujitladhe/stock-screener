import { useState } from "react";
import { placeOrder } from "../api";
import { showToast } from "../toast";
import { CloseIcon } from "../icons";
import { useDrawerMount } from "../hooks/useDrawerMount";

/**
 * "Exit" next to "Set stoploss" on an open position: places a normal
 * order in the OPPOSITE direction, right away, for some or all of the
 * held quantity. transactionType is derived the same way Positions.jsx
 * derives it for the stoploss drawer (signed total_quantity).
 */
export default function ExitPositionModal({ position, defaultTransactionType, onClose, onPlaced }) {
  const mounted = useDrawerMount();
  const side = defaultTransactionType || (position.quantity < 0 ? "B" : "S");
  const [quantity, setQuantity] = useState(position.quantity != null ? String(Math.abs(position.quantity)) : "");
  const [orderType, setOrderType] = useState("MKT");
  const [price, setPrice] = useState(position.ltp != null ? String(position.ltp) : "");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const heldQty = Math.abs(position.quantity || 0);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);

    const qty = parseInt(quantity, 10);
    if (!qty || qty <= 0) {
      setError("Enter a quantity above 0.");
      return;
    }
    if (qty > heldQty) {
      setError(`You only hold ${heldQty}.`);
      return;
    }
    if (orderType === "LMT" && (!price || parseFloat(price) <= 0)) {
      setError("Enter a limit price.");
      return;
    }

    setSubmitting(true);
    try {
      await placeOrder({
        trading_symbol: position.symbol,
        order_kind: "intraday",
        transaction_type: side,
        order_type: orderType,
        quantity: qty,
        product: "I",
        price: orderType === "LMT" ? parseFloat(price) : 0,
        trigger_price: 0,
        validity: "DAY",
      });
      showToast(`Order to exit ${position.symbol} placed.`, "success");
      if (onPlaced) onPlaced();
      onClose();
    } catch (err) {
      showToast(`Could not exit ${position.symbol}: ${err.message}`, "error");
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
            <h2 className="dr-title">Exit position</h2>
            <div className="muted small">{position.symbol}, holding {position.quantity ?? "?"} at {position.averagePrice ?? "?"}</div>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close" style={{ marginLeft: "auto" }}><CloseIcon size={18} /></button>
        </div>

        <div className="dr-body">
          <p className="hint">This places an order to close some or all of this position right away.</p>
          <div className="grid2">
            <label className="field">
              <span>Order type</span>
              <select className="select" value={orderType} onChange={(e) => setOrderType(e.target.value)}>
                <option value="MKT">Market</option>
                <option value="LMT">Limit</option>
              </select>
            </label>
            <label className="field"><span>Quantity</span><input className="input num" type="number" value={quantity} onChange={(e) => setQuantity(e.target.value)} /></label>
            {orderType === "LMT" && (
              <label className="field"><span>Limit price</span><input className="input num" type="number" step="any" value={price} onChange={(e) => setPrice(e.target.value)} /></label>
            )}
          </div>
          {error && <div className="err" role="alert">{error}</div>}
        </div>

        <div className="dr-foot">
          <button type="submit" className={`btn wide ${side === "S" ? "sell" : "buy"}`} disabled={submitting}>
            {submitting ? "Placing..." : `${side === "S" ? "Sell" : "Buy"} to exit`}
          </button>
          <button type="button" className="link" style={{ alignSelf: "center" }} onClick={onClose}>Cancel</button>
        </div>
      </form>
    </div>
  );
}
