import { useState, useEffect, useCallback, useRef } from "react";
import Login from "./pages/Login";
import Screener from "./pages/Screener";
import History from "./pages/History";
import Watchlist from "./pages/Watchlist";
import Alerts from "./pages/Alerts";
import Orders from "./pages/Orders";
import Positions from "./pages/Positions";
import ToastStack from "./components/ToastStack";
import { getCurrentSession } from "./api";
import { useScreenerSocket } from "./hooks/useScreenerSocket";
import { useStockColors } from "./hooks/useStockColors";
import { usePositions } from "./hooks/usePositions";
import { showAlertNotification, showBrowserNotification } from "./browserNotify";
import { playAlertSound } from "./soundAlert";
import { showToast } from "./toast";

export default function App() {
  const [clientId, setClientId] = useState(undefined); // undefined = still checking, null = logged out
  const [view, setView] = useState("screener"); // "screener" | "history" | "watchlist" | "alerts" | "orders" | "positions"
  // Incremented every time a user_alert arrives — Alerts.jsx watches
  // this to know when to refetch history, even if it's not the
  // currently visible page when the alert fires.
  const [alertRefreshSignal, setAlertRefreshSignal] = useState(0);
  // Same idea for auto trade (requirement 10): incremented whenever an
  // auto order fires (placed OR failed), so the Orders page reloads its
  // list live instead of only on manual refresh.
  const [ordersRefreshSignal, setOrdersRefreshSignal] = useState(0);
  // usePositions is called further down (it needs clientId), but the
  // auto-trade handler above it needs to trigger a positions refetch —
  // a ref bridges the two without reordering the hooks.
  const refetchPositionsRef = useRef(null);

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

  // An AUTO order fired (requirement 10e): tell the user whether it was
  // placed or failed, on whichever page they're looking at. Note
  // "success" means the broker ACCEPTED the order — whether it then
  // executes shows up in the Orders page status and, once filled, as a
  // position (which we refetch below so it appears with live P&L).
  const handleAutoTrade = useCallback((msg) => {
    const side = msg.transaction_type === "B" ? "Buy" : "Sell";
    const ok = msg.outcome === "success";

    const text = ok
      ? `Auto ${side} order placed: ${msg.quantity} x ${msg.trading_symbol}` +
        (msg.broker_order_no ? ` (order #${msg.broker_order_no})` : "") +
        (msg.trigger_details ? `. ${msg.trigger_details}` : "")
      : `Auto order for ${msg.trading_symbol} FAILED: ${msg.message || "unknown error"}`;

    showToast(text, ok ? "success" : "error");
    showBrowserNotification({
      title: ok ? `Auto order placed: ${msg.trading_symbol}` : `Auto order FAILED: ${msg.trading_symbol}`,
      body: text,
      tag: `auto-trade-${msg.order_id}`,
    });
    playAlertSound();

    setOrdersRefreshSignal((n) => n + 1);

    if (ok) {
      // A market order usually fills within a second or two; refetch
      // now and again shortly after so the new position shows up
      // without waiting for the next 10-second poll.
      const refetch = () => refetchPositionsRef.current && refetchPositionsRef.current();
      refetch();
      setTimeout(refetch, 3000);
    }
  }, []);

  // Owned here (not inside individual pages) so the WebSocket
  // connection survives navigating between pages instead of
  // disconnecting/reconnecting every time.
  const { rows, connectionStatus, flashRowId } = useScreenerSocket(!!clientId, handleUserAlert, handleAutoTrade);
  const { stockColors, refetchStockColors } = useStockColors(!!clientId);
  // Lifted here (not inside Positions.jsx) so the Screener page's
  // Open P&L widget and the Positions page itself share the SAME
  // polling interval and data, instead of each page opening its own
  // independent poll against the broker.
  const { openPositions, closedPositions, totalOpenPnl, loading: positionsLoading, error: positionsError, refetchPositions } = usePositions(!!clientId);
  refetchPositionsRef.current = refetchPositions;

  if (clientId === undefined) {
    return <div style={{ padding: 24, color: "var(--text-muted)" }}>Loading...</div>;
  }

  if (!clientId) {
    return (
      <>
        <Login onLoggedIn={setClientId} />
        <ToastStack />
      </>
    );
  }

  let page;

  if (view === "history") {
    page = (
      <History
        onNavigateLive={() => setView("screener")}
        stockColors={stockColors}
        onWatchlistChanged={refetchStockColors}
      />
    );
  } else if (view === "watchlist") {
    page = <Watchlist onNavigateLive={() => setView("screener")} onChanged={refetchStockColors} />;
  } else if (view === "alerts") {
    page = (
      <Alerts
        onNavigateLive={() => setView("screener")}
        refreshSignal={alertRefreshSignal}
      />
    );
  } else if (view === "orders") {
    page = (
      <Orders
        onNavigateLive={() => setView("screener")}
        refreshSignal={ordersRefreshSignal}
      />
    );
  } else if (view === "positions") {
    page = (
      <Positions
        onNavigateLive={() => setView("screener")}
        openPositions={openPositions}
        closedPositions={closedPositions}
        totalOpenPnl={totalOpenPnl}
        loading={positionsLoading}
        error={positionsError}
        refetchPositions={refetchPositions}
      />
    );
  } else {
    page = (
      <Screener
        clientId={clientId}
        onLoggedOut={() => setClientId(null)}
        onNavigateHistory={() => setView("history")}
        onNavigateWatchlist={() => setView("watchlist")}
        onNavigateAlerts={() => setView("alerts")}
        onNavigateOrders={() => setView("orders")}
        onNavigatePositions={() => setView("positions")}
        rows={rows}
        connectionStatus={connectionStatus}
        flashRowId={flashRowId}
        stockColors={stockColors}
        onWatchlistChanged={refetchStockColors}
        totalOpenPnl={totalOpenPnl}
        openPositionsCount={openPositions.length}
      />
    );
  }

  return (
    <>
      {page}
      <ToastStack />
    </>
  );
}
