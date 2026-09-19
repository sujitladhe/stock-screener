import { useState, useEffect, useCallback } from "react";
import { subscribeToast } from "../toast";

const AUTO_DISMISS_MS = 5000;

export default function ToastStack() {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  useEffect(() => {
    const unsubscribe = subscribeToast((toast) => {
      setToasts((prev) => [...prev, toast]);
      setTimeout(() => dismiss(toast.id), AUTO_DISMISS_MS);
    });
    return unsubscribe;
  }, [dismiss]);

  if (toasts.length === 0) return null;

  return (
    <div style={styles.stack}>
      {toasts.map((t) => (
        <div
          key={t.id}
          style={{
            ...styles.toast,
            borderColor: t.type === "error" ? "var(--negative)" : "var(--positive)",
          }}
          onClick={() => dismiss(t.id)}
        >
          <span style={{ color: t.type === "error" ? "var(--negative)" : "var(--positive)" }}>
            {t.type === "error" ? "\u2715" : "\u2713"}
          </span>
          <span style={styles.message}>{t.message}</span>
        </div>
      ))}
    </div>
  );
}

const styles = {
  stack: {
    position: "fixed", bottom: 20, right: 20, zIndex: 2000,
    display: "flex", flexDirection: "column", gap: 8, maxWidth: 340,
  },
  toast: {
    display: "flex", alignItems: "flex-start", gap: 8,
    background: "var(--surface)", border: "1px solid", borderRadius: 8,
    padding: "10px 14px", fontSize: 13, cursor: "pointer",
    boxShadow: "0 4px 16px rgba(0,0,0,0.3)",
  },
  message: { color: "var(--text)" },
};
