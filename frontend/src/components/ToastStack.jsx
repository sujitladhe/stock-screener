import { useState, useEffect, useCallback } from "react";
import { subscribeToast } from "../toast";
import { CloseIcon } from "../icons";

const AUTO_DISMISS_MS = 6500;
const AUTO_DISMISS_ERROR_MS = 9000;

export default function ToastStack() {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  useEffect(() => {
    const unsubscribe = subscribeToast((toast) => {
      setToasts((prev) => [...prev, toast]);
      setTimeout(() => dismiss(toast.id), toast.type === "error" ? AUTO_DISMISS_ERROR_MS : AUTO_DISMISS_MS);
    });
    return unsubscribe;
  }, [dismiss]);

  if (toasts.length === 0) return null;

  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast${t.type === "error" ? " error" : t.type === "mari" ? " mari" : ""}`} onClick={() => dismiss(t.id)}>
          <span className="grow">{t.message}</span>
          <CloseIcon size={14} />
        </div>
      ))}
    </div>
  );
}
