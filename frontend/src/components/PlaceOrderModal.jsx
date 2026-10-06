import { useMemo, useState } from "react";
import { useDrawerMount } from "../hooks/useDrawerMount";
import { placeOrder, createAutoOrder, updateAutoOrder } from "../api";
import { showToast } from "../toast";
import { CloseIcon } from "../icons";

const ORDER_TYPES = ["MKT", "LMT", "SL", "SLM"];
const ONE_CRORE = 10000000;
const MARKET_OPEN_HHMM = "09:15";
const MARKET_CLOSE_HHMM = "15:30";
const HOUR_OPTIONS = ["09", "10", "11", "12", "13", "14", "15"];

const PRODUCTS_BY_KIND = {
  delivery: [{ value: "C", label: "C — CNC (delivery)" }],
  intraday: [
    { value: "I", label: "I — Intraday" },
    { value: "M", label: "M — Margin" },
  ],
};

function minutesForHour(hour) {
  let first = 0, last = 59;
  if (hour === "09") first = 15;
  if (hour === "15") last = 30;
  return Array.from({ length: last - first + 1 }, (_, i) => String(first + i).padStart(2, "0"));
}

function ValidTillPicker({ value, onChange }) {
  const [hour, minute] = value ? value.split(":") : ["", ""];
  function handleHourChange(newHour) {
    if (!newHour) { onChange(""); return; }
    const allowed = minutesForHour(newHour);
    onChange(`${newHour}:${allowed.includes(minute) ? minute : allowed[0]}`);
  }
  return (
    <div className="timepick">
      <select className="select" value={hour} onChange={(e) => handleHourChange(e.target.value)} aria-label="Valid till hour">
        <option value="">--</option>
        {HOUR_OPTIONS.map((h) => <option key={h} value={h}>{h}</option>)}
      </select>
      <span className="muted">:</span>
      <select className="select" value={minute || ""} disabled={!hour} onChange={(e) => onChange(`${hour}:${e.target.value}`)} aria-label="Valid till minute">
        {!hour && <option value="">--</option>}
        {hour && minutesForHour(hour).map((m) => <option key={m} value={m}>{m}</option>)}
      </select>
      {value && <button type="button" className="link" style={{ marginLeft: 4 }} onClick={() => onChange("")}>Clear</button>}
    </div>
  );
}

function fmtInt(n) { return Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 }); }
function fmt2(n) { return Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }

