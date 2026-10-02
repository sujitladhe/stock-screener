import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "screener_settings_v1";

const DEFAULTS = {
  theme: "system", // "light" | "dark" | "system"
  riskEnabled: false,
  riskAmount: null, // rupees the user is willing to risk per trade
  riskPct: null, // default stoploss %, used to derive risk-per-share
};

function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? { ...DEFAULTS, ...JSON.parse(raw) } : { ...DEFAULTS };
  } catch {
    return { ...DEFAULTS };
  }
}
function save(settings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    /* storage unavailable -- setting just won't persist this session */
  }
}

/** Applies the effective theme to <html data-theme="..."> immediately, before React even renders, so there's no flash back to the OS theme. Exported separately so main.jsx can call it at boot. */
export function applyThemeAttr(settings) {
  const root = document.documentElement;
  if (settings.theme === "light") root.dataset.theme = "light";
  else if (settings.theme === "dark") root.dataset.theme = "dark";
  else delete root.dataset.theme;
}

/**
 * Settings the user set once and expects Screener to remember:
 *  - theme: explicit Light/Dark always wins and is remembered; "system"
 *    (the default until they pick one) follows the OS.
 *  - risk-based order sizing: used by PlaceOrderModal to prefill a new
 *    order's quantity from (risk amount) / (price * stoploss% / 100).
 */
export function useSettings() {
  const [settings, setSettings] = useState(load);

  useEffect(() => {
    applyThemeAttr(settings);
  }, [settings.theme]);

  const update = useCallback((patch) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch };
      save(next);
      return next;
    });
  }, []);

  // Clicking the sun/moon toggle always picks an explicit Light or
  // Dark (never "system") and remembers it -- "Match device" in
  // Settings is the only way back to following the OS.
  const toggleTheme = useCallback(() => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    update({ theme: dark ? "light" : "dark" });
  }, [update]);

  return { settings, update, toggleTheme };
}
