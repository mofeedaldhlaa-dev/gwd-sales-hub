import { useEffect, useState, useCallback } from "react";

let deferredInstallPrompt = null;
const installListeners = new Set();
const INSTALL_CONFIRMED_KEY = "gwd_pwa_install_confirmed";
const notifyInstallListeners = () => installListeners.forEach((listener) => listener());

const isStandaloneWindow = () => {
  if (typeof window === "undefined") return false;
  return Boolean(window.matchMedia?.("(display-mode: standalone)").matches || window.navigator.standalone === true);
};

const isMobileBrowser = () => {
  if (typeof navigator === "undefined") return false;
  return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent || "");
};

const isNativeApp = () => Boolean(
  typeof window !== "undefined" &&
  window.Capacitor &&
  typeof window.Capacitor.isNativePlatform === "function" &&
  window.Capacitor.isNativePlatform()
);

const wasInstalledBefore = () => {
  try { return localStorage.getItem(INSTALL_CONFIRMED_KEY) === "1"; } catch { return false; }
};

const markInstalled = () => {
  try { localStorage.setItem(INSTALL_CONFIRMED_KEY, "1"); } catch {}
};

const isInstalledApp = () => isStandaloneWindow() || isNativeApp() || wasInstalledBefore();

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (event) => {
    if (isInstalledApp()) return;
    event.preventDefault();
    deferredInstallPrompt = event;
    notifyInstallListeners();
  });
  window.addEventListener("appinstalled", () => {
    deferredInstallPrompt = null;
    markInstalled();
    notifyInstallListeners();
  });
}

/**
 * usePWAInstall — hook that captures the browser's `beforeinstallprompt` event
 * and exposes:
 *   - canInstall: boolean — true when the browser has offered an install prompt
 *   - installed: boolean — true if the app is already running as a PWA
 *   - promptInstall(): async — triggers the native install dialog (returns "accepted" | "dismissed" | "unsupported")
 */
export function usePWAInstall() {
  const [, setInstallVersion] = useState(0);
  const [installed, setInstalled] = useState(isInstalledApp);

  useEffect(() => {
    const refresh = () => {
      setInstallVersion((version) => version + 1);
      setInstalled(isInstalledApp());
    };
    installListeners.add(refresh);
    refresh();
    return () => installListeners.delete(refresh);
  }, []);

  const promptInstall = useCallback(async () => {
    const prompt = deferredInstallPrompt;
    if (!prompt) return "unsupported";
    try {
      prompt.prompt();
      const choice = await prompt.userChoice;
      deferredInstallPrompt = null;
      if (choice.outcome === "accepted") markInstalled();
      notifyInstallListeners();
      return choice.outcome || "dismissed";
    } catch { return "dismissed"; }
  }, []);

  return { canInstall: !!deferredInstallPrompt, installed, isMobile: isMobileBrowser(), isNative: isNativeApp(), promptInstall };
}

/** Swap the active <link rel="manifest"> to a specific href. */
export function setActiveManifest(href) {
  try {
    let link = document.querySelector('link[rel="manifest"]');
    if (!link) {
      link = document.createElement("link");
      link.rel = "manifest";
      document.head.appendChild(link);
    }
    if (link.getAttribute("href") !== href) link.setAttribute("href", href);
  } catch {}
}
