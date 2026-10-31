/**
 * GuidanceEngine — shows the server-side engine's decision.
 * Props: { guidance }
 *
 * The engine decides every 5 minutes using smoothed data and a confirmation
 * rule, so what you see here is intentionally stable.
 */

const BIAS_COLORS = {
  "BEARISH": "#ef4444",
  "NEUTRAL": "#6b7280",
  "BULLISH": "#22c55e",
};

function biasColor(bias) {
  return BIAS_COLORS[bias] || "#6b7280";
}

function hhmm(iso) {
  return iso ? iso.slice(11, 16) : "";
}

function ConfRing({ conf }) {
  const R   = 18;
  const C   = 2 * Math.PI * R;
  const arc = (conf / 100) * C;
  const color = conf >= 72 ? "#22c55e" : conf >= 58 ? "#f59e0b" : "#6b7280";
  return (
    <svg width="44" height="44" viewBox="0 0 44 44" className="opt-conf-ring">
      <circle cx="22" cy="22" r={R} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="3" />
      <circle
        cx="22" cy="22" r={R} fill="none"
        stroke={color} strokeWidth="3"
        strokeDasharray={`${arc} ${C - arc}`}
        strokeLinecap="round"
        transform="rotate(-90 22 22)"
      />
      <text x="22" y="26" textAnchor="middle" fontSize="10" fill={color} fontWeight="600">
        {conf}%
      </text>
    </svg>
  );
}

function SignalRow({ signal }) {
  const icon = signal.vote === "bull" ? "▲" : signal.vote === "bear" ? "▼" : "●";
  const cls  = signal.vote === "bull" ? "up" : signal.vote === "bear" ? "dn" : "neut";
  return (
    <div className="opt-signal-row">
      <span className={`opt-signal-vote opt-signal-vote--${cls}`}>{icon}</span>
      <span className="opt-signal-name">{signal.name}</span>
      <span className="opt-signal-val">{signal.value}</span>
      <span className="opt-signal-note">{signal.note}</span>
    </div>
  );
}

function OpCard({ op }) {
  const isSpike = op.is_spike;
  const typeLabel = isSpike ? `⚡ ${op.type}` : op.type;
  const typeCls   = op.type?.includes("CE") ? "ce" : op.type?.includes("PE") ? "pe" : "neutral";
  const riskCls   = op.risk === "Low" ? "low" : op.risk === "Med" ? "med" : "high";

  return (
    <div
      className={`opt-op-card opt-op-card--${typeCls} ${isSpike ? "opt-op-card--spike" : ""}`}
      style={op.fading ? { opacity: 0.6 } : undefined}
    >
      <div className="opt-op-card__head">
        <span className={`opt-op-badge opt-op-badge--${typeCls}`}>{typeLabel}</span>
        <span className="opt-op-strike">
          {op.pe_strike ? `${op.strike} / ${op.pe_strike}` : op.strike}
        </span>
        <ConfRing conf={op.confidence} />
      </div>
      <ul className="opt-op-reasons">
        {(op.reasons || []).map((r, i) => (
          <li key={i}>↳ {r}</li>
        ))}
      </ul>
      <div className="opt-op-foot">
        <span className={`opt-risk-badge opt-risk-badge--${riskCls}`}>{op.risk} Risk</span>
        {isSpike && <span className="opt-time-sensitive">Time-sensitive</span>}
        {op.fading && <span className="opt-time-sensitive">Fading — may be removed</span>}
        {!op.fading && !isSpike && op.cycles > 1 && (
          <span className="muted small">Held {op.cycles} cycles</span>
        )}
      </div>
    </div>
  );
}

function SpikeAlert({ alert }) {
  return (
    <div className="opt-spike-alert" style={alert.fading ? { opacity: 0.6 } : undefined}>
      <span className="opt-spike-alert__badge">⚡ SPIKE</span>
      <span className="opt-spike-alert__info">
        {alert.strike} {alert.type} — OI {alert.oi_chg_pct > 0 ? "+" : ""}
        {alert.oi_chg_pct?.toFixed(1)}% in {alert.window_min}m · V:OI {alert.voi?.toFixed(2)} · LTP {alert.ltp}
      </span>
      <span className="opt-spike-alert__dist">{alert.dist_from_spot}pts OTM</span>
      {alert.verdict && (
        <span className="muted small" style={{ flexBasis: "100%" }}>{alert.verdict}</span>
      )}
    </div>
  );
}

