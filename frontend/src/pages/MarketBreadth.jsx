import { useState, useEffect } from "react";
import { getMarketBreadth } from "../api";

// Format a YYYY-MM-DD date string as "21 Oct 2026" in IST
function fmtDate(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("en-IN", {
    day:   "2-digit",
    month: "short",
    year:  "numeric",
    timeZone: "Asia/Kolkata",
  });
}

// Sentiment label + colour based on breadth %
function sentimentOf(pct) {
  if (pct >= 60) return { label: "Bullish",  color: "var(--up)",   bg: "var(--up-soft)"   };
  if (pct <= 40) return { label: "Bearish",  color: "var(--down)", bg: "var(--down-soft)" };
  return             { label: "Neutral",  color: "var(--muted)", bg: "var(--sunken)"    };
}

const DAY_OPTIONS = [30, 60, 90, 180];

export default function MarketBreadth() {
  const [rows,    setRows]    = useState([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  const [days,    setDays]    = useState(90);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getMarketBreadth(days)
      .then((data) => { if (!cancelled) setRows(data); })
      .catch((e)   => { if (!cancelled) setError(e.message); })
      .finally(()  => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [days]);

  const latest   = rows[0] || null;
  const sentiment = latest ? sentimentOf(latest.breadth_pct) : null;

  return (
    <div style={{ paddingTop: 8 }}>

      {/* ── Stat strip ─────────────────────────────────────────────── */}
      <div className="mb-stat-strip">
        <div className="mb-stat mb-stat--up">
          <span className="mb-stat-val">
            {loading ? "—" : latest ? latest.above_count.toLocaleString() : "—"}
          </span>
          <span className="mb-stat-label">Above 50 MA</span>
        </div>

        <div className="mb-stat mb-stat--down">
          <span className="mb-stat-val">
            {loading ? "—" : latest ? latest.below_count.toLocaleString() : "—"}
          </span>
          <span className="mb-stat-label">Below 50 MA</span>
        </div>

        <div className="mb-stat">
          <span className="mb-stat-val">
            {loading ? "—" : latest ? `${latest.breadth_pct}%` : "—"}
          </span>
          <span className="mb-stat-label">Breadth (latest)</span>
        </div>
      </div>

      {/* ── Toolbar ────────────────────────────────────────────────── */}
      <div className="page-tools">
        <span className="tool-label">Show last</span>
        {DAY_OPTIONS.map((d) => (
          <button
            key={d}
            className={`btn sm${days === d ? " primary" : ""}`}
            onClick={() => setDays(d)}
          >
            {d}d
          </button>
        ))}

        {sentiment && (
          <span
            className="chip"
            style={{
              marginLeft:  "auto",
              color:       sentiment.color,
              background:  sentiment.bg,
              borderColor: sentiment.color + "44",
              fontWeight:  600,
            }}
          >
            {sentiment.label}
          </span>
        )}
      </div>

      {/* ── States ─────────────────────────────────────────────────── */}
      {loading && (
        <p style={{ color: "var(--muted)", padding: "32px 0" }}>Loading…</p>
      )}

      {!loading && error && (
        <p style={{ color: "var(--down)", padding: "32px 0" }}>{error}</p>
      )}

      {!loading && !error && rows.length === 0 && (
        <div className="empty">
          <b>No data yet</b>
          Run the daily candle sync script first, then come back here.
        </div>
      )}

      {/* ── Table ──────────────────────────────────────────────────── */}
      {!loading && !error && rows.length > 0 && (
        <div className="panel" style={{ overflow: "hidden" }}>
          <div style={{ overflowX: "auto" }}>
            <table className="mb-tbl">
              <thead>
                <tr>
                  <th>Date</th>
                  <th className="r">Above 50 MA</th>
                  <th className="r">Below 50 MA</th>
                  <th className="r">Total</th>
                  <th style={{ width: "38%" }}>Breadth</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, idx) => (
                  <tr key={row.candle_date} data-latest={idx === 0 ? "" : undefined}>
                    <td style={{ whiteSpace: "nowrap" }}>{fmtDate(row.candle_date)}</td>
                    <td className="r up num">{row.above_count.toLocaleString()}</td>
                    <td className="r down num">{row.below_count.toLocaleString()}</td>
                    <td className="r muted num">{row.total_count.toLocaleString()}</td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div className="mb-track">
                          <div
                            className="mb-fill"
                            style={{ width: `${Math.min(100, row.breadth_pct)}%` }}
                          />
                        </div>
                        <span
                          className="num"
                          style={{ fontSize: 12.5, color: "var(--muted)", minWidth: 40, textAlign: "right" }}
                        >
                          {row.breadth_pct}%
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
