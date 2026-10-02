import { useEffect, useRef } from "react";

const TV_SCRIPT_SRC = "https://s3.tradingview.com/tv.js";

function loadTradingViewScript() {
  return new Promise((resolve, reject) => {
    if (window.TradingView) {
      resolve();
      return;
    }
    const existing = document.querySelector(`script[src="${TV_SCRIPT_SRC}"]`);
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", reject);
      return;
    }
    const script = document.createElement("script");
    script.src = TV_SCRIPT_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = reject;
    document.body.appendChild(script);
  });
}

/**
 * Embeds TradingView's free public chart widget for a given NSE
 * symbol. Uses the "default, easiest setup" tier deliberately — no
 * persistent custom indicator layouts across sessions, since that
 * requires TradingView's separately-licensed Advanced Charting
 * Library and an approval process we agreed to defer.
 *
 * NOT TESTED LIVE — no network access in the environment this was
 * built in, so this has never actually rendered in a real browser.
 * Verify it loads correctly on your end before relying on it.
 */
export default function TradingViewChart({ symbol }) {
  const containerRef = useRef(null);
  const containerId = `tv-chart-${symbol.replace(/[^a-zA-Z0-9]/g, "_")}`;

  useEffect(() => {
    let cancelled = false;

    loadTradingViewScript()
      .then(() => {
        if (cancelled || !containerRef.current) return;
        containerRef.current.innerHTML = ""; // clear any previous widget instance
        // eslint-disable-next-line no-undef
        new window.TradingView.widget({
          autosize: true,
          symbol: `NSE:${symbol}`,
          interval: "1", // 1-minute, per requirement 4a
          timezone: "Asia/Kolkata",
          theme: "dark",
          style: "1",
          locale: "en",
          toolbar_bg: "#12161f",
          enable_publishing: false,
          allow_symbol_change: true,
          container_id: containerId,
        });
      })
      .catch((err) => {
        console.error("Failed to load TradingView widget script:", err);
      });

    return () => {
      cancelled = true;
    };
  }, [symbol, containerId]);

  return <div id={containerId} ref={containerRef} style={{ width: "100%", height: "100%" }} />;
}
