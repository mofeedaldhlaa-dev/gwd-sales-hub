import { Capacitor } from "@capacitor/core";
import { LocalNotifications } from "@capacitor/local-notifications";

export const isNativeApp = () => Capacitor.isNativePlatform();

const CHANNEL = {
  id: "gawadnet",
  name: "إشعارات GAWAD NET",
  description: "تنبيهات العمليات والإدارة",
  importance: 5,
  visibility: 1,
};

export async function ensureNativeNotificationChannel() {
  if (!isNativeApp()) return null;
  await LocalNotifications.createChannel(CHANNEL);
  return CHANNEL.id;
}

export async function getNativeNotificationStatus() {
  if (!isNativeApp()) return { display: "unsupported" };
  return LocalNotifications.checkPermissions();
}

export async function requestNativeNotificationPermission() {
  if (!isNativeApp()) return { display: "unsupported" };
  await ensureNativeNotificationChannel();
  return LocalNotifications.requestPermissions();
}

export async function scheduleNativeTestNotification() {
  const permission = await requestNativeNotificationPermission();
  if (permission.display !== "granted") return permission;
  const channelId = await ensureNativeNotificationChannel();
  await LocalNotifications.schedule({
    notifications: [{
      id: Math.floor(Date.now() / 1000) % 2147480000,
      title: "اختبار إشعارات GAWAD NET",
      body: "إذا ظهرت هذه الرسالة فإذن إشعارات Android يعمل.",
      channelId,
      smallIcon: "ic_launcher",
      schedule: { at: new Date(Date.now() + 1500), isExactNotification: false },
    }],
  });
  return permission;
}
