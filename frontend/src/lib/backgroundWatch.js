import { Capacitor, registerPlugin } from "@capacitor/core";

// Native Android foreground service that keeps delivering the in-app
// notifications (admin notifications, account requests, stock alerts) while the
// app itself is closed. Older APK builds do not ship the plugin, so every call
// degrades silently instead of breaking the web bundle.
const BackgroundWatch = registerPlugin("BackgroundWatch");

export const isBackgroundWatchSupported = () => Capacitor.isNativePlatform() && Capacitor.getPlatform() === "android";

const call = async (method, options) => {
  if (!isBackgroundWatchSupported()) return null;
  try {
    const handler = BackgroundWatch?.[method];
    if (typeof handler !== "function") return null;
    return await handler.call(BackgroundWatch, options);
  } catch (_) {
    return null;
  }
};

export const startBackgroundWatch = async ({ token, baseUrl } = {}) => {
  if (!token) return null;
  return call("start", { token, baseUrl: baseUrl || "" });
};

export const stopBackgroundWatch = () => call("stop");

export const setBackgroundWatchForeground = (foreground) => call("setAppState", { foreground: !!foreground });

// Height of the phone status bar in CSS pixels when the web view runs underneath
// it (Android 15+). Returns 0 when the system already insets the web view, so
// the shell never adds the gap twice.
export const getSafeAreaTop = () => call("getSafeAreaTop", {});

export const getBackgroundWatchStatus = () => call("status");

export const openBackgroundWatchSettings = () => call("openBatterySettings");
export const openBackgroundWatchNotificationSettings = () => call("openNotificationSettings");
export const showBackgroundWatchTest = () => call("test");
// Route stored by the native side when the user taps a closed-app alert, so the
// app can open the operation (voucher / invoice) that the notification announced.
export const getPendingBackgroundRoute = async () => {
  const result = await call("getPendingRoute");
  return result && result.route ? String(result.route) : "";
};
