/**
 * useOptionStream — React hook for the option chain WebSocket.
 *
 * Returns:
 *   { chainData, metrics, guidance, isConnected, error }
 *
 * chainData.strikes: { [strike: string]: { ce, pe } }
 * metrics: { spot, pcr, maxPain, atmIv, ivSkew, expectedMove, totalCeOI, totalPeOI }
 * guidance: { score, bias, confidence, signals, opportunities, spikeAlerts }
 */

import { useEffect, useRef, useState, useCallback } from "react";

const WS_URL = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/options/ws`;
const RECONNECT_DELAY = 3000;
const PING_INTERVAL   = 20000;

// ─── OI classification ─────────────────────────────────────────────────────

function classifyCe(oiChgPct, isDownDay) {
  if (Math.abs(oiChgPct) < 0.4) return null;
  if (isDownDay)
    return oiChgPct > 0 ? { label: "TRAP", css: "trap" } : { label: "UWD", css: "uwd" };
  return oiChgPct > 0 ? { label: "BULL", css: "bull" } : { label: "UWD", css: "uwd" };
}

function classifyPe(oiChgPct, isDownDay) {
  if (Math.abs(oiChgPct) < 0.4) return null;
  if (isDownDay)
    return oiChgPct > 0 ? { label: "BEAR", css: "bear" } : { label: "SCOV", css: "scov" };
  return oiChgPct > 0 ? { label: "SCOV", css: "scov" } : { label: "UWD", css: "uwd" };
}

// ─── Derived metrics ────────────────────────────────────────────────────────

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
  const atm  = spot ? Math.round(spot / 50) * 50 : 0;

  // ATM IV approximation (Brenner-Subrahmanyam)
  const atmSide = strikes[String(atm)] || {};
  const ceLtp   = atmSide.ce?.ltp || 0;
  const peLtp   = atmSide.pe?.ltp || 0;
  const T = 7 / 365;
  const ivApprox = (ltp) =>
    ltp && spot > 0 ? +((ltp / spot) * Math.sqrt((2 * Math.PI) / T) * 100).toFixed(1) : 0;
  const ceIv = ivApprox(ceLtp);
  const peIv = ivApprox(peLtp);
  const atmIv = ceIv && peIv ? +((ceIv + peIv) / 2).toFixed(1) : ceIv || peIv;

  // IV skew: OTM PE - OTM CE (1 strike each side from ATM)
  const otmPe   = strikes[String(atm - 50)]?.pe?.ltp || 0;
  const otmCe   = strikes[String(atm + 50)]?.ce?.ltp || 0;
  const otmPeIv = ivApprox(otmPe);
  const otmCeIv = ivApprox(otmCe);
  const ivSkew  = otmPeIv && otmCeIv ? +(otmPeIv - otmCeIv).toFixed(1) : 0;

  // Expected move: spot × IV × sqrt(1/252)
  const expectedMove =
    spot && atmIv ? +(spot * (atmIv / 100) * Math.sqrt(1 / 252)).toFixed(0) : 0;

  return {
    spot,
    pcr,
    maxPain: 0,   // computed server-side and sent in guidance
    atmIv,
    ivSkew,
    expectedMove,
    totalCeOI,
    totalPeOI,
    maxCeStrike,
    maxPeStrike,
  };
}

// ─── Hook ───────────────────────────────────────────────────────────────────

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

          setMetrics(computeMetrics(strikes, spot));

          if (data.guidance) {
            // Merge server-side max_pain into metrics
            setMetrics(prev => prev
              ? { ...prev, maxPain: data.guidance.max_pain || prev.maxPain }
              : prev
            );
            setGuidance({
              score:         data.guidance.score,
              bias:          data.guidance.bias,
              confidence:    data.guidance.confidence,
              signals:       data.guidance.signals       || [],
              opportunities: data.guidance.opportunities || [],
              spikeAlerts:   data.guidance.spike_alerts  || [],
              pcr:           data.guidance.pcr,
              maxPain:       data.guidance.max_pain,
              ivSkew:        data.guidance.iv_skew,
            });
          }
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

  return {
    chainData,
    metrics,
    guidance,
    isConnected,
    error,
    classifyCe,
    classifyPe,
  };
}
