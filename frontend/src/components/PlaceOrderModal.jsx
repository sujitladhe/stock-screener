import { useState, useMemo } from "react";
import { placeOrder, createAutoOrder } from "../api";
import { showToast } from "../toast";

const ORDER_TYPES = ["MKT", "LMT", "SL", "SLM"];

// 1 Crore = 1,00,00,000 = 10,000,000. Per architecture principle #9,
// money is stored in RAW rupees in the backend/DB and the "crores"
// convenience exists ONLY here at the input layer: the user types 6 for
// 6 Cr (0.6 = 60 Lac, 0.06 = 6 Lac) and we convert to rupees on submit.
const ONE_CRORE = 10000000;

// Auto orders are only ever checked inside these IST market hours (the
// backend enforces the same range for "valid till").
const MARKET_OPEN_HHMM = "09:15";
const MARKET_CLOSE_HHMM = "15:30";

// Product options are scoped to order kind, not a flat shared list --
// a real order was rejected by Ventura ("EXCH: Not Specified") when
// Delivery was selected but the product dropdown still held its
// Intraday default. Restricting the choices per kind (rather than
// just defaulting them) makes that mismatch structurally impossible.
const PRODUCTS_BY_KIND = {
  delivery: [{ value: "C", label: "C — CNC (delivery)" }],
  intraday: [
    { value: "I", label: "I — Intraday" },
    { value: "M", label: "M — Margin" },
  ],
};

