// ScreenerColumns.jsx — the column set shared by the Live and History
// tables (same data shape, same widths). Kept in one place so the two
// pages can't drift apart, and so resizing a column on one carries
// over to the other (see hooks/useColumnWidths.js).
//
// Per the approved design: every column except Stock is centre
// aligned, and Actions (chart / watchlist / Trade) sits right after
// Stock, before Price -- not trailing the row.

export const SCREENER_COLUMNS = [
  { key: "sym", label: "Stock", sortable: true, def: 220 },
  { key: "_actions", label: "", sortable: false, def: 180, align: "c" },
  { key: "ltp", label: "Price", sortable: true, align: "c", def: 100 },
  { key: "pct", label: "Change", sortable: true, align: "c", def: 100 },
  { key: "mult", label: "Rel Vol", sortable: true, align: "c", def: 90 },
  { key: "hits", label: "Hits", sortable: true, align: "c", def: 70, hideSm: true },
  { key: "last", label: "Last hit", sortable: true, align: "c", def: 110 },
];

// History has no action buttons and isn't sortable, but shares every
// other column (and its widths) with Live.
export const HISTORY_COLUMNS = SCREENER_COLUMNS.filter((c) => c.key !== "_actions").map((c) => ({
  ...c,
  sortable: false,
}));

export function ColGroup({ columns, widthOf, registerCol }) {
  return (
    <colgroup>
      {columns.map((c) => (
        <col key={c.key} data-col={c.key} ref={registerCol(c.key)} className={c.hideSm ? "hide-sm" : undefined} style={{ width: widthOf(c.key) }} />
      ))}
    </colgroup>
  );
}

/**
 * One <th>: either a sort button or a plain label, plus a drag handle
 * (unless the column can't be resized -- none currently can't). The
 * handle is a real, focusable element so it works with keyboard
 * (arrow keys nudge, Home resets) as well as pointer/touch drag.
 */
export function ResizableTh({ col, sortKey, sortDesc, onSort, onPointerDown, onDoubleClick, onKeyDown }) {
  const sorted = sortKey === col.key;
  const cls = [col.align === "c" ? "c" : "", col.hideSm ? "hide-sm" : "", sorted ? "sorted" : ""].filter(Boolean).join(" ");
  return (
    <th className={cls} aria-sort={sorted ? (sortDesc ? "descending" : "ascending") : undefined}>
      {col.sortable ? (
        <button type="button" onClick={() => onSort(col.key)}>
          {col.label}{sorted ? (sortDesc ? " ↓" : " ↑") : ""}
        </button>
      ) : (
        <span className="th-label">{col.label}</span>
      )}
      <span
        className="col-resizer"
        role="separator"
        aria-orientation="vertical"
        tabIndex={0}
        aria-label={`Resize the ${col.label || "action"} column`}
        onPointerDown={(e) => onPointerDown(e, col.key)}
        onDoubleClick={() => onDoubleClick(col.key)}
        onKeyDown={(e) => onKeyDown(e, col.key)}
      />
    </th>
  );
}
