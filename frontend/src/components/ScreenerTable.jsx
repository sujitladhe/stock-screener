import { useMemo, useState, useCallback } from "react";
import { rowId } from "../hooks/useScreenerSocket";
import { useColumnWidths } from "../hooks/useColumnWidths";
import { SCREENER_COLUMNS, ColGroup, ResizableTh } from "./ScreenerColumns";
import { useWatchlistMenu } from "./WatchlistMenu";
import PlaceOrderModal from "./PlaceOrderModal";
import FilterInput from "./FilterInput";
import { ChartIcon, BookmarkIcon, EyeOffIcon } from "../icons";
import { showToast } from "../toast";
import { ignoreStock } from "../api";

function openTradingViewChart(symbol) {
  window.open(
    `https://www.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(symbol)}`,
    "_blank",
    "noopener,noreferrer",
  );
}

function getSortValue(row, key) {
  switch (key) {
    case "pct":
      if (!row.prev_close || row.prev_close === 0) return -Infinity;
      return ((row.ltp - row.prev_close) / row.prev_close) * 100;
    case "sym":    return row.trading_symbol;
    case "mult":   return row.multiple;
    case "hits":   return row.occurrence_count;
    case "last":   return row.last_triggered_at;
    case "ltp":    return row.ltp;
    default:       return row[key];
  }
}

function PctChange({ ltp, prevClose }) {
  if (!prevClose || prevClose === 0) return <span className="muted">—</span>;
  const pct = ((ltp - prevClose) / prevClose) * 100;
  return <span className={pct >= 0 ? "up" : "down"}>{pct.toFixed(2)}%</span>;
}