/**
 * General order-entry modal — opened from a screener/watchlist row
 * (prefilled symbol + last-known LTP as the stoploss-calc reference
 * price), from the Orders page's "New order" search, or from
 * "Reorder" on a cancelled/rejected order (prefillOrder carries that
 * order's full field set so it reopens as a fresh, editable order —
 * never re-submits the old one, just starts from its values).
 *
 * TWO MODES (requirement 10):
 *   "Place now"  — the original behaviour: the order goes to the broker
 *                  immediately.
 *   "Auto trade" — the order is SAVED and the server places it by
 *                  itself once a volume-value and/or green 1-minute
 *                  candle % condition is met (during market hours,
 *                  optionally only until a "valid till" time). Reorder
 *                  of an auto order reopens in this mode with its
 *                  conditions prefilled.
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
export default function PlaceOrderModal({ symbol, defaultReferencePrice, prefillOrder, onClose, onPlaced }) {
  const prefillIsAuto = prefillOrder?.source === "auto";

  const [mode, setMode] = useState(prefillIsAuto ? "auto" : "now");

  const [orderKind, setOrderKind] = useState(prefillOrder?.order_kind || "intraday");
  const [transactionType, setTransactionType] = useState(prefillOrder?.transaction_type || "B");
  const [orderType, setOrderType] = useState(prefillOrder?.order_type || "MKT");
  const [product, setProduct] = useState(
    prefillOrder?.product || (prefillOrder?.order_kind === "delivery" ? "C" : "I")
  );
  const [validity, setValidity] = useState(prefillOrder?.validity || "DAY");
  const [price, setPrice] = useState(
    prefillOrder?.price ? String(prefillOrder.price) : (defaultReferencePrice ? String(defaultReferencePrice) : "")
  );
  const [triggerPrice, setTriggerPrice] = useState(prefillOrder?.trigger_price ? String(prefillOrder.trigger_price) : "");
  const [quantity, setQuantity] = useState(prefillOrder?.quantity ? String(prefillOrder.quantity) : "");

  const [useStoplossCalc, setUseStoplossCalc] = useState(!!prefillOrder?.stoploss_percentage);
  const [referencePrice, setReferencePrice] = useState(defaultReferencePrice ? String(defaultReferencePrice) : "");
  const [stoplossPercentage, setStoplossPercentage] = useState(
    prefillOrder?.stoploss_percentage ? String(prefillOrder.stoploss_percentage) : ""
  );
  const [stoplossValue, setStoplossValue] = useState(
    prefillOrder?.stoploss_value ? String(prefillOrder.stoploss_value) : ""
  );

  // --- auto trade conditions ---
  const prefillVolume = prefillIsAuto ? prefillOrder.auto_volume_threshold : null;
  const prefillCandle = prefillIsAuto ? prefillOrder.auto_candle_pct_threshold : null;
  const [useVolume, setUseVolume] = useState(prefillIsAuto ? prefillVolume != null : true);
  const [volumeCr, setVolumeCr] = useState(prefillVolume != null ? String(prefillVolume / ONE_CRORE) : "");
  const [useCandle, setUseCandle] = useState(prefillIsAuto ? prefillCandle != null : false);
  const [candlePct, setCandlePct] = useState(prefillCandle != null ? String(prefillCandle) : "");
  const [combinator, setCombinator] = useState(prefillOrder?.auto_combinator || "AND");
  const [validTill, setValidTill] = useState(prefillIsAuto && prefillOrder.auto_valid_till ? prefillOrder.auto_valid_till : "");

  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const isAuto = mode === "auto";
  const needsPrice = orderType === "LMT" || orderType === "SL";
  const needsTrigger = orderType === "SL" || orderType === "SLM";
  const productOptions = PRODUCTS_BY_KIND[orderKind];
  const sideLabel = transactionType === "B" ? "Buy" : "Sell";

  function handleOrderKindChange(kind) {
    setOrderKind(kind);
    // Keep product in sync with kind automatically -- see the
    // PRODUCTS_BY_KIND note above for why this matters.
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
    if (calculatedQuantity) setQuantity(String(calculatedQuantity));
  }

  // The rupee equivalent of what was typed in crores, shown as a
  // hint so "0.06" is never ambiguous.
  const volumeRupees = useMemo(() => {
    const cr = parseFloat(volumeCr);
    if (!cr || cr <= 0) return null;
    return Math.round(cr * ONE_CRORE);
  }, [volumeCr]);

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

    if (isAuto) {
      if (!useVolume && !useCandle) {
        setError("Choose at least one trigger: volume value, candle %, or both.");
        return;
      }
      let volumeThreshold = null;
      let candleThreshold = null;
      if (useVolume) {
        if (!volumeRupees) {
          setError("Enter the volume value in crores (6 = 6 Cr, 0.6 = 60 Lac, 0.06 = 6 Lac).");
          return;
        }
        volumeThreshold = volumeRupees;
      }
      if (useCandle) {
        const pct = parseFloat(candlePct);
        if (!pct || pct <= 0) {
          setError("Enter the candle % as a number above 0 (only green candles are tracked).");
          return;
        }
        candleThreshold = pct;
      }
      if (validTill && (validTill < MARKET_OPEN_HHMM || validTill > MARKET_CLOSE_HHMM)) {
        setError(`"Valid till" must be between ${MARKET_OPEN_HHMM} and ${MARKET_CLOSE_HHMM} (IST).`);
        return;
      }
    }

    setSubmitting(true);
    try {
      if (isAuto) {
        await createAutoOrder({
          ...orderFields,
          volume_threshold: useVolume ? volumeRupees : null,
          candle_pct_threshold: useCandle ? parseFloat(candlePct) : null,
          combinator: useVolume && useCandle ? combinator : null,
          valid_till: validTill || null,
        });
        showToast(`Auto ${sideLabel} order for ${symbol} is active — it will be placed when the condition is met.`, "success");
      } else {
        await placeOrder(orderFields);
        showToast(`${sideLabel} order for ${symbol} placed successfully.`, "success");
      }
      if (onPlaced) onPlaced();
      onClose();
    } catch (err) {
      showToast(`${isAuto ? "Auto order" : "Order"} for ${symbol} failed: ${err.message}`, "error");
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  const title = `${prefillOrder ? "Reorder" : (isAuto ? "Auto trade" : "Place order")} — ${symbol}`;
  const submitLabel = submitting
    ? (isAuto ? "Saving..." : "Placing...")
    : (isAuto ? `Create auto ${sideLabel.toLowerCase()} order` : `${sideLabel} ${symbol}`);

  return (
    <div style={styles.overlay} onClick={onClose}>
      <form style={styles.modal} onClick={(e) => e.stopPropagation()} onSubmit={handleSubmit}>
        <h2 style={styles.title}>{title}</h2>

        <ToggleGroup value={mode} onChange={setMode} options={[
          { value: "now", label: "Place now" },
          { value: "auto", label: "Auto trade" },
        ]} />

        <div style={styles.row}>
          <ToggleGroup value={transactionType} onChange={setTransactionType} options={[
            { value: "B", label: "Buy" },
            { value: "S", label: "Sell" },
          ]} />
          <ToggleGroup value={orderKind} onChange={handleOrderKindChange} options={[
            { value: "intraday", label: "Intraday" },
            { value: "delivery", label: "Delivery" },
          ]} />
        </div>

        {isAuto && (
          <div style={styles.autoBox}>
            <div style={styles.autoTitle}>Place this order automatically when</div>

            <label style={styles.checkboxRow}>
              <input type="checkbox" checked={useVolume} onChange={(e) => setUseVolume(e.target.checked)} />
              Volume value (volume × price) is at least
            </label>
            {useVolume && (
              <>
                <div style={styles.unitRow}>
                  <input
                    type="number"
                    step="any"
                    min="0"
                    placeholder="e.g. 6"
                    value={volumeCr}
                    onChange={(e) => setVolumeCr(e.target.value)}
                    style={styles.input}
                  />
                  <span style={styles.unit}>Cr</span>
                </div>
                <span style={styles.hint}>
                  {volumeRupees
                    ? `= \u20b9${volumeRupees.toLocaleString("en-IN")}`
                    : "In crores: 6 = 6 Cr, 0.6 = 60 Lac, 0.06 = 6 Lac"}
                </span>
              </>
            )}

            {useVolume && useCandle && (
              <select value={combinator} onChange={(e) => setCombinator(e.target.value)}>
                <option value="AND">AND — both conditions must be true</option>
                <option value="OR">OR — either condition is enough</option>
              </select>
            )}

            <label style={styles.checkboxRow}>
              <input type="checkbox" checked={useCandle} onChange={(e) => setUseCandle(e.target.checked)} />
              Current 1-minute candle is green and up at least
            </label>
            {useCandle && (
              <>
                <div style={styles.unitRow}>
                  <input
                    type="number"
                    step="any"
                    min="0"
                    placeholder="e.g. 1.7"
                    value={candlePct}
                    onChange={(e) => setCandlePct(e.target.value)}
                    style={styles.input}
                  />
                  <span style={styles.unit}>%</span>
                </div>
                <span style={styles.hint}>Only green candles count — a red candle never triggers this condition.</span>
              </>
            )}

            <div style={styles.field}>
              <span style={styles.label}>Valid till (IST, 24-hour, optional)</span>
              <ValidTillPicker value={validTill} onChange={setValidTill} />
            </div>
            <span style={styles.hint}>
              {validTill
                ? `Valid till ${validTill} covers the whole minute: it can still trigger at ${validTill}:59 and is held from the next minute.`
                : "Leave blank to watch until 15:30."}
              {" "}Checked live from 09:15 on trading days. It stays active on later days until it triggers or you cancel it.
              If the condition is already true when you save it during market hours, it is placed straight away.
            </span>
          </div>
        )}

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
              {productOptions.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
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
          {submitLabel}
        </button>
        <button type="button" style={styles.closeBtn} onClick={onClose}>Cancel</button>
      </form>
    </div>
  );
}

// Hours and minutes only — deliberately NOT <input type="time">, which
// some browsers render with a seconds field (HH:MM:SS). Auto orders use
// minute precision: "valid till 09:30" means the whole 09:30 minute.
// Options are limited to the 09:15 - 15:30 window the order is checked in.
const HOUR_OPTIONS = ["09", "10", "11", "12", "13", "14", "15"];

function minutesForHour(hour) {
  let first = 0;
  let last = 59;
  if (hour === "09") first = 15; // market opens 09:15
  if (hour === "15") last = 30;  // market closes 15:30
  return Array.from({ length: last - first + 1 }, (_, i) => String(first + i).padStart(2, "0"));
}

function ValidTillPicker({ value, onChange }) {
  const [hour, minute] = value ? value.split(":") : ["", ""];

  function handleHourChange(newHour) {
    if (!newHour) {
      onChange("");
      return;
    }
    // Keep the chosen minute if it's still allowed for this hour,
    // otherwise fall back to the first allowed one.
    const allowed = minutesForHour(newHour);
    onChange(`${newHour}:${allowed.includes(minute) ? minute : allowed[0]}`);
  }

  return (
    <div style={styles.timeRow}>
      <select value={hour} onChange={(e) => handleHourChange(e.target.value)} aria-label="Valid till hour">
        <option value="">--</option>
        {HOUR_OPTIONS.map((h) => <option key={h} value={h}>{h}</option>)}
      </select>
      <span style={styles.timeColon}>:</span>
      <select
        value={minute || ""}
        disabled={!hour}
        onChange={(e) => onChange(`${hour}:${e.target.value}`)}
        aria-label="Valid till minute"
      >
        {!hour && <option value="">--</option>}
        {hour && minutesForHour(hour).map((m) => <option key={m} value={m}>{m}</option>)}
      </select>
      {value && (
        <button type="button" style={styles.linkBtn} onClick={() => onChange("")}>Clear</button>
      )}
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
    padding: 20, width: 380, display: "flex", flexDirection: "column", gap: 10,
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
  autoBox: {
    display: "flex", flexDirection: "column", gap: 8,
    background: "rgba(245,166,35,0.06)", border: "1px solid rgba(245,166,35,0.35)",
    borderRadius: 8, padding: 12,
  },
  autoTitle: { fontSize: 12, fontWeight: 600 },
  unitRow: { display: "flex", alignItems: "center", gap: 8 },
  timeRow: { display: "flex", alignItems: "center", gap: 6 },
  timeColon: { fontSize: 14, color: "var(--text-muted)" },
  linkBtn: {
    background: "none", border: "none", color: "var(--focus)", fontSize: 12,
    padding: "0 0 0 6px", cursor: "pointer",
  },
  unit: { fontSize: 12, color: "var(--text-muted)", minWidth: 20 },
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