export default function GuidanceEngine({ guidance }) {
  if (!guidance) {
    return (
      <div className="opt-guidance-empty">
        <div className="opt-guidance-spinner" />
        <span>Guidance engine starting…</span>
      </div>
    );
  }

  if (guidance.warmingUp) {
    return (
      <div className="opt-guidance">
        <div className="opt-guidance__header">
          <h3 className="opt-guidance__title">Guidance Engine</h3>
          <span className="opt-guidance__refresh">↻ decides every 5 min</span>
        </div>
        <div className="opt-no-ops">{guidance.message || "Collecting data…"}</div>
        {guidance.spikeAlerts?.length > 0 && (
          <div className="opt-spikes">
            <div className="opt-spikes__header">⚡ Spike Alerts</div>
            {guidance.spikeAlerts.map((a, i) => <SpikeAlert key={i} alert={a} />)}
          </div>
        )}
      </div>
    );
  }

  const {
    score, bias, confidence, signals = [], flags = [], opportunities = [], spikeAlerts = [],
    pendingBias, pendingCount, confirmCycles, biasSince, evaluatedAt, windowMin,
  } = guidance;

  const spectrumLeft = `${((score + 5) / 10) * 100}%`;
  const bColor = biasColor(bias);

  return (
    <div className="opt-guidance" style={{ "--bias-color": bColor }}>
      <div className="opt-guidance__header">
        <h3 className="opt-guidance__title">Guidance Engine</h3>
        <span className="opt-guidance__refresh">
          ↻ every 5 min{evaluatedAt ? ` · decided ${hhmm(evaluatedAt)}` : ""}
        </span>
      </div>

      <div className="opt-bias-panel">
        <div className="opt-bias-main">
          <span className="opt-bias-label" style={{ color: bColor }}>{bias}</span>
          <span className="opt-bias-conf">{confidence}% agreement</span>
        </div>
        <div className="muted small">
          {biasSince ? `Confirmed since ${hhmm(biasSince)}` : "Confirmed bias"}
          {pendingBias
            ? ` · possible shift to ${pendingBias} (${pendingCount}/${confirmCycles} confirmations)`
            : ""}
        </div>
        <div className="opt-spectrum">
          <span className="opt-spectrum__label opt-spectrum__label--bear">BEAR</span>
          <div className="opt-spectrum__track">
            <div className="opt-spectrum__cursor" style={{ left: spectrumLeft }} />
          </div>
          <span className="opt-spectrum__label opt-spectrum__label--bull">BULL</span>
          <span className="opt-spectrum__score">Score: {score > 0 ? "+" : ""}{score}</span>
        </div>
      </div>

      {flags.length > 0 && (
        <div className="opt-spikes">
          {flags.map((f, i) => (
            <div key={i} className="opt-spike-alert">
              <span className="opt-spike-alert__badge">{f.label}</span>
              <span className="opt-spike-alert__info">{f.note}</span>
            </div>
          ))}
        </div>
      )}

      {signals.length > 0 && (
        <div className="opt-signals">
          <div className="opt-signals__header">Signal breakdown{windowMin ? ` (OI window ${windowMin} min)` : ""}</div>
          {signals.map((s, i) => <SignalRow key={i} signal={s} />)}
        </div>
      )}

      {spikeAlerts.length > 0 && (
        <div className="opt-spikes">
          <div className="opt-spikes__header">⚡ Spike Alerts</div>
          {spikeAlerts.map((a, i) => <SpikeAlert key={i} alert={a} />)}
        </div>
      )}

      {opportunities.length > 0 ? (
        <div className="opt-opportunities">
          <div className="opt-opportunities__header">Selling Opportunities</div>
          <div className="opt-op-grid">
            {opportunities.map((op, i) => <OpCard key={`${op.type}-${op.strike}-${i}`} op={op} />)}
          </div>
        </div>
      ) : (
        <div className="opt-no-ops">
          No confirmed opportunities right now. A setup must hold for a couple of cycles before it appears.
        </div>
      )}
    </div>
  );
}
