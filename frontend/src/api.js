// api.js — centralizes the backend base URL and fetch calls.

const API_BASE = import.meta.env.VITE_API_BASE || window.location.origin;
const WS_BASE = API_BASE.replace(/^http/, "ws");

async function handleJson(res, fallbackMsg) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || fallbackMsg);
  }
  return res.json();
}

// --- Auth ---

export async function login(credentials) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(credentials),
  });
  return handleJson(res, "Login failed");
}

export async function logout() {
  await fetch(`${API_BASE}/auth/logout`, { method: "POST", credentials: "include" });
}

export async function getCurrentSession() {
  const res = await fetch(`${API_BASE}/auth/me`, { credentials: "include" });
  if (!res.ok) return null;
  return res.json();
}

/**
 * Explicitly refreshes the Ventura auth token.
 * Returns { client_id, refreshed: bool } on success.
 *   refreshed = false  → token was already valid, no re-login was needed
 *   refreshed = true   → token was stale, a fresh Ventura login was performed
 * Throws an Error (with message from backend) if the re-login itself failed.
 */
export async function refreshSession() {
  const res = await fetch(`${API_BASE}/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  return handleJson(res, "Session refresh failed. Please log in again.");
}

// --- Screener ---

export async function getTodayScreener(search) {
  const url = new URL(`${API_BASE}/screener/today`);
  if (search) url.searchParams.set("search", search);
  const res = await fetch(url, { credentials: "include" });
  return handleJson(res, "Failed to load screener data");
}

export async function getScreenerHistory(dateStr, search) {
  const url = new URL(`${API_BASE}/screener/history`);
  url.searchParams.set("date", dateStr);
  if (search) url.searchParams.set("search", search);
  const res = await fetch(url, { credentials: "include" });
  return handleJson(res, "Failed to load screener history");
}

export async function getAvailableDates() {
  const res = await fetch(`${API_BASE}/screener/available-dates`, { credentials: "include" });
  return handleJson(res, "Failed to load available dates");
}

export function openScreenerSocket() {
  return new WebSocket(`${WS_BASE}/ws/screener`);
}

// --- Ignored stocks ---

export async function getIgnoredStocks() {
  const res = await fetch(`${API_BASE}/screener/ignored`, { credentials: "include" });
  return handleJson(res, "Failed to load ignored stocks");
}

export async function ignoreStock(tradingSymbol) {
  const res = await fetch(`${API_BASE}/screener/ignored`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ trading_symbol: tradingSymbol }),
  });
  return handleJson(res, "Failed to ignore stock");
}

export async function unignoreStock(tradingSymbol) {
  const res = await fetch(
    `${API_BASE}/screener/ignored/${encodeURIComponent(tradingSymbol)}`,
    { method: "DELETE", credentials: "include" },
  );
  return handleJson(res, "Failed to unignore stock");
}

export async function clearIgnoredStocks() {
  const res = await fetch(`${API_BASE}/screener/ignored`, {
    method: "DELETE",
    credentials: "include",
  });
  return handleJson(res, "Failed to clear ignored list");
}

// --- Watchlists ---

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

export async function clearWatchlistStocks(watchlistId) {
  const res = await fetch(`${API_BASE}/watchlists/${watchlistId}/stocks/all`, {
    method: "DELETE",
    credentials: "include",
  });
  return handleJson(res, "Failed to remove all stocks");
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

export async function getOrders(source = "all") {
  const url = new URL(`${API_BASE}/orders`);
  url.searchParams.set("source", source);
  const res = await fetch(url, { credentials: "include" });
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

export async function createAutoOrder(payload) {
  const res = await fetch(`${API_BASE}/orders/auto`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handleJson(res, "Failed to create auto order");
}

export async function updateAutoOrder(orderId, payload) {
  const res = await fetch(`${API_BASE}/orders/${orderId}/auto`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handleJson(res, "Failed to update auto order");
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
