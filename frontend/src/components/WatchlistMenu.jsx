import { useEffect, useRef, useState } from "react";
import { getWatchlists, addStockToWatchlist, removeStockFromWatchlist } from "../api";
import { showToast } from "../toast";

/**
 * Replaces the old full-screen "Add to watchlist" modal with a small
 * anchored menu (like the account menu), opened from the pip or the
 * bookmark icon on a Live row: pick a different watchlist to move the
 * stock there (the server handles the move -- a stock is only ever in
 * one watchlist), or remove it from the one it's currently in.
 *
 * Usage: const { open, menu } = useWatchlistMenu(refetchStockColors, onNavigateWatchlists);
 *        <button onClick={(e) => open(e, symbol)}>...</button>
 *        {menu}
 */
export function useWatchlistMenu(onChanged, onNavigateWatchlists) {
  const [state, setState] = useState(null); // {rect, symbol, loading, lists, current}
  const ref = useRef(null);

  async function open(e, symbol) {
    const rect = e.currentTarget.getBoundingClientRect();
    setState({ rect, symbol, loading: true, lists: [], current: null });
    try {
      const lists = await getWatchlists();
      let current = null;
      for (const l of lists) {
        const stock = l.stocks.find((s) => s.trading_symbol === symbol);
        if (stock) {
          current = { listId: l.id, stockId: stock.id, listName: l.name };
          break;
        }
      }
      setState((prev) => (prev && prev.symbol === symbol ? { ...prev, loading: false, lists, current } : prev));
    } catch {
      setState((prev) => (prev && prev.symbol === symbol ? { ...prev, loading: false, lists: [], current: null } : prev));
    }
  }
  function close() {
    setState(null);
  }

  useEffect(() => {
    if (!state) return;
    function onDown(e) {
      if (ref.current && !ref.current.contains(e.target)) close();
    }
    function onKey(e) {
      if (e.key === "Escape") close();
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [state]);

  async function pick(listId, listName) {
    const { symbol, current } = state;
    close();
    if (current?.listId === listId) return;
    try {
      await addStockToWatchlist(listId, symbol);
      showToast(current ? `${symbol} moved from ${current.listName} to ${listName}.` : `${symbol} added to ${listName}.`);
      onChanged && onChanged();
    } catch (err) {
      showToast(`Could not update watchlist: ${err.message}`, "error");
    }
  }

  async function remove() {
    const { symbol, current } = state;
    close();
    try {
      await removeStockFromWatchlist(current.listId, current.stockId);
      showToast(`${symbol} removed from ${current.listName}.`);
      onChanged && onChanged();
    } catch (err) {
      showToast(`Could not remove from watchlist: ${err.message}`, "error");
    }
  }

  const menu = state ? (
    <div
      ref={ref}
      className="menu"
      role="menu"
      style={{
        position: "fixed",
        top: Math.min(window.innerHeight - 8, state.rect.bottom + 6),
        // Anchored to the trigger's LEFT edge, not its right -- the
        // trigger here is often a small icon (the pip), and anchoring
        // from its right edge would push a 200px-wide menu mostly
        // behind/left of it instead of visually under it.
        left: Math.max(8, Math.min(window.innerWidth - 208, state.rect.left)),
      }}
    >
      {state.loading ? (
        <div style={{ padding: "10px 12px", fontSize: 13, color: "var(--muted)" }}>Loading...</div>
      ) : state.lists.length === 0 ? (
        <button
          type="button"
          role="menuitem"
          onClick={() => {
            close();
            onNavigateWatchlists && onNavigateWatchlists();
          }}
        >
          Create a watchlist first
        </button>
      ) : (
        <>
          {state.lists.map((l) => (
            <button type="button" role="menuitem" key={l.id} onClick={() => pick(l.id, l.name)}>
              <i className="swdot" style={{ background: l.color }} />
              <span>{l.name}</span>
              {state.current?.listId === l.id && <span className="tick">✓</span>}
            </button>
          ))}
          {state.current && (
            <button type="button" role="menuitem" onClick={remove}>
              Remove from watchlist
            </button>
          )}
        </>
      )}
    </div>
  ) : null;

  return { open, close, menu };
}
