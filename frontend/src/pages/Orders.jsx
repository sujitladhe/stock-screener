import { useState, useEffect, useMemo } from "react";
import { getOrders, cancelOrder } from "../api";
import { showToast } from "../toast";
import { useConfirm } from "../hooks/useConfirm";
import PlaceOrderModal from "../components/PlaceOrderModal";
import ModifyOrderModal from "../components/ModifyOrderModal";
import StockSearchInput from "../components/StockSearchInput";
import FilterInput from "../components/FilterInput";
import { DownIcon } from "../icons";

const TERMINAL_STATUSES = new Set(["Executed", "Cancelled", "Rejected"]);
const REORDERABLE_STATUSES = new Set(["Cancelled", "Rejected"]);
const ONE_CRORE = 10000000;

// Active / Triggering bubble to the very top; otherwise newest-first within each status.
const STATUS_PRIORITY = {
  Active: 0, Triggering: 1, Pending: 2,
  Executed: 3, Cancelled: 4, Rejected: 5,
};

const STATUS_PILL_CLASS = {
  Active: "p-active", Triggering: "p-trig", Pending: "p-pending",
  Executed: "p-exec", Rejected: "p-rej", Cancelled: "p-can",
};

function timeOnly(isoString) {
  const m = /(\d{2}):(\d{2}):(\d{2})/.exec(isoString || "");
  return m ? `${m[1]}:${m[2]}:${m[3]}` : "—";
}
function dateParts(isoLike) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(isoLike || "");
  return m ? { y: +m[1], mo: +m[2], d: +m[3] } : null;
}
function todayISTDateString() {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}
function daysAgo(dateStr, todayStr) {
  const a = dateParts(dateStr), b = dateParts(todayStr);
  if (!a || !b) return 0;
  return Math.max(0, Math.round((Date.UTC(b.y, b.mo - 1, b.d) - Date.UTC(a.y, a.mo - 1, a.d)) / 86400000));
}
function dayLabel(dateStr) {
  const p = dateParts(dateStr);
  if (!p) return dateStr;
  return new Date(p.y, p.mo - 1, p.d).toLocaleDateString("en-US", {
    weekday: "short", day: "numeric", month: "short", year: "numeric",
  });
}
function formatCrores(rupees) {
  const cr = rupees / ONE_CRORE;
  return `₹${(cr >= 10 ? cr.toFixed(1) : cr.toFixed(2))} Cr`;
}
function conditionText(o) {
  const parts = [];
  if (o.auto_volume_threshold != null) parts.push(`Value ≥ ${formatCrores(o.auto_volume_threshold)}`);
  if (o.auto_candle_pct_threshold != null) parts.push(`green candle ≥ ${o.auto_candle_pct_threshold}%`);
  let text = parts.join(` ${o.auto_combinator || "AND"} `);
  if (o.auto_day_high_pct_limit != null) text += ` · skip if up ≥ ${o.auto_day_high_pct_limit}%`;
  if (o.auto_valid_till) text += ` · valid till ${o.auto_valid_till}`;
  const lifetime = o.auto_expires_daily ? "today only" : "until executed";
  text += ` · ${lifetime}`;
  return text;
}
function priceText(o) {
  if (o.order_type === "MKT") return "at market price";
  if (o.order_type === "LMT") return `at ₹${o.price} limit`;
  if (o.order_type === "SL")  return `stop ₹${o.trigger_price}, limit ₹${o.price}`;
  return `stop ₹${o.trigger_price} at market`;
}
function activeWindowHint(o) {
  const now = new Date();
  const hhmm = now.toLocaleTimeString("en-GB", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
  const weekday = now.toLocaleDateString("en-US", { timeZone: "Asia/Kolkata", weekday: "short" });
  if (weekday === "Sat" || weekday === "Sun") return "Market closed — checking resumes next trading day";
  if (hhmm < "09:15") return "Checking starts at 09:15";
  const windowClosed = o.auto_valid_till ? hhmm > o.auto_valid_till : hhmm >= "15:30";
  if (windowClosed) {
    return o.auto_expires_daily
      ? "Window closed — today-only order will expire at end of day"
      : "Window closed for today — checking resumes next trading day";
  }
  return "Watching live";
}

function OrderRow({ o, onCancel, onReorder, onModify }) {
  const auto = o.source === "auto";
  const sideLabel = o.transaction_type === "B" ? "Buy" : "Sell";
  const canModify  = o.status === "Pending" || (auto && o.status === "Active");
  const canCancel  = o.status === "Active" || o.status === "Pending";
  const canReorder = REORDERABLE_STATUSES.has(o.status);

  return (
    <tr>
      <td className="top">
        <div>
          <span className="sym">{o.trading_symbol}</span>
          {auto && <span className="tag-auto">Auto</span>}
        </div>
        <div className="sub">{auto ? conditionText(o) : (o.order_kind === "delivery" ? "Delivery" : "Intraday")}</div>
      </td>
      <td className="top">
        <span className={`b ${o.transaction_type === "B" ? "up" : "down"}`}>{sideLabel}</span>{" "}
        <span className="num">{o.quantity}</span> {priceText(o)}
      </td>
      <td className="top">
        <span className={`pill ${STATUS_PILL_CLASS[o.status] || ""}`}><i /> {o.status}</span>
        <div className="sub">{auto && o.status === "Active" ? activeWindowHint(o) : (o.broker_message || "")}</div>
        {o.trigger_details && <div className="sub">{o.trigger_details}</div>}
      </td>
      <td className="top num">
        {o.triggered_at ? (
          <>
            <div>{timeOnly(o.placed_at)}</div>
            <div className="sub">Triggered {timeOnly(o.triggered_at)}</div>
          </>
        ) : timeOnly(o.placed_at)}
      </td>
      <td className="top">
        <div className="act-row">
          {canModify  && <button type="button" className="btn sm" onClick={() => onModify(o)}>Modify</button>}
          {canCancel  && <button type="button" className="btn sm danger" onClick={() => onCancel(o)}>Cancel</button>}
          {canReorder && <button type="button" className="btn sm" onClick={() => onReorder(o)}>Reorder</button>}
        </div>
      </td>
    </tr>
  );
}

function OrdersTable({ orders, onCancel, onReorder, onModify }) {
  return (
    <table className="tbl">
      <thead>
        <tr><th>Stock</th><th>Order</th><th>Status</th><th>Placed (IST)</th><th></th></tr>
      </thead>
      <tbody>
        {orders.map((o) => (
          <OrderRow key={o.id} o={o} onCancel={onCancel} onReorder={onReorder} onModify={onModify} />
        ))}
      </tbody>
    </table>
  );
}

export default function Orders({ refreshSignal, settings }) {
  const [allOrders, setAllOrders]         = useState([]);
  const [source, setSource]               = useState("all");
  const [symbolFilter, setSymbolFilter]   = useState(""); // NEW (0004) — text filter by stock name
  const [loading, setLoading]             = useState(true);
  const [error, setError]                 = useState(null);
  const [newOrderSymbol, setNewOrderSymbol]   = useState(null);
  const [modifyingOrder, setModifyingOrder]   = useState(null);
  const [reorderTarget, setReorderTarget]     = useState(null);
  const [editAutoTarget, setEditAutoTarget]   = useState(null);
  const [pastOrdersOpen, setPastOrdersOpen]   = useState(false);
  const [pastDay, setPastDay]                 = useState(null);
  const [confirm, confirmDialog]              = useConfirm();

  function reload({ showSpinner = true } = {}) {
    if (showSpinner) setLoading(true);
    getOrders("all")
      .then((data) => { setAllOrders(data); setError(null); })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { reload(); }, []);
  useEffect(() => { if (!refreshSignal) return; reload({ showSpinner: false }); }, [refreshSignal]);

  // Badge count is now managed in App.jsx via useAutoOrderSymbols — no local tracking needed.

  // Derived from the already-loaded order list — always in sync, no extra fetch needed.
  // Used to warn (and disable submit) when the user tries to create a duplicate Active auto order.
  const autoOrderSymbols = useMemo(
    () => new Set(allOrders.filter((o) => o.source === "auto" && o.status === "Active").map((o) => o.trading_symbol)),
    [allOrders],
  );

  const filtered = useMemo(() => {
    let list = source === "all" ? allOrders : allOrders.filter((o) => o.source === source);
    if (symbolFilter.trim()) {
      const term = symbolFilter.trim().toUpperCase();
      list = list.filter((o) => o.trading_symbol.includes(term));
    }
    return list;
  }, [allOrders, source, symbolFilter]);

  const today = todayISTDateString();

  // Active / Triggering orders surface permanently at the top of the page regardless
  // of when they were created. An auto order placed last Tuesday that still hasn't
  // fired should not be buried inside a collapsed "Earlier orders" section.
  const activeOrders = filtered.filter(
    (o) => o.status === "Active" || o.status === "Triggering",
  );

  // Everything else splits into today vs past by the date it actually reached the broker
  // (triggered_at for auto, placed_at for manual).
  const nonActive = filtered.filter(
    (o) => o.status !== "Active" && o.status !== "Triggering",
  );
  const todays = nonActive
    .filter((o) => daysAgo(o.triggered_at || o.placed_at, today) === 0)
    .sort((a, b) => (b.placed_at || "").localeCompare(a.placed_at || ""));
  const past = nonActive.filter((o) => daysAgo(o.triggered_at || o.placed_at, today) > 0);

  const pastDays = useMemo(
    () => [...new Set(past.map((o) => daysAgo(o.triggered_at || o.placed_at, today)))].sort((a, b) => a - b),
    [past, today],
  );
  const effectivePastDay   = pastDays.includes(pastDay) ? pastDay : pastDays[0];
  const pastDayOrders      = past
    .filter((o) => daysAgo(o.triggered_at || o.placed_at, today) === effectivePastDay)
    .sort((a, b) => (b.placed_at || "").localeCompare(a.placed_at || ""));

  const emptyMsg = source === "auto"
    ? ["No auto orders yet.", "Search a stock above, then choose Auto trade in the order window."]
    : source === "manual"
      ? ["No manual orders yet.", "Search a stock above to place one."]
      : ["No orders yet.", "Search a stock above to place your first one."];

  async function handleCancel(o) {
    const waiting = o.source === "auto" && o.status === "Active";
    const ok = await confirm(
      waiting ? "Cancel this auto order?" : "Cancel this order?",
      waiting
        ? `${o.trading_symbol} has not triggered yet — nothing sent to the broker.`
        : `${o.trading_symbol} will be cancelled with the broker.`,
      "Cancel order",
      true,
    );
    if (!ok) return;
    try {
      await cancelOrder(o.id);
      showToast(`${waiting ? "Auto order" : "Order"} for ${o.trading_symbol} cancelled.`);
      reload({ showSpinner: false });
    } catch (err) {
      showToast(`Could not cancel: ${err.message}`, "error");
      reload({ showSpinner: false });
    }
  }

  function handleReorder(o)  { setReorderTarget(o); }
  function handleModify(o)   {
    if (o.source === "auto" && o.status === "Active") setEditAutoTarget(o);
    else setModifyingOrder(o);
  }

  return (
    <div>
      <div className="page-tools">
        <label className="tool-label">
          Show
          <select className="select" value={source} onChange={(e) => setSource(e.target.value)} aria-label="Which orders to show">
            <option value="manual">Manual</option>
            <option value="auto">Auto</option>
            <option value="all">All</option>
          </select>
        </label>
        {/* NEW (0004) — search orders by stock symbol */}
        <FilterInput
          value={symbolFilter}
          onChange={setSymbolFilter}
          placeholder="Search orders by stock"
        />
        <div className="grow" />
        <div style={{ flex: "none", width: "min(340px, 100%)" }}>
          <StockSearchInput placeholder="Trade a stock: symbol or name" onSelect={setNewOrderSymbol} />
        </div>
      </div>

      {error && <div className="err" style={{ marginBottom: 16 }}>{error}</div>}

      {loading ? (
        <p className="muted small">Loading...</p>
      ) : (
        <>
          {/* ── Zone 1: Active / Triggering orders ──────────────────────────
              Always shown at the very top, regardless of the date they were
              created. An auto order from last week that hasn't fired yet must
              be immediately visible so the user can modify or cancel it.     */}
          {activeOrders.length > 0 && (
            <div style={{ marginBottom: 20 }}>
              <h2 className="section-title" style={{ marginTop: 0 }}>
                Waiting to trigger
                <span
                  style={{
                    marginLeft: 8,
                    padding: "1px 8px",
                    borderRadius: 10,
                    background: "var(--mari-soft)",
                    color: "var(--mari-ink)",
                    fontSize: 12,
                    fontWeight: 600,
                    verticalAlign: "middle",
                  }}
                >
                  {activeOrders.length}
                </span>
              </h2>
              <div className="panel table-panel">
                <OrdersTable
                  orders={activeOrders}
                  onCancel={handleCancel}
                  onReorder={handleReorder}
                  onModify={handleModify}
                />
              </div>
            </div>
          )}

          {/* ── Zone 2: Today's non-active orders ───────────────────────── */}
          {todays.length > 0 && (
            <div className="panel table-panel" style={{ marginBottom: 16 }}>
              <OrdersTable
                orders={todays}
                onCancel={handleCancel}
                onReorder={handleReorder}
                onModify={handleModify}
              />
            </div>
          )}

          {/* Empty state — only when all three zones are empty */}
          {activeOrders.length === 0 && todays.length === 0 && past.length === 0 && (
            <div className="panel empty"><b>{emptyMsg[0]}</b>{emptyMsg[1]}</div>
          )}

          {/* No-orders-today note — only when there are past orders to show but nothing today */}
          {activeOrders.length === 0 && todays.length === 0 && past.length > 0 && (
            <p className="muted small" style={{ margin: "4px 0 16px" }}>
              No{symbolFilter ? ` "${symbolFilter.toUpperCase()}"` : ""} orders placed today.
            </p>
          )}

          {/* ── Zone 3: Earlier orders (non-active only) ─────────────────── */}
          {past.length > 0 && (
            <details
              className="pastorders"
              open={pastOrdersOpen}
              onToggle={(e) => setPastOrdersOpen(e.currentTarget.open)}
            >
              <summary>
                <span className="chev"><DownIcon size={15} /></span>
                Earlier orders ({past.length})
              </summary>
              <div className="page-tools" style={{ padding: "14px 16px 0", margin: 0 }}>
                <label className="tool-label">
                  Day
                  <select
                    className="select"
                    value={effectivePastDay}
                    onChange={(e) => setPastDay(+e.target.value)}
                    aria-label="Choose a day"
                  >
                    {pastDays.map((n) => {
                      const sample = past.find(
                        (o) => daysAgo(o.triggered_at || o.placed_at, today) === n,
                      );
                      return (
                        <option key={n} value={n}>
                          {dayLabel(sample.triggered_at || sample.placed_at)}
                        </option>
                      );
                    })}
                  </select>
                </label>
                <span className="muted small">
                  {pastDayOrders.length} order{pastDayOrders.length === 1 ? "" : "s"} that day
                </span>
              </div>
              <div className="table-panel" style={{ marginTop: 10 }}>
                <OrdersTable
                  orders={pastDayOrders}
                  onCancel={handleCancel}
                  onReorder={handleReorder}
                  onModify={handleModify}
                />
              </div>
            </details>
          )}
        </>
      )}

      {newOrderSymbol && (
        <PlaceOrderModal
          symbol={newOrderSymbol}
          settings={settings}
          autoOrderSymbols={autoOrderSymbols}
          onClose={() => setNewOrderSymbol(null)}
          onPlaced={() => reload({ showSpinner: false })}
        />
      )}
      {reorderTarget && (
        <PlaceOrderModal
          symbol={reorderTarget.trading_symbol}
          prefillOrder={reorderTarget}
          settings={settings}
          autoOrderSymbols={autoOrderSymbols}
          onClose={() => setReorderTarget(null)}
          onPlaced={() => reload({ showSpinner: false })}
        />
      )}
      {editAutoTarget && (
        <PlaceOrderModal
          symbol={editAutoTarget.trading_symbol}
          prefillOrder={editAutoTarget}
          editOrderId={editAutoTarget.id}
          settings={settings}
          autoOrderSymbols={autoOrderSymbols}
          onClose={() => setEditAutoTarget(null)}
          onPlaced={() => reload({ showSpinner: false })}
        />
      )}
      {modifyingOrder && (
        <ModifyOrderModal order={modifyingOrder} onClose={() => setModifyingOrder(null)} onModified={() => reload({ showSpinner: false })} />
      )}
      {confirmDialog}
    </div>
  );
}
