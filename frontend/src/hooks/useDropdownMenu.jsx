import { useEffect, useRef, useState } from "react";

/**
 * A small floating menu anchored to whichever element triggered it.
 * Call open(event, items) from a click handler -- items is an array of
 * {label, color?, checked?, onClick}. Closes on outside click, Escape,
 * or picking an item. Position is computed from the trigger's own
 * bounding box so it works the same for a sidebar button or a table
 * row's icon.
 */
export function useDropdownMenu() {
  const [state, setState] = useState(null); // {rect, items}
  const menuRef = useRef(null);

  function open(e, items) {
    const rect = e.currentTarget.getBoundingClientRect();
    setState({ rect, items });
  }
  function close() {
    setState(null);
  }

  useEffect(() => {
    if (!state) return;
    function onDown(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) close();
    }
    function onKey(e) {
      if (e.key === "Escape") close();
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [state]);

  const menu = state ? (
    <div
      ref={menuRef}
      className="menu"
      role="menu"
      style={{
        top: Math.min(window.innerHeight - 8, state.rect.bottom + 6),
        left: Math.max(8, Math.min(window.innerWidth - 208, state.rect.right - 200)),
      }}
    >
      {state.items.map((it, i) => (
        <button
          type="button"
          role="menuitem"
          key={i}
          onClick={() => {
            close();
            it.onClick();
          }}
        >
          {it.color && <i className="swdot" style={{ background: it.color }} />}
          <span>{it.label}</span>
          {it.checked && <span className="tick">✓</span>}
        </button>
      ))}
    </div>
  ) : null;

  return { open, close, menu, isOpen: !!state };
}
