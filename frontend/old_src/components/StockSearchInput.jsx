import { useState, useEffect, useRef } from "react";
import { searchInstruments } from "../api";

/**
 * Debounced search-as-you-type against our ~2,655-stock instrument
 * database. Extracted as a shared component since both the Watchlist
 * page and the Alerts page need "search for any stock, pick one" --
 * duplicating the debounce/dropdown logic in two places would have
 * let them drift apart over time.
 */
export default function StockSearchInput({ placeholder, onSelect, clearOnSelect = true }) {
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
    if (clearOnSelect) setQuery("");
    else setQuery(symbol);
    setResults([]);
    setOpen(false);
  }

  return (
    <div style={styles.wrap}>
      <input
        style={styles.input}
        placeholder={placeholder || "Search by symbol or name..."}
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
  wrap: { position: "relative" },
  input: { width: "100%" },
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
