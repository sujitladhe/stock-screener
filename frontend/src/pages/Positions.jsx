import { useState } from "react";
import StoplossModal from "../components/StoplossModal";

/**
 * Field names confirmed against Ventura's EaseAPI Positions docs:
 * symbol, token, last_traded_price, exchange, segment, action,
 * product_type, average_traded_price, total_quantity (SIGNED --
 * negative means a short/sell position, positive means long/buy),
 * profit_loss, lot_size. F&O-only fields (instrument_type,
 * expiry_date, expiry_type, option_type, strike_price) are ignored
 * here since this app only trades equity.
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
    productType: raw.product_type ?? null,
    // A short position (signed quantity < 0) needs a BUY to exit; a
    // long position (quantity > 0) needs a SELL. This is derived with
    // confidence from the confirmed, signed total_quantity field --
    // StoplossModal still shows it as an editable default rather than
    // locking it, so a mistaken read never becomes unchangeable.
    exitTransactionType: quantity != null ? (quantity < 0 ? "B" : "S") : null,
  };
}

function PnL({ value }) {
  if (value === null || value === undefined) return <span style={{ color: "var(--text-muted)" }}>{"\u2014"}</span>;
  const num = Number(value);
  const isPositive = num >= 0;
  return (
    <span style={{ color: isPositive ? "var(--positive)" : "var(--negative)" }} className="mono">
      {isPositive ? "+" : ""}{num.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
    </span>
  );
}

export default function Positions({ onNavigateLive, openPositions: rawOpen, closedPositions: rawClosed, totalOpenPnl, loading, error, refetchPositions }) {
  const [stoplossTarget, setStoplossTarget] = useState(null);

  const openPositions = (rawOpen || []).map(normalizePosition);
  const closedPositions = (rawClosed || []).map(normalizePosition);

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <nav style={styles.nav}>
          <span style={styles.navLink} onClick={onNavigateLive}>Live</span>
          <span style={styles.navActive}>Positions</span>
        </nav>
        {openPositions.length > 0 && (
          <div style={styles.totalPnl}>
            Open P&amp;L: <PnL value={totalOpenPnl} />
            <span style={styles.liveTag}>live</span>
          </div>
        )}
      </header>

      {error && <div style={styles.error}>{error}</div>}

      {loading ? (
        <p style={styles.muted}>Loading...</p>
      ) : (
        <>
          <div style={styles.sectionTitle}>Open positions</div>
          {openPositions.length === 0 ? (
            <p style={styles.muted}>No open positions.</p>
          ) : (
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>Symbol</th>
                  <th style={styles.thRight}>Qty</th>
                  <th style={styles.thRight}>Avg price</th>
                  <th style={styles.thRight}>LTP</th>
                  <th style={styles.thRight}>P&amp;L</th>
                  <th style={styles.th}></th>
                </tr>
              </thead>
              <tbody>
                {openPositions.map((p, i) => (
                  <tr key={i}>
                    <td style={styles.tdLeft}>
                      {p.symbol}
                      {p.quantity < 0 && <span style={styles.shortTag}>Short</span>}
                    </td>
                    <td style={styles.tdRight} className="mono">{p.quantity ?? "—"}</td>
                    <td style={styles.tdRight} className="mono">{p.averagePrice ?? "—"}</td>
                    <td style={styles.tdRight} className="mono">{p.ltp ?? "—"}</td>
                    <td style={styles.tdRight}><PnL value={p.profitLoss} /></td>
                    <td style={styles.tdRight}>
                      <button style={styles.smallBtn} onClick={() => setStoplossTarget(p)}>Set stoploss</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div style={{ ...styles.sectionTitle, marginTop: 24 }}>Closed positions</div>
          {closedPositions.length === 0 ? (
            <p style={styles.muted}>No closed positions today.</p>
          ) : (
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>Symbol</th>
                  <th style={styles.thRight}>Qty</th>
                  <th style={styles.thRight}>Avg price</th>
                  <th style={styles.thRight}>P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {closedPositions.map((p, i) => (
                  <tr key={i}>
                    <td style={styles.tdLeft}>{p.symbol}</td>
                    <td style={styles.tdRight} className="mono">{p.quantity ?? "—"}</td>
                    <td style={styles.tdRight} className="mono">{p.averagePrice ?? "—"}</td>
                    <td style={styles.tdRight}><PnL value={p.profitLoss} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {stoplossTarget && (
        <StoplossModal
          position={stoplossTarget}
          defaultTransactionType={stoplossTarget.exitTransactionType}
          onClose={() => setStoplossTarget(null)}
          onPlaced={refetchPositions}
        />
      )}
    </div>
  );
}

const styles = {
  page: { padding: "20px 24px", maxWidth: 1100, margin: "0 auto" },
  header: {
    display: "flex", alignItems: "center", gap: 16, marginBottom: 20,
    paddingBottom: 16, borderBottom: "1px solid var(--border)",
  },
  nav: { display: "flex", gap: 16, fontSize: 13 },
  navActive: { color: "var(--text)", fontWeight: 500, borderBottom: "2px solid var(--focus)", paddingBottom: 2 },
  navLink: { color: "var(--text-muted)", cursor: "pointer", paddingBottom: 2 },
  totalPnl: { marginLeft: "auto", fontSize: 13, display: "flex", alignItems: "center", gap: 6 },
  liveTag: {
    fontSize: 9, color: "var(--positive)", border: "1px solid var(--positive)",
    borderRadius: 4, padding: "1px 4px", textTransform: "uppercase", letterSpacing: "0.03em",
  },
  sectionTitle: { fontSize: 13, fontWeight: 600, marginBottom: 10 },
  error: {
    fontSize: 12, color: "var(--negative)", background: "rgba(255, 92, 92, 0.1)",
    border: "1px solid rgba(255, 92, 92, 0.3)", borderRadius: 6, padding: "8px 12px", marginBottom: 16,
  },
  muted: { color: "var(--text-muted)", fontSize: 13, marginBottom: 12 },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13, marginBottom: 12 },
  th: { textAlign: "left", padding: "8px 10px", borderBottom: "1px solid var(--border)", fontWeight: 500, color: "var(--text-muted)" },
  thRight: { textAlign: "right", padding: "8px 10px", borderBottom: "1px solid var(--border)", fontWeight: 500, color: "var(--text-muted)" },
  tdLeft: { textAlign: "left", padding: "9px 10px", borderBottom: "1px solid var(--border)" },
  tdRight: { textAlign: "right", padding: "9px 10px", borderBottom: "1px solid var(--border)" },
  shortTag: {
    fontSize: 10, color: "var(--accent-strict)", border: "1px solid var(--accent-strict)",
    borderRadius: 4, padding: "1px 5px", marginLeft: 8,
  },
  smallBtn: { fontSize: 11, padding: "5px 9px" },
};
