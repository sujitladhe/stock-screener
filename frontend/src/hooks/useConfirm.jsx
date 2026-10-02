import { useCallback, useRef, useState } from "react";

/**
 * Usage:
 *   const [confirm, confirmDialog] = useConfirm();
 *   ...
 *   if (await confirm("Delete this alert?", "The SBIN alert will be removed.", "Delete alert", true)) { ... }
 *   ...
 *   return <>{page}{confirmDialog}</>;
 *
 * A real modal (not window.confirm) so it matches the rest of the
 * app's styling and can be styled as dangerous (red confirm button)
 * for destructive actions.
 */
export function useConfirm() {
  const [state, setState] = useState(null); // {title, body, okLabel, danger}
  const resolver = useRef(null);

  const confirm = useCallback((title, body, okLabel = "Confirm", danger = false) => {
    return new Promise((resolve) => {
      resolver.current = resolve;
      setState({ title, body, okLabel, danger });
    });
  }, []);

  const settle = useCallback((value) => {
    setState(null);
    if (resolver.current) {
      resolver.current(value);
      resolver.current = null;
    }
  }, []);

  const dialog = state ? (
    <div className="modal" onClick={() => settle(false)}>
      <div className="modal-card" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" onClick={(e) => e.stopPropagation()}>
        <h2 id="confirm-title">{state.title}</h2>
        <p>{state.body}</p>
        <div className="modal-actions">
          <button className="btn" onClick={() => settle(false)}>Keep it</button>
          <button className={`btn ${state.danger ? "danger" : "primary"}`} onClick={() => settle(true)} autoFocus>
            {state.okLabel}
          </button>
        </div>
      </div>
    </div>
  ) : null;

  return [confirm, dialog];
}
