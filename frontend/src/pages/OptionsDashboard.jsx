/**
 * OptionsDashboard — main page component.
 * Route: /options
 */

import MetricsStrip  from "../components/options/MetricsStrip";
import OptionChain   from "../components/options/OptionChain";
import GuidanceEngine from "../components/options/GuidanceEngine";
import { useOptionStream } from "../components/options/useOptionStream";

const LEGEND = [
  ["trap", "TRAP", "Call writers adding - resistance building (bearish)"],
  ["bull", "BULL", "Call buyers adding (bullish)"],
  ["scov", "SCOV", "Call writers covering (bullish)"],
  ["bull", "SUPT", "Put writers adding - support building (bullish)"],
  ["bear", "BEAR", "Put buyers adding (bearish)"],
  ["bear", "PCOV", "Put writers covering (bearish)"],
];

export default function OptionsDashboard() {
  const { chainData, metrics, guidance, isConnected, error } = useOptionStream();

  return (
    <div className="opt-dashboard">
      <div className="opt-topbar">
        <span className="opt-topbar__title">Option Dashboard · NIFTY</span>
        <div className="opt-topbar__right">
          <span className={`opt-conn-dot ${isConnected ? "opt-conn-dot--on" : "opt-conn-dot--off"}`} />
          <span className="opt-conn-label">
            {isConnected ? "Live" : error ? "Error" : "Connecting…"}
          </span>
          {chainData.expiry && (
            <span className="opt-expiry-chip">Expiry: {chainData.expiry}</span>
          )}
        </div>
      </div>

      <MetricsStrip metrics={metrics} guidance={guidance} isConnected={isConnected} />

      <div className="opt-main-grid">
        <section className="opt-guidance-col">
          <GuidanceEngine guidance={guidance} />
        </section>

        <section className="opt-chain-col">
          <div className="opt-chain-header">
            <div className="opt-chain-legend">
              <span className="opt-legend-ce">■ CE</span>
              <span className="opt-legend-pe">■ PE</span>
              {guidance && !guidance.warmingUp && guidance.windowMin && (
                <span className="muted small" style={{ marginLeft: 8 }}>
                  Signals compare with {guidance.windowMin} min ago
                  {guidance.evaluatedAt ? ` · updated ${guidance.evaluatedAt.slice(11, 16)}` : ""}
                </span>
              )}
            </div>
            <div className="opt-chain-badges">
              {LEGEND.map(([cls, label, tip]) => (
                <span key={label} className={`opt-badge opt-badge--${cls}`} title={tip}>{label}</span>
              ))}
            </div>
          </div>
          <OptionChain chainData={chainData} guidance={guidance} />
        </section>
      </div>
    </div>
  );
}
