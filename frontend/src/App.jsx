import { useState, useEffect, useCallback } from "react";
import Login from "./pages/Login";
import Screener from "./pages/Screener";
import History from "./pages/History";
import Watchlist from "./pages/Watchlist";
import Alerts from "./pages/Alerts";
import { getCurrentSession } from "./api";
import { useScreenerSocket } from "./hooks/useScreenerSocket";
import { useStockColors } from "./hooks/useStockColors";
import { showAlertNotification } from "./browserNotify";
import { playAlertSound } from "./soundAlert";

export default function App() {
  const [clientId, setClientId] = useState(undefined); // undefined = still checking, null = logged out
  const [view, setView] = useState("screener"); // "screener" | "history" | "watchlist" | "alerts"
  // Incremented every time a user_alert arrives — Alerts.jsx watches
  // this to know when to refetch history, even if it's not the
  // currently visible page when the alert fires.
  const [alertRefreshSignal, setAlertRefreshSignal] = useState(0);

  useEffect(() => {
    getCurrentSession()
      .then((session) => setClientId(session ? session.client_id : null))
      .catch(() => setClientId(null));
  }, []);

  // Fires regardless of which page is currently showing — a personal
  // alert should notify the user even if they're looking at History
  // or Watchlist, not just the Live screener page.
  const handleUserAlert = useCallback((alert) => {
    showAlertNotification(alert);
    if (alert.sound_enabled) {
      playAlertSound();
    }
    setAlertRefreshSignal((n) => n + 1);
  }, []);

  // Owned here (not inside individual pages) so the WebSocket
  // connection survives navigating between pages instead of
  // disconnecting/reconnecting every time.
  const { rows, connectionStatus, flashRowId } = useScreenerSocket(!!clientId, handleUserAlert);
  const { stockColors, refetchStockColors } = useStockColors(!!clientId);

  if (clientId === undefined) {
    return <div style={{ padding: 24, color: "var(--text-muted)" }}>Loading...</div>;
  }

  if (!clientId) {
    return <Login onLoggedIn={setClientId} />;
  }

  if (view === "history") {
    return (
      <History
        onNavigateLive={() => setView("screener")}
        stockColors={stockColors}
        onWatchlistChanged={refetchStockColors}
      />
    );
  }

  if (view === "watchlist") {
    return <Watchlist onNavigateLive={() => setView("screener")} onChanged={refetchStockColors} />;
  }

  if (view === "alerts") {
    return (
      <Alerts
        onNavigateLive={() => setView("screener")}
        refreshSignal={alertRefreshSignal}
      />
    );
  }

  return (
    <Screener
      clientId={clientId}
      onLoggedOut={() => setClientId(null)}
      onNavigateHistory={() => setView("history")}
      onNavigateWatchlist={() => setView("watchlist")}
      onNavigateAlerts={() => setView("alerts")}
      rows={rows}
      connectionStatus={connectionStatus}
      flashRowId={flashRowId}
      stockColors={stockColors}
      onWatchlistChanged={refetchStockColors}
    />
  );
}
