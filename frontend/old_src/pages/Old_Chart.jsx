import TradingViewChart from "../components/TradingViewChart";
import ScreenerTable from "../components/ScreenerTable";

export default function Chart({ symbol, rows, flashSymbol, onBack, onRowClick }) {
  const stockRow = rows.find((r) => r.trading_symbol === symbol);

  return (
    <div style={styles.page}>
      <div style={styles.crumb}>
        <span style={styles.back} onClick={onBack}>&larr; Back to screener</span>
      </div>

      <div style={styles.stockHead}>
        <span style={styles.sym} className="mono">{symbol}</span>
        {stockRow && (
          <>
            <span className="mono">{"\u20b9"}{stockRow.ltp}</span>
            <span style={styles.muted}>{stockRow.multiple.toFixed(1)}x avg volume</span>
          </>
        )}
      </div>

      <div style={styles.chartWrap}>
        <TradingViewChart key={symbol} symbol={symbol} />
      </div>

      <div style={styles.dock}>
        <div style={styles.dockHead}>Screener — live, docked while charting</div>
        <div style={styles.dockBody}>
          <ScreenerTable
            rows={rows}
            flashSymbol={flashSymbol}
            emptyMessage="No stocks have triggered today yet."
            onRowClick={onRowClick}
          />
        </div>
      </div>
    </div>
  );
}

const styles = {
  page: { padding: "16px 24px", display: "flex", flexDirection: "column", height: "100vh", boxSizing: "border-box" },
  crumb: { fontSize: 12, marginBottom: 8, flexShrink: 0 },
  back: { color: "var(--focus)", cursor: "pointer" },
  stockHead: { display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12, flexShrink: 0 },
  sym: { fontSize: 18, fontWeight: 600 },
  muted: { fontSize: 12, color: "var(--text-muted)" },
  chartWrap: {
    flex: 1,
    minHeight: 300,
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: 8,
    overflow: "hidden",
    marginBottom: 12,
  },
  dock: {
    height: 240,
    flexShrink: 0,
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: 8,
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  dockHead: {
    padding: "8px 12px",
    borderBottom: "1px solid var(--border)",
    fontSize: 11,
    color: "var(--text-muted)",
    textTransform: "uppercase",
    letterSpacing: "0.03em",
    flexShrink: 0,
  },
  dockBody: { flex: 1, overflowY: "auto", padding: "8px 12px" },
};
