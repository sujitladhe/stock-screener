import { useState, useEffect, useRef } from "react";
import { searchInstruments } from "../api";
import { SearchIcon, CloseIcon } from "../icons";

/**
 * Debounced search-as-you-type against the shared instrument database.
 * Used anywhere the user picks ONE stock to act on next (placing an
 * order, adding to a watchlist, creating an alert) -- as opposed to
 * FilterInput, which narrows what's already on screen.
 */
export default function StockSearchInput({ placeholder, onSelect, clearOnSelect = true, value: controlledValue }) {
  const [query, setQuery] = useState(controlledValue || "");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef(null);

  useEffect(() => {
    if (controlledValue !== undefined) setQuery(controlledValue);
  }, [controlledValue]);

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

  function handleClear() {
    setQuery("");
    setResults([]);
    setOpen(false);
  }

  return (
    <div className="ss">
      <span className="ss-icon"><SearchIcon /></span>
      <input
        className="input"
        placeholder={placeholder || "Search by symbol or name..."}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => results.length > 0 && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        aria-label={placeholder || "Search by symbol or name"}
      />
      {query && (
        <button type="button" className="ss-clear" aria-label="Clear search" onMouseDown={(e) => { e.preventDefault(); handleClear(); }}>
          <CloseIcon size={14} />
        </button>
      )}
      {open && results.length > 0 && (
        <div className="ss-list">
          {results.map((r) => (
            <button
              type="button"
              key={r.trading_symbol}
              className="ss-item"
              onMouseDown={() => handleSelect(r.trading_symbol)}
            >
              <b>{r.trading_symbol}</b>
              <span>{r.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
