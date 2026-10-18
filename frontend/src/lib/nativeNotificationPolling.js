import { Capacitor } from "@capacitor/core";
import { ensureNativeNotificationChannel } from "@/lib/nativeNotifications";
import { showFullTextAndroidNotification } from "@/lib/nativeSecurity";

const SNAPSHOT_KEY = "gawad-native-notification-snapshot-v1";
const POLL_MS = 15_000;
let timer = null;
let inFlight = false;
let onVisibilityChange = null;

const readSnapshot = () => {
  try { return JSON.parse(localStorage.getItem(SNAPSHOT_KEY) || "null") || { notificationIds: [], stock: {} }; }
  catch { return { notificationIds: [], stock: {} }; }
};
const saveSnapshot = (value) => {
  try { localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(value)); } catch (_) {}
};
const readNotificationSettings = () => {
  try { return { enabled: true, in_app_enabled: true, stock_alerts_enabled: true, ...(JSON.parse(localStorage.getItem("gwd_notification_settings") || "{}")) }; }
  catch { return { enabled: true, in_app_enabled: true, stock_alerts_enabled: true }; }
};
const notificationId = (seed) => {
  let hash = 2166136261;
  for (const char of String(seed)) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
  return Math.abs(hash) % 2147480000 || 1;
};

// The screen that opens when the phone notification is tapped: always the
// notifications screen, showing the notification text itself (same behaviour as
// tapping a row inside the admin notifications screen) - never a document
// editor. The stored notification id is passed so the exact row is opened.
const notificationRoute = (item) => {
  const id = item?.id ? String(item.id) : "";
  if (id && !id.startsWith("stock:")) return `/admin-notifications?focus=${encodeURIComponent(id)}`;
  return "/admin-notifications";
};
const showAndroidNotification = async ({ seed, title, body, route }) => {
  const channelId = await ensureNativeNotificationChannel();
  await showFullTextAndroidNotification({
    id: notificationId(seed),
    title: String(title || "إشعار GAWAD NET"),
    body: String(body || "لديك إشعار جديد"),
    channelId,
    route: String(route || ""),
  });
};

const poll = async (api) => {
  if (inFlight || !navigator.onLine) return;
  const settings = readNotificationSettings();
  if (settings.enabled === false || settings.in_app_enabled === false) return;
  inFlight = true;
  try {
    const [notificationsResult, stockResult] = await Promise.allSettled([
      api.get("/notifications"),
      settings.stock_alerts_enabled === false ? Promise.resolve({ data: { alerts: [] } }) : api.get("/stock/alerts"),
    ]);
    const previous = readSnapshot();
    const asList = (value) => (Array.isArray(value) ? value : (Array.isArray(value?.items) ? value.items : []));
    const currentItems = notificationsResult.status === "fulfilled" ? asList(notificationsResult.value.data) : [];
    const currentIds = notificationsResult.status === "fulfilled"
      ? currentItems.map((item) => item.id).filter(Boolean)
      : previous.notificationIds;
    const previousIds = new Set(previous.notificationIds || []);
    const newItems = currentItems.filter((item) => item.id && !previousIds.has(item.id));
    const currentStock = {};
    const stockItems = stockResult.status === "fulfilled" ? (stockResult.value.data?.alerts || []) : [];
    for (const alert of stockItems) {
      const key = `${alert.type}:${alert.category_id}`;
      const signature = `${alert.available}:${alert.threshold}`;
      currentStock[key] = signature;
      if (previous.stock?.[key] !== signature) {
        newItems.push({
          id: `stock:${key}:${signature}`,
          title: "تنبيه مخزون",
          message: `${alert.category_name || "فئة مخزون"}: المتوفر ${alert.available}، وحد التنبيه ${alert.threshold}`,
          category: "stock_alert",
          target: { route: alert.category_id ? `/stock?category=${alert.category_id}` : "/stock" },
        });
      }
    }
    // The first snapshot establishes the baseline and does not flood the phone
    // with historical notifications. Only changes after that point are shown.
    if (previous.initialized) {
      for (const item of newItems.slice(0, 20)) {
        await showAndroidNotification({
          seed: item.id,
          title: item.title || (item.category === "account_request" ? "طلب إنشاء حساب" : "إشعار التطبيق"),
          body: item.message || "لديك إشعار جديد داخل التطبيق.",
          route: notificationRoute(item),
        });
      }
    }
    saveSnapshot({
      initialized: true,
      notificationIds: currentIds.slice(0, 300),
      stock: currentStock,
      updatedAt: new Date().toISOString(),
    });
  } catch (_) {
    // Notification polling must never block the ERP UI or financial requests.
  } finally {
    inFlight = false;
  }
};

export async function startNativeNotificationPolling(api) {
  if (!Capacitor.isNativePlatform() || !api || timer) return;
  try { await ensureNativeNotificationChannel(); } catch (_) {}
  await poll(api);
  timer = window.setInterval(() => poll(api), POLL_MS);
  onVisibilityChange = () => {
    if (document.visibilityState === "visible") poll(api);
  };
  document.addEventListener("visibilitychange", onVisibilityChange);
}

export async function stopNativeNotificationPolling() {
  if (timer) window.clearInterval(timer);
  timer = null;
  if (onVisibilityChange) document.removeEventListener("visibilitychange", onVisibilityChange);
  onVisibilityChange = null;
}
