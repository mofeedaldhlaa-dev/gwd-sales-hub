import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Database, RefreshCw, ShieldCheck, DownloadCloud, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { getLocalStorageHealth, initOfflineStorage, isOnline, setOfflineMeta, syncCloudDataToLocal } from "@/lib/offline";
import { getAppNow } from "@/lib/DateService";
import { useAuth } from "@/lib/auth";
import { useLocation } from "react-router-dom";
import { Capacitor } from "@capacitor/core";

const READY_KEY = "jawad-offline-initialized-native-v1";
const STORAGE_READY_KEY = `${READY_KEY}:storage`;
const PUBLIC_PATHS = ["/", "/net", "/order", "/order-card"];

const registerWorker = async () => {
  if (Capacitor.isNativePlatform()) return false;
  if (!("serviceWorker" in navigator)) return false;
  try {
    const publicBase = String(process.env.PUBLIC_URL || "").replace(/\/$/, "");
    const workerPath = `${publicBase || ""}/service-worker.js`;
    const workerScope = `${publicBase || ""}/`;
    await navigator.serviceWorker.register(workerPath, { scope: workerScope, updateViaCache: "none" });
    return true;
  } catch {
    return false;
  }
};

const isPublicPortal = (path) => PUBLIC_PATHS.includes(path) || path.startsWith("/order/") || path.startsWith("/order-card/");

