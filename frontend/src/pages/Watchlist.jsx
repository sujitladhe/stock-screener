import { useState, useEffect, useRef } from "react";
import {
  getWatchlists,
  createWatchlist,
  deleteWatchlist,
  addStockToWatchlist,
  removeStockFromWatchlist,
  searchInstruments,
} from "../api";

const COLOR_CHOICES = ["#f5c400", "#3dd68c", "#5b8cff", "#ff6b5b", "#c084fc", "#f5a623"];

function openTradingViewChart(symbol) {
  const url = `https://www.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(symbol)}`;
  window.open(url, "_blank", "noopener,noreferrer");
}

function ExternalLinkIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  );
}

export default function Watchlist({ onNavigateLive, onChanged }) {
  const [watchlists, setWatchlists] = useState([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState(COLOR_CHOICES[0]);
  const [error, setError] = useState(null);
  const [collapsedIds, setCollapsedIds] = useState(new Set());

  function reload() {
    setLoading(true);
    getWatchlists()
      .then(setWatchlists)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(reload, []);

  function toggleCollapsed(watchlistId) {
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      if (next.has(watchlistId)) next.delete(watchlistId);
      else next.add(watchlistId);
      return next;
    });
  }

  async function handleCreate(e) {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;
    try {
      await createWatchlist(name, newColor);
      setNewName("");
      reload();
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleDelete(watchlistId) {
    if (!window.confirm("Delete this watchlist and all its stocks?")) return;
    await deleteWatchlist(watchlistId);
    reload();
    if (onChanged) onChanged();
  }

  async function handleAddStock(watchlistId, symbol) {
    await addStockToWatchlist(watchlistId, symbol);
    reload();
    if (onChanged) onChanged();
  }

  async function handleRemoveStock(watchlistId, stockId) {
    await removeStockFromWatchlist(watchlistId, stockId);
    reload();
    if (onChanged) onChanged();
  }

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <nav style={styles.nav}>
          <span style={styles.navLink} onClick={onNavigateLive}>Live</span>
          <span style={styles.navActive}>Watchlist</span>
        </nav>
      </header>

      <form style={styles.createCard} onSubmit={handleCreate}>
        <input
          style={styles.input}
          placeholder="New watchlist name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <div style={styles.colorRow}>
          {COLOR_CHOICES.map((c) => (
            <button
              type="button"
              key={c}
              onClick={() => setNewColor(c)}
              style={{
                ...styles.colorSwatch,
                background: c,
                outline: newColor === c ? "2px solid var(--text)" : "none",
                outlineOffset: 2,
              }}
              aria-label={`Choose color ${c}`}
            />
          ))}
        </div>
        <button type="submit">Create watchlist</button>
      </form>

      {error && <div style={styles.error}>{error}</div>}

      {loading ? (
        <p style={styles.muted}>Loading...</p>
      ) : watchlists.length === 0 ? (
        <p style={styles.muted}>No watchlists yet — create one above.</p>
      ) : (
        watchlists.map((wl) => {
          const isCollapsed = collapsedIds.has(wl.id);
          return (
            <div key={wl.id} style={styles.listCard}>
              <div style={styles.listHead}>
                <span style={styles.listName}>
                  <button
                    style={styles.collapseBtn}
                    onClick={() => toggleCollapsed(wl.id)}
                    aria-label={isCollapsed ? `Expand ${wl.name}` : `Collapse ${wl.name}`}
                    title={isCollapsed ? "Expand" : "Collapse"}
                  >
                    {isCollapsed ? "+" : "\u2212"}
                  </button>
                  <span style={styles.colorDot(wl.color)} />
                  {wl.name}
                  <span style={styles.stockCount}>({wl.stocks.length})</span>
                </span>
                <button style={styles.deleteBtn} onClick={() => handleDelete(wl.id)}>Delete list</button>
              </div>

              {!isCollapsed && (
                <>
                  <AddStockSearch onSelect={(symbol) => handleAddStock(wl.id, symbol)} />

                  {wl.stocks.length === 0 ? (
                    <p style={styles.mutedSmall}>No stocks in this watchlist yet.</p>
                  ) : (
                    <table style={styles.table}>
                      <tbody>
                        {wl.stocks.map((stock) => (
                          <tr key={stock.id}>
                            <td style={styles.tdLeft}>
                              <span style={styles.symbolCell}>
                                {stock.trading_symbol}
                                <button
                                  className="chart-icon-btn"
                                  style={styles.chartIconBtn}
                                  onClick={() => openTradingViewChart(stock.trading_symbol)}
                                  title={`Open ${stock.trading_symbol} chart on TradingView`}
                                  aria-label={`Open ${stock.trading_symbol} chart on TradingView`}
                                >
                                  <ExternalLinkIcon />
                                </button>
                              </span>
                            </td>
                            <td style={styles.tdRight}>
                              <button style={styles.smallBtn} onClick={() => handleRemoveStock(wl.id, stock.id)}>
                                Remove
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}

/**
 * Search-as-you-type against our ~2,655-stock instrument database
 * (not limited to what's currently in the screener) — lets a stock be
 * added to a watchlist even if it hasn't triggered the screener at
 * all today.
 */
function AddStockSearch({ onSelect }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef(null);

  useEffect(() => {
    clearTimeout(debounceRef.current);
    if (!query.trim()) {
      setResults([]);
      return;
    }
    debounceRef.current = setTimeout(() => {
      searchInstruments(query).then((r) => {
        setResults(r);
        setOpen(true);
      });
    }, 250);
    return () => clearTimeout(debounceRef.current);
  }, [query]);

  function handleSelect(symbol) {
    onSelect(symbol);
    setQuery("");
    setResults([]);
    setOpen(false);
  }

  return (
    <div style={styles.searchWrap}>
      <input
        style={styles.input}
        placeholder="Add a stock (search by symbol or name)..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => results.length > 0 && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && results.length > 0 && (
        <div style={styles.dropdown}>
          {results.map((r) => (
            <div
              key={r.trading_symbol}
              style={styles.dropdownItem}
              onMouseDown={() => handleSelect(r.trading_symbol)}
            >
              <span style={styles.dropdownSymbol}>{r.trading_symbol}</span>
              <span style={styles.dropdownName}>{r.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const styles = {
  page: { padding: "20px 24px", maxWidth: 700, margin: "0 auto" },
  header: {
    display: "flex", alignItems: "center", gap: 16, marginBottom: 20,
    paddingBottom: 16, borderBottom: "1px solid var(--border)",
  },
  nav: { display: "flex", gap: 16, fontSize: 13 },
  navActive: { color: "var(--text)", fontWeight: 500, borderBottom: "2px solid var(--focus)", paddingBottom: 2 },
  navLink: { color: "var(--text-muted)", cursor: "pointer", paddingBottom: 2 },
  createCard: {
    display: "flex", alignItems: "center", gap: 10, marginBottom: 20,
    background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: 12,
  },
  input: { flex: 1 },
  colorRow: { display: "flex", gap: 6 },
  colorSwatch: { width: 20, height: 20, borderRadius: "50%", border: "none", cursor: "pointer", padding: 0 },
  error: {
    fontSize: 12, color: "var(--negative)", background: "rgba(255, 92, 92, 0.1)",
    border: "1px solid rgba(255, 92, 92, 0.3)", borderRadius: 6, padding: "8px 12px", marginBottom: 16,
  },
  muted: { color: "var(--text-muted)", fontSize: 13 },
  mutedSmall: { color: "var(--text-muted)", fontSize: 12, padding: "8px 0" },
  listCard: {
    background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8,
    padding: 16, marginBottom: 14,
  },
  listHead: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 },
  listName: { fontSize: 14, fontWeight: 600, display: "flex", alignItems: "center", gap: 4 },
  collapseBtn: {
    width: 20, height: 20, display: "inline-flex", alignItems: "center", justifyContent: "center",
    padding: 0, fontSize: 14, lineHeight: 1, marginRight: 4, borderRadius: 4,
  },
  colorDot: (color) => ({
    display: "inline-block", width: 9, height: 9, borderRadius: "50%", background: color, marginRight: 4,
  }),
  stockCount: { color: "var(--text-muted)", fontWeight: 400, fontSize: 12, marginLeft: 4 },
  deleteBtn: { fontSize: 11, color: "var(--negative)", borderColor: "rgba(255,92,92,0.4)" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13, marginTop: 10 },
  tdLeft: { textAlign: "left", padding: "8px 4px", borderBottom: "1px solid var(--border)" },
  tdRight: { textAlign: "right", padding: "8px 4px", borderBottom: "1px solid var(--border)" },
  smallBtn: { fontSize: 11, padding: "5px 9px" },
  symbolCell: { display: "inline-flex", alignItems: "center", gap: 7 },
  chartIconBtn: {
    display: "inline-flex", alignItems: "center", justifyContent: "center",
    background: "none", border: "none", padding: 2, margin: 0,
    color: "var(--text-muted)", cursor: "pointer", borderRadius: 4,
  },
  searchWrap: { position: "relative" },
  dropdown: {
    position: "absolute", top: "100%", left: 0, right: 0, zIndex: 10, marginTop: 4,
    background: "var(--surface-2, var(--surface))", border: "1px solid var(--border)", borderRadius: 6,
    maxHeight: 220, overflowY: "auto",
  },
  dropdownItem: {
    padding: "8px 10px", cursor: "pointer", display: "flex", justifyContent: "space-between", gap: 10,
    borderBottom: "1px solid var(--border)", fontSize: 12,
  },
  dropdownSymbol: { fontWeight: 600, flexShrink: 0 },
  dropdownName: { color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
};
