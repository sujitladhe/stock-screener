import { useState } from "react";
import { modifyOrder } from "../api";
import { showToast } from "../toast";
import { CloseIcon } from "../icons";
import { useDrawerMount } from "../hooks/useDrawerMount";

const ORDER_TYPES = ["MKT", "LMT", "SL", "SLM"];

/**
 * Modifies a still-Pending order -- one already sitting with the
 * broker. Orders.jsx only shows "Modify" for that status (an Active
 * auto order that hasn't triggered yet goes through PlaceOrderModal's
 * edit-in-place mode instead, since it isn't at the broker yet).
 */
export default function ModifyOrderModal({ order, onClose, onModified }) {
  const mounted = useDrawerMount();
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
    <div className={`scrim${mounted ? " open" : ""}`} onClick={onClose}>
      <form className={`drawer${mounted ? " open" : ""}`} onClick={(e) => e.stopPropagation()} onSubmit={handleSubmit}>
        <div className="dr-head">
          <div>
            <h2 className="dr-title">Modify order</h2>
            <div className="muted small">{order.trading_symbol} · {order.transaction_type === "B" ? "Buy" : "Sell"} · order #{order.broker_order_no || order.id}</div>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close" style={{ marginLeft: "auto" }}><CloseIcon size={18} /></button>
        </div>

        <div className="dr-body">
          <label className="field">
            <span>Order type</span>
            <select className="select" value={orderType} onChange={(e) => setOrderType(e.target.value)}>
              {ORDER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>

          <div className="grid2">
            {needsPrice && (
              <label className="field"><span>Price</span><input className="input num" type="number" step="any" value={price} onChange={(e) => setPrice(e.target.value)} /></label>
            )}
            {needsTrigger && (
              <label className="field"><span>Trigger price</span><input className="input num" type="number" step="any" value={triggerPrice} onChange={(e) => setTriggerPrice(e.target.value)} /></label>
            )}
          </div>

          <div className="grid2">
            <label className="field"><span>Quantity</span><input className="input num" type="number" value={quantity} onChange={(e) => setQuantity(e.target.value)} /></label>
            <label className="field">
              <span>Validity</span>
              <select className="select" value={validity} onChange={(e) => setValidity(e.target.value)}>
                <option value="DAY">DAY</option>
                <option value="IOC">IOC</option>
              </select>
            </label>
          </div>

          {error && <div className="err" role="alert">{error}</div>}
        </div>

        <div className="dr-foot">
          <button type="submit" className="btn wide primary" disabled={submitting}>{submitting ? "Saving..." : "Save changes"}</button>
          <button type="button" className="link" style={{ alignSelf: "center" }} onClick={onClose}>Cancel</button>
        </div>
      </form>
    </div>
  );
}
