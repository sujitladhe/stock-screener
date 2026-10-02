import { useState, useEffect, useCallback, useRef } from "react";
import { getPositions } from "../api";

const POLL_INTERVAL_MS = 10000;

/**
 * Polls positions periodically rather than recomputing P&L from live
 * ticks ourselves -- per ventura_trading.get_positions's own
 * docstring, the broker's P&L figure is authoritative and this app
 * deliberately avoids building a parallel from-scratch P&L engine.
 * "Live" here means frequently refreshed from the broker's own
 * numbers, not client-side derived.
 *
 * enabled: pass false to stay fully inert (no polling) -- used so
 * this doesn't start before the user is logged in, same pattern as
 * useScreenerSocket/useStockColors.
 */
export function usePositions(enabled = true) {
  const [openPositions, setOpenPositions] = useState([]);
  const [closedPositions, setClosedPositions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);

  const refetch = useCallback(() => {
    if (!enabled) return;
    getPositions()
      .then((data) => {
        setOpenPositions(data.open_positions || []);
        setClosedPositions(data.closed_positions || []);
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    refetch();
    intervalRef.current = setInterval(refetch, POLL_INTERVAL_MS);
    return () => clearInterval(intervalRef.current);
  }, [enabled, refetch]);

  const totalOpenPnl = openPositions.reduce((sum, p) => sum + (Number(p.profit_loss) || 0), 0);

  return { openPositions, closedPositions, totalOpenPnl, loading, error, refetchPositions: refetch };
}