export default function PlaceOrderModal({
  symbol,
  defaultReferencePrice,
  prefillOrder,
  editOrderId,
  settings,
  autoOrderSymbols = new Set(),
  onClose,
  onPlaced,
}) {
  const isEdit = !!editOrderId;
  const isReorder = !!prefillOrder && !isEdit;
  const prefillIsAuto = prefillOrder?.source === "auto";
  const rs = settings || {};

  const [mode, setMode] = useState(prefillIsAuto ? "auto" : "now");
  const [orderKind, setOrderKind] = useState(prefillOrder?.order_kind || "intraday");
  const [transactionType, setTransactionType] = useState(prefillOrder?.transaction_type || "B");
  const [orderType, setOrderType] = useState(prefillOrder?.order_type || "MKT");
  const [product, setProduct] = useState(prefillOrder?.product || (prefillOrder?.order_kind === "delivery" ? "C" : "I"));
  const [validity, setValidity] = useState(prefillOrder?.validity || "DAY");
  const [price, setPrice] = useState(
    prefillOrder?.price ? String(prefillOrder.price) : (defaultReferencePrice ? String(defaultReferencePrice) : ""),
  );
  const [triggerPrice, setTriggerPrice] = useState(prefillOrder?.trigger_price ? String(prefillOrder.trigger_price) : "");

  const autoQty = useMemo(() => {
    if (prefillOrder) return null;
    if (!rs.riskEnabled || !(rs.riskAmount > 0) || !(rs.riskPct > 0) || !(defaultReferencePrice > 0)) return null;
    const riskPerShare = defaultReferencePrice * (rs.riskPct / 100);
    if (riskPerShare <= 0) return null;
    return Math.floor(rs.riskAmount / riskPerShare);
  }, [prefillOrder, rs.riskEnabled, rs.riskAmount, rs.riskPct, defaultReferencePrice]);

  const [quantity, setQuantity] = useState(
    prefillOrder?.quantity ? String(prefillOrder.quantity) : (autoQty > 0 ? String(autoQty) : ""),
  );
  const [qtyAutoHintVisible, setQtyAutoHintVisible] = useState(autoQty > 0);

  const [useStoplossCalc, setUseStoplossCalc] = useState(!!prefillOrder?.stoploss_percentage);
  const [referencePrice, setReferencePrice] = useState(defaultReferencePrice ? String(defaultReferencePrice) : "");
  const [stoplossPercentage, setStoplossPercentage] = useState(
    prefillOrder?.stoploss_percentage ? String(prefillOrder.stoploss_percentage) : (rs.riskPct ? String(rs.riskPct) : ""),
  );
  const [stoplossValue, setStoplossValue] = useState(
    prefillOrder?.stoploss_value ? String(prefillOrder.stoploss_value) : (!prefillOrder && rs.riskAmount ? String(rs.riskAmount) : ""),
  );

  // --- auto trade conditions ---
  const prefillVolumeCr = prefillIsAuto && prefillOrder.auto_volume_threshold != null
    ? prefillOrder.auto_volume_threshold / ONE_CRORE : null;
  const prefillCandle = prefillIsAuto ? prefillOrder.auto_candle_pct_threshold : null;
  const [useVolume, setUseVolume]   = useState(prefillIsAuto ? prefillVolumeCr != null : true);
  const [volumeCr, setVolumeCr]     = useState(prefillVolumeCr != null ? String(prefillVolumeCr) : "");
  const [useCandle, setUseCandle]   = useState(prefillIsAuto ? prefillCandle != null : false);
  const [candlePct, setCandlePct]   = useState(prefillCandle != null ? String(prefillCandle) : "");
  const [combinator, setCombinator] = useState(prefillOrder?.auto_combinator || "AND");
  const [validTill, setValidTill]   = useState(prefillIsAuto && prefillOrder.auto_valid_till ? prefillOrder.auto_valid_till : "");

  // NEW (0004) — day-high cap and order lifetime
  const [dayHighPct, setDayHighPct]       = useState(
    prefillIsAuto && prefillOrder.auto_day_high_pct_limit != null
      ? String(prefillOrder.auto_day_high_pct_limit) : "",
  );
  const [autoExpiresDaily, setAutoExpiresDaily] = useState(
    prefillIsAuto ? (prefillOrder.auto_expires_daily ?? false) : false,
  );

  const [error, setError]         = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const mounted = useDrawerMount();

  const isAuto = mode === "auto";
  const needsPrice   = orderType === "LMT" || orderType === "SL";
  const needsTrigger = orderType === "SL"  || orderType === "SLM";
  const productOptions = PRODUCTS_BY_KIND[orderKind];
  const sideLabel = transactionType === "B" ? "Buy" : "Sell";

  // Check for a duplicate Active auto order on this symbol.
  // Applies to NEW orders AND reorders — both create a fresh Active order, so both must be
  // blocked if one already exists. Only genuine edits (!isEdit) are exempt because an edit
  // updates the SAME order rather than creating another one.
  const hasDuplicateAutoOrder = !isEdit && isAuto && autoOrderSymbols.has(symbol);

  function handleOrderKindChange(kind) {
    setOrderKind(kind);
    setProduct(kind === "delivery" ? "C" : "I");
  }

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
    if (calculatedQuantity) { setQuantity(String(calculatedQuantity)); setQtyAutoHintVisible(false); }
  }
  function handleQtyChange(v) { setQuantity(v); setQtyAutoHintVisible(false); }

  const volumeRupees = useMemo(() => {
    const cr = parseFloat(volumeCr);
    if (!cr || cr <= 0) return null;
    return Math.round(cr * ONE_CRORE);
  }, [volumeCr]);

  const windowPct = useMemo(() => {
    if (!validTill) return 100;
    const [h, m] = validTill.split(":").map(Number);
    const endMin = h * 60 + m + 1 - (9 * 60 + 15);
    return Math.max(0, Math.min(100, (endMin / (15.5 * 60 - 9.25 * 60)) * 100));
  }, [validTill]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);

    const qty = parseInt(quantity, 10);
    if (!qty || qty <= 0) { setError("Enter a valid quantity."); return; }
    if (needsPrice && (!price || parseFloat(price) <= 0)) { setError("Enter a price for this order type."); return; }
    if (needsTrigger && (!triggerPrice || parseFloat(triggerPrice) <= 0)) { setError("Enter a trigger price."); return; }

    const orderFields = {
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
    };

    let autoFields = null;
    if (isAuto) {
      if (!useVolume && !useCandle) { setError("Choose at least one condition."); return; }
      let volume_threshold = null, candle_pct_threshold = null;
      if (useVolume) {
        if (!volumeRupees) { setError("Enter the volume value in crores."); return; }
        volume_threshold = volumeRupees;
      }
      if (useCandle) {
        const pct = parseFloat(candlePct);
        if (!pct || pct <= 0) { setError("Enter the candle % above 0."); return; }
        candle_pct_threshold = pct;
      }
      if (validTill && (validTill < MARKET_OPEN_HHMM || validTill > MARKET_CLOSE_HHMM)) {
        setError(`"Valid till" must be between ${MARKET_OPEN_HHMM} and ${MARKET_CLOSE_HHMM} (IST).`);
        return;
      }
      const parsedDayHighPct = dayHighPct ? parseFloat(dayHighPct) : null;
      if (parsedDayHighPct !== null && (parsedDayHighPct <= 0 || parsedDayHighPct >= 100)) {
        setError("Day-high cap must be between 0 and 100.");
        return;
      }
      autoFields = {
        volume_threshold,
        candle_pct_threshold,
        combinator: useVolume && useCandle ? combinator : null,
        valid_till: validTill || null,
        day_high_pct_limit: parsedDayHighPct,          // NEW (0004)
        auto_expires_daily: autoExpiresDaily,           // NEW (0004)
      };
    }

    setSubmitting(true);
    try {
      if (isEdit) {
        await updateAutoOrder(editOrderId, { ...orderFields, ...autoFields });
        showToast(`Auto order for ${symbol} updated.`, "success");
      } else if (isAuto) {
        await createAutoOrder({ ...orderFields, ...autoFields });
        showToast(
          `Auto ${sideLabel} order for ${symbol} is active — it will be placed when the condition is met.`,
          "success",
        );
      } else {
        await placeOrder(orderFields);
        showToast(`${sideLabel} order for ${symbol} placed successfully.`, "success");
      }
      if (onPlaced) onPlaced();
      onClose();
    } catch (err) {
      showToast(`${isAuto || isEdit ? "Auto order" : "Order"} for ${symbol} failed: ${err.message}`, "error");
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  const title    = isEdit ? "Edit auto order" : isReorder ? "Reorder" : symbol;
  const subtitle = isEdit
    ? `Editing auto order #${editOrderId}`
    : isReorder ? `${symbol}, from order #${prefillOrder.id}` : null;
  const submitLabel = submitting
    ? (isEdit ? "Saving..." : isAuto ? "Saving..." : "Placing...")
    : isEdit
      ? "Save changes"
      : isAuto
        ? `Create auto ${sideLabel.toLowerCase()} order`
        : `${sideLabel} ${symbol}`;

  return (
    <div className={`scrim${mounted ? " open" : ""}`} onClick={onClose}>
      <form className={`drawer${mounted ? " open" : ""}`} onClick={(e) => e.stopPropagation()} onSubmit={handleSubmit}>
        <div className="dr-head">
          <div>
            <h2 className="dr-title">{title}</h2>
            <div className="muted small">{subtitle || symbol}</div>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close order window" style={{ marginLeft: "auto" }}>
            <CloseIcon size={18} />
          </button>
        </div>

        <div className="dr-body">
          <div className="seg side" role="group" aria-label="Buy or sell">
            <button type="button" className={`side-b${transactionType === "B" ? " active" : ""}`} aria-pressed={transactionType === "B"} onClick={() => setTransactionType("B")}>Buy</button>
            <button type="button" className={`side-s${transactionType === "S" ? " active" : ""}`} aria-pressed={transactionType === "S"} onClick={() => setTransactionType("S")}>Sell</button>
          </div>

          <div className="tabs" role="tablist">
            <button type="button" role="tab" className={mode === "now" ? "active" : ""} aria-selected={mode === "now"} onClick={() => setMode("now")}>Place now</button>
            <button type="button" role="tab" className={mode === "auto" ? "active" : ""} aria-selected={mode === "auto"} onClick={() => setMode("auto")}>Auto trade</button>
          </div>
          <p className="hint">
            {isEdit
              ? "Still waiting to trigger — every field here can still be changed."
              : isAuto
                ? "Saved now, placed for you when the conditions are met. Works even if you close the app."
                : "Sent to the broker straight away."}
          </p>

          {/* NEW (0004) — duplicate auto order warning */}
          {isAuto && hasDuplicateAutoOrder && (
            <div
              style={{
                padding: "11px 13px",
                borderRadius: 10,
                background: "var(--ms)",
                color: "var(--mi)",
                fontSize: 13,
              }}
            >
              <b>You already have an active auto order for {symbol}.</b>
              <br />
              Only one waiting order per stock is allowed. Cancel the existing one first, then create a new one.
            </div>
          )}

          {isAuto && (
            <section className="autobox" aria-label="Auto trade conditions">
              <h3>Place this order automatically when</h3>

              <label className="check">
                <input type="checkbox" checked={useVolume} onChange={(e) => setUseVolume(e.target.checked)} />
                <span>Volume value (volume × price) in the current minute is at least</span>
              </label>
              {useVolume && (
                <>
                  <div className="unit">
                    <input className="input num" inputMode="decimal" placeholder="e.g. 6" value={volumeCr} onChange={(e) => setVolumeCr(e.target.value)} />
                    <span>Cr</span>
                  </div>
                  <span className="hint ind">{volumeRupees ? `= ₹${fmtInt(volumeRupees)}` : "In crores: 6 = 6 Cr, 0.6 = 60 Lac"}</span>
                </>
              )}

              {useVolume && useCandle && (
                <select className="select" value={combinator} onChange={(e) => setCombinator(e.target.value)}>
                  <option value="AND">AND — both conditions must be true</option>
                  <option value="OR">OR — either condition is enough</option>
                </select>
              )}

              <label className="check">
                <input type="checkbox" checked={useCandle} onChange={(e) => setUseCandle(e.target.checked)} />
                <span>Current 1-minute candle is green and up at least</span>
              </label>
              {useCandle && (
                <>
                  <div className="unit">
                    <input className="input num" inputMode="decimal" placeholder="e.g. 1.7" value={candlePct} onChange={(e) => setCandlePct(e.target.value)} />
                    <span>%</span>
                  </div>
                  <span className="hint ind">Only green candles count — a red candle never triggers this.</span>
                </>
              )}

              {/* NEW (0004) — day-high cap */}
              <div className="field">
                <span>Skip if stock is already up this much today (optional)</span>
                <div className="unit">
                  <input
                    className="input num"
                    inputMode="decimal"
                    placeholder="e.g. 14"
                    value={dayHighPct}
                    onChange={(e) => setDayHighPct(e.target.value)}
                    style={{ maxWidth: 100 }}
                  />
                  <span>%</span>
                </div>
                <span className="hint">
                  {dayHighPct
                    ? `If the stock is already up ${dayHighPct}% or more, the order waits. Once it pulls back under ${dayHighPct}%, it resumes checking.`
                    : "Leave blank to trigger regardless of how much the stock has moved today."}
                </span>
              </div>

              {/* NEW (0004) — order lifetime */}
              <div className="field">
                <span>Order stays active</span>
                <div className="seg" role="group" aria-label="Order lifetime" style={{ marginTop: 2 }}>
                  <button
                    type="button"
                    className={!autoExpiresDaily ? "active" : ""}
                    aria-pressed={!autoExpiresDaily}
                    onClick={() => setAutoExpiresDaily(false)}
                  >
                    Until executed
                  </button>
                  <button
                    type="button"
                    className={autoExpiresDaily ? "active" : ""}
                    aria-pressed={autoExpiresDaily}
                    onClick={() => setAutoExpiresDaily(true)}
                  >
                    Today only
                  </button>
                </div>
                <span className="hint">
                  {autoExpiresDaily
                    ? "Today only: if it doesn't trigger before 15:30 IST, it expires. You'd need to create it again tomorrow."
                    : "Until executed: stays active across trading days until it fires or you cancel it manually."}
                </span>
              </div>

              <div className="field">
                <span>Valid till (IST, 24-hour, optional)</span>
                <ValidTillPicker value={validTill} onChange={setValidTill} />
              </div>
              <div>
                <div className="win-track" aria-hidden="true">
                  <i className="win-range" style={{ width: `${windowPct}%` }} />
                </div>
                <div className="win-labels" aria-hidden="true">
                  <span style={{ left: 0 }}>9:15</span>
                  {validTill && (
                    <span className="win-end" style={{ left: `${windowPct}%`, transform: windowPct > 88 ? "translateX(-100%)" : "translateX(-50%)" }}>
                      until {validTill}
                    </span>
                  )}
                  <span style={{ right: 0, left: "auto" }}>3:30</span>
                </div>
              </div>
              <p className="hint">
                {validTill
                  ? `Valid till ${validTill} covers the whole minute (can still trigger at ${validTill}:59).`
                  : "Watched until 15:30 if you don't set a cut-off."}
                {" "}Checked live from 09:15 on trading days.
              </p>
            </section>
          )}

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
            <label className="field">
              <span>Quantity</span>
              <input className="input num" type="number" value={quantity} onChange={(e) => handleQtyChange(e.target.value)} />
              {qtyAutoHintVisible && autoQty > 0 && (
                <span className="hint">Auto-set from your risk settings. Edit anytime.</span>
              )}
            </label>
            <label className="field">
              <span>Product</span>
              <select className="select" value={product} onChange={(e) => setProduct(e.target.value)}>
                {productOptions.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
              </select>
            </label>
          </div>

          <label className="check">
            <input type="checkbox" checked={useStoplossCalc} onChange={(e) => setUseStoplossCalc(e.target.checked)} />
            <span>Calculate quantity from a stoploss value</span>
          </label>

          {useStoplossCalc && (
            <details className="calc" open>
              <summary>Work out the quantity from my risk</summary>
              <div className="grid2">
                <label className="field"><span>Reference price</span><input className="input num" type="number" step="any" value={referencePrice} onChange={(e) => setReferencePrice(e.target.value)} /></label>
                <label className="field"><span>Stoploss %</span><input className="input num" type="number" step="any" value={stoplossPercentage} onChange={(e) => setStoplossPercentage(e.target.value)} /></label>
              </div>
              <label className="field" style={{ marginTop: 10 }}>
                <span>Most I want to lose (₹)</span>
                <input className="input num" type="number" step="any" value={stoplossValue} onChange={(e) => setStoplossValue(e.target.value)} />
              </label>
              <div className="calc-out">
                <span className="hint">{calculatedQuantity ? `Risking that amount at that stoploss gives ${calculatedQuantity} shares.` : "Fill in all three to see a quantity."}</span>
                {calculatedQuantity ? <button type="button" className="btn sm" onClick={applyCalculatedQuantity}>Use {calculatedQuantity}</button> : null}
              </div>
            </details>
          )}

          <div className="grid2">
            <div className="seg" role="group" aria-label="Intraday or delivery">
              <button type="button" className={orderKind === "intraday" ? "active" : ""} onClick={() => handleOrderKindChange("intraday")}>Intraday</button>
              <button type="button" className={orderKind === "delivery" ? "active" : ""} onClick={() => handleOrderKindChange("delivery")}>Delivery</button>
            </div>
            <label className="field">
              <span>Order stays valid for</span>
              <select className="select" value={validity} onChange={(e) => setValidity(e.target.value)}>
                <option value="DAY">The day</option>
                <option value="IOC">Fill now or cancel (IOC)</option>
              </select>
            </label>
          </div>

          {error && <div className="err" role="alert">{error}</div>}
        </div>

        <div className="dr-foot">
          <button
            type="submit"
            className={`btn wide ${isEdit ? "primary" : transactionType === "B" ? "buy" : "sell"}`}
            disabled={submitting || hasDuplicateAutoOrder}
          >
            {submitLabel}
          </button>
          <button type="button" className="link" style={{ alignSelf: "center" }} onClick={onClose}>Cancel</button>
        </div>
      </form>
    </div>
  );
}
