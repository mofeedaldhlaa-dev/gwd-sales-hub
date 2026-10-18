import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

import { APP_TIMEZONE, parseServerDate } from "@/lib/DateService";
import { Capacitor, registerPlugin } from "@capacitor/core";
const ExternalApps = registerPlugin("ExternalApps");
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

export const fmt = (n) => {
  if (n === null || n === undefined || isNaN(n)) return "0";
  return Number(n).toLocaleString("en-US", { maximumFractionDigits: 2 });
};

export const fmtDate = (iso) => {
  if (!iso) return "";
  try {
    const d = parseServerDate(iso);
    return d.toLocaleDateString("en-GB", { timeZone: APP_TIMEZONE }) + " " + d.toLocaleTimeString("en-GB", { timeZone: APP_TIMEZONE, hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
};

export const fmtDateOnly = (iso) => {
  if (!iso) return "";
  try {
    const d = parseServerDate(iso);
    return d.toLocaleDateString("en-GB", { timeZone: APP_TIMEZONE });
  } catch { return iso; }
};

export const genUUID = () => {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
};

/**
 * Customer password in the same shape the server generates (JWD + 5 chars of
 * A-Z/0-9), so an admin-generated password looks identical to an auto-created
 * one. Prefers crypto.getRandomValues, falls back to Math.random.
 */
export const genCustomerPassword = (length = 8) => {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  const size = Math.max(6, Number(length) || 8);
  const out = [];
  try {
    const buf = new Uint32Array(size);
    window.crypto.getRandomValues(buf);
    for (let i = 0; i < size; i++) out.push(alphabet[buf[i] % alphabet.length]);
  } catch {
    for (let i = 0; i < size; i++) out.push(alphabet[Math.floor(Math.random() * alphabet.length)]);
  }
  return "JWD" + out.join("").slice(0, size - 3);
};

export const deviceId = () => {
  let id = localStorage.getItem("jwd_device");
  if (!id) {
    id = "dev-" + genUUID();
    localStorage.setItem("jwd_device", id);
  }
  return id;
};

export const localOperationNumber = (seed = genUUID()) => {
  const text = String(seed);
  let hash = 2166136261;
  for (let i = 0; i < text.length; i++) hash = Math.imul(hash ^ text.charCodeAt(i), 16777619);
  return `G${String(hash >>> 0).padStart(10, "0")}`;
};

/**
 * Hardware-based phone fingerprint. Stable across DIFFERENT BROWSERS on the
 * SAME phone (does NOT use userAgent or canvas, which vary per browser).
 * Uses only OS/hardware-level signals that every mobile browser exposes.
 * Returns a 32-char hex hash. Async because we hash with SubtleCrypto.
 */
export const phoneFingerprint = async () => {
  const parts = [
    navigator.platform || "",
    `${screen.width}x${screen.height}x${screen.colorDepth || 0}`,
    `${window.devicePixelRatio || 1}`,
    (Intl.DateTimeFormat().resolvedOptions().timeZone) || "",
    `${navigator.hardwareConcurrency || 0}`,
    `${navigator.deviceMemory || 0}`,
    `${navigator.maxTouchPoints || 0}`,
    (navigator.userAgentData?.platform) || "",
  ].join("|");
  try {
    const buf = new TextEncoder().encode(parts);
    const hash = await crypto.subtle.digest("SHA-256", buf);
    return "ph-" + Array.from(new Uint8Array(hash)).map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 32);
  } catch {
    // Fallback: DJB2-ish hash so login still works on very old browsers.
    let h = 5381;
    for (let i = 0; i < parts.length; i++) h = ((h << 5) + h + parts.charCodeAt(i)) | 0;
    return "ph-" + (h >>> 0).toString(16);
  }
};

const readMessagingSettings = () => {
  try { return { whatsapp_enabled: true, sms_enabled: true, country_code: "+967", ...(JSON.parse(localStorage.getItem("gwd_messaging_settings") || "{}")) }; }
  catch { return { whatsapp_enabled: true, sms_enabled: true, country_code: "+967" }; }
};
const normalizeWithCountry = (phone, countryCode) => {
  let n = String(phone || "").replace(/\D/g, "");
  if (n.startsWith("00")) n = n.slice(2);
  const cc = String(countryCode || "+967").replace(/\D/g, "");
  if (cc && !n.startsWith(cc) && n.length <= 9) n = cc + n;
  return n;
};
export const openWhatsApp = (phone, text) => {
  const messaging = readMessagingSettings();
  if (!messaging.whatsapp_enabled) { alert("تم تعطيل الإرسال عبر واتساب من إعدادات الرسائل."); return; }
  if (!phone) {
    alert("لا يوجد رقم هاتف مسجل لهذا الحساب.");
    return;
  }
  const n = normalizeWithCountry(phone, messaging.country_code);
  if (Capacitor.isNativePlatform()) {
    // Leave the ERP WebView entirely. WhatsApp can open the compose window
    // offline; sending itself still depends on WhatsApp's own connectivity.
    ExternalApps.openWhatsApp({ phone: n, text: text || "" }).catch(() => {
      try { window.location.href = `whatsapp://send?phone=${n}&text=${encodeURIComponent(text || "")}`; } catch { /* no-op */ }
    });
    return;
  }
  const href = `https://wa.me/${n}?text=${encodeURIComponent(text || "")}`;
  try {
    const popup = window.open(href, "_blank");
    if (!popup) window.location.href = href;
  } catch {
    window.location.href = href;
  }
};

export const openWhatsAppUrl = (url) => {
  if (!url) return;
  if (!readMessagingSettings().whatsapp_enabled) { alert("تم تعطيل الإرسال عبر واتساب من إعدادات الرسائل."); return; }
  if (Capacitor.isNativePlatform()) {
    try {
      const parsed = new URL(url);
      const phone = parsed.pathname.replace(/\D/g, "");
      const text = parsed.searchParams.get("text") || "";
      window.location.href = `whatsapp://send?phone=${phone}&text=${encodeURIComponent(text)}`;
      return;
    } catch { /* fall through to normal URL opening */ }
  }
  try { window.open(url, "_blank"); } catch { window.location.href = url; }
};

export const openSMS = (phone, text) => {
  const messaging = readMessagingSettings();
  if (!messaging.sms_enabled) { alert("تم تعطيل الإرسال عبر الرسائل النصية من إعدادات الرسائل."); return; }
  if (!phone) return;
  const n = "+" + normalizeWithCountry(phone, messaging.country_code);
  const body = encodeURIComponent(text || "");
  // iOS uses '&', Android uses '?'. Modern browsers accept '?body='. Use it.
  const href = `sms:${n}?body=${body}`;
  // Use location.href to invoke the OS SMS app (window.open often blocks sms: on mobile).
  try { window.location.href = href; }
  catch { window.open(href, "_self"); }
};

export const buildInvoiceMessage = ({ company, number, kind, details, amount, discount, total, paid, remaining, balance_after }) => {
  const parts = [
    `من ${company}`,
    `المخاء`,
    `784225716`,
    ``,
    `عليكم فاتورة رقم: ${number}`,
    `تفاصيل الفاتورة:`,
    details || "",
    ``,
    `مبلغ الفاتورة: ${fmt(total)}`,
  ];
  if (discount > 0) parts.push(`الخصم: ${fmt(discount)}`);
  if (paid !== undefined) parts.push(`المدفوع: ${fmt(paid)}`, `المتبقي: ${fmt(remaining)}`);
  if (balance_after !== null && balance_after !== undefined) {
    parts.push(``, `الرصيد الإجمالي عليكم: ${fmt(balance_after)}`);
  }
  return parts.join("\n");
};

export const buildReceiptMessage = ({ company, kind, number, amount, description, balance_after }) => {
  const dir = kind === "receipt" ? "لكم" : "عليكم";
  const parts = [
    `من ${company}`,
    `المخاء`,
    `784225716`,
    ``,
    `${dir} سند رقم: ${number}`,
    `مبلغ السند: ${fmt(amount)}`,
    `تفاصيل السند:`,
    description || "-",
  ];
  if (balance_after !== null && balance_after !== undefined) {
    parts.push(``, `إجمالي الرصيد عليكم: ${fmt(balance_after)}`);
  }
  return parts.join("\n");
};
