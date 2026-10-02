// toast.js — a minimal publish/subscribe module for toast
// notifications. Deliberately not React context: any component
// (a modal several levels deep, a page) just calls showToast()
// without needing to be wrapped in a provider or passed a callback
// down through props. <ToastStack/> in App.jsx is the one subscriber
// that actually renders them.

let idCounter = 0;
const listeners = new Set();

export function showToast(message, type = "success") {
  const toast = { id: ++idCounter, message, type };
  listeners.forEach((listener) => listener(toast));
}

export function subscribeToast(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
