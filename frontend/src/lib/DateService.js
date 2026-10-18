import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { apiUrl } from "@/lib/apiConfig";

export const APP_TIMEZONE = "Asia/Aden";
export const APP_UTC_OFFSET = "+03:00";
const pad = (n) => String(n).padStart(2, "0");
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const zoneFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: APP_TIMEZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
const SERVER_DATE_TIMEOUT_MS = 8_000;

// This module is the only place allowed to create the current application date.
let officialServerClock = null;

export const dateIso = (date) => {
  const d = date instanceof Date ? date : new Date(date || Date.now());
  const parts = Object.fromEntries(zoneFormatter.formatToParts(d).map((p) => [p.type, p.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
};

export const setOfficialServerClock = (payload) => {
  const serverMs = Date.parse(payload?.iso || "");
  if (Number.isFinite(serverMs) && DATE_RE.test(payload?.date || "")) {
    officialServerClock = { ...payload, serverMs, syncedAtMs: Date.now() };
  }
  return officialServerClock;
};

export const getAppNow = () => officialServerClock
  ? new Date(officialServerClock.serverMs + (Date.now() - officialServerClock.syncedAtMs))
  : new Date(Date.now());
export const todayIso = () => dateIso(getAppNow());
export const getCalendarDate = () => new Date(`${todayIso()}T12:00:00${APP_UTC_OFFSET}`);
export const monthStartDate = () => new Date(`${todayIso().slice(0, 7)}-01T12:00:00${APP_UTC_OFFSET}`);
export const monthStartIso = () => `${todayIso().slice(0, 7)}-01`;
export const parseDateBoundary = (value, endOfDay = false) => value && DATE_RE.test(value)
  ? new Date(`${value}T${endOfDay ? "23:59:59.999" : "00:00:00.000"}${APP_UTC_OFFSET}`)
  : null;
export const parseServerDate = (value) => {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};
export const formatAppNow = () => getAppNow().toLocaleString("en-GB", { timeZone: APP_TIMEZONE });
export const yearStartIso = () => `${todayIso().slice(0, 4)}-01-01`;
export const dateInputValue = (date = getAppNow()) => dateIso(date);

const DateContext = createContext(null);

async function requestServerDate(signal) {
  const headers = {};
  const token = typeof localStorage !== "undefined" ? localStorage.getItem("jwd_token") : "";
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(apiUrl("/system/date"), {
    method: "GET",
    headers,
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new Error(`SERVER_DATE_${response.status}`);
  const payload = await response.json();
  if (!payload?.iso || !DATE_RE.test(payload?.date || "")) throw new Error("INVALID_SERVER_DATE");
  return payload;
}

export function AppDateProvider({ children }) {
  const [ready, setReady] = useState(false);
  const [selectedDate, setSelectedDate] = useState("");
  const [clockVersion, setClockVersion] = useState(0);
  const activeRef = useRef(true);

  const sync = useCallback(async ({ showLoader = false } = {}) => {
    if (showLoader) setReady(false);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), SERVER_DATE_TIMEOUT_MS);
    try {
      const payload = await requestServerDate(controller.signal);
      if (!activeRef.current) return;
      const previousOfficialDate = officialServerClock?.date || "";
      const clock = setOfficialServerClock(payload);
      if (!clock) throw new Error("INVALID_SERVER_DATE");
      setSelectedDate((previous) => (!previous || previous === previousOfficialDate ? clock.date : previous));
      setClockVersion((version) => version + 1);
      setReady(true);
    } catch (error) {
      if (!activeRef.current) return;
      // A date endpoint outage must not blank the application. Keep a valid
      // synchronized clock when available, otherwise use the device date only
      // as a temporary fallback until the next online refresh.
      const previousOfficialDate = officialServerClock?.date || "";
      if (!officialServerClock) {
        const now = new Date();
        const fallbackDate = dateIso(now);
        setOfficialServerClock({ iso: now.toISOString(), date: fallbackDate, timezone: APP_TIMEZONE, source: "fallback" });
        setSelectedDate((previous) => (!previous || previous === previousOfficialDate ? fallbackDate : previous));
      }
      setClockVersion((version) => version + 1);
      setReady(true);
      if (process.env.NODE_ENV !== "production") console.warn("Server date sync unavailable; using fallback clock", error);
    } finally {
      window.clearTimeout(timeout);
    }
  }, []);

  useEffect(() => {
    activeRef.current = true;
    sync({ showLoader: true });
    const timer = window.setInterval(() => sync(), 60_000);
    const refreshVisible = () => { if (document.visibilityState === "visible") sync(); };
    window.addEventListener("online", refreshVisible);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => {
      activeRef.current = false;
      window.clearInterval(timer);
      window.removeEventListener("online", refreshVisible);
      document.removeEventListener("visibilitychange", refreshVisible);
    };
  }, [sync]);

  const value = useMemo(() => ({
    ready,
    timezone: APP_TIMEZONE,
    utcOffset: APP_UTC_OFFSET,
    now: getAppNow,
    todayIso,
    officialDate: todayIso(),
    clockVersion,
    selectedDate,
    setSelectedDate,
    refresh: () => sync({ showLoader: false }),
  }), [ready, selectedDate, clockVersion, sync]);

  if (!ready) return <div dir="rtl" className="min-h-screen flex items-center justify-center" aria-label="loading"><div className="h-7 w-7 animate-spin rounded-full border-2 border-[#D4AF37] border-t-transparent" /></div>;
  return <DateContext.Provider value={value}>{children}</DateContext.Provider>;
}

export const useAppDate = () => {
  const value = useContext(DateContext);
  if (!value) throw new Error("useAppDate must be used inside AppDateProvider");
  return value;
};

export const isValidDateIso = (value) => DATE_RE.test(value || "");
export const daysInMonthIso = (year, month) => new Date(Date.UTC(Number(year), Number(month), 0)).getUTCDate();
export const buildDateIso = (year, month, day) => `${year}-${pad(month)}-${pad(day)}`;
