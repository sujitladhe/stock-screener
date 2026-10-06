import { useState, useEffect } from "react";
import {
  getWatchlists, createWatchlist, deleteWatchlist,
  addStockToWatchlist, removeStockFromWatchlist, clearWatchlistStocks,
} from "../api";
import StockSearchInput from "../components/StockSearchInput";
import PlaceOrderModal from "../components/PlaceOrderModal";
import { useConfirm } from "../hooks/useConfirm";
import { showToast } from "../toast";
import { ChartIcon, DownIcon } from "../icons";

const COLOR_CHOICES = ["#f5c400", "#3dd68c", "#5b8cff", "#ff6b5b", "#c084fc", "#f5a623"];

function openTradingViewChart(symbol) {
  window.open(
    `https://www.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(symbol)}`,
    "_blank",
    "noopener,noreferrer",
  );
}

export default function Watchlist({ onChanged, settings }) {
  const [lists, setLists]       = useState([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);
  const [newName, setNewName]   = useState("");
  const [newColor, setNewColor] = useState(COLOR_CHOICES[0]);
  const [collapsed, setCollapsed] = useState(new Set());
  const [buySymbol, setBuySymbol] = useState(null);
  const [confirm, confirmDialog]  = useConfirm();

  function reload() {
    setLoading(true);
    getWatchlists()
      .then(setLists)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }
  useEffect(reload, []);

  function toggleCollapsed(id) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
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
      showToast(`Watchlist "${name}" created.`);
      reload();
    } catch (err) {
      showToast(err.message, "error");
      setError(err.message);
    }
  }

  async function handleDelete(list) {
    const ok = await confirm(
      "Delete this watchlist?",
      `"${list.name}" and its ${list.stocks.length} stock${list.stocks.length === 1 ? "" : "s"} will be removed.`,
      "Delete list",
      true,
    );
    if (!ok) return;
    await deleteWatchlist(list.id);
    reload();
    if (onChanged) onChanged();
  }

  // NEW (0004) — Remove all stocks without deleting the watchlist
  async function handleClearStocks(list) {
    if (list.stocks.length === 0) {
      showToast("This watchlist has no stocks to remove.");
      return;
    }
    const ok = await confirm(
      `Remove all ${list.stocks.length} stocks from "${list.name}"?`,
      "The watchlist itself stays. The stocks themselves aren't affected.",
      "Remove all stocks",
      true,
    );
    if (!ok) return;
    try {
      await clearWatchlistStocks(list.id);
      showToast(`All stocks removed from "${list.name}".`);
      reload();
      if (onChanged) onChanged();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleAddStock(listId, symbol) {
    await addStockToWatchlist(listId, symbol);
    reload();
    if (onChanged) onChanged();
  }

  async function handleRemoveStock(listId, stockId) {
    await removeStockFromWatchlist(listId, stockId);
    reload();
    if (onChanged) onChanged();
  }

  return (
    <div>
      <form className="panel form-panel" style={{ margin: "6px 0 20px" }} onSubmit={handleCreate}>
        <label className="field" style={{ flex: 1, minWidth: 200 }}>
          <span>New watchlist</span>
          <input className="input" placeholder="For example: Gap-ups" maxLength={30} value={newName} onChange={(e) => setNewName(e.target.value)} />
        </label>
        <div className="field">
          <span>Colour</span>
          <div className="swatches" role="group" aria-label="Watchlist colour">
            {COLOR_CHOICES.map((c) => (
              <button
                type="button"
                key={c}
                className={`swatch${c === newColor ? " active" : ""}`}
                style={{ "--c": c }}
                onClick={() => setNewColor(c)}
                aria-label={`Colour ${c}`}
              />
            ))}
          </div>
        </div>
        <button type="submit" className="btn primary" style={{ alignSelf: "flex-end" }}>Create watchlist</button>
      </form>

      {error && <div className="err" style={{ marginBottom: 16 }}>{error}</div>}

      {loading ? (
        <p className="muted small">Loading...</p>
      ) : lists.length === 0 ? (
        <div className="panel empty">
          <b>No watchlists yet.</b>
          Create one above. Stocks in a watchlist get its colour on the Live screen.
        </div>
      ) : (
        <div className="stack">
          {lists.map((l) => {
            const isCollapsed = collapsed.has(l.id);
            return (
              <section key={l.id} className="panel wl" style={{ "--c": l.color }}>
                <div className="wl-head">
                  <button
                    type="button"
                    className="icon-btn"
                    onClick={() => toggleCollapsed(l.id)}
                    aria-label={isCollapsed ? `Expand ${l.name}` : `Collapse ${l.name}`}
                    aria-expanded={!isCollapsed}
                    style={{ transform: isCollapsed ? "rotate(-90deg)" : "none" }}
                  >
                    <DownIcon size={18} />
                  </button>
                  <h2>{l.name}</h2>
                  <span className="muted">{l.stocks.length} {l.stocks.length === 1 ? "stock" : "stocks"}</span>
                  <div className="grow" />
                  {/* NEW (0004) — Remove all stocks */}
                  {l.stocks.length > 0 && (
                    <button
                      type="button"
                      className="btn sm danger"
                      onClick={() => handleClearStocks(l)}
                      title={`Remove all stocks from ${l.name}`}
                    >
                      Remove all stocks
                    </button>
                  )}
                  <button type="button" className="btn sm danger" onClick={() => handleDelete(l)}>Delete list</button>
                </div>
                {!isCollapsed && (
                  <div className="wl-body">
                    <StockSearchInput
                      placeholder="Add a stock: search by symbol or name"
                      onSelect={(symbol) => handleAddStock(l.id, symbol)}
                    />
                    {l.stocks.length === 0 ? (
                      <p className="muted small" style={{ padding: "6px 0" }}>No stocks yet. Search above to add one.</p>
                    ) : (
                      l.stocks.map((s) => (
                        <div className="wl-row" key={s.id}>
                          <button
                            type="button"
                            className="icon-btn"
                            style={{ flex: "none" }}
                            onClick={() => openTradingViewChart(s.trading_symbol)}
                            title={`Open ${s.trading_symbol} on TradingView`}
                            aria-label={`Open ${s.trading_symbol} chart on TradingView`}
                          >
                            <ChartIcon />
                          </button>
                          <span className="sym">{s.trading_symbol}</span>
                          <div className="grow" />
                          <button type="button" className="btn sm buy-soft" onClick={() => setBuySymbol(s.trading_symbol)}>Buy</button>
                          <button type="button" className="btn sm" onClick={() => handleRemoveStock(l.id, s.id)}>Remove</button>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}

      {buySymbol && (
        <PlaceOrderModal symbol={buySymbol} settings={settings} onClose={() => setBuySymbol(null)} onPlaced={reload} />
      )}
      {confirmDialog}
    </div>
  );
}
