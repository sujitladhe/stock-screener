import { useState, useEffect, useRef, useCallback } from "react";
import { openScreenerSocket, getTodayScreener } from "../api";

const MAX_LIVE_ROWS = 500;

/**
 * Manages the screener's live data AND routes personal alert
 * notifications (requirement 9) -- both travel over the SAME
 * WebSocket connection now, distinguished by a "type" field the
 * backend adds ("screener_alert" vs "user_alert"). Screener messages
 * update `rows` as before; user_alert messages are handed to the
 * onUserAlert callback instead, so App.jsx can show a browser
 * notification + play a sound regardless of which page is showing.
 *
 * enabled: pass false to keep this fully inert (no fetch, no socket)
 * -- used so the connection doesn't open before the user is logged in.
 */
export function useScreenerSocket(enabled = true, onUserAlert = null) {
  const [rows, setRows] = useState([]);
  const [connectionStatus, setConnectionStatus] = useState("connecting");
  const [flashRowId, setFlashRowId] = useState(null);
  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const hasConnectedOnceRef = useRef(false);
  const onUserAlertRef = useRef(onUserAlert);
  onUserAlertRef.current = onUserAlert;

  const addOccurrence = useCallback((newRow) => {
    setRows((prev) => {
      const updated = [newRow, ...prev];
      return updated.length > MAX_LIVE_ROWS ? updated.slice(0, MAX_LIVE_ROWS) : updated;
    });
    setFlashRowId(rowId(newRow));
  }, []);

  const connect = useCallback(() => {
    const ws = openScreenerSocket();
    wsRef.current = ws;

    ws.onopen = () => {
      hasConnectedOnceRef.current = true;
      setConnectionStatus("connected");
    };
    ws.onclose = () => {
      setConnectionStatus(hasConnectedOnceRef.current ? "reconnecting" : "connecting");
      reconnectTimerRef.current = setTimeout(connect, 3000);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "user_alert") {
        if (onUserAlertRef.current) onUserAlertRef.current(message);
      } else {
        addOccurrence(message);
      }
    };
  }, [addOccurrence]);

  useEffect(() => {
    if (!enabled) return;
    getTodayScreener().then(setRows).catch(() => {});
    connect();
    return () => {
      clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, [enabled, connect]);

  return { rows, connectionStatus, connected: connectionStatus === "connected", flashRowId };
}

/**
 * A stable identifier for one occurrence row -- exported so
 * ScreenerTable can compute the same id for rows that came from the
 * initial REST load and match flashRowId consistently either way.
 */
export function rowId(row) {
  return `${row.trading_symbol}__${row.last_triggered_at}`;
}
