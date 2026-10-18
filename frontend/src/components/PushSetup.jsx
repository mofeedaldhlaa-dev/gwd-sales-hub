import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { BellRing, X } from "lucide-react";
import { toast } from "sonner";
import { getNativeNotificationStatus, isNativeApp, requestNativeNotificationPermission } from "@/lib/nativeNotifications";

function decodeKey(base64) {
  const pad = "=".repeat((4 - base64.length % 4) % 4);
  const raw = atob((base64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

const PROMPT_KEY = "jawad-push-prompt-v1";
let pushSyncPromise = null;

const syncPushSubscription = async () => {
  if (pushSyncPromise) return pushSyncPromise;
  pushSyncPromise = (async () => {
    const key = (await api.get("/push/public-key")).data?.public_key;
    if (!key) throw new Error("push-key");
    const registration = await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: decodeKey(key) });
    }
    await api.post("/push/subscribe", { subscription: subscription.toJSON() });
    return subscription;
  })().finally(() => { pushSyncPromise = null; });
  return pushSyncPromise;
};

export default function PushSetup() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const syncGranted = async () => {
      if (isNativeApp()) {
        try {
          const status = await getNativeNotificationStatus();
          if (status.display === "granted") localStorage.setItem(PROMPT_KEY, "granted");
        } catch (_) {}
        return;
      }
      if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window) || Notification.permission !== "granted") return;
      try {
        if (cancelled) return;
        await syncPushSubscription();
        localStorage.setItem(PROMPT_KEY, "granted");
      } catch (_) { /* retry on the next page load if the worker is still updating */ }
    };
    if (isNativeApp()) {
      getNativeNotificationStatus().then((status) => {
        if (!cancelled && status.display === "prompt") {
          const timer = window.setTimeout(() => setOpen(true), 900);
          return () => window.clearTimeout(timer);
        }
        if (!cancelled && status.display === "granted") syncGranted();
        return undefined;
      }).catch(() => {});
    } else if ("Notification" in window && Notification.permission === "granted") syncGranted();
    const seen = localStorage.getItem(PROMPT_KEY);
    if (!seen && "Notification" in window && Notification.permission === "default") {
      const timer = window.setTimeout(() => setOpen(true), 900);
      return () => { cancelled = true; window.clearTimeout(timer); };
    }
    return () => { cancelled = true; };
  }, []);

  const closeWithoutRepeat = () => {
    localStorage.setItem(PROMPT_KEY, "dismissed");
    setOpen(false);
  };

  const enable = async () => {
    setBusy(true);
    try {
      if (isNativeApp()) {
        const permission = await requestNativeNotificationPermission();
        if (permission.display !== "granted") {
          localStorage.setItem(PROMPT_KEY, "denied");
          setOpen(false);
          toast.error("لم يتم السماح بإشعارات Android؛ فعّلها من إعدادات التطبيق");
          return;
        }
        localStorage.setItem(PROMPT_KEY, "granted");
        setOpen(false);
        toast.success("تم تفعيل إذن إشعارات Android");
        return;
      }
      if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) {
        localStorage.setItem(PROMPT_KEY, "unsupported");
        setOpen(false);
        toast.error("الإشعارات النظامية غير مدعومة في هذا المتصفح");
        return;
      }
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        localStorage.setItem(PROMPT_KEY, "denied");
        setOpen(false);
        toast.error("لم يتم السماح بالإشعارات؛ يمكنك تفعيلها لاحقاً من إعدادات الجهاز");
        return;
      }
      await syncPushSubscription();
      localStorage.setItem(PROMPT_KEY, "granted");
      setOpen(false);
      toast.success("تم تفعيل إشعارات الهاتف");
    } catch (e) {
      localStorage.setItem(PROMPT_KEY, "failed");
      setOpen(false);
      toast.error(e?.response?.data?.detail || "تعذر تفعيل إشعارات الهاتف");
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[80] flex items-end sm:items-center justify-center p-3 bg-black/45" dir="rtl" data-testid="push-permission-dialog">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl border border-[#D4AF37]/40 overflow-hidden">
        <div className="flex items-start justify-between gap-3 p-5 bg-gradient-to-l from-[#221340] to-[#452480] text-white">
          <div><div className="flex items-center gap-2 text-lg font-black"><BellRing size={21}/> تفعيل إشعارات التطبيق</div><p className="text-sm text-white/80 mt-2">لتصلك التنبيهات المهمة حتى عند عدم فتح لوحة التحكم.</p></div>
          <button type="button" onClick={closeWithoutRepeat} className="p-1 rounded hover:bg-white/10" aria-label="إغلاق"><X size={18}/></button>
        </div>
        <div className="p-5 space-y-3">
          <p className="text-sm text-slate-600">يمكنك السماح الآن أو رفض الطلب. لن تظهر هذه النافذة بشكل مزعج في كل مرة.</p>
          <div className="flex gap-2">
            <Button type="button" onClick={enable} disabled={busy} className="flex-1 bg-[#452480] hover:bg-[#5A2FA0]" data-testid="push-enable">{busy ? "جاري التفعيل..." : "تفعيل الإشعارات"}</Button>
            <Button type="button" variant="outline" onClick={closeWithoutRepeat} disabled={busy} data-testid="push-dismiss">لاحقاً</Button>
          </div>
        </div>
      </div>
    </div>
  );
}
