import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import api, { errText } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog";
import { toast } from "sonner";
import { fmt } from "@/lib/utils";
import { Database, RotateCcw, Trash2, Download, Upload, Send, CloudDownload, Plus, Coins, Bell, X, CheckCircle2, Smartphone, Fingerprint, FolderOpen } from "lucide-react";
import IncentivesManager from "@/pages/IncentivesManager";
import { useAuth } from "@/lib/auth";
import { usePWAInstall } from "@/lib/pwaInstall";
import { getNativeNotificationStatus, isNativeApp, scheduleNativeTestNotification } from "@/lib/nativeNotifications";
import { checkDevicePermissions, requestDevicePermissions } from "@/lib/devicePermissions";
import { authenticateWithBiometric, getBiometricAvailability, isBiometricLockEnabled, isNativeAndroid, setBiometricLockEnabled } from "@/lib/nativeSecurity";
import { ensureNativeDatabaseFile, openNativeDatabaseFile } from "@/lib/nativeLocalDatabase";
import { clearSmsGatewayQueue, configureSmsGateway, flushSmsGatewayQueue, getSmsGatewayStatus, requestSmsGatewayPermission, setSmsGatewayEnabled, syncSmsGatewaySenderIds } from "@/lib/nativeSmsGateway";
import { getBackgroundWatchStatus, openBackgroundWatchSettings, openBackgroundWatchNotificationSettings, showBackgroundWatchTest } from "@/lib/backgroundWatch";

