import { useState, useEffect } from "react";
import { getIgnoredStocks, unignoreStock, clearIgnoredStocks } from "../api";
import { showToast } from "../toast";
import { useConfirm } from "../hooks/useConfirm";
import { ChartIcon } from "../icons";

function openTradingViewChart(symbol) {
  window.open(
    `https://www.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(symbol)}`,
    "_blank",
    "noopener,noreferrer",
  );
}

function timeOnly(isoString) {
  const m = /(\d{2}):(\d{2}):(\d{2})/.exec(isoString || "");
  return m ? `${m[1]}:${m[2]}` : "—";
}

export default function Ignored({ onKeepWatch }) {
  const [ignored, setIgnored] = useState([]);
  const [loading, setLoading] = useState(true);
  const [confirm, confirmDialog] = useConfirm();

  function reload() {
    setLoading(true);
    getIgnoredStocks()
      .then(setIgnored)
      .catch(() => setIgnored([]))
      .finally(() => setLoading(false));
  }

  useEffect(() => { reload(); }, []);

  async function handleKeepWatch(symbol) {
    try {
      await unignoreStock(symbol);
      showToast(`${symbol} is back on your Live feed.`);
      reload();
      if (onKeepWatch) onKeepWatch();
    } catch (err) {
      showToast(`Could not unignore ${symbol}: ${err.message}`, "error");
    }
  }

  async function handleWatchAll() {
    const ok = await confirm(
      "Watch all again?",
      "All stocks will reappear on your Live feed for the rest of today.",
      "Watch all",
      false,
    );
    if (!ok) return;
    try {
      await clearIgnoredStocks();
      showToast("All stocks are back on your Live feed.");
      reload();
      if (onKeepWatch) onKeepWatch();
    } catch (err) {
      showToast(`Could not clear ignored list: ${err.message}`, "error");
    }
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 12, flexWrap: "wrap", marginBottom: 6 }}>
        <p className="muted small" style={{ marginRight: "auto", maxWidth: "52ch" }}>
          Stocks hidden from Live today even when they match the screener. The list resets automatically each trading day — you start fresh every morning.
        </p>
        {ignored.length > 0 && (
          <button className="btn" onClick={handleWatchAll}>Watch all again</button>
        )}
      </div>

      {loading ? (
        <p className="muted small" style={{ padding: "20px 0" }}>Loading...</p>
      ) : ignored.length === 0 ? (
        <div className="panel empty">
          <b>Nothing ignored today.</b>
          Use the eye-off button on any Live row to hide a stock for today.
        </div>
      ) : (
        <div className="panel table-panel">
          <table className="tbl" style={{ width: "100%" }}>
            <thead>
              <tr>
                <th>Stock</th>
                <th>Ignored at</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {ignored.map((item) => (
                <tr key={item.trading_symbol}>
                  <td>
                    <div className="cell">
                      <span className="sym">{item.trading_symbol}</span>
                    </div>
                  </td>
                  <td className="n">{timeOnly(item.ignored_at)}</td>
                  <td>
                    <div className="act-row">
                      <button
                        type="button"
                        className="icon-btn"
                        onClick={() => openTradingViewChart(item.trading_symbol)}
                        title={`Open ${item.trading_symbol} on TradingView`}
                        aria-label={`Open ${item.trading_symbol} chart on TradingView`}
                      >
                        <ChartIcon />
                      </button>
                      <button
                        type="button"
                        className="btn sm primary"
                        onClick={() => handleKeepWatch(item.trading_symbol)}
                      >
                        Keep watch
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {confirmDialog}
    </div>
  );
}