export default function ScreenerTable({
  rows,
  flashRowId,
  emptyMessage,
  stockColors = {},
  ignoredSymbols = new Set(),
  onIgnore,
  onWatchlistChanged,
  onNavigateWatchlists,
  settings,
  autoOrderSymbols = new Set(),
  refetchAutoOrders,
}) {
  const [search, setSearch]             = useState("");
  const [onlyWatchlisted, setOnlyWatchlisted] = useState(false);
  const [changeFilter, setChangeFilter] = useState("all"); // "all" | "positive" | "negative"
  const [sortKey, setSortKey]           = useState("last_triggered_at");
  const [sortDesc, setSortDesc]         = useState(true);
  const [orderModalRow, setOrderModalRow] = useState(null);

  const colWidths = useColumnWidths(SCREENER_COLUMNS);
  const { open: openWatchMenu, menu: watchMenu } = useWatchlistMenu(onWatchlistChanged, onNavigateWatchlists);

  const greenThreshold = settings?.greenCandleThreshold ?? 1.5;

  const handleIgnore = useCallback(async (symbol) => {
    try {
      await ignoreStock(symbol);
      showToast(`${symbol} hidden for today. Go to Ignored to bring it back.`);
      if (onIgnore) onIgnore(symbol);
    } catch (err) {
      showToast(`Could not ignore ${symbol}: ${err.message}`, "error");
    }
  }, [onIgnore]);

  const filtered = useMemo(() => {
    const term = search.toLowerCase();
    return [...rows]
      .filter((r) => !ignoredSymbols.has(r.trading_symbol))
      .filter((r) => r.trading_symbol.toLowerCase().includes(term))
      .filter((r) => {
        if (onlyWatchlisted && !stockColors[r.trading_symbol]) return false;
        return true;
      })
      .filter((r) => {
        if (changeFilter === "all") return true;
        if (!r.prev_close || r.prev_close === 0) return changeFilter === "all";
        const pct = ((r.ltp - r.prev_close) / r.prev_close) * 100;
        return changeFilter === "positive" ? pct >= 0 : pct < 0;
      })
      .sort((a, b) => {
        let av = getSortValue(a, sortKey);
        let bv = getSortValue(b, sortKey);
        if (typeof av === "string") { av = av.toLowerCase(); bv = bv.toLowerCase(); }
        if (av < bv) return sortDesc ? 1 : -1;
        if (av > bv) return sortDesc ? -1 : 1;
        return 0;
      });
  }, [rows, search, onlyWatchlisted, changeFilter, stockColors, sortKey, sortDesc, ignoredSymbols]);

  function toggleSort(key) {
    if (sortKey === key) setSortDesc((d) => !d);
    else { setSortKey(key); setSortDesc(key !== "sym"); }
  }

  return (
    <div>
      <div className="toolbar">
        <FilterInput value={search} onChange={setSearch} placeholder="Search a symbol or company" />
        <label className="tool-label">
          Change
          <select
            className="select"
            style={{ width: "auto", minWidth: 110 }}
            value={changeFilter}
            onChange={(e) => setChangeFilter(e.target.value)}
            aria-label="Filter by change direction"
          >
            <option value="all">All</option>
            <option value="positive">Positive</option>
            <option value="negative">Negative</option>
          </select>
        </label>
        <div className="seg inline" role="group" aria-label="Which stocks to show">
          <button
            type="button"
            className={!onlyWatchlisted ? "active" : ""}
            aria-pressed={!onlyWatchlisted}
            onClick={() => setOnlyWatchlisted(false)}
          >
            All hits
          </button>
          <button
            type="button"
            className={onlyWatchlisted ? "active" : ""}
            aria-pressed={onlyWatchlisted}
            onClick={() => setOnlyWatchlisted(true)}
          >
            In my watchlists
          </button>
        </div>
      </div>

      <div className="panel table-panel">
        <table className="tbl resizable">
          <ColGroup columns={SCREENER_COLUMNS} widthOf={colWidths.widthOf} registerCol={colWidths.registerCol} />
          <thead>
            <tr>
              {SCREENER_COLUMNS.map((col) => (
                <ResizableTh
                  key={col.key}
                  col={col}
                  sortKey={sortKey}
                  sortDesc={sortDesc}
                  onSort={toggleSort}
                  onPointerDown={colWidths.onPointerDown}
                  onDoubleClick={colWidths.onDoubleClick}
                  onKeyDown={colWidths.onKeyDown}
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => {
              const isGreenCandle =
                greenThreshold != null &&
                row.candle_pct != null &&
                row.candle_pct >= greenThreshold;
              const hasAutoOrder = autoOrderSymbols.has(row.trading_symbol);

              return (
                <Row
                  key={rowId(row)}
                  row={row}
                  isFlashing={flashRowId === rowId(row)}
                  isGreenCandle={isGreenCandle}
                  hasAutoOrder={hasAutoOrder}
                  color={stockColors[row.trading_symbol]}
                  onOpenWatchMenu={(e) => openWatchMenu(e, row.trading_symbol)}
                  onTrade={() => setOrderModalRow(row)}
                  onIgnore={() => handleIgnore(row.trading_symbol)}
                />
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={SCREENER_COLUMNS.length} className="empty">
                  {rows.filter((r) => !ignoredSymbols.has(r.trading_symbol)).length === 0
                    ? emptyMessage
                    : "No matches for that search or filter."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {watchMenu}

      {orderModalRow && (
        <PlaceOrderModal
          symbol={orderModalRow.trading_symbol}
          defaultReferencePrice={orderModalRow.ltp}
          settings={settings}
          autoOrderSymbols={autoOrderSymbols}
          onClose={() => setOrderModalRow(null)}
          onPlaced={() => { if (refetchAutoOrders) refetchAutoOrders(); }}
        />
      )}
    </div>
  );
}

function Row({ row, isFlashing, isGreenCandle, hasAutoOrder, color, onOpenWatchMenu, onTrade, onIgnore }) {
  // Green-candle rows get a subtle green background; flash (marigold) takes priority.
  const rowClass = isFlashing ? "flash" : isGreenCandle ? "row-green" : undefined;

  return (
    <tr className={rowClass}>
      <td>
        <div className="cell">
          <button
            type="button"
            className="pip"
            style={{ background: color || "transparent" }}
            onClick={onOpenWatchMenu}
            title={color ? "In a watchlist — click to change" : `Add ${row.trading_symbol} to a watchlist`}
            aria-label={`Watchlist for ${row.trading_symbol}`}
          />
          <div>
            <div className="sym">{row.trading_symbol}</div>
          </div>
        </div>
      </td>
      {/* Actions column */}
      <td className="c">
        <div className="acts">
          <button
            type="button"
            className="icon-btn"
            onClick={() => openTradingViewChart(row.trading_symbol)}
            title={`Open ${row.trading_symbol} on TradingView`}
            aria-label={`Open ${row.trading_symbol} chart on TradingView`}
          >
            <ChartIcon />
          </button>
          <button
            type="button"
            className="icon-btn"
            onClick={onOpenWatchMenu}
            title={color ? "In a watchlist — click to change" : "Add to a watchlist"}
            aria-label={`Watchlist for ${row.trading_symbol}`}
          >
            <BookmarkIcon filled={!!color} />
          </button>
          <button type="button" className="btn sm" onClick={onTrade}>
            Trade
          </button>
          <button
            type="button"
            className="icon-btn"
            onClick={onIgnore}
            title={`Ignore ${row.trading_symbol} for today`}
            aria-label={`Ignore ${row.trading_symbol} for today`}
          >
            <EyeOffIcon />
          </button>
        </div>
        {/* Tags below the action buttons */}
        <div style={{ display: "flex", gap: 4, justifyContent: "center", flexWrap: "wrap", marginTop: 2 }}>
          {isGreenCandle && (
            <span
              style={{
                display: "inline-block",
                padding: "1px 6px",
                borderRadius: 5,
                background: "var(--up-soft)",
                color: "var(--up)",
                fontSize: 11,
                fontWeight: 600,
              }}
            >
              +{row.candle_pct?.toFixed(1)}%
            </span>
          )}
          {hasAutoOrder && (
            <span
              style={{
                display: "inline-block",
                padding: "1px 6px",
                borderRadius: 5,
                border: "1px solid var(--m)",
                color: "var(--mi)",
                fontSize: 11,
                fontWeight: 600,
              }}
            >
              Auto
            </span>
          )}
        </div>
      </td>
      <td className="c num">{row.ltp}</td>
      <td className="c num">
        <PctChange ltp={row.ltp} prevClose={row.prev_close} />
      </td>
      <td className="c num">
        {row.circuit_pct != null ? `${row.circuit_pct}%` : <span className="muted">—</span>}
      </td>
      <td className="c num">{Math.round(Number(row.multiple))}</td>
      <td className="c num hide-sm">{row.occurrence_count}</td>
      <td className="c num">
        {new Date(row.last_triggered_at).toLocaleTimeString("en-IN", { hour12: false })}
      </td>
    </tr>
  );
}
