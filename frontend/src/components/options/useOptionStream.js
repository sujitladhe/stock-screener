/**
 * useOptionStream — React hook for the option chain WebSocket.
 *
 * Returns: { chainData, metrics, guidance, isConnected, error }
 *
 * The chain (prices / OI) updates live. The guidance (bias, signals,
 * opportunities, per-strike OI labels) is produced by the server-side engine
 * every 5 minutes and is already smoothed and confirmed — the browser does not
 * recompute it. PCR / max pain / IV / skew / expected move shown in the metric
 * strip also come from the engine (smoothed) once it has a decision.
 */

import { useEffect, useRef, useState, useCallback } from "react";

const WS_URL = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/options/ws`;
const RECONNECT_DELAY = 3000;
const PING_INTERVAL   = 20000;

function computeMetrics(strikes, spot) {
  let totalCeOI = 0, totalPeOI = 0;
  let maxCeOI = 0, maxPeOI = 0;
  let maxCeStrike = 0, maxPeStrike = 0;

  Object.entries(strikes).forEach(([s, side]) => {
    const strike = Number(s);
    if (side.ce?.oi) {
      totalCeOI += side.ce.oi;
      if (side.ce.oi > maxCeOI) { maxCeOI = side.ce.oi; maxCeStrike = strike; }
    }
    if (side.pe?.oi) {
      totalPeOI += side.pe.oi;
      if (side.pe.oi > maxPeOI) { maxPeOI = side.pe.oi; maxPeStrike = strike; }
    }
  });

  const pcr = totalCeOI > 0 ? +(totalPeOI / totalCeOI).toFixed(3) : 1.0;

  return {
    spot, pcr, maxPain: 0, atmIv: 0, ivSkew: 0, expectedMove: 0,
    totalCeOI, totalPeOI, maxCeStrike, maxPeStrike,
  };
}

function mapGuidance(g) {
  return {
    warmingUp:     !!g.warming_up,
    message:       g.message,
    score:         g.score ?? 0,
    bias:          g.bias,
    rawBias:       g.raw_bias,
    confidence:    g.confidence ?? 0,
    pendingBias:   g.pending_bias,
    pendingCount:  g.pending_count ?? 0,
    confirmCycles: g.confirm_cycles ?? 2,
    biasSince:     g.bias_since,
    signals:       g.signals       || [],
    flags:         g.flags         || [],
    opportunities: g.opportunities || [],
    spikeAlerts:   g.spike_alerts  || [],
    strikeSignals: g.strike_signals || {},
    pcr:           g.pcr,
    maxPain:       g.max_pain,
    ivSkew:        g.iv_skew,
    atmIv:         g.atm_iv,
    expectedMove:  g.expected_move,
    evaluatedAt:   g.evaluated_at,
    windowMin:     g.window_min,
    historyMinutes: g.history_minutes ?? 0,
  };
}

export function useOptionStream() {
  const [chainData,    setChainData]    = useState({ strikes: {}, expiry: null, atm: 0 });
  const [metrics,      setMetrics]      = useState(null);
  const [guidance,     setGuidance]     = useState(null);
  const [isConnected,  setIsConnected]  = useState(false);
  const [error,        setError]        = useState(null);

  const wsRef        = useRef(null);
  const pingRef      = useRef(null);
  const reconnectRef = useRef(null);

  const connect = useCallback(() => {
    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        setError(null);
        pingRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send("ping");
        }, PING_INTERVAL);
      };

      ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data);
          const spot    = data.spot || 0;
          const strikes = data.strikes || {};

          setChainData({
            strikes,
            expiry:    data.expiry,
            atm:       data.atm || (spot ? Math.round(spot / 50) * 50 : 0),
            connected: data.connected,
          });

          const base = computeMetrics(strikes, spot);
          const g = data.guidance;
          if (g && !g.warming_up) {
            if (g.pcr != null)           base.pcr = g.pcr;
            if (g.max_pain != null)      base.maxPain = g.max_pain;
            if (g.atm_iv != null)        base.atmIv = g.atm_iv;
            if (g.iv_skew != null)       base.ivSkew = g.iv_skew;
            if (g.expected_move != null) base.expectedMove = g.expected_move;
          }
          setMetrics(base);

          if (g) setGuidance(mapGuidance(g));
        } catch (_) {}
      };

      ws.onerror = () => setError("Connection error");

      ws.onclose = () => {
        setIsConnected(false);
        clearInterval(pingRef.current);
        reconnectRef.current = setTimeout(connect, RECONNECT_DELAY);
      };
    } catch (err) {
      setError(String(err));
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      clearInterval(pingRef.current);
      clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { chainData, metrics, guidance, isConnected, error };
}
