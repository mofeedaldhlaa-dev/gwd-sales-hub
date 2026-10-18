import { useCallback, useEffect, useMemo, useState } from "react";
import api, { errText } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import PeriodFilter, { todayIso } from "@/components/PeriodFilter";
import { printReport } from "@/lib/print";
import { toast } from "sonner";
import { Ban, CheckCircle2, ClipboardList, MonitorSmartphone, Plus, Printer, RefreshCw, Search, Smartphone, Trash2, Unlock, Wifi, XCircle } from "lucide-react";

const STATUS_LABELS = {
  approved: "تم الاعتماد وتقيد السند",
  accepted: "تم القبول والمطابقة",
  rejected: "مرفوضة",
  manual_review: "مراجعة يدوية",
  unclaimed: "غير مرتبطة بطلب",
};

const operationText = (row) => row.operation_type === "direct_card_sale"
  ? `مبيعات كرت نت${row.invoice_number ? ` — فاتورة ${row.invoice_number}` : ""}`
  : (row.receipt_number ? `سند ${row.receipt_number}` : "بدون سند");

const statusClass = (status) => ({
  approved: "bg-emerald-100 text-emerald-800",
  accepted: "bg-blue-100 text-blue-800",
  rejected: "bg-red-100 text-red-800",
  manual_review: "bg-amber-100 text-amber-800",
  unclaimed: "bg-slate-100 text-slate-700",
}[status] || "bg-slate-100 text-slate-700");

const dateText = (value) => value ? String(value).replace("T", " ").slice(0, 19) : "-";

