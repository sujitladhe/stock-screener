import { useState, useMemo, useEffect, useRef } from "react";
import { rowId } from "../hooks/useScreenerSocket";
import AddToWatchlistModal from "./AddToWatchlistModal";
import PlaceOrderModal from "./PlaceOrderModal";

/**
 * Renders a searchable, sortable screener table.
 *
 * stockColors: {trading_symbol: colorHex} - a stock in a watchlist
 * gets that watchlist's color as a left-border accent. Replaces the
 * earlier per-stock "leg" system entirely (removed per an explicit
 * product decision) - a stock now belongs to at most one watchlist,
 * so there's exactly one color to show, no ambiguity.
 *
 * The "Condition" column/badge from earlier versions is intentionally
 * removed per product decision - condition_matched is still present
 * in the row data but no longer rendered.
 *
 * % change is DERIVED (ltp vs prev_close), not a field on the row
 * itself -- so sorting by it needs its own accessor rather than a
 * plain row[sortKey] lookup (which would always be undefined for
 * "pct_change" and silently no-op the sort).
 */
function getSortValue(row, key) {
  if (key === "pct_change") {
    if (row.prev_close === null || row.prev_close === undefined || row.prev_close === 0) {
      return -Infinity; // stocks with no baseline sort to the bottom, consistently
    }
    return ((row.ltp - row.prev_close) / row.prev_close) * 100;
  }
  return row[key];
}

export default function ScreenerTable({ rows, flashRowId, emptyMessage, stockColors = {}, onWatchlistChanged }) {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState("last_triggered_at");
  const [sortDesc, setSortDesc] = useState(true);
  const [watchlistModalSymbol, setWatchlistModalSymbol] = useState(null);
  const [orderModalRow, setOrderModalRow] = useState(null);

  const filtered = useMemo(() => {
    const term = search.toLowerCase();
    const list = rows.filter((r) => r.trading_symbol.toLowerCase().includes(term));
    return list.sort((a, b) => {
      let av = getSortValue(a, sortKey), bv = getSortValue(b, sortKey);
      if (typeof av === "string") { av = av.toLowerCase(); bv = bv.toLowerCase(); }
      if (av < bv) return sortDesc ? 1 : -1;
      if (av > bv) return sortDesc ? -1 : 1;
      return 0;
    });
  }, [rows, search, sortKey, sortDesc]);

  function toggleSort(key) {
    if (sortKey === key) setSortDesc((d) => !d);
    else { setSortKey(key); setSortDesc(true); }
  }

  return (
    <div>
      <div style={styles.searchWrap}>
        <input
          style={styles.search}
          type="text"
          placeholder="Search symbol"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <button
            style={styles.clearBtn}
            onClick={() => setSearch("")}
            aria-label="Clear search"
            title="Clear search"
          >
            &times;
          </button>
        )}
      </div>

      <table style={styles.table}>
        <thead>
          <tr>
            <th
              style={{ ...styles.th, textAlign: "left", color: sortKey === "trading_symbol" ? "var(--text)" : "var(--text-muted)" }}
              onClick={() => toggleSort("trading_symbol")}
            >
              Symbol{sortKey === "trading_symbol" ? (sortDesc ? " \u2193" : " \u2191") : ""}
            </th>
            <Th label="LTP" col="ltp" toggleSort={toggleSort} currentSort={sortKey} sortDesc={sortDesc} />
            <Th label="% Chg" col="pct_change" toggleSort={toggleSort} currentSort={sortKey} sortDesc={sortDesc} />
            <Th label="Rel Vol" col="multiple" toggleSort={toggleSort} currentSort={sortKey} sortDesc={sortDesc} />
            <Th label="Occurrences" col="occurrence_count" toggleSort={toggleSort} currentSort={sortKey} sortDesc={sortDesc} />
            <Th label="Last Triggered" col="last_triggered_at" toggleSort={toggleSort} currentSort={sortKey} sortDesc={sortDesc} />
          </tr>
        </thead>
        <tbody>
          {filtered.map((row) => (
            <Row
              key={rowId(row)}
              row={row}
              isFlashing={flashRowId === rowId(row)}
              color={stockColors[row.trading_symbol]}
              onAddToWatchlist={() => setWatchlistModalSymbol(row.trading_symbol)}
              onPlaceOrder={() => setOrderModalRow(row)}
            />
          ))}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={6} style={styles.empty}>
                {rows.length === 0 ? emptyMessage : "No matches for that search."}
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {watchlistModalSymbol && (
        <AddToWatchlistModal
          symbol={watchlistModalSymbol}
          onClose={() => setWatchlistModalSymbol(null)}
          onAdded={onWatchlistChanged}
        />
      )}

      {orderModalRow && (
        <PlaceOrderModal
          symbol={orderModalRow.trading_symbol}
          defaultReferencePrice={orderModalRow.ltp}
          onClose={() => setOrderModalRow(null)}
        />
      )}
    </div>
  );
}

