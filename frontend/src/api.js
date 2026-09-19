// api.js — centralizes the backend base URL and fetch calls so it's
// defined once, not scattered across components.

const API_BASE = import.meta.env.VITE_API_BASE || window.location.origin;
const WS_BASE = API_BASE.replace(/^http/, "ws");

export async function login(credentials) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include", // send/receive the session cookie
    body: JSON.stringify(credentials),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Login failed");
  }
  return res.json();
}

export async function logout() {
  await fetch(`${API_BASE}/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
}

export async function getCurrentSession() {
  const res = await fetch(`${API_BASE}/auth/me`, { credentials: "include" });
  if (!res.ok) return null;
  return res.json();
}

export async function getTodayScreener(search) {
  const url = new URL(`${API_BASE}/screener/today`);
  if (search) url.searchParams.set("search", search);
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) throw new Error("Failed to load screener data");
  return res.json();
}

export async function getScreenerHistory(dateStr, search) {
  const url = new URL(`${API_BASE}/screener/history`);
  url.searchParams.set("date", dateStr);
  if (search) url.searchParams.set("search", search);
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) throw new Error("Failed to load screener history");
  return res.json();
}

export async function getAvailableDates() {
  const res = await fetch(`${API_BASE}/screener/available-dates`, { credentials: "include" });
  if (!res.ok) throw new Error("Failed to load available dates");
  return res.json();
}

export function openScreenerSocket() {
  return new WebSocket(`${WS_BASE}/ws/screener`);
}

// --- Watchlists ---

async function handleJson(res, fallbackMsg) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || fallbackMsg);
  }
  return res.json();
}

export async function getWatchlists() {
  const res = await fetch(`${API_BASE}/watchlists`, { credentials: "include" });
  return handleJson(res, "Failed to load watchlists");
}

export async function createWatchlist(name, color) {
  const res = await fetch(`${API_BASE}/watchlists`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ name, color }),
  });
  return handleJson(res, "Failed to create watchlist");
}

export async function deleteWatchlist(watchlistId) {
  const res = await fetch(`${API_BASE}/watchlists/${watchlistId}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handleJson(res, "Failed to delete watchlist");
}

export async function addStockToWatchlist(watchlistId, tradingSymbol) {
  const res = await fetch(`${API_BASE}/watchlists/${watchlistId}/stocks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ trading_symbol: tradingSymbol }),
  });
  return handleJson(res, "Failed to add stock to watchlist");
}

export async function removeStockFromWatchlist(watchlistId, stockId) {
  const res = await fetch(`${API_BASE}/watchlists/${watchlistId}/stocks/${stockId}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handleJson(res, "Failed to remove stock");
}

export async function getStockColors() {
  const res = await fetch(`${API_BASE}/watchlists/stock-colors`, { credentials: "include" });
  if (!res.ok) return {};
  return res.json();
}

export async function searchInstruments(query) {
  if (!query || query.trim().length === 0) return [];
  const url = new URL(`${API_BASE}/instruments/search`);
  url.searchParams.set("q", query.trim());
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) return [];
  return res.json();
}

// --- Alerts ---

export async function getAlerts() {
  const res = await fetch(`${API_BASE}/alerts`, { credentials: "include" });
  return handleJson(res, "Failed to load alerts");
}

export async function createAlert(payload) {
  const res = await fetch(`${API_BASE}/alerts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handleJson(res, "Failed to create alert");
}

export async function toggleAlert(alertId) {
  const res = await fetch(`${API_BASE}/alerts/${alertId}/toggle`, {
    method: "PATCH",
    credentials: "include",
  });
  return handleJson(res, "Failed to toggle alert");
}

export async function deleteAlert(alertId) {
  const res = await fetch(`${API_BASE}/alerts/${alertId}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handleJson(res, "Failed to delete alert");
}

export async function getAlertHistory() {
  const res = await fetch(`${API_BASE}/alerts/history`, { credentials: "include" });
  return handleJson(res, "Failed to load alert history");
}

export async function clearAlertHistory() {
  const res = await fetch(`${API_BASE}/alerts/history`, {
    method: "DELETE",
    credentials: "include",
  });
  return handleJson(res, "Failed to clear alert history");
}

// --- Orders ---

export async function getOrders() {
  const res = await fetch(`${API_BASE}/orders`, { credentials: "include" });
  return handleJson(res, "Failed to load orders");
}

export async function placeOrder(payload) {
  const res = await fetch(`${API_BASE}/orders/place`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handleJson(res, "Failed to place order");
}

export async function cancelOrder(orderId) {
  const res = await fetch(`${API_BASE}/orders/${orderId}/cancel`, {
    method: "POST",
    credentials: "include",
  });
  return handleJson(res, "Failed to cancel order");
}

export async function modifyOrder(orderId, payload) {
  const res = await fetch(`${API_BASE}/orders/${orderId}/modify`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handleJson(res, "Failed to modify order");
}

// --- Positions ---

export async function getPositions() {
  const res = await fetch(`${API_BASE}/positions`, { credentials: "include" });
  return handleJson(res, "Failed to load positions");
}

export async function placeStoplossOrder(payload) {
  const res = await fetch(`${API_BASE}/positions/stoploss`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handleJson(res, "Failed to place stoploss order");
}
