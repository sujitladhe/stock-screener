import { useCallback, useEffect, useRef, useState } from "react";

const STORAGE_KEY = "screener_col_widths_v1";
const MIN_COL_PX = 24;

function loadWidths() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}
function saveWidths(widths) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(widths));
  } catch {
    /* storage unavailable -- widths just won't persist this session */
  }
}

/**
 * Resizable-column state for the Live and History tables. They share
 * one persisted set of widths (same columns), so dragging a column on
 * either page carries over to the other -- each call to this hook
 * just reads/writes the same localStorage key independently.
 *
 * Deliberately NOT dependent on any other column: each <col> gets its
 * OWN explicit pixel width, the table itself is width:auto (see
 * index.css's `.tbl.resizable`), so widening one column can never
 * shrink another -- the table just grows and the panel scrolls.
 * There is also no per-column minimum beyond a tiny floor (24px): if
 * the user shrinks a column enough to crop its content, that's their
 * call, not something this hook second-guesses.
 */
export function useColumnWidths(columns) {
  const [widths, setWidths] = useState(loadWidths);
  const colRefs = useRef({});
  const drag = useRef(null);

  const defaultOf = useCallback(
    (key) => columns.find((c) => c.key === key)?.def ?? 100,
    [columns]
  );
  const widthOf = useCallback((key) => widths[key] ?? defaultOf(key), [widths, defaultOf]);

  const registerCol = useCallback((key) => (el) => {
    colRefs.current[key] = el;
  }, []);

  const commit = useCallback((key, px) => {
    setWidths((prev) => {
      const next = { ...prev, [key]: Math.max(MIN_COL_PX, Math.round(px)) };
      saveWidths(next);
      return next;
    });
  }, []);

  const resetColumn = useCallback((key) => {
    setWidths((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      saveWidths(next);
      return next;
    });
    const el = colRefs.current[key];
    if (el) el.style.width = `${defaultOf(key)}px`;
  }, [defaultOf]);

  const nudge = useCallback((key, deltaPx) => {
    const cur = widths[key] ?? defaultOf(key);
    commit(key, Math.max(MIN_COL_PX, cur + deltaPx));
  }, [widths, defaultOf, commit]);

  const onPointerDown = useCallback((e, key) => {
    const el = colRefs.current[key];
    if (!el) return;
    drag.current = { key, startX: e.clientX, startWidth: el.getBoundingClientRect().width };
    e.currentTarget.setPointerCapture?.(e.pointerId);
    document.body.style.cursor = "col-resize";
    e.preventDefault();
  }, []);

  useEffect(() => {
    function onMove(e) {
      const d = drag.current;
      if (!d) return;
      const el = colRefs.current[d.key];
      if (!el) return;
      const w = Math.max(MIN_COL_PX, Math.round(d.startWidth + (e.clientX - d.startX)));
      el.style.width = `${w}px`;
    }
    function onUp() {
      const d = drag.current;
      if (!d) return;
      const el = colRefs.current[d.key];
      if (el) commit(d.key, parseFloat(el.style.width));
      drag.current = null;
      document.body.style.cursor = "";
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [commit]);

  const onKeyDown = useCallback((e, key) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      nudge(key, e.key === "ArrowLeft" ? -12 : 12);
      e.preventDefault();
    } else if (e.key === "Home") {
      resetColumn(key);
      e.preventDefault();
    }
  }, [nudge, resetColumn]);

  return { widthOf, registerCol, onPointerDown, onDoubleClick: resetColumn, onKeyDown };
}