function Th({ label, col, toggleSort, currentSort, sortDesc }) {
  const active = currentSort === col;
  return (
    <th
      style={{ ...styles.th, color: active ? "var(--text)" : "var(--text-muted)" }}
      onClick={() => toggleSort(col)}
    >
      {label}{active ? (sortDesc ? " \u2193" : " \u2191") : ""}
    </th>
  );
}

function openTradingViewChart(symbol) {
  const url = `https://www.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(symbol)}`;
  window.open(url, "_blank", "noopener,noreferrer");
}

function ExternalLinkIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  );
}

function BookmarkIcon({ filled }) {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function OrderIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="19" x2="12" y2="5" />
      <polyline points="5 12 12 5 19 12" />
    </svg>
  );
}

/**
 * % change formatting per an explicit product decision:
 *   - positive: green, no "+" prefix
 *   - negative: red, WITH a "-" prefix
 *   - toFixed already produces a leading "-" for negatives on its
 *     own, so no extra sign-handling is needed beyond styling.
 */
function PctChange({ ltp, prevClose }) {
  if (prevClose === null || prevClose === undefined || prevClose === 0) {
    return <span style={{ color: "var(--text-muted)" }}>{"\u2014"}</span>;
  }
  const pct = ((ltp - prevClose) / prevClose) * 100;
  const isPositive = pct >= 0;
  return (
    <span style={{ color: isPositive ? "var(--positive)" : "var(--negative)" }}>
      {pct.toFixed(2)}%
    </span>
  );
}

function Row({ row, isFlashing, color, onAddToWatchlist, onPlaceOrder }) {
  const [flashing, setFlashing] = useState(false);
  const timerRef = useRef(null);

  useEffect(() => {
    if (!isFlashing) return;
    setFlashing(true);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setFlashing(false), 1200);
    return () => clearTimeout(timerRef.current);
  }, [isFlashing, row.last_triggered_at]);

  return (
    <tr
      style={{
        ...styles.row,
        background: flashing ? "rgba(61, 214, 140, 0.12)" : "transparent",
        borderLeft: `3px solid ${color || "transparent"}`,
      }}
    >
      <td style={styles.tdLeft}>
        <span style={styles.symbolCell}>
          {row.trading_symbol}
          <button
            className="chart-icon-btn"
            style={styles.chartIconBtn}
            onClick={() => openTradingViewChart(row.trading_symbol)}
            title={`Open ${row.trading_symbol} chart on TradingView`}
            aria-label={`Open ${row.trading_symbol} chart on TradingView`}
          >
            <ExternalLinkIcon />
          </button>
          <button
            className="chart-icon-btn"
            style={styles.chartIconBtn}
            onClick={onAddToWatchlist}
            title={color ? "In a watchlist \u2014 click to move to a different one" : `Add ${row.trading_symbol} to watchlist`}
            aria-label={`Add ${row.trading_symbol} to watchlist`}
          >
            <BookmarkIcon filled={!!color} />
          </button>
          <button
            className="chart-icon-btn"
            style={styles.chartIconBtn}
            onClick={onPlaceOrder}
            title={`Place an order for ${row.trading_symbol}`}
            aria-label={`Place an order for ${row.trading_symbol}`}
          >
            <OrderIcon />
          </button>
        </span>
      </td>
      <td style={styles.tdNum} className="mono">{row.ltp}</td>
      <td style={styles.tdNum} className="mono">
        <PctChange ltp={row.ltp} prevClose={row.prev_close} />
      </td>
      <td style={styles.tdNum} className="mono">{Math.round(Number(row.multiple))}</td>
      <td style={styles.tdNum} className="mono">{row.occurrence_count}</td>
      <td style={styles.tdNum} className="mono">
        {new Date(row.last_triggered_at).toLocaleTimeString("en-IN", { hour12: false })}
      </td>
    </tr>
  );
}

const styles = {
  searchWrap: { position: "relative", maxWidth: 280, marginBottom: 12 },
  search: { width: "100%", paddingRight: 28 },
  clearBtn: {
    position: "absolute", right: 4, top: "50%", transform: "translateY(-50%)",
    background: "none", border: "none", color: "var(--text-muted)", fontSize: 16,
    lineHeight: 1, cursor: "pointer", padding: "2px 6px",
  },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th: { textAlign: "right", padding: "8px 12px", borderBottom: "1px solid var(--border)", fontWeight: 500, cursor: "pointer", userSelect: "none" },
  row: { transition: "background 0.3s ease" },
  tdLeft: { textAlign: "left", padding: "9px 12px", borderBottom: "1px solid var(--border)" },
  tdNum: { textAlign: "right", padding: "9px 12px", borderBottom: "1px solid var(--border)" },
  symbolCell: { display: "inline-flex", alignItems: "center", gap: 7 },
  chartIconBtn: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    background: "none",
    border: "none",
    padding: 2,
    margin: 0,
    color: "var(--text-muted)",
    cursor: "pointer",
    borderRadius: 4,
  },
  empty: { textAlign: "center", padding: "40px 0", color: "var(--text-muted)" },
};
