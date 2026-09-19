import { logout } from "../api";
import ScreenerTable from "../components/ScreenerTable";

const STATUS_LABELS = {
  connecting: "Connecting",
  reconnecting: "Reconnecting",
};

function OpenPnlWidget({ totalOpenPnl, openPositionsCount, onClick }) {
  if (!openPositionsCount) return null;
  const isPositive = totalOpenPnl >= 0;
  return (
    <div style={styles.pnlWidget} onClick={onClick} title="Open positions P&L — click to view positions">
      <span style={styles.pnlLabel}>Open P&amp;L</span>
      <span className="mono" style={{ color: isPositive ? "var(--positive)" : "var(--negative)", fontWeight: 600 }}>
        {isPositive ? "+" : ""}{totalOpenPnl.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
      </span>
    </div>
  );
}

// Note: the live socket state and stockColors are owned by App.jsx,
// not this component — passed down as props — so they survive
// navigating between pages instead of resetting.
export default function Screener({
  clientId, onLoggedOut, onNavigateHistory, onNavigateWatchlist, onNavigateAlerts,
  onNavigateOrders, onNavigatePositions,
  rows, connectionStatus, flashRowId, stockColors, onWatchlistChanged,
  totalOpenPnl, openPositionsCount,
}) {
  async function handleLogout() {
    await logout();
    onLoggedOut();
  }

  const isConnected = connectionStatus === "connected";

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <div style={styles.headerLeft}>
          <span style={styles.dot(isConnected)} />
          {!isConnected && (
            <span style={styles.statusText}>{STATUS_LABELS[connectionStatus] || "Disconnected"}</span>
          )}
        </div>
        <nav style={styles.nav}>
          <span style={styles.navActive}>Live</span>
          <span style={styles.navLink} onClick={onNavigateHistory}>History</span>
          <span style={styles.navLink} onClick={onNavigateWatchlist}>Watchlist</span>
          <span style={styles.navLink} onClick={onNavigateAlerts}>Alerts</span>
          <span style={styles.navLink} onClick={onNavigateOrders}>Orders</span>
          <span style={styles.navLink} onClick={onNavigatePositions}>Positions</span>
        </nav>
        <div style={styles.headerRight}>
          <OpenPnlWidget totalOpenPnl={totalOpenPnl} openPositionsCount={openPositionsCount} onClick={onNavigatePositions} />
          <span style={styles.clientId}>{clientId}</span>
          <button onClick={handleLogout}>Sign out</button>
        </div>
      </header>

      <ScreenerTable
        rows={rows}
        flashRowId={flashRowId}
        emptyMessage="No stocks have triggered today yet."
        stockColors={stockColors}
        onWatchlistChanged={onWatchlistChanged}
      />
    </div>
  );
}

const styles = {
  page: { padding: "20px 24px", maxWidth: 1100, margin: "0 auto" },
  header: {
    display: "flex",
    alignItems: "center",
    gap: 16,
    marginBottom: 16,
    paddingBottom: 16,
    borderBottom: "1px solid var(--border)",
  },
  headerLeft: { display: "flex", alignItems: "center", gap: 8, minWidth: 20 },
  dot: (connected) => ({
    width: 8, height: 8, borderRadius: "50%",
    background: connected ? "var(--positive)" : "var(--negative)",
    display: "inline-block",
  }),
  statusText: { fontSize: 12, color: "var(--text-muted)" },
  nav: { display: "flex", gap: 16, fontSize: 13 },
  navActive: { color: "var(--text)", fontWeight: 500, borderBottom: "2px solid var(--focus)", paddingBottom: 2 },
  navLink: { color: "var(--text-muted)", cursor: "pointer", paddingBottom: 2 },
  headerRight: { display: "flex", alignItems: "center", gap: 14, marginLeft: "auto" },
  clientId: { fontSize: 12, color: "var(--text-muted)" },
  pnlWidget: {
    display: "flex", alignItems: "center", gap: 6, cursor: "pointer",
    background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6,
    padding: "5px 10px", fontSize: 12,
  },
  pnlLabel: { color: "var(--text-muted)" },
};
