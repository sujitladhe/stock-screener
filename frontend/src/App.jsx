import { useState, useEffect, useCallback, useRef } from "react";
import Login from "./pages/Login";
import Screener from "./pages/Screener";
import History from "./pages/History";
import Watchlist from "./pages/Watchlist";
import Alerts from "./pages/Alerts";
import Orders from "./pages/Orders";
import Positions from "./pages/Positions";
import Settings from "./pages/Settings";
import ToastStack from "./components/ToastStack";
import { getCurrentSession, logout } from "./api";
import { useScreenerSocket } from "./hooks/useScreenerSocket";
import { useStockColors } from "./hooks/useStockColors";
import { usePositions } from "./hooks/usePositions";
import { useSettings } from "./hooks/useSettings";
import { useDropdownMenu } from "./hooks/useDropdownMenu";
import { showAlertNotification, showBrowserNotification } from "./browserNotify";
import { playAlertSound } from "./soundAlert";
import { showToast } from "./toast";
import { NAV_ICONS, SunIcon, MoonIcon } from "./icons";

const NAV = [
  ["live", "Live"],
  ["orders", "Orders"],
  ["positions", "Positions"],
  ["watchlists", "Watchlists"],
  ["alerts", "Alerts"],
  ["history", "History"],
  ["settings", "Settings"],
];

function BrandMark() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
      <rect width="28" height="28" rx="8" fill="var(--text)" />
      <rect x="6" y="15" width="3.6" height="7" rx="1.2" fill="var(--ground)" />
      <rect x="12.2" y="11" width="3.6" height="11" rx="1.2" fill="var(--ground)" />
      <rect x="18.4" y="6" width="3.6" height="16" rx="1.2" fill="var(--mari)" />
    </svg>
  );
}

export default function App() {
  const [clientId, setClientId] = useState(undefined); // undefined = still checking, null = logged out
  const [view, setView] = useState("live");
  const [alertRefreshSignal, setAlertRefreshSignal] = useState(0);
  const [ordersRefreshSignal, setOrdersRefreshSignal] = useState(0);
  const [autoActiveCount, setAutoActiveCount] = useState(0);
  const refetchPositionsRef = useRef(null);

  const { settings, update: updateSettings, toggleTheme } = useSettings();
  const { open: openAccountMenu, menu: accountMenu } = useDropdownMenu();

  useEffect(() => {
    getCurrentSession()
      .then((session) => setClientId(session ? session.client_id : null))
      .catch(() => setClientId(null));
  }, []);

  const handleUserAlert = useCallback((alert) => {
    showAlertNotification(alert);
    if (alert.sound_enabled) playAlertSound();
    setAlertRefreshSignal((n) => n + 1);
  }, []);

  const handleAutoTrade = useCallback((msg) => {
    const side = msg.transaction_type === "B" ? "Buy" : "Sell";
    const ok = msg.outcome === "success";
    const text = ok
      ? `Auto ${side} order placed: ${msg.quantity} × ${msg.trading_symbol}` +
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
      const refetch = () => refetchPositionsRef.current && refetchPositionsRef.current();
      refetch();
      setTimeout(refetch, 3000);
    }
  }, []);

  const { rows, connectionStatus, flashRowId } = useScreenerSocket(!!clientId, handleUserAlert, handleAutoTrade);
  const { stockColors, refetchStockColors } = useStockColors(!!clientId);
  const { openPositions, closedPositions, totalOpenPnl, loading: positionsLoading, error: positionsError, refetchPositions } = usePositions(!!clientId);
  refetchPositionsRef.current = refetchPositions;

  async function handleLogout() {
    await logout();
    setClientId(null);
  }

  if (clientId === undefined) {
    return <div style={{ padding: 24, color: "var(--muted)" }}>Loading...</div>;
  }

  if (!clientId) {
    return (
      <>
        <Login onLoggedIn={setClientId} />
        <ToastStack />
      </>
    );
  }

  const badges = {
    orders: autoActiveCount,
    positions: openPositions.length,
  };

  let page;
  if (view === "history") {
    page = <History stockColors={stockColors} onWatchlistChanged={refetchStockColors} onNavigateWatchlists={() => setView("watchlists")} settings={settings} />;
  } else if (view === "watchlists") {
    page = <Watchlist onChanged={refetchStockColors} settings={settings} />;
  } else if (view === "alerts") {
    page = <Alerts refreshSignal={alertRefreshSignal} />;
  } else if (view === "orders") {
    page = <Orders refreshSignal={ordersRefreshSignal} settings={settings} onAutoActiveCountChange={setAutoActiveCount} />;
  } else if (view === "positions") {
    page = (
      <Positions
        openPositions={openPositions}
        closedPositions={closedPositions}
        totalOpenPnl={totalOpenPnl}
        loading={positionsLoading}
        error={positionsError}
        refetchPositions={refetchPositions}
      />
    );
  } else if (view === "settings") {
    page = <Settings settings={settings} onChange={updateSettings} />;
  } else {
    page = (
      <Screener
        rows={rows}
        flashRowId={flashRowId}
        stockColors={stockColors}
        onWatchlistChanged={refetchStockColors}
        onNavigateWatchlists={() => setView("watchlists")}
        settings={settings}
      />
    );
  }

  const dark = settings.theme === "dark" || (settings.theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const pageTitle = NAV.find(([k]) => k === view)?.[1] || "Live";

  return (
    <div className="app">
      <aside className="rail" aria-label="Main">
        <button type="button" className="brand" onClick={() => setView("live")} aria-label="Screener home">
          <BrandMark />Screener
        </button>
        <nav className="nav">
          {NAV.map(([key, label]) => {
            const Icon = NAV_ICONS[key];
            const badge = badges[key];
            return (
              <button
                type="button"
                key={key}
                className={`navlink${view === key ? " active" : ""}`}
                aria-current={view === key ? "page" : undefined}
                onClick={() => setView(key)}
              >
                <Icon size={20} />
                <span>{label}</span>
                {!!badge && <span className="count" title={key === "orders" ? "Auto orders waiting to trigger" : "Open positions"}>{badge}</span>}
              </button>
            );
          })}
        </nav>
      </aside>

      <div className="main">
        <header className="topbar">
          <h1>{pageTitle}</h1>
          <span className="chip" title="Live data connection">
            <i className={`dot${connectionStatus === "connected" ? " on" : ""}`} /><span className="lbl-hide">{connectionStatus === "connected" ? "Connected" : connectionStatus === "reconnecting" ? "Reconnecting" : "Connecting"}</span>
          </span>
          {openPositions.length > 0 && (
            <button type="button" className="chip" onClick={() => setView("positions")} title="Open positions profit and loss">
              <span className="muted lbl-hide">Open P&amp;L</span>
              <b className="num" style={{ color: totalOpenPnl >= 0 ? "var(--up)" : "var(--down)" }}>
                {totalOpenPnl >= 0 ? "+" : "-"}₹{Math.abs(Math.round(totalOpenPnl)).toLocaleString("en-IN")}
              </b>
            </button>
          )}
          <button type="button" className="icon-btn bordered" onClick={toggleTheme} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>
            {dark ? <SunIcon size={17} /> : <MoonIcon size={17} />}
          </button>
          <button
            type="button"
            className="chip"
            aria-haspopup="menu"
            onClick={(e) => openAccountMenu(e, [{ label: "Sign out", onClick: handleLogout }])}
          >
            {clientId}
          </button>
        </header>
        <main className="content">{page}</main>
      </div>

      {accountMenu}
      <ToastStack />
    </div>
  );
}
