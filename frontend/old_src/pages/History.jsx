import { useState, useEffect } from "react";
import { getScreenerHistory, getAvailableDates } from "../api";
import ScreenerTable from "../components/ScreenerTable";

export default function History({ onNavigateLive, stockColors, onWatchlistChanged }) {
  const [availableDates, setAvailableDates] = useState([]);
  const [selectedDate, setSelectedDate] = useState(null);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getAvailableDates().then((dates) => {
      setAvailableDates(dates);
      if (dates.length > 0) setSelectedDate(dates[0]);
    });
  }, []);

  useEffect(() => {
    if (!selectedDate) return;
    setLoading(true);
    getScreenerHistory(selectedDate)
      .then(setRows)
      .finally(() => setLoading(false));
  }, [selectedDate]);

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <nav style={styles.nav}>
          <span style={styles.navLink} onClick={onNavigateLive}>Live</span>
          <span style={styles.navActive}>History</span>
        </nav>
        <div style={styles.spacer} />
        {availableDates.length > 0 && (
          <select
            style={styles.dateSelect}
            value={selectedDate || ""}
            onChange={(e) => setSelectedDate(e.target.value)}
          >
            {availableDates.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        )}
      </header>

      {availableDates.length === 0 ? (
        <p style={styles.empty}>No screener history yet — check back once the screener has run for a day.</p>
      ) : loading ? (
        <p style={styles.empty}>Loading...</p>
      ) : (
        <ScreenerTable
          rows={rows}
          emptyMessage="No stocks triggered on this date."
          stockColors={stockColors}
          onWatchlistChanged={onWatchlistChanged}
        />
      )}
    </div>
  );
}

const styles = {
  page: { padding: "20px 24px", maxWidth: 1100, margin: "0 auto" },
  header: {
    display: "flex",
    alignItems: "center",
    gap: 16,
    marginBottom: 16,
    paddingBottom: 16,
    borderBottom: "1px solid var(--border)",
  },
  nav: { display: "flex", gap: 16, fontSize: 13 },
  navActive: { color: "var(--text)", fontWeight: 500, borderBottom: "2px solid var(--focus)", paddingBottom: 2 },
  navLink: { color: "var(--text-muted)", cursor: "pointer", paddingBottom: 2 },
  spacer: { flex: 1 },
  dateSelect: { padding: "7px 10px" },
  empty: { color: "var(--text-muted)", fontSize: 13, padding: "20px 0" },
};
