import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

// Applied synchronously, before the first paint, so a browser that
// already chose Light or Dark doesn't flash the OS theme for a frame
// first (useSettings() re-applies this from React once mounted, but
// by then it would already be too late to avoid the flash).
(function applyStoredThemeBeforeRender() {
  try {
    const raw = localStorage.getItem("screener_settings_v1");
    const theme = raw ? JSON.parse(raw).theme : "system";
    if (theme === "light") document.documentElement.dataset.theme = "light";
    else if (theme === "dark") document.documentElement.dataset.theme = "dark";
  } catch {
    /* storage unavailable -- falls back to following the OS theme */
  }
})();

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);
