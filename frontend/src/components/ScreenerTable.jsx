import { useMemo, useState } from "react";
import { rowId } from "../hooks/useScreenerSocket";
import { useColumnWidths } from "../hooks/useColumnWidths";
import { SCREENER_COLUMNS, ColGroup, ResizableTh } from "./ScreenerColumns";
import { useWatchlistMenu } from "./WatchlistMenu";
import PlaceOrderModal from "./PlaceOrderModal";
import FilterInput from "./FilterInput";
import { ChartIcon, BookmarkIcon } from "../icons";
import { showToast } from "../toast";

function openTradingViewChart(symbol) {
  const url = `https://www.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(symbol)}`;
  window.open(url, "_blank", "noopener,noreferrer");
}

function getSortValue(row, key) {
  switch (key) {
    case "pct":
      if (row.prev_close === null || row.prev_close === undefined || row.prev_close === 0) return -Infinity;
      return ((row.ltp - row.prev_close) / row.prev_close) * 100;
    case "sym": return row.trading_symbol;
    case "mult": return row.multiple;
    case "hits": return row.occurrence_count;
    case "last": return row.last_triggered_at;
    case "ltp": return row.ltp;
    default: return row[key];
  }
}

function PctChange({ ltp, prevClose }) {
  if (prevClose === null || prevClose === undefined || prevClose === 0) {
    return <span className="muted">{"—"}</span>;
  }
  const pct = ((ltp - prevClose) / prevClose) * 100;
  return <span className={pct >= 0 ? "up" : "down"}>{pct.toFixed(2)}%</span>;
}

export default function ScreenerTable({ rows, flashRowId, emptyMessage, stockColors = {}, onWatchlistChanged, onNavigateWatchlists, settings }) {
  const [search, setSearch] = useState("");
  const [onlyWatchlisted, setOnlyWatchlisted] = useState(false);
  const [sortKey, setSortKey] = useState("last_triggered_at");
  const [sortDesc, setSortDesc] = useState(true);
  const [orderModalRow, setOrderModalRow] = useState(null);

  const colWidths = useColumnWidths(SCREENER_COLUMNS);
  const { open: openWatchMenu, menu: watchMenu } = useWatchlistMenu(onWatchlistChanged, onNavigateWatchlists);

  const filtered = useMemo(() => {
    const term = search.toLowerCase();
    let list = rows.filter((r) => r.trading_symbol.toLowerCase().includes(term));
    if (onlyWatchlisted) list = list.filter((r) => !!stockColors[r.trading_symbol]);
    return [...list].sort((a, b) => {
      let av = getSortValue(a, sortKey);
      let bv = getSortValue(b, sortKey);
      if (typeof av === "string") { av = av.toLowerCase(); bv = bv.toLowerCase(); }
      if (av < bv) return sortDesc ? 1 : -1;
      if (av > bv) return sortDesc ? -1 : 1;
      return 0;
    });
  }, [rows, search, onlyWatchlisted, stockColors, sortKey, sortDesc]);

  function toggleSort(key) {
    if (sortKey === key) setSortDesc((d) => !d);
    else { setSortKey(key); setSortDesc(key !== "sym"); }
  }

  return (
    <div>
      <div className="toolbar">
        <FilterInput value={search} onChange={setSearch} placeholder="Search a symbol or company" />
        <div className="seg inline" role="group" aria-label="Which stocks to show">
          <button type="button" className={!onlyWatchlisted ? "active" : ""} aria-pressed={!onlyWatchlisted} onClick={() => setOnlyWatchlisted(false)}>All hits</button>
          <button type="button" className={onlyWatchlisted ? "active" : ""} aria-pressed={onlyWatchlisted} onClick={() => setOnlyWatchlisted(true)}>In my watchlists</button>
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
            {filtered.map((row) => (
              <Row
                key={rowId(row)}
                row={row}
                isFlashing={flashRowId === rowId(row)}
                color={stockColors[row.trading_symbol]}
                onOpenWatchMenu={(e) => openWatchMenu(e, row.trading_symbol)}
                onTrade={() => setOrderModalRow(row)}
              />
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={SCREENER_COLUMNS.length} className="empty">{rows.length === 0 ? emptyMessage : "No matches for that search."}</td></tr>
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
          onClose={() => setOrderModalRow(null)}
        />
      )}
    </div>
  );
}

function Row({ row, isFlashing, color, onOpenWatchMenu, onTrade }) {
  return (
    <tr className={isFlashing ? "flash" : undefined}>
      <td>
        <div className="cell">
          <button type="button" className="pip" style={{ background: color || "transparent" }} onClick={onOpenWatchMenu} title={color ? "In a watchlist — click to change" : `Add ${row.trading_symbol} to a watchlist`} aria-label={`Watchlist for ${row.trading_symbol}`} />
          <div>
            <div className="sym">{row.trading_symbol}</div>
          </div>
        </div>
      </td>
      <td className="c">
        <div className="acts">
          <button type="button" className="icon-btn" onClick={() => openTradingViewChart(row.trading_symbol)} title={`Open ${row.trading_symbol} on TradingView`} aria-label={`Open ${row.trading_symbol} chart on TradingView`}>
            <ChartIcon />
          </button>
          <button type="button" className="icon-btn" onClick={onOpenWatchMenu} title={color ? "In a watchlist — click to change" : "Add to a watchlist"} aria-label={`Watchlist for ${row.trading_symbol}`}>
            <BookmarkIcon filled={!!color} />
          </button>
          <button type="button" className="btn sm" onClick={onTrade}>Trade</button>
        </div>
      </td>
      <td className="c num">{row.ltp}</td>
      <td className="c num"><PctChange ltp={row.ltp} prevClose={row.prev_close} /></td>
      <td className="c num">{Math.round(Number(row.multiple))}</td>
      <td className="c num hide-sm">{row.occurrence_count}</td>
      <td className="c num">{new Date(row.last_triggered_at).toLocaleTimeString("en-IN", { hour12: false })}</td>
    </tr>
  );
}
