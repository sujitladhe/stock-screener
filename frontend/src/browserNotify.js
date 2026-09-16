// browserNotify.js -- wraps the Notification API. Requesting
// permission must happen from a real user action (a button click) in
// most browsers, not automatically on page load -- so this exposes a
// request function the Alerts page calls from a button, plus a show
// function used whenever an alert actually fires.

export function getNotificationPermission() {
  if (!("Notification" in window)) return "unsupported";
  return Notification.permission; // "granted" | "denied" | "default"
}

export async function requestNotificationPermission() {
  if (!("Notification" in window)) return "unsupported";
  return Notification.requestPermission();
}

/**
 * Shows a browser notification if permission has been granted.
 * Silently does nothing otherwise -- the in-app alert history and
 * sound (if enabled) are the fallback for a user who hasn't granted
 * (or has denied) notification permission.
 */
export function showAlertNotification(alert) {
  if (getNotificationPermission() !== "granted") return;

  const title = `${alert.trading_symbol} alert triggered`;
  const body = `${alert.condition_summary} -- LTP ${alert.ltp}`;

  const notification = new Notification(title, {
    body,
    tag: `alert-${alert.alert_id}-${alert.triggered_at}`,
  });

  notification.onclick = () => {
    window.focus();
    notification.close();
  };
}
