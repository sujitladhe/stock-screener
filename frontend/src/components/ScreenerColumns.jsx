// ScreenerColumns.jsx — shared column set for the Live and History tables.
// Updated in 0004: added Circuit column; Actions column now includes the ignore button.

export const SCREENER_COLUMNS = [
  { key: "sym",     label: "Stock",   sortable: true,  def: 210 },
  { key: "_actions",label: "",        sortable: false, def: 195, align: "c" },
  { key: "ltp",     label: "Price",   sortable: true,  align: "c", def: 100 },
  { key: "pct",     label: "Change",  sortable: true,  align: "c", def: 100 },
  { key: "circuit", label: "Circuit", sortable: false, align: "c", def: 80 },
  { key: "mult",    label: "Rel vol", sortable: true,  align: "c", def: 90 },
  { key: "hits",    label: "Hits",    sortable: true,  align: "c", def: 60, hideSm: true },
  { key: "last",    label: "Last hit",sortable: true,  align: "c", def: 110 },
];

// History shares all columns except Actions and is non-sortable.
export const HISTORY_COLUMNS = SCREENER_COLUMNS
  .filter((c) => c.key !== "_actions")
  .map((c) => ({ ...c, sortable: false }));

export function ColGroup({ columns, widthOf, registerCol }) {
  return (
    <colgroup>
      {columns.map((c) => (
        <col
          key={c.key}
          data-col={c.key}
          ref={registerCol(c.key)}
          className={c.hideSm ? "hide-sm" : undefined}
          style={{ width: widthOf(c.key) }}
        />
      ))}
    </colgroup>
  );
}

export function ResizableTh({ col, sortKey, sortDesc, onSort, onPointerDown, onDoubleClick, onKeyDown }) {
  const sorted = sortKey === col.key;
  const cls = [
    col.align === "c" ? "c" : "",
    col.hideSm ? "hide-sm" : "",
    sorted ? "sorted" : "",
  ].filter(Boolean).join(" ");

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
