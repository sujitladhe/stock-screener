import { useState } from "react";
import StoplossModal from "../components/StoplossModal";
import ExitPositionModal from "../components/ExitPositionModal";
import { ChartIcon } from "../icons";

function openTradingViewChart(symbol) {
  const url = `https://www.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(symbol)}`;
  window.open(url, "_blank", "noopener,noreferrer");
}

/**
 * Field names confirmed against Ventura's EaseAPI Positions docs:
 * symbol, token, last_traded_price, exchange, segment, action,
 * product_type, average_traded_price, total_quantity (SIGNED --
 * negative means a short/sell position), profit_loss, lot_size.
 */
function normalizePosition(raw) {
  const quantity = raw.total_quantity ?? null;
  return {
    raw,
    symbol: raw.symbol ?? "Unknown symbol",
    quantity,
    averagePrice: raw.average_traded_price ?? null,
    ltp: raw.last_traded_price ?? null,
    profitLoss: raw.profit_loss ?? null,
    // A short position (signed quantity < 0) needs a BUY to exit; a
    // long position (quantity > 0) needs a SELL. Both drawers show this
    // as an editable default, never a locked choice.
    exitTransactionType: quantity != null ? (quantity < 0 ? "B" : "S") : null,
  };
}

function PnL({ value }) {
  if (value === null || value === undefined) return <span className="muted">{"—"}</span>;
  const num = Number(value);
  const isPositive = num >= 0;
  return (
    <span className={`num ${isPositive ? "up" : "down"}`}>
      {isPositive ? "+" : ""}{num.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
    </span>
  );
}

export default function Positions({ openPositions: rawOpen, closedPositions: rawClosed, totalOpenPnl, loading, error, refetchPositions }) {
  const [stoplossTarget, setStoplossTarget] = useState(null);
  const [exitTarget, setExitTarget] = useState(null);

  const openPositions = (rawOpen || []).map(normalizePosition);
  const closedPositions = (rawClosed || []).map(normalizePosition);

  return (
    <div>
      <section className="panel pos-hero">
        <div>
          <p className="muted">Open profit and loss</p>
          <p className="pos-total" style={{ color: totalOpenPnl >= 0 ? "var(--up)" : "var(--down)" }}>
            {totalOpenPnl >= 0 ? "+" : "-"}₹{Math.abs(Math.round(totalOpenPnl)).toLocaleString("en-IN")}
            {openPositions.length > 0 && <span className="livetag"><i className="dot on" />Live</span>}
          </p>
        </div>
        <p className="muted small" style={{ maxWidth: "34ch" }}>Figures come from your broker and refresh every few seconds.</p>
      </section>

      {error && <div className="err" style={{ marginBottom: 16 }}>{error}</div>}

      {loading ? (
        <p className="muted small">Loading...</p>
      ) : (
        <>
          <h2 className="section-title">Open positions</h2>
          {openPositions.length === 0 ? (
            <div className="panel empty"><b>No open positions.</b>Orders you place show up here once they fill.</div>
          ) : (
            <div className="panel table-panel">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Stock</th><th className="r">Quantity</th><th className="r">Average price</th><th className="r">Price now</th><th className="r">Profit and loss</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {openPositions.map((p, i) => (
                    <tr key={i}>
                      <td>
                        <div className="cell">
                          <button type="button" className="icon-btn" style={{ marginRight: 8, flex: "none" }} onClick={() => openTradingViewChart(p.symbol)} title={`Open ${p.symbol} on TradingView`} aria-label={`Open ${p.symbol} chart on TradingView`}>
                            <ChartIcon />
                          </button>
                          <span className="sym">{p.symbol}</span>
                          {p.quantity < 0 && <span className="short">Short</span>}
                        </div>
                      </td>
                      <td className="r num">{p.quantity ?? "—"}</td>
                      <td className="r num">{p.averagePrice ?? "—"}</td>
                      <td className="r num">{p.ltp ?? "—"}</td>
                      <td className="r"><PnL value={p.profitLoss} /></td>
                      <td className="r">
                        <div className="act-row">
                          <button type="button" className="btn sm" onClick={() => setExitTarget(p)}>Exit</button>
                          <button type="button" className="btn sm" onClick={() => setStoplossTarget(p)}>Set stoploss</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h2 className="section-title" style={{ marginTop: 24 }}>Closed positions</h2>
          {closedPositions.length === 0 ? (
            <div className="panel empty"><b>No closed positions today.</b></div>
          ) : (
            <div className="panel table-panel">
              <table className="tbl">
                <thead>
                  <tr><th>Stock</th><th className="r">Quantity</th><th className="r">Average price</th><th className="r">Profit and loss</th></tr>
                </thead>
                <tbody>
                  {closedPositions.map((p, i) => (
                    <tr key={i}>
                      <td>
                        <div className="cell">
                          <button type="button" className="icon-btn" style={{ marginRight: 8, flex: "none" }} onClick={() => openTradingViewChart(p.symbol)} title={`Open ${p.symbol} on TradingView`} aria-label={`Open ${p.symbol} chart on TradingView`}>
                            <ChartIcon />
                          </button>
                          <span className="sym">{p.symbol}</span>
                        </div>
                      </td>
                      <td className="r num">{p.quantity ?? "—"}</td>
                      <td className="r num">{p.averagePrice ?? "—"}</td>
                      <td className="r"><PnL value={p.profitLoss} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {stoplossTarget && (
        <StoplossModal position={stoplossTarget} defaultTransactionType={stoplossTarget.exitTransactionType} onClose={() => setStoplossTarget(null)} onPlaced={refetchPositions} />
      )}
      {exitTarget && (
        <ExitPositionModal position={exitTarget} defaultTransactionType={exitTarget.exitTransactionType} onClose={() => setExitTarget(null)} onPlaced={refetchPositions} />
      )}
    </div>
  );
}