export default function OfflineSetupGate({ children }) {
  const { user } = useAuth();
  const location = useLocation();
  const publicPortal = isPublicPortal(location.pathname);
  const adminApp = !publicPortal;
  const userReadyKey = useMemo(() => `${READY_KEY}:${user?.id || user?.username || "guest"}`, [user]);
  const currentReadyKey = user ? userReadyKey : STORAGE_READY_KEY;
  const [ready, setReady] = useState(() => !adminApp);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState({ percent: 0, label: "تهيئة قاعدة البيانات" });
  const [health, setHealth] = useState(null);
  const lastCloudSyncRef = useRef(0);
  const loginEntry = location.pathname === "/mof30" && (user === undefined || user === null);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      if (!adminApp) {
        if (!cancelled) setReady(true);
        return;
      }
      const stored = localStorage.getItem(currentReadyKey) === "1";
      if (!stored) {
        // Creating an empty SQLite file is not enough. Offline screens are
        // unlocked only after at least one successful online bootstrap.
        if (!isOnline() && user) {
          try {
            await initOfflineStorage();
            const localHealth = await getLocalStorageHealth();
            const hasLocalData = Number(localHealth.data || 0) > 0 || Number(localHealth.cache || 0) > 0;
            if (!hasLocalData) throw new Error("يجب الاتصال بالإنترنت مرة واحدة لتحميل البيانات إلى التخزين المحلي قبل العمل دون إنترنت.");
            localStorage.setItem(currentReadyKey, "1");
            if (!cancelled) { setHealth(localHealth); setReady(true); }
          } catch (e) {
            if (!cancelled) { setHealth(null); setError(e?.message || "لا توجد بيانات محلية بعد."); setReady(false); }
          }
          return;
        }
        if (!cancelled) { setReady(false); setHealth(null); }
        return;
      }
      if (user === undefined || user === null) {
        if (!cancelled) setReady(true);
        return;
      }
      try {
        const currentHealth = await getLocalStorageHealth();
        const validNative = currentHealth.mode !== "native-sqlite" || (Number(currentHealth.device) >= 1 && Number(currentHealth.data) > 0);
        if (!cancelled) {
          setHealth(currentHealth);
          setReady(validNative);
          if (!validNative) localStorage.removeItem(currentReadyKey);
        }
      } catch {
        if (!cancelled) setReady(false);
      }
    };
    check();
    return () => { cancelled = true; };
  }, [adminApp, currentReadyKey, user]);

  const initialize = useCallback(async () => {
    setBusy(true);
    setError("");
    setProgress({ percent: 0, label: "تهيئة قاعدة البيانات" });
    try {
      const workerReady = await registerWorker();
      await syncCloudDataToLocal(user, setProgress);
      const currentHealth = await getLocalStorageHealth();
      if (currentHealth.mode === "native-sqlite" && (!currentHealth.device || !currentHealth.data)) {
        throw new Error("لم تكتمل عملية التحقق من قاعدة البيانات الداخلية.");
      }
      await setOfflineMeta("bootstrap_complete", { completed_at: getAppNow().toISOString(), worker_ready: workerReady, health: currentHealth });
      localStorage.setItem(currentReadyKey, "1");
      setHealth(currentHealth);
      setProgress({ percent: 100, label: "اكتملت التهيئة" });
      setReady(true);
    } catch (e) {
      setProgress((current) => ({ ...current, percent: Math.min(Number(current.percent) || 0, 95) }));
      setError(e?.message || "تعذر إكمال تهيئة البيانات. سيتم إعادة المحاولة.");
      setReady(false);
    } finally {
      setBusy(false);
    }
  }, [currentReadyKey, user]);

  useEffect(() => {
    if (!adminApp || !user || ready || busy || error || !isOnline()) return;
    if (localStorage.getItem(currentReadyKey) === "1") return;
    initialize();
  }, [adminApp, busy, currentReadyKey, error, initialize, ready, user]);

  useEffect(() => {
    if (!adminApp || !user || !ready) return undefined;
    let cancelled = false;
    const refreshCloudSnapshots = async () => {
      if (!isOnline() || document.visibilityState === "hidden") return;
      const now = Date.now();
      // Avoid duplicate SQLite writes caused by Android resume plus the online
      // event arriving together, while still checking the cloud on each real
      // app launch/resume.
      if (now - lastCloudSyncRef.current < 15_000) return;
      lastCloudSyncRef.current = now;
      try {
        const result = await syncCloudDataToLocal(user);
        if (!cancelled && result?.health) setHealth(result.health);
      } catch {
        // Local data remains usable when the cloud is temporarily unavailable.
      }
    };
    const onVisible = () => { if (document.visibilityState === "visible") refreshCloudSnapshots(); };
    const onOnline = () => refreshCloudSnapshots();
    refreshCloudSnapshots();
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onOnline);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
    };
  }, [adminApp, ready, user]);

  if (!adminApp || loginEntry || ready) return children;

  return (
    <div className="min-h-screen bg-[#F6F4FB] flex items-center justify-center p-4" dir="rtl" data-testid="offline-setup-gate">
      <Card className="w-full max-w-xl p-6 sm:p-8 space-y-5 shadow-xl border-[#D4AF37]/30">
        <div className="flex items-center gap-3 text-[#221340]"><Database size={30} /><h1 className="text-2xl font-black">تهيئة التخزين المحلي</h1></div>
        <p className="text-slate-600 leading-7">يحتاج تطبيق إدارة الحسابات إلى إنشاء قاعدة بيانات محلية على الهاتف حتى يتمكن من العمل بدون إنترانت وحفظ العمليات ومزامنتها تلقائياً عند عودة الاتصال.</p>
        <div className="rounded-xl bg-emerald-50 border border-emerald-200 p-4 text-sm text-emerald-800 space-y-2">
          <div className="flex items-center gap-2 font-bold"><ShieldCheck size={18} /> التخزين داخل المساحة الخاصة بالتطبيق</div>
          <div>في نسخة Android تُنشأ قاعدة SQLite باسم gawad_net_local.db داخل تخزين التطبيق الداخلي، ولا تُستخدم مجلدات Download أو Documents أو التخزين العام.</div>
        </div>
        {busy && (
          <div className="space-y-3" data-testid="offline-bootstrap-progress">
            <div className="flex items-center justify-between text-sm font-bold text-[#452480]"><span className="flex items-center gap-2"><DownloadCloud size={17} /> جاري تحميل بيانات التطبيق...</span><span>{progress.percent}%</span></div>
            <div className="h-3 rounded-full bg-slate-200 overflow-hidden"><div className="h-full bg-[#452480] transition-all duration-300" style={{ width: `${Math.max(0, Math.min(100, progress.percent))}%` }} /></div>
            <div className="text-sm text-slate-600">{progress.label}</div>
          </div>
        )}
        {!busy && health && <div className="text-xs text-slate-500 flex items-center gap-2"><CheckCircle2 size={15} className="text-emerald-600" /> سيتم التحقق من الجداول والبيانات قبل السماح بالدخول.</div>}
        {error && <div className="rounded-lg bg-red-50 border border-red-200 text-red-700 p-3 text-sm">تعذر إكمال تهيئة البيانات. سيتم إعادة المحاولة.<br />{error}</div>}
        <Button onClick={initialize} disabled={busy} className="w-full bg-[#452480] hover:bg-[#5A2FA0]" data-testid="offline-setup-allow">
          <RefreshCw size={17} className={`ml-2 ${busy ? "animate-spin" : ""}`} />
          {busy ? "جاري تحميل بيانات التطبيق..." : "السماح بالتخزين"}
        </Button>
      </Card>
    </div>
  );
}
