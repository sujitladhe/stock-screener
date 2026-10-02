import { useState, useEffect } from "react";
import { getWatchlists, createWatchlist, addStockToWatchlist } from "../api";

const COLOR_CHOICES = ["#f5c400", "#3dd68c", "#5b8cff", "#ff6b5b", "#c084fc", "#f5a623"];

/**
 * Per an explicit product decision, the earlier "First Leg / Second
 * Leg" choice is REMOVED entirely. Adding a stock to a watchlist now
 * just needs: which watchlist. If the stock is already in a
 * different watchlist, the backend automatically moves it (a stock
 * can only be in one watchlist at a time) - no extra UI needed here
 * for that, it's handled server-side.
 */
export default function AddToWatchlistModal({ symbol, onClose, onAdded }) {
  const [watchlists, setWatchlists] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState(COLOR_CHOICES[0]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    getWatchlists().then((lists) => {
      setWatchlists(lists);
      if (lists.length > 0) setSelectedId(lists[0].id);
      else setCreating(true);
    });
  }, []);

  async function handleCreateWatchlist() {
    const name = newName.trim();
    if (!name) return;
    setError(null);
    try {
      const wl = await createWatchlist(name, newColor);
      setWatchlists((prev) => [...prev, wl]);
      setSelectedId(wl.id);
      setCreating(false);
      setNewName("");
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleAdd() {
    if (!selectedId) {
      setError("Choose or create a watchlist first.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await addStockToWatchlist(selectedId, symbol);
      if (onAdded) onAdded();
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        <h2 style={styles.title}>Add {symbol} to watchlist</h2>

        {watchlists.length > 0 && !creating && (
          <>
            <label style={styles.label}>Watchlist</label>
            <select
              style={styles.select}
              value={selectedId || ""}
              onChange={(e) => setSelectedId(Number(e.target.value))}
            >
              {watchlists.map((wl) => (
                <option key={wl.id} value={wl.id}>{wl.name}</option>
              ))}
            </select>
            <button style={styles.linkBtn} onClick={() => setCreating(true)}>+ New watchlist</button>
          </>
        )}

        {creating && (
          <>
            <div style={styles.newRow}>
              <input
                style={styles.input}
                placeholder="Watchlist name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                autoFocus
              />
            </div>
            <label style={styles.label}>Color</label>
            <div style={styles.colorRow}>
              {COLOR_CHOICES.map((c) => (
                <button
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
            <div style={styles.newRow}>
              <button onClick={handleCreateWatchlist}>Create watchlist</button>
              {watchlists.length > 0 && (
                <button onClick={() => setCreating(false)}>Cancel</button>
              )}
            </div>
          </>
        )}

        {error && <div style={styles.error}>{error}</div>}

        {!creating && (
          <button style={styles.addBtn} onClick={handleAdd} disabled={submitting || !selectedId}>
            {submitting ? "Adding..." : "Add to watchlist"}
          </button>
        )}

        <button style={styles.closeBtn} onClick={onClose}>Cancel</button>
      </div>
    </div>
  );
}

const styles = {
  overlay: {
    position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
    display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
  },
  modal: {
    background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10,
    padding: 20, width: 320, display: "flex", flexDirection: "column", gap: 10,
  },
  title: { fontSize: 15, fontWeight: 600, margin: "0 0 4px 0" },
  label: { fontSize: 12, color: "var(--text-muted)" },
  select: { width: "100%", padding: "8px 10px" },
  linkBtn: {
    background: "none", border: "none", color: "var(--focus)", fontSize: 12,
    padding: 0, textAlign: "left", cursor: "pointer", width: "fit-content",
  },
  newRow: { display: "flex", gap: 6 },
  input: { flex: 1, padding: "8px 10px" },
  colorRow: { display: "flex", gap: 8 },
  colorSwatch: { width: 22, height: 22, borderRadius: "50%", border: "none", cursor: "pointer", padding: 0 },
  error: {
    fontSize: 12, color: "var(--negative)", background: "rgba(255, 92, 92, 0.1)",
    border: "1px solid rgba(255, 92, 92, 0.3)", borderRadius: 6, padding: "6px 10px",
  },
  addBtn: { background: "var(--focus)", borderColor: "var(--focus)", color: "#fff", marginTop: 4 },
  closeBtn: { background: "none", border: "none", color: "var(--text-muted)", fontSize: 12, marginTop: 2 },
};