import { todayIso } from "@/lib/DateService";
function CurrenciesManager() {
  const [items, setItems] = useState([]);
  const [form, setForm] = useState({ name: "", symbol: "", rate_to_yer: "", active: true });
  const [editing, setEditing] = useState(null);
  const load = () => api.get("/currencies").then((r) => setItems(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);
  const save = async () => {
    if (!form.name.trim() || !form.symbol.trim() || !form.rate_to_yer || Number(form.rate_to_yer) <= 0) {
      toast.error("اكمل بيانات العملة"); return;
    }
    try {
      const payload = { name: form.name.trim(), symbol: form.symbol.trim(), rate_to_yer: Number(form.rate_to_yer), active: !!form.active };
      if (editing) await api.put(`/currencies/${editing.id}`, payload);
      else await api.post("/currencies", payload);
      toast.success("تم الحفظ");
      setForm({ name: "", symbol: "", rate_to_yer: "", active: true });
      setEditing(null);
      load();
    } catch (e) { toast.error(errText(e)); }
  };
  const remove = async (c) => {
    if (!window.confirm(`حذف العملة "${c.name}"؟ إذا كانت مستخدمة سيتم تعطيلها فقط دون حذف السجل التاريخي.`)) return;
    try {
      const r = await api.delete(`/currencies/${c.id}`);
      toast.success(r.data.action === "disabled" ? "تم تعطيل العملة (لأنها مستخدمة في عمليات سابقة)" : "تم الحذف");
      load();
    } catch (e) { toast.error(errText(e)); }
  };
  const beginEdit = (c) => { setEditing(c); setForm({ name: c.name, symbol: c.symbol, rate_to_yer: c.rate_to_yer, active: !!c.active }); };
  return (
    <div className="space-y-3">
      <div className="text-xs text-slate-500 bg-blue-50 border border-blue-200 rounded p-2">
        <Coins size={12} className="inline ml-1"/>
        يتم حفظ العملة وسعر الصرف مع كل عملية. تغيير سعر الصرف يؤثر على العمليات الجديدة فقط.
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-2 items-end">
        <div><Label>الاسم</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="دولار أمريكي" data-testid="cur-name"/></div>
        <div><Label>الرمز</Label><Input value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} placeholder="USD" data-testid="cur-symbol"/></div>
        <div><Label>سعر مقابل الريال</Label><Input type="number" value={form.rate_to_yer} onChange={(e) => setForm({ ...form, rate_to_yer: e.target.value })} placeholder="530" data-testid="cur-rate"/></div>
        <div className="flex flex-col gap-1">
          <label className="text-xs flex items-center gap-1"><input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} data-testid="cur-active"/> مفعّلة</label>
          <Button onClick={save} className="bg-[#221340]" data-testid="cur-save"><Plus size={14} className="ml-1"/> {editing ? "تحديث" : "إضافة"}</Button>
          {editing && <button onClick={() => { setEditing(null); setForm({ name: "", symbol: "", rate_to_yer: "", active: true }); }} className="text-xs text-slate-500 hover:underline">إلغاء التعديل</button>}
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50"><tr className="text-right"><th className="p-2">الاسم</th><th className="p-2">الرمز</th><th className="p-2">السعر (ريال)</th><th className="p-2">الحالة</th><th className="p-2">إجراء</th></tr></thead>
          <tbody>
            {items.map((c) => (
              <tr key={c.id} className="border-t">
                <td className="p-2">{c.name}</td>
                <td className="p-2 font-mono">{c.symbol}</td>
                <td className="p-2 num">{fmt(c.rate_to_yer)}</td>
                <td className="p-2"><span className={`text-xs px-2 py-0.5 rounded-full ${c.active ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-600"}`}>{c.active ? "مفعّلة" : "معطلة"}</span></td>
                <td className="p-2 flex gap-1">
                  <Button size="sm" variant="outline" className="h-6 text-xs" onClick={() => beginEdit(c)} data-testid={`cur-edit-${c.id}`}>تعديل</Button>
                  <Button size="sm" variant="outline" className="h-6 text-xs text-red-600" onClick={() => remove(c)} data-testid={`cur-del-${c.id}`}><Trash2 size={12}/></Button>
                </td>
              </tr>
            ))}
            {items.length === 0 && <tr><td colSpan={5} className="p-4 text-center text-slate-400">لا توجد عملات — أضف عملة جديدة أعلاه</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}


function InstallAppPanel() {
  const { user } = useAuth();
  const { canInstall, installed, promptInstall } = usePWAInstall();
  const [allowed, setAllowed] = useState([]);
  const [raw, setRaw] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [installedFlag, setInstalledFlag] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [pushStatus, setPushStatus] = useState(null);
  const [testingPush, setTestingPush] = useState(false);
  const [devicePerms, setDevicePerms] = useState(null);
  const [bgWatch, setBgWatch] = useState(null);

  useEffect(() => {
    setLoading(true);
    api.get("/settings").then((r) => {
      const list = r.data?.install_allowed_emails || [];
      setAllowed(list);
      setRaw(list.join("\n"));
    }).finally(() => setLoading(false));
    if (isNativeApp()) {
      checkDevicePermissions().then(setDevicePerms).catch(() => {});
      getBackgroundWatchStatus().then(setBgWatch).catch(() => {});
      getNativeNotificationStatus()
        .then((status) => setPushStatus({ native: true, configured: true, subscribed: status.display === "granted", devices: status.display === "granted" ? 1 : 0, display: status.display }))
        .catch(() => setPushStatus({ native: true, configured: true, subscribed: false, devices: 0, display: "prompt" }));
    } else {
      api.get("/push/status").then((r) => setPushStatus(r.data)).catch(() => setPushStatus({ configured: false, subscribed: false, devices: 0 }));
    }
    try { setInstalledFlag(!!localStorage.getItem("gwd_admin_pwa_installed")); } catch {}
    const onInstalled = () => {
      try { localStorage.setItem("gwd_admin_pwa_installed", String(Date.now())); } catch {}
      setInstalledFlag(true);
    };
    window.addEventListener("appinstalled", onInstalled);
    return () => window.removeEventListener("appinstalled", onInstalled);
  }, []);

  const meAllowed = user?.email && allowed.map((e) => e.toLowerCase()).includes(user.email.toLowerCase());
  const isSuperAdmin = user?.role === "admin";
  const isInstalled = installed || installedFlag;

  const save = async () => {
    const list = raw
      .split(/[\n,;]+/)
      .map((e) => e.trim().toLowerCase())
      .filter(Boolean);
    setSaving(true);
    try {
      await api.post("/settings", { install_allowed_emails: list });
      setAllowed(list);
      toast.success("تم تحديث قائمة المسموح لهم بالتثبيت");
    } catch (e) { toast.error(errText(e)); }
    setSaving(false);
  };

  const doInstall = async () => {
    if (!meAllowed) { toast.error("هذا الإيميل غير مسموح له بتثبيت تطبيق الإدارة"); return; }
    if (!canInstall) {
      toast.error("المتصفح لم يعرض خيار التثبيت بعد. افتح التطبيق مرة أخرى بعد ثوانٍ، أو استخدم قائمة المتصفح: تثبيت التطبيق.");
      return;
    }
    const outcome = await promptInstall();
    if (outcome === "accepted") {
      try { localStorage.setItem("gwd_admin_pwa_installed", String(Date.now())); } catch {}
      setInstalledFlag(true);
      toast.success("تم بدء التثبيت");
    }
  };

  const doUpdate = async () => {
    setUpdating(true);
    try {
      if ("serviceWorker" in navigator) {
        const regs = await navigator.serviceWorker.getRegistrations();
        await Promise.all(regs.map((r) => r.update().catch(() => {})));
      }
      if ("caches" in window) {
        const keys = await caches.keys();
        await Promise.all(keys.filter((k) => !k.startsWith("jawad-")).map((k) => caches.delete(k)));
      }
      toast.success("جارٍ تحميل أحدث نسخة...");
      setTimeout(() => window.location.reload(true), 700);
    } catch (e) {
      toast.error("تعذّر التحقق من التحديث");
      setUpdating(false);
    }
  };

  const resetInstall = () => {
    if (!window.confirm("إعادة تفعيل زر التثبيت — يستخدم فقط لو أُلغي التطبيق من الجهاز. متابعة؟")) return;
    try { localStorage.removeItem("gwd_admin_pwa_installed"); } catch {}
    setInstalledFlag(false);
    toast.info("تم إعادة تفعيل زر التثبيت");
  };

  const testPush = async () => {
    setTestingPush(true);
    try {
      if (isNativeApp()) {
        const status = await scheduleNativeTestNotification();
        if (status.display !== "granted") {
          toast.error("إذن إشعارات Android غير مفعّل؛ فعّله من إعدادات التطبيق ثم أعد المحاولة.");
          setPushStatus((current) => ({ ...(current || {}), native: true, configured: true, subscribed: false, devices: 0, display: status.display }));
          return;
        }
        toast.success("تم جدولة إشعار اختبار Android");
        setPushStatus({ native: true, configured: true, subscribed: true, devices: 1, display: "granted" });
        return;
      }
      const response = await api.post("/push/test", { title: "اختبار إشعارات GAWAD NET", message: "إذا ظهرت هذه الرسالة فاشتراك هذا الجهاز يعمل." });
      if (!response.data?.ok) {
        toast.error("لم يؤكد مزود Push تسليم الإشعار؛ تحقق من إذن الجهاز والاشتراك.");
        return;
      }
      toast.success("أرسل الخادم إشعار الاختبار بنجاح");
      const status = await api.get("/push/status");
      setPushStatus(status.data);
    } catch (error) {
      toast.error(errText(error) || "تعذر إرسال إشعار الاختبار");
    } finally {
      setTestingPush(false);
    }
  };

  const requestDeviceAccess = async () => {
    try {
      const status = await requestDevicePermissions();
      setDevicePerms(status);
      toast.success("تم تحديث صلاحيات الجهاز؛ راجع الحالات المعروضة أدناه");
    } catch (error) {
      toast.error(errText(error) || "تعذر طلب صلاحيات الجهاز");
    }
  };

  return (
    <div className="space-y-4" data-testid="install-panel">
      <div className="rounded-lg border border-[#452480]/20 bg-[#F8F5FF] p-3 flex items-start gap-3">
        <div className="w-10 h-10 rounded-full bg-[#452480] text-white flex items-center justify-center shrink-0">
          <Smartphone size={20}/>
        </div>
        <div className="flex-1 text-sm">
          <div className="font-bold text-[#221340]">إدارة الحسابات (MOF30)</div>
          <div className="text-xs text-slate-600 mt-1 leading-relaxed">
            ثبّت لوحة الإدارة كتطبيق مستقل على شاشة الجهاز (يفتح مباشرة على النطاق <span dir="ltr" className="font-mono">/mof30</span>). التثبيت مسموح فقط للإيميلات المضافة أدناه، ومسموح <b>مرة واحدة</b> — بعدها يظهر زر «تحديث التطبيق».
          </div>
          <div className="mt-2 flex items-center gap-2 flex-wrap">
            {isInstalled ? (
              <>
                <Button
                  onClick={doUpdate}
                  disabled={updating}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white"
                  data-testid="update-admin-btn"
                >
                  <RotateCcw size={14} className="ml-1"/>
                  {updating ? "جاري التحديث..." : "تحديث التطبيق"}
                </Button>
                <span className="text-[11px] px-2 py-1 rounded-full bg-emerald-100 text-emerald-800 font-bold">التطبيق مثبَّت مسبقاً</span>
                {isSuperAdmin && (
                  <button
                    type="button"
                    onClick={resetInstall}
                    className="text-[11px] text-slate-500 hover:text-red-600 hover:underline"
                    data-testid="reset-install-flag"
                  >
                    إعادة تفعيل زر التثبيت
                  </button>
                )}
              </>
            ) : (
              <>
                <Button
                  onClick={doInstall}
                  disabled={loading || !meAllowed}
                  className="bg-[#452480] hover:bg-[#5A2FA0] text-white"
                  data-testid="install-admin-btn"
                >
                  <Download size={14} className="ml-1"/>
                  {meAllowed ? "تثبيت تطبيق الإدارة" : "غير مسموح لك بالتثبيت"}
                </Button>
                <span className="text-[11px] text-slate-500">
                  حالتك: {user?.email ? <span className="font-mono" dir="ltr">{user.email}</span> : "لا يوجد بريد لحسابك"} —
                  {meAllowed ? <span className="text-emerald-700 font-bold"> مسموح</span> : <span className="text-red-700 font-bold"> غير مسموح</span>}
                </span>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="border rounded-lg p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3" data-testid="push-status-panel">
        <div>
          <div className="font-bold text-sm text-[#221340] flex items-center gap-2"><Bell size={15}/> إشعارات الهاتف</div>
          <div className="text-xs text-slate-600 mt-1">
            {!pushStatus ? "جاري فحص الاشتراك..." : pushStatus.native ? (pushStatus.subscribed ? "إذن إشعارات Android مفعّل" : "إذن إشعارات Android غير مفعّل") : !pushStatus.configured ? "مفاتيح Push غير مكتملة على الخادم" : pushStatus.subscribed ? `مشترك — ${pushStatus.devices} جهاز` : "لا يوجد اشتراك محفوظ لهذا المستخدم"}
          </div>
        </div>
        <Button type="button" variant="outline" onClick={testPush} disabled={testingPush || !pushStatus?.configured || !pushStatus?.subscribed}>
          {testingPush ? "جاري الاختبار..." : pushStatus?.native ? "اختبار إشعار Android" : "إرسال إشعار اختبار"}
        </Button>
      </div>

      {isNativeApp() && (
        <div className="border rounded-lg p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3" data-testid="background-watch-panel">
          <div className="min-w-0">
            <div className="font-bold text-sm text-[#221340] flex items-center gap-2"><Bell size={15}/> الإشعارات والتطبيق مغلق</div>
            <div className="text-xs text-slate-600 mt-1">
              {bgWatch === null
                ? "جاري فحص خدمة الخلفية..."
                : bgWatch?.running
                  ? `الخدمة تعمل${watchAge(bgWatch?.last_check) ? ` — آخر فحص ${watchAge(bgWatch.last_check)}` : ""}`
                  : "الخدمة متوقفة — افتح التطبيق لتشغيلها"}
            </div>
            <div className="flex flex-wrap gap-2 text-[11px] mt-2">
              <span className={`px-2 py-1 rounded-full ${bgWatch?.notifications_enabled === false ? "bg-rose-100 text-rose-700" : "bg-emerald-100 text-emerald-700"}`} data-testid="background-watch-permission">
                إذن الإشعارات: {bgWatch?.notifications_enabled === false ? "مغلق" : "مفتوح"}
              </span>
              <span className={`px-2 py-1 rounded-full ${bgWatch?.battery_optimized ? "bg-amber-100 text-amber-700" : "bg-emerald-100 text-emerald-700"}`}>
                قيود البطارية: {bgWatch?.battery_optimized ? "مفعّلة" : "غير مفعّلة"}
              </span>
              {bgWatch?.last_error ? (
                <span className="px-2 py-1 rounded-full bg-rose-100 text-rose-700">آخر خطأ: {watchErrorLabel(bgWatch.last_error)}</span>
              ) : null}
            </div>
            <div className="text-[11px] text-slate-500 mt-2">
              تصل إشعارات الإدارة وطلبات الحساب وتنبيهات المخزون حتى لو كان التطبيق مغلقاً. تُعرض أحدث التنبيهات عند إغلاق التطبيق أو تصغيره، ويظهر إشعار دائم أثناء عمل الخدمة (شرط أندرويد). لضمان الاستمرار اسمح للتطبيق بالتشغيل التلقائي وبدون قيود على البطارية.
            </div>
          </div>
          <div className="flex flex-col gap-2 shrink-0">
            <Button
              type="button"
              variant="outline"
              onClick={async () => {
                const result = await showBackgroundWatchTest();
                if (result === null) toast.error("الإشعار التجريبي يعمل داخل تطبيق أندرويد فقط");
                else if (result && result.notifications_enabled === false) toast.error("إذن الإشعارات مغلق — افتح إعدادات الإشعارات واسمح بها");
                else toast.success("تم إرسال إشعار تجريبي — تحقق من شريط الإشعارات");
              }}
              data-testid="background-watch-test-btn"
            >
              إرسال إشعار تجريبي
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={async () => {
                const result = await openBackgroundWatchNotificationSettings();
                if (!result) toast.error("تعذّر فتح إعدادات الإشعارات — افتحها من إعدادات النظام");
              }}
              data-testid="background-watch-notification-settings-btn"
            >
              إعدادات الإشعارات
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={async () => {
                const result = await openBackgroundWatchSettings();
                if (!result) toast.error("تعذّر فتح إعدادات النظام — افتحها يدوياً: البطارية ← بلا قيود");
              }}
              data-testid="background-watch-settings-btn"
            >
              إعدادات البطارية
            </Button>
          </div>
        </div>
      )}

      {isNativeApp() && (
        <div className="border rounded-lg p-3 space-y-2" data-testid="device-permissions-panel">
          <div className="font-bold text-sm text-[#221340]">صلاحيات التطبيق</div>
          <div className="text-xs text-slate-600">تستخدم جهات الاتصال لاختيار رقم المشترك، وتستخدم صلاحية الملفات والوسائط لاختيار أو رفع الملفات من الجهاز.</div>
          <div className="flex flex-wrap gap-2 text-xs">
            <span className={`px-2 py-1 rounded-full ${devicePerms?.contacts === "granted" || devicePerms?.contacts === "limited" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>جهات الاتصال: {devicePerms?.contacts || "جاري الفحص"}</span>
            <span className={`px-2 py-1 rounded-full ${devicePerms?.storage === "granted" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>الملفات والوسائط: {devicePerms?.storage || "جاري الفحص"}</span>
          </div>
          <Button type="button" variant="outline" onClick={requestDeviceAccess}>طلب صلاحيات الجهاز</Button>
        </div>
      )}

      {isSuperAdmin && (
        <div className="border rounded-lg p-3">
          <div className="font-bold text-sm text-[#221340] mb-2">قائمة الإيميلات المسموح لها بالتثبيت</div>
          <div className="text-[11px] text-slate-500 mb-2">إيميل واحد في كل سطر (أو مفصولة بفاصلة).</div>
          <textarea
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            rows={4}
            className="w-full border rounded-md p-2 text-sm font-mono"
            dir="ltr"
            placeholder="admin@example.com"
            data-testid="install-allowed-list"
          />
          <div className="mt-2 flex items-center justify-between">
            <div className="text-[11px] text-slate-500">
              حالياً: <strong>{allowed.length}</strong> إيميل مسموح
            </div>
            <Button onClick={save} disabled={saving} className="bg-[#221340]" data-testid="install-allowed-save">
              {saving ? "جاري..." : "حفظ القائمة"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function BiometricLockPanel() {
  const [enabled, setEnabled] = useState(isBiometricLockEnabled());
  const [availability, setAvailability] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getBiometricAvailability().then(setAvailability).catch((error) => setAvailability({ available: false, reason: error?.message || "تعذر فحص البصمة" }));
  }, []);

  const toggle = async () => {
    if (enabled) {
      setBiometricLockEnabled(false);
      setEnabled(false);
      toast.success("تم إيقاف قفل التطبيق بالبصمة");
      return;
    }
    if (!isNativeAndroid()) {
      toast.error("قفل البصمة متاح داخل تطبيق Android فقط");
      return;
    }
    if (!availability?.available) {
      toast.error(availability?.reason || "البصمة غير متاحة على هذا الجهاز");
      return;
    }
    setBusy(true);
    try {
      await authenticateWithBiometric("تأكيد تفعيل قفل تطبيق GAWAD NET");
      setBiometricLockEnabled(true);
      setEnabled(true);
      toast.success("تم تفعيل قفل التطبيق بالبصمة");
    } catch (error) {
      toast.error(error?.message || "لم يتم تفعيل قفل البصمة");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-6 space-y-3" data-testid="biometric-lock-card">
      <div className="flex items-center gap-2 text-lg font-bold text-[#221340]"><Fingerprint size={20} /> قفل التطبيق بالبصمة</div>
      <p className="text-sm text-slate-600 leading-6">عند تفعيل هذا الخيار سيطلب التطبيق بصمة الجهاز عند العودة إليه بعد مغادرته. هذا الخيار لا يلغي رسالة تحديث البيانات الاختيارية.</p>
      <div className="flex items-center justify-between gap-3 rounded-lg border bg-slate-50 p-3">
        <div>
          <div className="font-bold text-sm">الحالة: {enabled ? "مفعّل" : "متوقف"}</div>
          <div className="text-xs text-slate-500 mt-1">{availability?.reason || "جاري فحص البصمة..."}</div>
        </div>
        <Button type="button" onClick={toggle} disabled={busy || availability?.available === false && !enabled} className={enabled ? "bg-red-600 hover:bg-red-700" : "bg-[#452480] hover:bg-[#5A2FA0]"} data-testid="biometric-lock-toggle">
          <Fingerprint size={15} className="ml-1" /> {busy ? "جاري التحقق..." : enabled ? "إيقاف القفل" : "تفعيل القفل"}
        </Button>
      </div>
    </Card>
  );
}

function SmsGatewaySettingsPanel() {
  const [form, setForm] = useState({ baseUrl: "", deviceId: "", secret: "", enabled: false });
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [permissionBusy, setPermissionBusy] = useState(false);
  const [queueBusy, setQueueBusy] = useState(false);
  const native = isNativeApp();

  const refreshStatus = useCallback(async () => {
    if (!native) {
      setStatus({ supported: false, reason: "يتطلب تطبيق Android" });
      return;
    }
    try {
      const next = await getSmsGatewayStatus();
      setStatus({ supported: true, ...next });
      try {
        const banks = await api.get("/bank-accounts");
        const senderIds = (banks.data || [])
          .filter((bank) => bank.active !== false)
          .flatMap((bank) => bank.gateway_sender_ids || [])
          .filter(Boolean)
          .join(",");
        await syncSmsGatewaySenderIds(senderIds);
      } catch (_) {}
      setForm((current) => ({ ...current, enabled: Boolean(next?.enabled), baseUrl: current.baseUrl || next?.base_url || "", deviceId: current.deviceId || next?.device_id || "" }));
    } catch (error) {
      setStatus({ supported: false, reason: error?.message || "تعذر قراءة حالة Gateway" });
    }
  }, [native]);

  useEffect(() => { refreshStatus(); }, [refreshStatus]);

  const requestPermission = async () => {
    setPermissionBusy(true);
    try {
      const result = await requestSmsGatewayPermission();
      toast.success(result?.granted ? "تم منح إذن استقبال الرسائل" : "تم تحديث إذن استقبال الرسائل");
      await refreshStatus();
    } catch (error) {
      toast.error(error?.message || "لم يتم منح إذن استقبال الرسائل");
    } finally {
      setPermissionBusy(false);
    }
  };

  const save = async () => {
    if (!native) { toast.error("إعداد SMS Gateway متاح داخل تطبيق Android فقط"); return; }
    if (!form.secret || form.secret.trim().length < 32) { toast.error("أدخل مفتاح HMAC بطول 32 حرفاً على الأقل"); return; }
    setBusy(true);
    try {
      const result = await configureSmsGateway(form);
      setForm((current) => ({ ...current, secret: "", enabled: Boolean(result?.enabled) }));
      toast.success("تم حفظ إعدادات SMS Gateway بأمان");
      await refreshStatus();
    } catch (error) {
      toast.error(error?.message || "تعذر حفظ إعدادات SMS Gateway");
    } finally {
      setBusy(false);
    }
  };

  const toggle = async () => {
    setBusy(true);
    try {
      const result = await setSmsGatewayEnabled(!form.enabled);
      setForm((current) => ({ ...current, enabled: Boolean(result?.enabled) }));
      toast.success(result?.enabled ? "تم تفعيل استقبال SMS Gateway" : "تم إيقاف استقبال SMS Gateway");
      await refreshStatus();
    } catch (error) {
      toast.error(error?.message || "تعذر تغيير حالة SMS Gateway");
    } finally {
      setBusy(false);
    }
  };

  const flushQueue = async () => {
    setQueueBusy(true);
    try {
      await flushSmsGatewayQueue();
      toast.success("تم تشغيل رفع الرسائل المعلقة");
      await refreshStatus();
    } catch (error) {
      toast.error(error?.message || "تعذر تشغيل رفع الرسائل");
    } finally {
      setQueueBusy(false);
    }
  };

  const clearQueue = async () => {
    if (!window.confirm("سيتم حذف الرسائل غير المرفوعة من طابور هذا الجهاز فقط، ولن تُحذف الرسائل التي وصلت إلى الخادم. متابعة؟")) return;
    setQueueBusy(true);
    try {
      await clearSmsGatewayQueue();
      toast.success("تم مسح طابور الجهاز المحلي");
      await refreshStatus();
    } catch (error) {
      toast.error(error?.message || "تعذر مسح الطابور المحلي");
    } finally {
      setQueueBusy(false);
    }
  };

  return (
    <Card className="p-6 space-y-4" data-testid="sms-gateway-settings-card">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-full bg-[#452480] text-white flex items-center justify-center shrink-0"><Smartphone size={20}/></div>
        <div>
          <div className="text-lg font-bold text-[#221340]">SMS Gateway للحسابات البنكية</div>
          <p className="text-xs text-slate-600 mt-1 leading-6">يستقبل التطبيق رسائل Sender IDs المعتمدة فقط، يضعها في طابور محلي مشفّر، ثم يرفعها موقّعة إلى الخادم للمراجعة. لا ينشئ هذا القسم سنداً ولا يعدّل الرصيد تلقائياً.</p>
        </div>
      </div>

      {!native && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800" data-testid="sms-gateway-web-warning">افتح هذه الصفحة داخل تطبيق Android لإعداد Gateway واستقبال الرسائل الفعلية.</div>}

      <div className="grid grid-cols-1 gap-3">
        <div><Label>عنوان الخادم HTTPS</Label><Input value={form.baseUrl} onChange={(e) => setForm({ ...form, baseUrl: e.target.value })} placeholder="https://example.com" dir="ltr" data-testid="sms-gateway-base-url" disabled={!native}/></div>
        <div><Label>معرّف جهاز الاستقبال</Label><Input value={form.deviceId} onChange={(e) => setForm({ ...form, deviceId: e.target.value })} placeholder="gateway-phone-01" dir="ltr" data-testid="sms-gateway-device-id" disabled={!native}/></div>
        <div><Label>مفتاح HMAC السري</Label><Input type="password" value={form.secret} onChange={(e) => setForm({ ...form, secret: e.target.value })} placeholder="يُحفظ داخل Android Keystore ولا يُعرض لاحقاً" dir="ltr" autoComplete="new-password" data-testid="sms-gateway-secret" disabled={!native}/></div>
        <div className="rounded-md border border-blue-200 bg-blue-50 p-2 text-xs text-blue-900">يتم التعرف على Sender ID تلقائياً من معرّفات المرسل المحفوظة داخل شاشة الحسابات البنكية والمحافظ، ولا يحتاج هذا الهاتف إلى إدخالها يدوياً.</div>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={requestPermission} disabled={!native || permissionBusy} variant="outline" data-testid="sms-gateway-permission">
          {permissionBusy ? "جاري الطلب..." : "طلب إذن استقبال SMS"}
        </Button>
        <Button type="button" onClick={save} disabled={!native || busy} className="bg-[#452480] hover:bg-[#5A2FA0]" data-testid="sms-gateway-save">
          {busy ? "جاري الحفظ..." : "حفظ إعدادات Gateway"}
        </Button>
      </div>

      <div className="rounded-lg border bg-slate-50 p-3 space-y-3" data-testid="sms-gateway-status">
        <div className="flex flex-wrap gap-2 text-xs">
          <span className={`px-2 py-1 rounded-full ${status?.permission === "GRANTED" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>الإذن: {status?.permission || "غير معروف"}</span>
          <span className={`px-2 py-1 rounded-full ${status?.configured ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-600"}`}>الإعداد: {status?.configured ? "مكتمل" : "غير مكتمل"}</span>
          <span className={`px-2 py-1 rounded-full ${status?.enabled ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-600"}`}>الحالة: {status?.enabled ? "مفعّل" : "متوقف"}</span>
          <span className="px-2 py-1 rounded-full bg-blue-100 text-blue-700">الطابور: {status?.queue_size ?? "—"}</span>
        </div>
        <div className="text-xs text-slate-500">{status?.last_received_at ? `آخر رسالة: ${new Date(Number(status.last_received_at)).toLocaleString("ar-YE")}` : "لم تُستقبل رسالة على هذا الجهاز بعد."}</div>
        {status?.last_upload_status && status.last_upload_status !== "200" && status.last_upload_status !== "201" && (
          <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900" data-testid="sms-gateway-last-upload-error">
            <div className="font-bold">آخر نتيجة رفع: HTTP {status.last_upload_status} — المرسل: <span dir="ltr" className="font-mono">{status.last_upload_sender || "غير معروف"}</span></div>
            {status.last_upload_error && <div className="mt-1 break-words">{status.last_upload_error}</div>}
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <Button type="button" onClick={toggle} disabled={!native || !status?.configured || busy} className={form.enabled ? "bg-red-600 hover:bg-red-700" : "bg-emerald-700 hover:bg-emerald-800"} data-testid="sms-gateway-toggle">
            {form.enabled ? "إيقاف Gateway" : "تفعيل Gateway"}
          </Button>
          <Button type="button" onClick={flushQueue} disabled={!native || queueBusy} variant="outline" data-testid="sms-gateway-flush">رفع الطابور الآن</Button>
          <Button type="button" onClick={clearQueue} disabled={!native || queueBusy} variant="outline" className="text-red-700" data-testid="sms-gateway-clear">مسح الطابور المحلي</Button>
        </div>
      </div>
    </Card>
  );
}

const watchAge = (value) => {
  const ms = Number(value || 0);
  if (!ms || Number.isNaN(ms)) return "";
  const minutes = Math.max(0, Math.round((Date.now() - ms) / 60000));
  if (minutes < 1) return "قبل لحظات";
  if (minutes === 1) return "قبل دقيقة";
  if (minutes < 60) return `قبل ${minutes} دقيقة`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `قبل ${hours} ساعة`;
  return `قبل ${Math.round(hours / 24)} يوم`;
};

const watchErrorLabel = (code) => (
  {
    session_expired: "انتهت الجلسة — افتح التطبيق لتجديدها",
    no_token: "لا توجد جلسة محفوظة",
  }[code] || String(code || "")
);

export default function SettingsPage() {
  const [s, setS] = useState({ currency: "ريال", logo_url: "", low_stock_default: 20, backup_email: "",  });
  const [backupEmails, setBackupEmails] = useState([""]);
  const [savingEmail, setSavingEmail] = useState(false);
  const [backupSettings, setBackupSettings] = useState({ time: "02:00", auto: false });
  const [savingAuto, setSavingAuto] = useState(false);
  const [runningNow, setRunningNow] = useState(false);
  const [latestBackup, setLatestBackup] = useState(null);
  const [restoringCloud, setRestoringCloud] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetForm, setResetForm] = useState({ username: "", password: "" });
  const [localDbBusy, setLocalDbBusy] = useState(false);

  useEffect(() => {
    api.get("/settings").then((r) => {
      setS(r.data);
      setBackupEmails(r.data.backup_emails?.length ? r.data.backup_emails : (r.data.backup_email ? [r.data.backup_email] : [""]));
      setBackupSettings({
        time: r.data.backup_time || "02:00",
        auto: !!r.data.backup_auto,
      });
    });
    api.get("/backup/latest").then((r) => {
      if (r.data?.exists) setLatestBackup(r.data);
    }).catch(() => {});
  }, []);

  const save = async () => {
    try { await api.post("/settings", s); const latest = await api.get("/settings"); setS(latest.data || s); toast.success("تم الحفظ"); } catch (e) { toast.error(errText(e)); }
  };

  const saveBackupEmail = async () => {
    const emails = backupEmails.map((v) => String(v || "").trim().toLowerCase()).filter(Boolean);
    if (!emails.length || emails.some((v) => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v))) {
      toast.error("يوجد بريد غير صحيح. أدخل بريدًا واحدًا أو عدة عناوين مفصولة بسطر أو فاصلة.");
      return;
    }
    setSavingEmail(true);
    try {
      await api.post("/settings", { backup_email: emails[0], backup_emails: [...new Set(emails)] });
      const uniqueEmails = [...new Set(emails)];
      setBackupEmails(uniqueEmails.length ? uniqueEmails : [""]);
      setS((prev) => ({ ...prev, backup_email: uniqueEmails[0] || "", backup_emails: uniqueEmails }));
      toast.success(`تم حفظ ${uniqueEmails.length} بريد للنسخ الاحتياطي.`);
    } catch (e) { toast.error(errText(e)); }
    setSavingEmail(false);
  };

  const saveBackupAuto = async () => {
    const time = backupSettings.time || "02:00";
    if (!/^\d{2}:\d{2}$/.test(time)) {
      toast.error("الرجاء إدخال وقت صحيح بصيغة HH:MM.");
      return;
    }
    if (backupSettings.auto && !backupEmails.some((email) => String(email || "").trim())) {
      toast.error("يرجى حفظ البريد الإلكتروني للنسخ أولاً قبل تفعيل النسخ التلقائي.");
      return;
    }
    setSavingAuto(true);
    try {
      await api.post("/settings", { backup_time: time, backup_auto: !!backupSettings.auto });
      toast.success(backupSettings.auto ? "تم تفعيل النسخ الاحتياطي التلقائي." : "تم حفظ إعدادات النسخ التلقائي.");
    } catch (e) { toast.error(errText(e)); }
    setSavingAuto(false);
  };

  const runBackupNow = async () => {
    const emails = backupEmails.map((v) => String(v || "").trim()).filter(Boolean);
    if (!emails.length) {
      toast.error("يرجى حفظ البريد الإلكتروني للنسخ أولاً.");
      return;
    }
    setRunningNow(true);
    try {
      const r = await api.post("/backup/run-now");
      if (r.data?.email_sent) {
        toast.success(`تم رفع النسخة (${(r.data.size/1024).toFixed(1)} KB) وإرسال الرابط إلى ${r.data.email_to}`);
      } else if (r.data?.email_error) {
        toast.error(`تم الرفع لكن فشل الإرسال: ${r.data.email_error}`);
      } else {
        toast.success(`تم رفع النسخة إلى السحابة (${(r.data.size/1024).toFixed(1)} KB)`);
      }
      // refresh latest
      const l = await api.get("/backup/latest");
      if (l.data?.exists) setLatestBackup(l.data);
    } catch (e) { toast.error(errText(e)); }
    setRunningNow(false);
  };

  const openLocalDatabase = async () => {
    setLocalDbBusy(true);
    try {
      const status = await ensureNativeDatabaseFile();
      if (status?.mode === "web") {
        toast.info("ملف SQLite الداخلي متاح داخل تطبيق Android فقط.");
      } else {
        await openNativeDatabaseFile();
        toast.success("تم تجهيز ملف التخزين المحلي وطلب فتحه من مدير الملفات.");
      }
    } catch (e) {
      toast.error(e?.message || "تعذر فتح ملف التخزين المحلي");
    } finally {
      setLocalDbBusy(false);
    }
  };

  const restoreLatestCloud = async () => {
    if (!latestBackup) {
      toast.error("لا توجد نسخة سحابية للاستعادة.");
      return;
    }
    const when = (latestBackup.created_at || "").replace("T", " ").slice(0, 16);
    if (!window.confirm(
      `سيتم استعادة آخر نسخة سحابية (${when}). سيتم استبدال كل البيانات (باستثناء المستخدمين) بمحتوى النسخة، مع إنشاء نسخة أمان تلقائية أولاً. تأكيد؟`
    )) return;
    setRestoringCloud(true);
    try {
      const r = await api.post("/backup/restore-latest", { confirm: true });
      toast.success(`تمت الاستعادة بنجاح — ${r.data?.total_docs || 0} وثيقة من ${Object.keys(r.data?.restored || {}).length} مجموعة.`);
      setTimeout(() => window.location.reload(), 1500);
    } catch (e) { toast.error(errText(e)); }
    setRestoringCloud(false);
  };

  const exportBackup = async () => {
    try {
      const r = await api.get("/backup/export");
      const blob = new Blob([JSON.stringify(r.data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `jawad-backup-${todayIso()}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("تم إنشاء النسخة الاحتياطية");
    } catch (e) { toast.error(errText(e)); }
  };

  const uploadBackup = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (!window.confirm("سيتم استبدال البيانات الحالية. سيتم إنشاء نسخة أمان تلقائية أولاً. تأكيد؟")) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      await api.post("/backup/restore", { data });
      toast.success("تمت الاستعادة");
    } catch (e) { toast.error(errText(e)); }
  };

  const performReset = async () => {
    try {
      await api.post("/settings/reset-data", { username: resetForm.username, password: resetForm.password, confirm: true });
      toast.success("تم مسح البيانات التشغيلية مع إبقاء فئات الكروت");
      setResetOpen(false);
      setResetForm({ username: "", password: "" });
    } catch (e) { toast.error(errText(e)); }
  };

  return (
    <div className="space-y-6 max-w-2xl" data-testid="settings-page">
      <Card className="p-6 space-y-4">
        <div className="text-lg font-bold text-[#221340]">إعدادات عامة</div>
        <div><Label>اسم الشبكة</Label><Input value={s.company_name || ""} disabled/></div>
        <div><Label>الهاتف</Label><Input value={s.company_phone || ""} disabled/></div>
        <div>
          <Label>العملة</Label>
          <Select value={s.currency || "ريال"} onValueChange={(v) => setS({ ...s, currency: v })}>
            <SelectTrigger data-testid="set-currency"><SelectValue/></SelectTrigger>
            <SelectContent>
              <SelectItem value="ريال">ريال يمني (ريال)</SelectItem>
              <SelectItem value="ر.س">ريال سعودي (ر.س)</SelectItem>
              <SelectItem value="د.إ">درهم إماراتي (د.إ)</SelectItem>
              <SelectItem value="ج.م">جنيه مصري (ج.م)</SelectItem>
              <SelectItem value="د.ك">دينار كويتي (د.ك)</SelectItem>
              <SelectItem value="د.ب">دينار بحريني (د.ب)</SelectItem>
              <SelectItem value="ر.ع">ريال عماني (ر.ع)</SelectItem>
              <SelectItem value="ر.ق">ريال قطري (ر.ق)</SelectItem>
              <SelectItem value="د.ع">دينار عراقي (د.ع)</SelectItem>
              <SelectItem value="د.أ">دينار أردني (د.أ)</SelectItem>
              <SelectItem value="ل.س">ليرة سورية (ل.س)</SelectItem>
              <SelectItem value="USD">دولار أمريكي (USD)</SelectItem>
              <SelectItem value="EUR">يورو (EUR)</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div><Label>حد التنبيه الافتراضي للمخزون</Label><Input type="number" value={s.low_stock_default || 20} onChange={(e) => setS({ ...s, low_stock_default: Number(e.target.value) })}/></div>
        <div><Label>رابط الشعار</Label><Input value={s.logo_url || ""} onChange={(e) => setS({ ...s, logo_url: e.target.value })}/></div>
        <Button onClick={save} className="bg-[#221340]" data-testid="set-save">حفظ</Button>
      </Card>

      <Link to="/message-center" className="block"><Card className="p-4 hover:border-[#452480] transition"><div className="font-bold text-[#221340] flex items-center gap-2"><Bell size={18}/> مركز الرسائل والإشعارات والتنبيهات</div><p className="text-xs text-slate-500 mt-1">كل الإعدادات، النصوص، القنوات، والإرسال من شاشة واحدة.</p></Card></Link>

      <Card className="p-6 space-y-4" data-testid="install-card">
        <div className="text-lg font-bold text-[#221340] flex items-center gap-2"><Smartphone size={20}/> تثبيت / تحديث «إدارة الحسابات»</div>
        <InstallAppPanel/>
      </Card>

      <BiometricLockPanel/>

      <SmsGatewaySettingsPanel/>

      <Card className="p-6 space-y-3" data-testid="local-storage-panel">
        <div className="text-lg font-bold text-[#221340] flex items-center gap-2"><Database size={20}/> التخزين المحلي للجهاز</div>
        <p className="text-sm text-slate-600 leading-6">ينشئ التطبيق ملف <span className="font-mono">gawad_net_local.db</span> داخل مساحة Android الخاصة بالتطبيق، ثم ينسخ نسخة قابلة للفتح إلى مستندات التطبيق عند الطلب.</p>
        <Button type="button" onClick={openLocalDatabase} disabled={localDbBusy} className="bg-[#452480] hover:bg-[#5A2FA0] w-full sm:w-auto" data-testid="open-local-database">
          <FolderOpen size={15} className="ml-1"/> {localDbBusy ? "جاري تجهيز الملف..." : "فتح ملف التخزين المحلي"}
        </Button>
      </Card>

      <Card className="p-6 space-y-4" data-testid="currencies-panel">
        <div className="text-lg font-bold text-[#221340]">العملات المتعددة</div>
        <CurrenciesManager/>
        <IncentivesManager/>
      </Card>

      <Card className="p-6 space-y-4">
        <div className="text-lg font-bold text-[#221340] flex items-center gap-2"><Database size={20}/> النسخ الاحتياطي والمزامنة</div>
        <div>
            <Label>عناوين البريد الإلكتروني للنسخ الاحتياطية</Label>
            <div className="space-y-2" data-testid="backup-email-list">
              {backupEmails.map((email, index) => (
                <div key={`backup-email-${index}`} className="flex gap-2">
                  <Input type="email" value={email} onChange={(e) => setBackupEmails((prev) => prev.map((v, i) => i === index ? e.target.value : v))} data-testid={`backup-email-${index}`} placeholder="admin@example.com" autoComplete="email" inputMode="email" />
                  {backupEmails.length > 1 && <Button type="button" variant="outline" onClick={() => setBackupEmails((prev) => prev.filter((_, i) => i !== index))} aria-label="حذف البريد"><X size={16}/></Button>}
                </div>
              ))}
            </div>
          <Button type="button" variant="outline" className="mt-2" onClick={() => setBackupEmails((prev) => [...prev, ""])}><Plus size={14} className="ml-1"/> إضافة بريد آخر</Button>
          <div className="text-xs text-slate-500 mt-1">كل بريد في خانة مستقلة، وسترسل النسخة إلى جميع العناوين المحفوظة.</div>
          <Button
            onClick={saveBackupEmail}
            disabled={savingEmail}
            className="mt-2 bg-[#452480] hover:bg-[#5A2FA0]"
            data-testid="backup-email-save"
          >
            {savingEmail ? "جاري..." : "حفظ البريد الإلكتروني"}
          </Button>
        </div>
        <div className="pt-3 border-t space-y-3">
          <div><Label>وقت النسخ اليومي</Label><Input type="time" value={backupSettings.time} onChange={(e) => setBackupSettings({ ...backupSettings, time: e.target.value })} data-testid="backup-time"/></div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={backupSettings.auto} onChange={(e) => setBackupSettings({ ...backupSettings, auto: e.target.checked })} data-testid="backup-auto-toggle"/> تفعيل النسخ الاحتياطي التلقائي</label>
          <Button
            onClick={saveBackupAuto}
            disabled={savingAuto}
            className="bg-[#452480] hover:bg-[#5A2FA0] w-full sm:w-auto"
            data-testid="backup-auto-save"
          >
            {savingAuto ? "جاري..." : "حفظ إعدادات النسخ التلقائي"}
          </Button>
          <div className="flex gap-2 flex-wrap pt-3 border-t">
            <Button onClick={runBackupNow} disabled={runningNow} className="bg-emerald-700 hover:bg-emerald-800" data-testid="backup-run-now"><Send size={14} className="ml-1"/> {runningNow ? "جاري الرفع والإرسال..." : "رفع للسحابة وإرسال بالبريد الآن"}</Button>
            <Button onClick={restoreLatestCloud} disabled={restoringCloud || !latestBackup} className="bg-amber-600 hover:bg-amber-700 disabled:opacity-50" data-testid="backup-restore-latest"><CloudDownload size={14} className="ml-1"/> {restoringCloud ? "جاري الاستعادة..." : "استعادة آخر نسخة سحابية"}</Button>
            <Button onClick={exportBackup} className="bg-[#221340]" data-testid="backup-export"><Download size={14} className="ml-1"/> تنزيل نسخة محلية</Button>
            <label className="inline-flex">
              <input type="file" accept=".json" onChange={uploadBackup} className="hidden" data-testid="backup-upload"/>
              <span className="bg-[#452480] text-white px-4 py-2 rounded cursor-pointer flex items-center gap-1 text-sm hover:bg-[#5A2FA0]"><Upload size={14}/> استعادة نسخة</span>
            </label>
          </div>
          {latestBackup ? (
            <div className="text-xs text-slate-600 bg-slate-50 rounded p-2 mt-2" data-testid="latest-backup-info">
              آخر نسخة سحابية: <strong>{(latestBackup.created_at || "").replace("T"," ").slice(0,16)}</strong>
              — الحجم: {(latestBackup.size/1024).toFixed(1)} KB — المصدر: {latestBackup.trigger || "—"}
            </div>
          ) : (
            <div className="text-xs text-slate-500 mt-2">لا توجد نسخة سحابية بعد. اضغط "رفع للسحابة" لإنشاء أول نسخة.</div>
          )}
          <div className="text-xs text-slate-500 pt-2">
            الرفع للسحابة يستخدم تخزين Emergent Object Storage ويُرسل رابط تحميل صالح لمدة 14 يوماً إلى بريدك.
            التشغيل التلقائي يعمل يومياً في الوقت المحدد (توقيت عدن) داخل خدمة FastAPI.
          </div>
        </div>
      </Card>

      <Card className="p-6 space-y-3 border-red-200 bg-red-50/40">
        <div className="text-lg font-bold text-red-700 flex items-center gap-2"><Trash2 size={20}/> منطقة الخطر</div>
        <div className="text-sm text-slate-700">يمسح هذا الإجراء البيانات التشغيلية السابقة: العملاء، الموردين، الكروت، المخزون، الفواتير، السندات، المصروفات، التحويلات، الطلبات، الإشعارات وقيود المخزون. <strong>تبقى فئات الكروت وتعريفاتها محفوظة</strong>، بينما يبدأ مخزونها من الصفر. المستخدمون والإعدادات محفوظة.</div>
        <AlertDialog open={resetOpen} onOpenChange={setResetOpen}>
          <AlertDialogTrigger asChild><Button variant="destructive" data-testid="reset-btn"><Trash2 size={14} className="ml-1"/> مسح جميع البيانات السابقة</Button></AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle className="text-red-700">⚠️ عملية غير قابلة للتراجع</AlertDialogTitle>
              <AlertDialogDescription>سيحذف هذا الإجراء بيانات العمليات والكروت والمخزون نهائياً، مع إبقاء فئات الكروت وتعريفاتها. أدخل بيانات المدير للتأكيد.</AlertDialogDescription>
            </AlertDialogHeader>
            <div className="space-y-3">
              <div><Label>اسم المستخدم</Label><Input value={resetForm.username} onChange={(e) => setResetForm({ ...resetForm, username: e.target.value })} data-testid="reset-username"/></div>
              <div><Label>كلمة المرور</Label><Input type="password" value={resetForm.password} onChange={(e) => setResetForm({ ...resetForm, password: e.target.value })} data-testid="reset-password"/></div>
            </div>
            <AlertDialogFooter>
              <AlertDialogCancel>إلغاء</AlertDialogCancel>
              <AlertDialogAction onClick={performReset} className="bg-red-600 hover:bg-red-700" data-testid="reset-confirm">تأكيد المسح</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </Card>
    </div>
  );
}
