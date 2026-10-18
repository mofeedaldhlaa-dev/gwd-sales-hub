import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api, { errText } from "@/lib/api";
import { CopyButton } from "@/components/CopyText";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { genCustomerPassword,  fmtDate, openSMS, openWhatsAppUrl } from "@/lib/utils";
import DocumentPreviewDialog from "@/components/DocumentPreviewDialog";
import {
  Bell, Check, CheckCircle2, ClipboardList, Edit3, MessageSquare, RefreshCw,
  RotateCcw, Save, Search, Send, Smartphone, UserPlus, Users, Volume2, Vibrate,
  X, Boxes, FileText, Settings2, ChevronLeft,
} from "lucide-react";

const DEFAULT_NOTIFICATION_SETTINGS = {
  enabled: true,
  in_app_enabled: true,
  web_push_enabled: true,
  stock_alerts_enabled: true,
  account_requests_enabled: true,
  operation_alerts_enabled: true,
  sound_enabled: true,
  vibration_enabled: true,
};
const DEFAULT_MESSAGING_SETTINGS = {
  whatsapp_enabled: true,
  sms_enabled: true,
  default_channel: "whatsapp",
  country_code: "+967",
  append_company_name: true,
};
const DEFAULT_EVENT_SETTINGS = {
  free_card_notification: { enabled: true, channels: ["in_app"] },
  user_lock: { enabled: true, channels: ["in_app"] },
  account_request: { enabled: true, channels: ["in_app"] },
  stock_alerts: { enabled: true, channels: ["in_app"] },
  welcome_account: { enabled: true, channels: ["whatsapp"] },
  password_reset: { enabled: true, channels: ["whatsapp"] },
  unblock_account: { enabled: true, channels: ["whatsapp"] },
  sale_notification: { enabled: true, channels: ["in_app"] },
  sale_success_whatsapp: { enabled: true, channels: ["whatsapp"] },
  purchase_notification: { enabled: true, channels: ["in_app"] },
  voucher_notification: { enabled: true, channels: ["in_app"] },
  voucher_success_whatsapp: { enabled: true, channels: ["whatsapp"] },
  subscriber_transfer_notification: { enabled: true, channels: ["in_app"] },
  quick_recharge_notification: { enabled: true, channels: ["in_app"] },
  card_order_notification: { enabled: true, channels: ["in_app"] },
  unbind_account: { enabled: true, channels: ["whatsapp"] },
  payment_request: { enabled: true, channels: ["whatsapp"] },
  admin_broadcast: { enabled: true, channels: ["in_app"] },
};
const EVENT_GROUPS = [
  {
    title: "إشعارات الإدارة",
    icon: Settings2,
    items: [
      ["admin_broadcast", "الإشعارات المرسلة للعملاء", "إرسال إشعار جماعي أو محدد إلى حسابات العملاء."],
      ["account_request", "طلبات إنشاء الحساب", "تنبيه الإدارة عند وصول طلب إنشاء حساب جديد."],
      ["user_lock", "حظر مستخدم بعد محاولات فاشلة", "تنبيه الإدارة عند قفل حساب مستخدم."],
      ["stock_alerts", "تنبيهات المخزون", "تنبيهات انخفاض مخزون الكروت والكميات."],
      ["free_card_notification", "إرسال كرت مجاني", "تنبيه الإدارة عند تسليم كرت مجاني لأي مستلم."],
    ],
  },
  {
    title: "إشعارات العملاء والعمليات",
    icon: Bell,
    items: [
      ["sale_notification", "فاتورة المبيعات", "إشعار العميل بعد تسجيل فاتورة مبيعات."],
      ["sale_success_whatsapp", "نجاح حفظ فاتورة المبيعات", "النص الذي يرسل من نافذة نجاح حفظ الفاتورة."],
      ["purchase_notification", "فاتورة المشتريات", "إشعار الحساب المرتبط بعد تسجيل فاتورة مشتريات."],
      ["voucher_notification", "السندات", "إشعار تسجيل سند قبض أو صرف."],
      ["voucher_success_whatsapp", "نجاح حفظ السند", "النص الذي يرسل من نافذة نجاح حفظ السند."],
      ["subscriber_transfer_notification", "تحويل بين المشتركين", "إشعار التحويل الوارد والصادر."],
      ["quick_recharge_notification", "تحويل الرصيد", "إشعار تحويل الرصيد من الصندوق."],
      ["card_order_notification", "شراء الكروت", "إشعار تنفيذ طلب شراء الكروت."],
      ["payment_request", "طلب التسديد", "رسالة طلب تسديد المديونية."],
    ],
  },
  {
    title: "رسائل الحساب والأجهزة",
    icon: UserPlus,
    items: [
      ["welcome_account", "ترحيب الحساب الجديد", "رسالة بيانات الحساب بعد الموافقة على طلب الإنشاء."],
      ["password_reset", "تعديل كلمة المرور", "رسالة بيانات الدخول بعد تغيير كلمة المرور."],
      ["unblock_account", "فك حظر الحساب", "رسالة عند فك الحظر عن رقم العميل."],
      ["unbind_account", "فك ربط الجهاز", "رسالة عند فك ربط جهاز العميل."],
    ],
  },
];
const CHANNELS = [
  ["in_app", "داخل النظام"],
  ["whatsapp", "WhatsApp"],
  ["sms", "SMS"],
];
const EVENT_LABELS = Object.fromEntries(EVENT_GROUPS.flatMap((g) => g.items.map(([key, title]) => [key, title])));

