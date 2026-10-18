import { useEffect, useRef, useState } from "react";
import { App as CapacitorApp } from "@capacitor/app";
import { Fingerprint, RefreshCw, SkipForward, CloudDownload, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/lib/auth";
import { syncCloudDataToLocal } from "@/lib/offline";
import { authenticateWithBiometric, isBiometricLockEnabled, isNativeAndroid } from "@/lib/nativeSecurity";
import { toast } from "sonner";

const BIOMETRIC_REAUTH_AFTER_MS = 60 * 1000;

function CloudRefreshPrompt({ openSignal, user }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState({ percent: 0, label: "جاهز لتحديث البيانات" });
  const [error, setError] = useState("");
  const handledSignal = useRef(0);

  useEffect(() => {
    if (!user || !openSignal || openSignal === handledSignal.current) return;
    handledSignal.current = openSignal;
    setError("");
    setProgress({ percent: 0, label: "جاهز لتحديث البيانات" });
    setOpen(true);
  }, [openSignal, user]);

  const close = () => {
    if (busy) return;
    setOpen(false);
    setError("");
  };

  const refresh = async () => {
    if (!navigator.onLine) {
      setError("لا يمكن تحديث البيانات من السحابة دون اتصال بالإنترنت. يمكنك المتابعة دون تحديث.");
      return;
    }
    setBusy(true);
    setError("");
    setProgress({ percent: 0, label: "بدء تحديث البيانات من السحابة" });
    try {
      await syncCloudDataToLocal(user, (step) => setProgress({
        percent: Math.max(0, Math.min(100, Number(step?.percent) || 0)),
        label: `تحديث: ${step?.label || "تحميل البيانات"}`,
      }));
      setProgress({ percent: 100, label: "اكتمل تحديث بيانات التطبيق من السحابة" });
      toast.success("تم تحديث بيانات التطبيق من السحابة");
      window.setTimeout(close, 450);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "تعذر تحديث البيانات. يمكنك المتابعة بالبيانات المحلية.");
      setProgress((current) => ({ ...current, percent: Math.min(Number(current.percent) || 0, 95) }));
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[110] bg-[#160D29]/70 backdrop-blur-sm flex items-center justify-center p-4" dir="rtl" data-testid="cloud-refresh-prompt">
      <Card className="w-full max-w-xl p-6 sm:p-8 shadow-2xl border-[#D4AF37]/50 space-y-5">
        <div className="flex items-start gap-3">
          <div className="w-11 h-11 shrink-0 rounded-full bg-[#452480]/10 text-[#452480] flex items-center justify-center"><CloudDownload size={23} /></div>
          <div>
            <h2 className="text-xl font-black text-[#221340]">تحديث بيانات التطبيق</h2>
            <p className="text-sm text-slate-600 mt-1 leading-6">يمكنك تحديث البيانات من السحابة عند الطلب، أو المتابعة مباشرة بالبيانات الموجودة محليًا. التحديث اختياري.</p>
          </div>
        </div>
        <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-3 text-sm text-emerald-800 flex gap-2"><ShieldCheck size={18} className="shrink-0" /> لن يتم حذف البيانات المحلية أو تغيير الأرصدة بسبب اختيار التحديث.</div>
        {busy && (
          <div className="space-y-2" data-testid="cloud-refresh-progress">
            <div className="flex justify-between text-sm font-bold text-[#452480]"><span>{progress.label}</span><span>{progress.percent}%</span></div>
            <div className="h-3 rounded-full bg-slate-200 overflow-hidden"><div className="h-full bg-[#452480] transition-all duration-300" style={{ width: `${progress.percent}%` }} /></div>
          </div>
        )}
        {!busy && error && <div className="rounded-lg bg-red-50 border border-red-200 text-red-700 p-3 text-sm" data-testid="cloud-refresh-error">{error}</div>}
        <div className="flex flex-col sm:flex-row gap-2">
          <Button type="button" onClick={refresh} disabled={busy} className="flex-1 bg-[#452480] hover:bg-[#5A2FA0]" data-testid="cloud-refresh-now"><RefreshCw size={16} className={`ml-2 ${busy ? "animate-spin" : ""}`} /> {busy ? "جاري التحديث..." : "تحديث الآن"}</Button>
          <Button type="button" onClick={close} disabled={busy} variant="outline" className="flex-1" data-testid="cloud-refresh-skip"><SkipForward size={16} className="ml-2" /> المتابعة بدون تحديث</Button>
        </div>
      </Card>
    </div>
  );
}

function BiometricLockOverlay({ onRetry }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const authenticatingRef = useRef(false);

  const authenticate = async () => {
    if (authenticatingRef.current) return;
    authenticatingRef.current = true;
    setBusy(true);
    setError("");
    try {
      await authenticateWithBiometric("افتح تطبيق GAWAD NET بالبصمة");
      onRetry(true);
    } catch (e) {
      setError(e?.message || "تعذر التحقق بالبصمة. حاول مرة أخرى.");
      onRetry(false);
    } finally {
      authenticatingRef.current = false;
      setBusy(false);
    }
  };

  useEffect(() => {
    // Give the Capacitor bridge and Android activity a short moment to become
    // active after a cold start or a long background resume, then open the
    // native prompt automatically. The prompt itself owns the fingerprint UI.
    const timer = window.setTimeout(() => authenticate(), 220);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <div className="fixed inset-0 z-[120] bg-[#160D29]/85 backdrop-blur-sm flex items-center justify-center p-4" dir="rtl" data-testid="biometric-lock-overlay">
      <Card className="w-full max-w-md p-6 sm:p-8 shadow-2xl border-[#D4AF37]/50 space-y-5 text-center">
        <div className="mx-auto w-16 h-16 rounded-full bg-[#452480]/10 text-[#452480] flex items-center justify-center"><Fingerprint size={34} /></div>
        <div>
          <h1 className="text-xl font-black text-[#221340]">التطبيق مقفل بالبصمة</h1>
          <p className="text-sm text-slate-600 mt-2 leading-6">استخدم بصمة الجهاز للعودة إلى تطبيق GAWAD NET.</p>
        </div>
        {error && <div className="rounded-md border border-red-200 bg-red-50 text-red-700 text-sm px-3 py-2" data-testid="biometric-lock-error">{error}</div>}
        <Button type="button" onClick={authenticate} disabled={busy} className="w-full bg-[#221340] hover:bg-[#311B5C]" data-testid="biometric-lock-retry">
          <Fingerprint size={17} className="ml-2" /> {busy ? "جاري التحقق..." : "المحاولة بالبصمة"}
        </Button>
      </Card>
    </div>
  );
}

export default function SessionSecurityGate({ children }) {
  const { user } = useAuth();
  const [openSignal, setOpenSignal] = useState(0);
  const [biometricLocked, setBiometricLocked] = useState(false);
  const backgroundAtRef = useRef(null);

  const lockForBiometric = () => {
    let hasSession = false;
    try { hasSession = Boolean(localStorage.getItem("jwd_token")); } catch {}
    if (isNativeAndroid() && hasSession && isBiometricLockEnabled()) {
      setBiometricLocked(true);
      return true;
    }
    return false;
  };

  useEffect(() => {
    // Start the native prompt from the app bootstrap, before /auth/me finishes.
    // This makes the fingerprint sensor usable immediately after opening the
    // APK instead of waiting for the authenticated React view to mount.
    const timer = window.setTimeout(() => {
      lockForBiometric();
    }, 180);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!isNativeAndroid()) return undefined;
    let disposed = false;
    const markBackground = () => { backgroundAtRef.current = Date.now(); };
    const checkResume = () => {
      const backgroundAt = backgroundAtRef.current;
      backgroundAtRef.current = null;
      if (!backgroundAt || disposed) return;
      if (Date.now() - backgroundAt >= BIOMETRIC_REAUTH_AFTER_MS) lockForBiometric();
    };
    const appStateListener = CapacitorApp.addListener("appStateChange", ({ isActive }) => {
      if (isActive) checkResume();
      else markBackground();
    });
    const onVisibilityChange = () => {
      if (document.hidden) markBackground();
      else checkResume();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      disposed = true;
      appStateListener.then((listener) => listener.remove()).catch(() => {});
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, []);

  useEffect(() => {
    if (!user) return undefined;
    const openRefreshPrompt = () => setOpenSignal((value) => value + 1);
    window.addEventListener("open-cloud-refresh", openRefreshPrompt);
    // Hiding the Android WebView is normal backgrounding and must not lock or
    // recreate the UI. A process/activity recreation mounts this gate again;
    // the bootstrap effect above asks for the biometric credential then.
    return () => {
      window.removeEventListener("open-cloud-refresh", openRefreshPrompt);
    };
  }, [user]);

  useEffect(() => {
    if (!user) {
      setBiometricLocked(false);
    }
  }, [user]);

  return (
    <>
      {children}
      <CloudRefreshPrompt openSignal={openSignal} user={user} />
      {biometricLocked && user && <BiometricLockOverlay onRetry={(ok) => { if (ok) setBiometricLocked(false); }} />}
    </>
  );
}
