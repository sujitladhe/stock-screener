import { useState, useEffect } from "react";
import { getScreenerHistory, getAvailableDates } from "../api";
import { useColumnWidths } from "../hooks/useColumnWidths";
import { HISTORY_COLUMNS, ColGroup, ResizableTh } from "../components/ScreenerColumns";
import { ChartIcon } from "../icons";

function openTradingViewChart(symbol) {
  const url = `https://www.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(symbol)}`;
  window.open(url, "_blank", "noopener,noreferrer");
}

function PctChange({ ltp, prevClose }) {
  if (prevClose === null || prevClose === undefined || prevClose === 0) {
    return <span className="muted">{"—"}</span>;
  }
  const pct = ((ltp - prevClose) / prevClose) * 100;
  return <span className={pct >= 0 ? "up" : "down"}>{pct.toFixed(2)}%</span>;
}

export default function History({ stockColors }) {
  const [availableDates, setAvailableDates] = useState([]);
  const [selectedDate, setSelectedDate] = useState(null);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const colWidths = useColumnWidths(HISTORY_COLUMNS);

  useEffect(() => {
    getAvailableDates().then((dates) => {
      setAvailableDates(dates);
      if (dates.length > 0) setSelectedDate(dates[0]);
    });
  }, []);

  useEffect(() => {
    if (!selectedDate) return;
    setLoading(true);
    getScreenerHistory(selectedDate).then(setRows).finally(() => setLoading(false));
  }, [selectedDate]);

  return (
    <div>
      <div className="page-tools">
        {availableDates.length > 0 && (
          <label className="tool-label">
            Day
            <select className="select" value={selectedDate || ""} onChange={(e) => setSelectedDate(e.target.value)} aria-label="Choose a day">
              {availableDates.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
        )}
        {!loading && rows.length > 0 && <span className="muted small">{rows.length} stocks hit that day</span>}
      </div>

      {availableDates.length === 0 ? (
        <p className="muted small" style={{ padding: "20px 0" }}>No screener history yet — check back once the screener has run for a day.</p>
      ) : loading ? (
        <p className="muted small" style={{ padding: "20px 0" }}>Loading...</p>
      ) : (
        <div className="panel table-panel">
          <table className="tbl resizable">
            <ColGroup columns={HISTORY_COLUMNS} widthOf={colWidths.widthOf} registerCol={colWidths.registerCol} />
            <thead>
              <tr>
                {HISTORY_COLUMNS.map((col) => (
                  <ResizableTh key={col.key} col={col} onPointerDown={colWidths.onPointerDown} onDoubleClick={colWidths.onDoubleClick} onKeyDown={colWidths.onKeyDown} />
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.trading_symbol}>
                  <td>
                    <div className="cell">
                      <button type="button" className="icon-btn" style={{ marginRight: 8, flex: "none" }} onClick={() => openTradingViewChart(row.trading_symbol)} title={`Open ${row.trading_symbol} on TradingView`} aria-label={`Open ${row.trading_symbol} chart on TradingView`}>
                        <ChartIcon />
                      </button>
                      <span className="pip" style={{ background: stockColors[row.trading_symbol] || "transparent" }} />
                      <div className="sym">{row.trading_symbol}</div>
                    </div>
                  </td>
                  <td className="c num">{row.ltp}</td>
                  <td className="c num"><PctChange ltp={row.ltp} prevClose={row.prev_close} /></td>
                  <td className="c num">{Math.round(Number(row.multiple))}</td>
                  <td className="c num hide-sm">{row.occurrence_count}</td>
                  <td className="c num">{new Date(row.last_triggered_at).toLocaleTimeString("en-IN", { hour12: false })}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td colSpan={HISTORY_COLUMNS.length} className="empty">No stocks triggered on this date.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
