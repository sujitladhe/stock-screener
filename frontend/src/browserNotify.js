// browserNotify.js -- wraps the Notification API. Requesting
// permission must happen from a real user action (a button click) in
// most browsers, not automatically on page load -- so this exposes a
// request function the Alerts page calls from a button, plus show
// functions used whenever an alert (or an auto-trade result) fires.

export function getNotificationPermission() {
  if (!("Notification" in window)) return "unsupported";
  return Notification.permission; // "granted" | "denied" | "default"
}

export async function requestNotificationPermission() {
  if (!("Notification" in window)) return "unsupported";
  return Notification.requestPermission();
}

/**
 * Generic browser notification. Silently does nothing unless
 * permission has been granted -- the in-app toast / order list are the
 * fallback for a user who hasn't granted (or has denied) permission.
 */
export function showBrowserNotification({ title, body, tag }) {
  if (getNotificationPermission() !== "granted") return;

  const notification = new Notification(title, { body, tag });

  notification.onclick = () => {
    window.focus();
    notification.close();
  };
}

/**
 * Shows a browser notification for a fired price/value alert
 * (requirement 9) if permission has been granted.
 */
export function showAlertNotification(alert) {
  showBrowserNotification({
    title: `${alert.trading_symbol} alert triggered`,
    body: `${alert.condition_summary} -- LTP ${alert.ltp}`,
    tag: `alert-${alert.alert_id}-${alert.triggered_at}`,
  });
}
