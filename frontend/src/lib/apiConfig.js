import { Capacitor } from "@capacitor/core";

// The browser deployment can use the configured environment value or same-origin /api.
// Native Android needs an absolute HTTPS origin because its WebView origin is localhost.
const configuredOrigin = String(process.env.REACT_APP_BACKEND_URL || "").trim().replace(/\/$/, "");
export const BACKEND_ORIGIN = configuredOrigin || (Capacitor.isNativePlatform() ? "https://gawad.cc" : "");
export const API_BASE = `${BACKEND_ORIGIN}/api`;

export const apiUrl = (path = "") => {
  const cleanPath = String(path).startsWith("/") ? String(path) : `/${path}`;
  return `${API_BASE}${cleanPath}`;
};

export default BACKEND_ORIGIN;

// Prevent an accidental production build with a literal undefined host.
if (typeof window !== "undefined" && BACKEND_ORIGIN === "undefined") {
  console.error("Invalid API configuration: REACT_APP_BACKEND_URL resolved to undefined");
}
