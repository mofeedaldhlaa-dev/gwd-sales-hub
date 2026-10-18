import { Capacitor, registerPlugin } from "@capacitor/core";

const BiometricAuth = registerPlugin("BiometricAuth");
const FullTextNotification = registerPlugin("FullTextNotification");

const BIOMETRIC_KEY = "gawad-biometric-lock-enabled-v1";

export const isNativeAndroid = () => Capacitor.isNativePlatform();

export const isBiometricLockEnabled = () => {
  try { return localStorage.getItem(BIOMETRIC_KEY) === "1"; } catch { return false; }
};

export const setBiometricLockEnabled = (enabled) => {
  try {
    if (enabled) localStorage.setItem(BIOMETRIC_KEY, "1");
    else localStorage.removeItem(BIOMETRIC_KEY);
  } catch (_) {}
};

export async function getBiometricAvailability() {
  if (!isNativeAndroid()) return { available: false, reason: "متاح داخل تطبيق Android فقط" };
  try { return await BiometricAuth.isAvailable(); }
  catch { return { available: false, reason: "تعذر فحص أمان الجهاز" }; }
}

export async function authenticateWithBiometric(reason = "افتح تطبيق GAWAD NET بالبصمة") {
  if (!isNativeAndroid()) throw new Error("البصمة متاحة داخل تطبيق Android فقط");
  try { return await BiometricAuth.authenticate({ reason }); }
  catch (error) { throw new Error(error?.message || "تعذر التحقق بالبصمة أو قفل الجهاز"); }
}

export async function showFullTextAndroidNotification({ id, title, body, channelId = "gawadnet", route = "" }) {
  if (!isNativeAndroid()) return { delivered: false, reason: "web" };
  try {
    return await FullTextNotification.notify({
      id: Number(id) || Math.floor(Date.now() / 1000) % 2147480000,
      title: String(title || "إشعار GAWAD NET"),
      body: String(body || "لديك إشعار جديد داخل التطبيق."),
      channelId,
      // The screen the app must open when the notification is tapped.
      route: String(route || ""),
    });
  } catch { return { delivered: false, reason: "تعذر عرض الإشعار الأصلي" }; }
}

export { BIOMETRIC_KEY };