export default function SmsGateway() {
  const [gatewayState, setGatewayState] = useState(null);
  const [devices, setDevices] = useState([]);
  const [activeDeviceId, setActiveDeviceId] = useState("");
  const [blockedCustomers, setBlockedCustomers] = useState([]);
  const [deviceForm, setDeviceForm] = useState({ device_id: "", label: "", note: "", active: true });
  const [savingDevice, setSavingDevice] = useState(false);
  const [period, setPeriod] = useState("day");
  const [start, setStart] = useState(todayIso());
  const [end, setEnd] = useState(todayIso());
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [report, setReport] = useState({ items: [], counts: {}, total: 0 });
  const [loading, setLoading] = useState(true);
  const [reportLoading, setReportLoading] = useState(false);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    try {
      const [configResponse, deviceResponse, blockedResponse] = await Promise.all([
        api.get("/payment-gateway/config"),
        api.get("/payment-gateway/devices"),
        api.get("/payment-verifications/blocked-customers"),
      ]);
      setGatewayState(configResponse.data || null);
      setDevices(deviceResponse.data?.items || []);
      setActiveDeviceId(deviceResponse.data?.active_device_id || "");
      setBlockedCustomers(blockedResponse.data || []);
    } catch (error) {
      toast.error(errText(error) || "تعذر تحميل إعدادات SMS Gateway");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadReport = useCallback(async () => {
    setReportLoading(true);
    try {
      const response = await api.get("/payment-gateway/messages/report", {
        params: { start, end, q: q.trim() || undefined, status_filter: status || undefined, limit: 5000 },
      });
      setReport(response.data || { items: [], counts: {}, total: 0 });
    } catch (error) {
      toast.error(errText(error) || "تعذر تحميل تقرير الرسائل الواردة");
    } finally {
      setReportLoading(false);
    }
  }, [start, end, q, status]);

  useEffect(() => { loadSettings(); }, [loadSettings]);
  useEffect(() => { loadReport(); }, [loadReport]);

  const updatePeriod = ({ period: nextPeriod, start: nextStart, end: nextEnd }) => {
    setPeriod(nextPeriod);
    setStart(nextStart || "");
    setEnd(nextEnd || "");
  };

  const addDevice = async () => {
    if (!deviceForm.device_id.trim() || !deviceForm.label.trim()) {
      toast.error("أدخل معرف الجهاز واسماً واضحاً للجهاز");
      return;
    }
    setSavingDevice(true);
    try {
      await api.post("/payment-gateway/devices", { ...deviceForm, device_id: deviceForm.device_id.trim(), label: deviceForm.label.trim() });
      toast.success("تمت إضافة جهاز Gateway");
      setDeviceForm({ device_id: "", label: "", note: "", active: true });
      await loadSettings();
    } catch (error) {
      toast.error(errText(error) || "تعذر إضافة الجهاز");
    } finally {
      setSavingDevice(false);
    }
  };

  const activateDevice = async (deviceId) => {
    if (!window.confirm("سيصبح هذا الجهاز هو الجهاز المقبول لاستقبال رسائل SMS الجديدة. متابعة؟")) return;
    try {
      await api.post(`/payment-gateway/devices/${encodeURIComponent(deviceId)}/activate`);
      setActiveDeviceId(deviceId);
      toast.success("تم تغيير جهاز استقبال الرسائل");
      await loadSettings();
    } catch (error) {
      toast.error(errText(error) || "تعذر تغيير الجهاز");
    }
  };

  const removeDevice = async (device) => {
    if (device.source === "environment") {
      toast.error("الجهاز المعرّف في الخادم لا يُحذف من الواجهة");
      return;
    }
    if (!window.confirm(`حذف الجهاز «${device.label || device.device_id}»؟`)) return;
    try {
      await api.delete(`/payment-gateway/devices/${encodeURIComponent(device.device_id)}`);
      toast.success("تم حذف الجهاز");
      await loadSettings();
    } catch (error) {
      toast.error(errText(error) || "تعذر حذف الجهاز");
    }
  };

  const unlockPaymentCustomer = async (item) => {
    if (!window.confirm(`فك حظر حساب السداد للعميل «${item.customer_name || item.phone || item.customer_id}»؟`)) return;
    try {
      await api.post(`/payment-verifications/blocked-customers/${encodeURIComponent(item.customer_id)}/unlock`);
      toast.success("تم فك حظر حساب السداد");
      await loadSettings();
    } catch (error) {
      toast.error(errText(error) || "تعذر فك الحظر");
    }
  };

  const reportRows = useMemo(() => report.items || [], [report.items]);
  const printGatewayReport = () => {
    printReport({
      title: "تقرير رسائل SMS Gateway الواردة",
      headers: ["التاريخ", "المصدر", "المبلغ", "المرجع", "الحالة", "السند", "نص الرسالة"],
      rows: reportRows.map((row) => [dateText(row.received_at), row.sender_id || "-", row.amount ?? "-", row.transaction_id || row.payment_reference || "-", STATUS_LABELS[row.status] || row.status, operationText(row), row.sms_text || "-"]),
      totals: [{ label: "إجمالي الرسائل المعروضة", value: reportRows.length }, { label: "تم اعتمادها وتقيد سند", value: report.counts?.approved || 0 }, { label: "تم قبولها ومطابقتها", value: report.counts?.accepted || 0 }],
      username: "",
    });
  };

  return (
    <div className="space-y-4 max-w-7xl mx-auto" data-testid="sms-gateway-screen" dir="rtl">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-extrabold text-[#221340] flex items-center gap-2"><Smartphone size={24} className="text-[#452480]" /> SMS Gateway</h1>
          <p className="text-xs text-slate-500 mt-1">إدارة جهاز استقبال الرسائل، مصادر الحسابات البنكية، ومراجعة الرسائل التي نتجت عنها عمليات سداد.</p>
        </div>
        <Button variant="outline" onClick={() => { loadSettings(); loadReport(); }} disabled={loading || reportLoading} data-testid="sms-gateway-refresh"><RefreshCw size={14} className="ml-1" /> تحديث</Button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-2" data-testid="sms-gateway-summary">
        {[["approved", "معتمدة ومقيدة", CheckCircle2], ["accepted", "مقبولة ومطابقة", Wifi], ["rejected", "مرفوضة", XCircle], ["manual_review", "مراجعة يدوية", ClipboardList], ["unclaimed", "غير مرتبطة", Search]].map(([key, label, Icon]) => <button type="button" key={key} onClick={() => setStatus(status === key ? "" : key)} className={`text-right rounded-xl border p-3 bg-white hover:border-[#452480] ${status === key ? "ring-2 ring-[#452480]/30" : ""}`} data-testid={`sms-summary-${key}`}><div className="flex items-center justify-between gap-2"><Icon size={16} className="text-[#452480]" /><span className="text-[11px] text-slate-500">{label}</span></div><div className="text-xl font-extrabold text-[#221340] mt-1">{report.counts?.[key] || 0}</div></button>)}
      </div>

      <Card className="p-4 space-y-2" data-testid="sms-gateway-bank-settings">
        <h2 className="font-bold text-[#221340]">مصدر Sender تلقائي من الحسابات البنكية</h2>
        <p className="text-xs text-slate-500">لا توجد خانة مستقلة للمصدر هنا. أضف Sender ID الرسمي داخل بطاقة الحساب البنكي أو المحفظة؛ سيستخدمه التطبيق والخادم تلقائياً.</p>
      </Card>

      <Card className="p-4 space-y-3" data-testid="sms-gateway-devices">
        <div><h2 className="font-bold text-[#221340] flex items-center gap-2"><MonitorSmartphone size={17} /> أجهزة استقبال الرسائل</h2><p className="text-xs text-slate-500 mt-1">يمكن تفعيل جهاز واحد في الوقت نفسه. تغيير الجهاز يغيّر الجهاز المقبول للرسائل الجديدة فقط، ولا يحذف السجل السابق.</p></div>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-2 items-end border rounded-lg p-3 bg-slate-50"><div><Label className="text-xs">معرف الجهاز</Label><Input value={deviceForm.device_id} onChange={(e) => setDeviceForm({ ...deviceForm, device_id: e.target.value })} placeholder="gateway-phone-02" dir="ltr" data-testid="sms-device-id" /></div><div><Label className="text-xs">اسم الجهاز</Label><Input value={deviceForm.label} onChange={(e) => setDeviceForm({ ...deviceForm, label: e.target.value })} placeholder="هاتف البنك الجديد" data-testid="sms-device-label" /></div><div><Label className="text-xs">ملاحظة</Label><Input value={deviceForm.note} onChange={(e) => setDeviceForm({ ...deviceForm, note: e.target.value })} placeholder="الشريحة والبنك" data-testid="sms-device-note" /></div><Button onClick={addDevice} disabled={savingDevice} className="bg-[#221340]" data-testid="sms-device-add"><Plus size={14} className="ml-1" /> إضافة جهاز</Button></div>
        <div className="space-y-2">{devices.map((device) => <div key={device.device_id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border rounded-lg p-3"><div className="min-w-0"><div className="font-bold text-sm flex items-center gap-2">{device.label || device.device_id}{device.is_active && <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700">نشط</span>}</div><div className="font-mono text-xs text-slate-600" dir="ltr">{device.device_id}</div><div className="text-xs text-slate-500">{device.note || "-"}</div></div><div className="flex gap-2 shrink-0">{!device.is_active && <Button size="sm" variant="outline" onClick={() => activateDevice(device.device_id)} data-testid={`sms-device-activate-${device.device_id}`}>تفعيل</Button>}<Button size="sm" variant="outline" className="text-red-600" onClick={() => removeDevice(device)} disabled={device.source === "environment"} data-testid={`sms-device-delete-${device.device_id}`}><Trash2 size={14} /></Button></div></div>)}{!devices.length && <div className="text-sm text-slate-500">لم تتم إضافة أجهزة إضافية. يظهر الجهاز المعتمد في الخادم عند تهيئة المتغيرات السرية.</div>}</div>
        <div className="text-xs text-slate-500">الجهاز النشط حالياً: <span className="font-mono" dir="ltr">{activeDeviceId || "غير محدد"}</span></div>
      </Card>

      <Card className="p-4 space-y-3" data-testid="sms-gateway-payment-blocks">
        <div><h2 className="font-bold text-[#221340] flex items-center gap-2"><Ban size={17} /> حسابات السداد الموقوفة</h2><p className="text-xs text-slate-500 mt-1">يتم إيقاف تأكيد الدفع بعد 10 محاولات خاطئة، ولا يُفك الإيقاف إلا من الإدارة.</p></div>
        <div className="space-y-2">{blockedCustomers.map((item) => <div key={item.customer_id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border border-red-100 rounded-lg p-3 bg-red-50/50"><div className="min-w-0"><div className="font-bold text-sm">{item.customer_name || "عميل"}</div><div className="text-xs text-slate-600" dir="ltr">{item.phone || item.customer_id}</div><div className="text-xs text-red-700 mt-1">محاولات خاطئة: {item.failed_attempts || 0}</div></div><Button size="sm" onClick={() => unlockPaymentCustomer(item)} className="bg-[#452480]" data-testid={`sms-payment-unlock-${item.customer_id}`}><Unlock size={14} className="ml-1" /> فك الحظر</Button></div>)}{!blockedCustomers.length && <div className="text-sm text-slate-500 rounded-lg bg-slate-50 p-3">لا توجد حسابات سداد موقوفة.</div>}</div>
      </Card>

      <Card className="p-4 space-y-3" data-testid="sms-gateway-report">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2"><div><h2 className="font-bold text-[#221340] flex items-center gap-2"><ClipboardList size={17} /> تقرير الرسائل الواردة</h2><p className="text-xs text-slate-500 mt-1">يشمل نص الرسالة كاملاً، حالة المطابقة، والعملية أو سند القبض المرتبط بها.</p></div><div className="flex gap-2"><Button variant="outline" onClick={printGatewayReport} disabled={!reportRows.length} data-testid="sms-gateway-print"><Printer size={14} className="ml-1" /> طباعة</Button><Button variant="outline" onClick={loadReport} disabled={reportLoading} data-testid="sms-gateway-report-refresh"><RefreshCw size={14} /></Button></div></div>
        <PeriodFilter period={period} start={start} end={end} onChange={updatePeriod} testidPrefix="sms-report-period" />
        <div className="flex flex-col sm:flex-row gap-2"><div className="relative flex-1"><Search size={15} className="absolute right-3 top-3 text-slate-400" /><Input className="pr-9" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && loadReport()} placeholder="ابحث في نص الرسالة أو المصدر أو المرجع أو الجهاز" data-testid="sms-report-search" /></div><select value={status} onChange={(e) => setStatus(e.target.value)} className="border rounded-md px-3 text-sm" data-testid="sms-report-status"><option value="">كل الحالات</option>{Object.entries(STATUS_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><Button onClick={loadReport} className="bg-[#452480]" disabled={reportLoading} data-testid="sms-report-apply"><Search size={14} className="ml-1" /> بحث</Button></div>
        <div className="text-xs text-slate-500">عدد النتائج: <strong>{report.total || 0}</strong></div>
        <div className="overflow-x-auto"><table className="w-full text-xs min-w-[1050px]"><thead className="bg-slate-50"><tr className="text-right"><th className="p-2">التاريخ</th><th className="p-2">المصدر / الجهاز</th><th className="p-2">المبلغ</th><th className="p-2">المرجع</th><th className="p-2">الحالة</th><th className="p-2">السند / المبيعات</th><th className="p-2">نص الرسالة الكامل</th></tr></thead><tbody>{reportRows.map((row) => <tr key={row.message_id} className="border-t align-top"><td className="p-2 whitespace-nowrap" dir="ltr">{dateText(row.received_at)}</td><td className="p-2"><div>{row.sender_id || "-"}</div><div className="font-mono text-[10px] text-slate-500" dir="ltr">{row.device_id || "-"}</div></td><td className="p-2 num font-bold">{row.amount ?? "-"}</td><td className="p-2 font-mono" dir="ltr">{row.transaction_id || row.payment_reference || "-"}</td><td className="p-2"><span className={`px-2 py-1 rounded-full whitespace-nowrap ${statusClass(row.status)}`}>{STATUS_LABELS[row.status] || row.status}</span>{row.failure_reason && <div className="mt-1 text-red-600 max-w-[180px]">{row.failure_reason}</div>}</td><td className="p-2"><div className={row.operation_type === "direct_card_sale" ? "font-bold text-emerald-700" : ""}>{operationText(row)}</div><div className="text-slate-500">{row.customer_name || "-"}</div></td><td className="p-2 whitespace-pre-wrap max-w-[440px]">{row.sms_text || "-"}</td></tr>)}{!reportRows.length && <tr><td colSpan={7} className="p-8 text-center text-slate-400">لا توجد رسائل ضمن الفلاتر الحالية</td></tr>}</tbody></table></div>
      </Card>
    </div>
  );
}
