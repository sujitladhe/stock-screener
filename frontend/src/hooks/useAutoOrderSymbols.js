import { useState, useEffect, useCallback, useRef } from "react";
import { getOrders } from "../api";

const POLL_INTERVAL_MS = 30_000;

/**
 * Returns a Set of trading symbols that have at least one Active auto order.
 * Used by the Live screener to show an "Auto" tag on matching rows, and by
 * PlaceOrderModal to warn (and disable submit) when a duplicate would be created.
 *
 * Polls every 30 seconds and refreshes immediately after an order is placed or
 * cancelled (via the refetch() callback passed to relevant components).
 */
export function useAutoOrderSymbols(enabled = true) {
  const [autoOrderSymbols, setAutoOrderSymbols] = useState(new Set());
  const intervalRef = useRef(null);

  const refetch = useCallback(() => {
    if (!enabled) return;
    getOrders("auto")
      .then((orders) => {
        const active = orders.filter((o) => o.status === "Active");
        setAutoOrderSymbols(new Set(active.map((o) => o.trading_symbol)));
      })
      .catch(() => {});
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    refetch();
    intervalRef.current = setInterval(refetch, POLL_INTERVAL_MS);
    return () => clearInterval(intervalRef.current);
  }, [enabled, refetch]);

  return { autoOrderSymbols, refetchAutoOrders: refetch };
}
