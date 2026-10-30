/**
 * OptionsDashboard — main page component.
 * Route: /options
 */

import MetricsStrip  from "../components/options/MetricsStrip";
import OptionChain   from "../components/options/OptionChain";
import GuidanceEngine from "../components/options/GuidanceEngine";
import { useOptionStream } from "../components/options/useOptionStream";

export default function OptionsDashboard() {
  const {
    chainData,
    metrics,
    guidance,
    isConnected,
    error,
    classifyCe,
    classifyPe,
  } = useOptionStream();

  return (
    <div className="opt-dashboard">
      {/* Top bar */}
      <div className="opt-topbar">
        <span className="opt-topbar__title">Option Dashboard · NIFTY</span>
        <div className="opt-topbar__right">
          <span className={`opt-conn-dot ${isConnected ? "opt-conn-dot--on" : "opt-conn-dot--off"}`} />
          <span className="opt-conn-label">
            {isConnected ? "Live" : error ? "Error" : "Connecting…"}
          </span>
          {chainData.expiry && (
            <span className="opt-expiry-chip">
              Expiry: {chainData.expiry}
            </span>
          )}
        </div>
      </div>

      {/* Metrics row */}
      <MetricsStrip metrics={metrics} guidance={guidance} isConnected={isConnected} />

      {/* Main grid: Guidance | Chain */}
      <div className="opt-main-grid">
        <section className="opt-guidance-col">
          <GuidanceEngine guidance={guidance} />
        </section>

        <section className="opt-chain-col">
          <div className="opt-chain-header">
            <div className="opt-chain-legend">
              <span className="opt-legend-ce">■ CE</span>
              <span className="opt-legend-pe">■ PE</span>
            </div>
            <div className="opt-chain-badges">
              <span className="opt-badge opt-badge--trap">TRAP</span>
              <span className="opt-badge opt-badge--bull">BULL</span>
              <span className="opt-badge opt-badge--bear">BEAR</span>
              <span className="opt-badge opt-badge--scov">SCOV</span>
            </div>
          </div>
          <OptionChain
            chainData={chainData}
            guidance={guidance}
            classifyCe={classifyCe}
            classifyPe={classifyPe}
          />
        </section>
      </div>
    </div>
  );
}
