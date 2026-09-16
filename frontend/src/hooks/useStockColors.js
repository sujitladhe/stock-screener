import { useState, useEffect, useCallback } from "react";
import { getStockColors } from "../api";

/**
 * Fetches {trading_symbol: colorHex} for the CURRENT user across all
 * their watchlists — used to tint screener rows. Replaces the earlier
 * "leg" system entirely: a stock now belongs to at most one watchlist,
 * and takes that watchlist's color, so there's no ambiguity about
 * which color should win.
 *
 * Exposes a refetch function so the screener can refresh colors right
 * after a stock is added/removed via the watchlist modal or page,
 * without waiting for a full reload.
 */
export function useStockColors(enabled = true) {
  const [stockColors, setStockColors] = useState({});

  const refetch = useCallback(() => {
    if (!enabled) return;
    getStockColors().then(setStockColors).catch(() => {});
  }, [enabled]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { stockColors, refetchStockColors: refetch };
}
