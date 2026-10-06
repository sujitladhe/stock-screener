import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "screener_settings_v1";

const DEFAULTS = {
  theme: "system",
  riskEnabled: false,
  riskAmount: null,
  riskPct: null,
  // NEW (0004): minimum candle % for the green-candle highlight on Live rows.
  // A row whose current-minute candle is green AND >= this % gets a tinted background.
  // Set to null to disable the highlight entirely.
  greenCandleThreshold: 1.5,
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
  } catch { /* storage unavailable */ }
}

export function applyThemeAttr(settings) {
  const root = document.documentElement;
  if (settings.theme === "light") root.dataset.theme = "light";
  else if (settings.theme === "dark") root.dataset.theme = "dark";
  else delete root.dataset.theme;
}

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

  const toggleTheme = useCallback(() => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    update({ theme: dark ? "light" : "dark" });
  }, [update]);

  return { settings, update, toggleTheme };
}