function SectionButton({ active, onClick, icon: Icon, children }) {
  return <button type="button" onClick={onClick} className={`rounded-lg border px-3 py-2 text-sm font-bold transition ${active ? "border-[#452480] bg-[#452480] text-white" : "border-slate-200 bg-white text-[#221340] hover:border-[#452480]"}`}>
    <Icon size={15} className="inline ml-1" />{children}
  </button>;
}

function EventCard({ item, config, onChange }) {
  const [key, title, description] = item;
  const value = config[key] || DEFAULT_EVENT_SETTINGS[key] || { enabled: true, channels: ["in_app"] };
  const toggleChannel = (channel) => {
    const channels = value.channels.includes(channel) ? value.channels.filter((c) => c !== channel) : [...value.channels, channel];
    onChange(key, { ...value, channels });
  };
  return <Card className={`p-4 space-y-3 ${value.enabled ? "border-slate-200" : "border-red-200 bg-red-50/30"}`} data-testid={`message-event-${key}`}>
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0"><div className="font-bold text-[#221340] flex items-center gap-2"><ClipboardList size={16} />{title}</div><p className="text-xs text-slate-500 mt-1">{description}</p></div>
      <label className="flex items-center gap-2 shrink-0 text-xs font-bold"><input type="checkbox" checked={!!value.enabled} onChange={(e) => onChange(key, { ...value, enabled: e.target.checked })} data-testid={`message-event-enabled-${key}`} /> تشغيل</label>
    </div>
    <div className="flex flex-wrap gap-2 border-t pt-3">
      {CHANNELS.map(([channel, label]) => <label key={channel} className="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs"><input type="checkbox" checked={value.channels.includes(channel)} onChange={() => toggleChannel(channel)} disabled={!value.enabled} data-testid={`message-event-channel-${key}-${channel}`} />{label}</label>)}
    </div>
  </Card>;
}

export default function MessageNotificationCenter({ initialSection = "" }) {
  const [searchParams] = useSearchParams();
  // A phone notification tap opens this screen with ?focus=<notification id>:
  // the matching row is opened (its text and its operation) exactly as if the
  // user had tapped the row manually.
  const focusId = searchParams.get("focus") || "";
  const focusedRef = useRef("");
  const [section, setSection] = useState(() => initialSection || searchParams.get("section") || "events");
  const [preview, setPreview] = useState({ open: false, kind: "", entityId: "" });
  const [notificationSettings, setNotificationSettings] = useState(DEFAULT_NOTIFICATION_SETTINGS);
  const [messagingSettings, setMessagingSettings] = useState(DEFAULT_MESSAGING_SETTINGS);
  const [eventSettings, setEventSettings] = useState(DEFAULT_EVENT_SETTINGS);
  const [templates, setTemplates] = useState([]);
  const [prefix, setPrefix] = useState("");
  const [suffix, setSuffix] = useState("");
  const [customers, setCustomers] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [requests, setRequests] = useState([]);
  const [broadcastLog, setBroadcastLog] = useState([]);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [audience, setAudience] = useState("all");
  const [mode, setMode] = useState("all");
  const [selected, setSelected] = useState([]);
  const [search, setSearch] = useState("");
  const [logSearch, setLogSearch] = useState("");
  const [approveId, setApproveId] = useState(null);
  const [approveForm, setApproveForm] = useState({ credit_limit: 500, customer_type: "customer", password: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState(false);
  const [bcastChannels, setBcastChannels] = useState(["in_app"]);
  const [outreach, setOutreach] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const [settingsRes, customersRes, notificationsRes, requestsRes, logRes, templatesRes] = await Promise.all([
        api.get("/settings"), api.get("/customers"), api.get("/notifications"), api.get("/register-requests"), api.get("/notifications/broadcast-log"), api.get("/message-templates"),
      ]);
      const asList = (value) => (Array.isArray(value) ? value : (Array.isArray(value?.items) ? value.items : []));
      const settings = settingsRes.data || {};
      setNotificationSettings({ ...DEFAULT_NOTIFICATION_SETTINGS, ...(settings.notification_settings || {}) });
      setMessagingSettings({ ...DEFAULT_MESSAGING_SETTINGS, ...(settings.messaging_settings || {}) });
      setEventSettings({ ...DEFAULT_EVENT_SETTINGS, ...(settings.message_event_settings || {}) });
      setTemplates(Array.isArray(settings.message_templates) ? settings.message_templates : asList(templatesRes.data));
      setPrefix(settings.auto_message_prefix || "");
      setSuffix(settings.auto_message_suffix || "");
      setCustomers(asList(customersRes.data));
      setNotifications(asList(notificationsRes.data));
      setRequests(asList(requestsRes.data));
      setBroadcastLog(asList(logRes.data));
    } catch (e) { toast.error(errText(e)); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    const requested = searchParams.get("section");
    if (["events", "templates", "channels", "send", "inbox", "admin_inbox", "account_requests"].includes(requested)) setSection(requested);
  }, [searchParams]);

  const saveAll = async () => {
    setSaving(true);
    try {
      const templatePayload = Object.fromEntries(templates.map((t) => [t.key, t.text === (t.default_text || "") ? "" : t.text]));
      const r = await api.post("/settings", {
        notification_settings: notificationSettings,
        messaging_settings: messagingSettings,
        message_event_settings: eventSettings,
        message_templates: templatePayload,
        auto_message_prefix: prefix.trim(),
        auto_message_suffix: suffix.trim(),
      });
      const next = r.data || {};
      setNotificationSettings({ ...DEFAULT_NOTIFICATION_SETTINGS, ...(next.notification_settings || notificationSettings) });
      setMessagingSettings({ ...DEFAULT_MESSAGING_SETTINGS, ...(next.messaging_settings || messagingSettings) });
      setEventSettings({ ...DEFAULT_EVENT_SETTINGS, ...(next.message_event_settings || eventSettings) });
      if (Array.isArray(next.message_templates)) setTemplates(next.message_templates);
      localStorage.setItem("gwd_notification_settings", JSON.stringify(next.notification_settings || notificationSettings));
      localStorage.setItem("gwd_messaging_settings", JSON.stringify(next.messaging_settings || messagingSettings));
      window.dispatchEvent(new Event("notification-settings-changed"));
      window.dispatchEvent(new Event("messaging-settings-changed"));
      toast.success("تم حفظ مركز الرسائل والإشعارات بالكامل");
    } catch (e) { toast.error(errText(e)); }
    finally { setSaving(false); }
  };

  const filteredCustomers = useMemo(() => {
    const q = search.trim().toLowerCase();
    return customers.filter((c) => !q || (c.name || "").toLowerCase().includes(q) || (c.phone || "").includes(q));
  }, [customers, search]);
  const filteredLog = useMemo(() => {
    const q = logSearch.trim().toLowerCase();
    return broadcastLog.filter((row) => !q || (row.title || "").toLowerCase().includes(q) || (row.message || "").toLowerCase().includes(q));
  }, [broadcastLog, logSearch]);
  const pendingRequests = requests.filter((r) => r.status === "pending");
  const generalNotifications = notifications.filter((n) => n.category !== "account_request");
  const navigate = useNavigate();
  // Tapping an admin notification opens the operation it announces: the voucher or
  // invoice itself when we have its id, otherwise the screen that owns the event.
  useEffect(() => {
    if (!focusId || loading || focusedRef.current === focusId) return undefined;
    const target = notifications.find((row) => row.id === focusId);
    if (!target) return undefined;
    focusedRef.current = focusId;
    if (section !== "inbox" && section !== "admin_inbox") setSection("inbox");
    openNotification(target);
    const timer = setTimeout(() => {
      const el = document.querySelector(`[data-testid="admin-notification-${focusId}"]`);
      if (el && el.scrollIntoView) el.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 350);
    return () => clearTimeout(timer);
  }, [focusId, notifications, loading, section]);

  const openNotification = (n) => {
    const target = n.target || {};
    if (!n.read) {
      api.post(`/notifications/${n.id}/read`)
        .then(() => setNotifications((rows) => rows.map((row) => (row.id === n.id ? { ...row, read: true } : row))))
        .catch(() => {});
    }
    if (target.kind === "document" && target.entity_id) {
      setPreview({ open: true, kind: target.document, entityId: target.entity_id });
      return;
    }
    if (target.route) {
      navigate(target.route);
      return;
    }
    toast.info("لا توجد عملية مرتبطة بهذا الإشعار");
  };

  const sendBroadcast = async () => {
    if (!title.trim() || !message.trim()) { toast.error("العنوان والنص إلزاميان"); return; }
    if (mode === "selected" && !selected.length) { toast.error("اختر حساباً واحداً على الأقل"); return; }
    setSending(true);
    try {
      const body = { title: title.trim(), message: message.trim(), audience, channels: bcastChannels };
      if (mode === "selected") body.recipients = selected;
      const r = await api.post("/notifications/broadcast", body);
      if (r.data?.disabled) toast.warning("تم إيقاف إشعارات العملاء من المركز الموحد");
      else toast.success(`تم تنفيذ الإرسال إلى ${r.data.count} حساب`);
      setOutreach(r.data?.outreach && r.data.outreach.length ? r.data.outreach : null);
      setTitle(""); setMessage(""); setSelected([]); await load();
    } catch (e) { toast.error(errText(e)); }
    finally { setSending(false); }
  };

  const approve = async (id) => {
    try {
      const r = await api.post(`/register-requests/${id}/approve`, { ...approveForm, credit_limit: Number(approveForm.credit_limit) || 0, password: approveForm.password || null });
      if (r.data?.whatsapp_url) window.open(r.data.whatsapp_url, "_blank", "noopener,noreferrer");
      toast.success("تمت الموافقة وإنشاء الحساب"); setApproveId(null); await load();
    } catch (e) { toast.error(errText(e)); }
  };
  const reject = async (id) => { try { await api.post(`/register-requests/${id}/reject`); toast.success("تم رفض الطلب"); await load(); } catch (e) { toast.error(errText(e)); } };
  const toggleSelected = (id) => setSelected((old) => old.includes(id) ? old.filter((x) => x !== id) : [...old, id]);
  const resetTemplate = (key) => setTemplates((old) => old.map((t) => t.key === key ? { ...t, text: t.default_text || t.text, customized: false } : t));
  const updateTemplate = (key, text) => setTemplates((old) => old.map((t) => t.key === key ? { ...t, text, customized: text !== (t.default_text || "") } : t));
  const deleteLog = async (row) => {
    const id = row.group_id || row._id;
    if (!id || !window.confirm("حذف الإشعار من جميع الحسابات المستلمة؟")) return;
    try { await api.post("/notifications/broadcast/delete-many", { group_ids: [id] }); setBroadcastLog((old) => old.filter((x) => (x.group_id || x._id) !== id)); toast.success("تم حذف الإشعار"); } catch (e) { toast.error(errText(e)); }
  };

  return <div className="space-y-5 max-w-6xl" dir="rtl" data-testid="message-notification-center">
    <Card className="p-5 bg-gradient-to-l from-[#221340] to-[#452480] text-white">
      <div className="flex items-start justify-between gap-3"><div><h1 className="text-xl font-black flex items-center gap-2"><MessageSquare className="text-[#D4AF37]" /> إعدادات الرسائل والإشعارات والتنبيهات</h1><p className="text-sm text-white/75 mt-2">المركز الوحيد للتحكم في التشغيل، القنوات، النصوص، والإرسال. أي عنصر متوقف لا يُرسل من النظام.</p></div><Button onClick={load} variant="outline" className="bg-white/10 text-white border-white/30 hover:bg-white/20" disabled={loading}><RefreshCw size={15} className="ml-1" /> تحديث</Button></div>
    </Card>
    <div className="flex flex-wrap gap-2" data-testid="message-center-sections">
      <SectionButton active={section === "events"} onClick={() => setSection("events")} icon={Settings2}>أحداث الرسائل</SectionButton>
      <SectionButton active={section === "templates"} onClick={() => setSection("templates")} icon={Edit3}>نصوص القوالب</SectionButton>
      <SectionButton active={section === "channels"} onClick={() => setSection("channels")} icon={Smartphone}>SMS و WhatsApp</SectionButton>
      <SectionButton active={section === "send"} onClick={() => setSection("send")} icon={Send}>إشعار للعملاء</SectionButton>
      <SectionButton active={section === "admin_inbox"} onClick={() => setSection("admin_inbox")} icon={Bell}>إشعارات الإدارة</SectionButton>
      <SectionButton active={section === "account_requests"} onClick={() => setSection("account_requests")} icon={UserPlus}>طلبات إنشاء الحساب</SectionButton>
    </div>

    {loading && <Card className="p-8 text-center text-slate-500">جاري تحميل المركز...</Card>}
    {!loading && section === "events" && <div className="space-y-4">
      <Card className="p-4 border-amber-200 bg-amber-50/50"><div className="font-bold text-[#221340]">قاعدة الإرسال المركزية</div><p className="text-xs text-slate-600 mt-1">فعّل الحدث ثم اختر قناة أو أكثر. يتم تطبيق هذه الإعدادات على عمليات النظام الحالية والجديدة.</p></Card>
      <div className="grid md:grid-cols-2 gap-4">{EVENT_GROUPS.flatMap((group) => group.items).map((item) => <EventCard key={item[0]} item={item} config={eventSettings} onChange={(key, value) => setEventSettings((old) => ({ ...old, [key]: value }))} />)}</div>
      <Card className="p-4 space-y-3"><div className="font-bold text-[#221340] flex items-center gap-2"><Bell size={17} /> إعدادات عامة للإشعارات</div><div className="grid sm:grid-cols-2 gap-2">{[["enabled", "تفعيل نظام الإشعارات"], ["in_app_enabled", "داخل التطبيق"], ["web_push_enabled", "الإشعارات الفورية"], ["operation_alerts_enabled", "إشعارات العمليات"], ["stock_alerts_enabled", "تنبيهات المخزون"], ["account_requests_enabled", "طلبات إنشاء الحساب"], ["sound_enabled", "الصوت"], ["vibration_enabled", "الاهتزاز"]].map(([key, label]) => <label key={key} className="flex items-center gap-2 rounded-lg border p-3 text-sm"><input type="checkbox" checked={!!notificationSettings[key]} onChange={(e) => setNotificationSettings((old) => ({ ...old, [key]: e.target.checked }))} />{label}</label>)}</div></Card>
    </div>}

    {!loading && section === "templates" && <div className="space-y-4"><Card className="p-4 border-blue-200 bg-blue-50/50"><div className="font-bold text-[#221340]">نصوص الرسائل والأحداث</div><p className="text-xs text-slate-600 mt-1">يمكن تعديل النص مع الإبقاء على المتغيرات بين الأقواس، أو الضغط على استعادة الافتراضي. احفظ من الزر أسفل الصفحة.</p></Card><div className="grid md:grid-cols-2 gap-4">{templates.map((t) => <Card key={t.key} className="p-4 space-y-3" data-testid={`message-template-${t.key}`}><div className="flex items-start justify-between gap-2"><div><div className="font-bold text-[#221340]">{EVENT_LABELS[t.key] || t.name}</div><p className="text-xs text-slate-500 mt-1">{t.description}</p></div>{t.customized && <span className="text-[10px] rounded-full bg-amber-100 text-amber-700 px-2 py-1">مخصص</span>}</div><Textarea rows={6} value={t.text || ""} onChange={(e) => updateTemplate(t.key, e.target.value)} data-testid={`message-template-input-${t.key}`} /><div className="text-[10px] text-slate-500">المتغيرات: {(t.variables || []).map((v) => `{{${v}}}`).join("، ") || "لا توجد"}</div><Button variant="outline" size="sm" onClick={() => resetTemplate(t.key)}><RotateCcw size={13} className="ml-1" /> استعادة النص الافتراضي</Button></Card>)}</div></div>}

    {!loading && section === "channels" && <div className="space-y-4"><Card className="p-5 space-y-4"><div className="font-bold text-[#221340] flex items-center gap-2"><Smartphone size={18} /> قنوات الرسائل</div><div className="grid sm:grid-cols-2 gap-3"><label className="flex items-center gap-2 border rounded-lg p-3"><input type="checkbox" checked={!!messagingSettings.whatsapp_enabled} onChange={(e) => setMessagingSettings((s) => ({ ...s, whatsapp_enabled: e.target.checked }))} /> تفعيل WhatsApp</label><label className="flex items-center gap-2 border rounded-lg p-3"><input type="checkbox" checked={!!messagingSettings.sms_enabled} onChange={(e) => setMessagingSettings((s) => ({ ...s, sms_enabled: e.target.checked }))} /> تفعيل SMS</label></div><div className="grid sm:grid-cols-2 gap-3"><div><Label>القناة الافتراضية</Label><select value={messagingSettings.default_channel} onChange={(e) => setMessagingSettings((s) => ({ ...s, default_channel: e.target.value }))} className="w-full border rounded-md p-2 text-sm"><option value="whatsapp">WhatsApp</option><option value="sms">SMS</option></select></div><div><Label>رمز الدولة</Label><Input value={messagingSettings.country_code} onChange={(e) => setMessagingSettings((s) => ({ ...s, country_code: e.target.value }))} placeholder="+967" /></div></div><label className="flex items-center gap-2 border rounded-lg p-3 text-sm"><input type="checkbox" checked={!!messagingSettings.append_company_name} onChange={(e) => setMessagingSettings((s) => ({ ...s, append_company_name: e.target.checked }))} /> إضافة اسم الشبكة في الرسائل</label></Card><Card className="p-5 space-y-3"><div className="font-bold text-[#221340] flex items-center gap-2"><MessageSquare size={18} /> بداية وخاتمة الرسائل التلقائية</div><div className="grid md:grid-cols-2 gap-3"><div><Label>بداية الرسالة</Label><Textarea rows={3} value={prefix} onChange={(e) => setPrefix(e.target.value)} /></div><div><Label>خاتمة الرسالة</Label><Textarea rows={3} value={suffix} onChange={(e) => setSuffix(e.target.value)} /></div></div><p className="text-xs text-slate-500">تُطبّق مرة واحدة على الرسائل التي ينشئها النظام، ولا توجد شاشة أخرى لتعديلها.</p></Card></div>}

    {!loading && section === "send" && <div className="space-y-4"><Card className="p-5 space-y-4"><div className="font-bold text-[#221340] flex items-center gap-2"><Send size={18} /> إرسال إشعار للعملاء</div><div><Label>العنوان</Label><Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="مثال: تنبيه من الإدارة" /></div><div><Label>النص</Label><Textarea rows={4} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="اكتب نص الإشعار..." /></div><div className="grid grid-cols-2 gap-2"><button type="button" onClick={() => setMode("all")} className={`rounded-lg border p-2 text-sm font-bold ${mode === "all" ? "bg-[#452480] text-white" : ""}`}>جميع الحسابات</button><button type="button" onClick={() => setMode("selected")} className={`rounded-lg border p-2 text-sm font-bold ${mode === "selected" ? "bg-[#452480] text-white" : ""}`}>حسابات محددة</button></div>{mode === "all" && <div className="grid grid-cols-3 gap-2">{[["all", "الكل"], ["pos", "نقاط البيع"], ["customer", "العملاء"]].map(([key, label]) => <button key={key} type="button" onClick={() => setAudience(key)} className={`rounded-lg border p-2 text-xs font-bold ${audience === key ? "bg-emerald-700 text-white" : ""}`}>{label}</button>)}</div>}{mode === "selected" && <div className="space-y-2 border rounded-lg p-3"><Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="بحث بالاسم أو الهاتف" /><div className="text-xs text-slate-500">المحدد: {selected.length}</div><div className="max-h-48 overflow-y-auto space-y-1">{filteredCustomers.map((c) => <label key={c.id} className="flex items-center gap-2 p-2 rounded hover:bg-slate-50"><input type="checkbox" checked={selected.includes(c.id)} onChange={() => toggleSelected(c.id)} /><span>{c.name} — {c.phone || "-"}</span></label>)}</div></div>}<div><Label>طرق الإرسال</Label><div className="grid grid-cols-3 gap-2">{[["in_app", "إشعار نافذة العميل"], ["sms", "رسالة نصية"], ["whatsapp", "رسالة واتساب"]].map(([key, label]) => { const active = bcastChannels.includes(key); return (<button key={key} type="button" data-testid={`bcast-channel-${key}`} onClick={() => setBcastChannels((old) => active ? old.filter((c) => c !== key) : [...old, key])} className={`rounded-lg border p-2 text-xs font-bold ${active ? "bg-[#221340] text-white" : ""}`}>{label}</button>); })}</div><div className="text-xs text-slate-500 mt-1">إشعار نافذة العميل يصل مباشرة داخل حساب العميل، أما النصية والواتساب فتُفتح قائمة إرسال لكل مستلم.</div></div><Button onClick={sendBroadcast} disabled={sending} className="w-full bg-[#452480]"><Send size={14} className="ml-1" />{sending ? "جاري الإرسال..." : "إرسال الإشعار"}</Button>{outreach && outreach.length > 0 && (<div className="border rounded-lg p-3 space-y-2" data-testid="bcast-outreach"><div className="font-bold text-sm">قائمة الإرسال ({outreach.length})</div><div className="max-h-72 overflow-y-auto divide-y">{outreach.map((row) => (<div key={row.customer_id} className="flex items-center justify-between gap-2 py-2 text-sm"><span>{row.name || row.phone}</span><span className="flex gap-1">{row.whatsapp_url ? <Button size="sm" onClick={() => openWhatsAppUrl(row.whatsapp_url)}>واتساب</Button> : null}{row.sms_phone ? <Button size="sm" variant="outline" onClick={() => openSMS(row.sms_phone, row.sms_text)}>نصية</Button> : null}</span></div>))}</div></div>)}</Card><Card className="p-5 space-y-3"><div className="flex items-center justify-between gap-2"><div className="font-bold text-[#221340] flex items-center gap-2"><FileText size={17} /> سجل الإشعارات المرسلة</div><Input className="max-w-xs" value={logSearch} onChange={(e) => setLogSearch(e.target.value)} placeholder="بحث" /></div>{filteredLog.length ? filteredLog.map((row) => <div key={row.group_id || row._id} className="border rounded-lg p-3"><div className="flex justify-between gap-2"><b>{row.title}</b><button type="button" onClick={() => deleteLog(row)} className="text-red-600 text-xs"><TrashIcon /></button></div><p className="text-sm text-slate-600 whitespace-pre-line mt-1">{row.message}</p><div className="text-xs text-slate-500 mt-2">المستلمون: {row.count} — المقروء: {row.read_count}</div></div>) : <div className="text-center text-slate-400 p-4">لا يوجد سجل</div>}</Card></div>}

    {!loading && (section === "inbox" || section === "admin_inbox") && <div className="space-y-4"><Card className="p-5"><div className="font-bold text-[#221340] flex items-center gap-2"><Bell size={18} /> إشعارات الإدارة</div><div className="space-y-2 mt-3">{generalNotifications.length ? generalNotifications.map((n) => <button type="button" key={n.id} onClick={() => openNotification(n)} className={`w-full text-right border rounded-lg p-3 transition hover:border-[#452480] hover:bg-[#452480]/5 ${n.read ? "opacity-75" : ""}`} data-testid={`admin-notification-${n.id}`}><div className="flex items-start justify-between gap-2"><div className="min-w-0"><div className="font-bold flex items-center gap-2">{!n.read && <span className="inline-block w-2 h-2 rounded-full bg-[#452480] shrink-0" />}{n.title}</div><div className="text-sm text-slate-600 mt-1">{n.message}</div><div className="text-xs text-slate-400 mt-1">{fmtDate(n.created_at)}{n.target && n.target.kind !== "none" ? ` — اضغط لعرض ${n.target.label}` : ""}</div></div><ChevronLeft size={16} className="text-slate-400 shrink-0 mt-1" /></div></button>) : <div className="text-center text-slate-400 p-4">لا توجد إشعارات جديدة</div>}</div></Card></div>}
    {!loading && (section === "inbox" || section === "account_requests") && <div className="space-y-4"><Card className="p-5"><div className="font-bold text-[#221340] flex items-center gap-2"><UserPlus size={18} /> طلبات إنشاء الحساب ({pendingRequests.length})</div><div className="space-y-2 mt-3">{pendingRequests.length ? pendingRequests.map((r) => <div key={r.id} className="border rounded-lg p-3 space-y-2"><div className="flex justify-between gap-2"><div><b>{r.full_name}</b><div className="text-xs text-slate-500">{r.phone} — {r.address || ""}</div></div><div className="flex gap-2"><Button size="sm" onClick={() => setApproveId(r.id)} className="bg-green-600"><Check size={13} className="ml-1" /> موافقة</Button><Button size="sm" variant="outline" onClick={() => reject(r.id)}><X size={13} /></Button></div></div>{approveId === r.id && <div className="grid sm:grid-cols-3 gap-2 border-t pt-2"><Input type="number" value={approveForm.credit_limit} onChange={(e) => setApproveForm((f) => ({ ...f, credit_limit: e.target.value }))} placeholder="سقف الحساب" /><select value={approveForm.customer_type} onChange={(e) => setApproveForm((f) => ({ ...f, customer_type: e.target.value }))} className="border rounded-md p-2 text-sm"><option value="customer">عميل</option><option value="pos">نقطة بيع</option></select><div className="flex items-center gap-2"><Input type="password" value={approveForm.password} onChange={(e) => setApproveForm((f) => ({ ...f, password: e.target.value }))} placeholder="كلمة المرور اختيارية" /><Button type="button" variant="outline" className="shrink-0 h-9" data-testid="approve-generate-password" onClick={() => setApproveForm((f) => ({ ...f, password: genCustomerPassword() }))}>توليد</Button>{approveForm.password ? <CopyButton text={approveForm.password} label="نسخ" testid="approve-copy-password" className="shrink-0 h-9" /> : null}</div><Button onClick={() => approve(r.id)} className="bg-[#452480] sm:col-span-3">تأكيد إنشاء الحساب</Button></div>}</div>) : <div className="text-center text-slate-400 p-4">لا توجد طلبات معلقة</div>}</div></Card></div>}

    <DocumentPreviewDialog
      open={preview.open}
      onOpenChange={(value) => setPreview((current) => ({ ...current, open: value }))}
      document={preview.kind}
      entityId={preview.entityId}
    />
    <div className="sticky bottom-3 z-10 flex justify-end"><Button onClick={saveAll} disabled={loading || saving} className="bg-[#221340] shadow-lg" data-testid="message-center-save"><Save size={15} className="ml-1" />{saving ? "جاري حفظ المركز..." : "حفظ جميع إعدادات المركز"}</Button></div>
  </div>;
}

function TrashIcon() { return <span aria-hidden="true">حذف</span>; }
