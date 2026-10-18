import { useEffect, useMemo, useState } from "react";
import api, { errText } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fmtDate } from "@/lib/utils";
import { Search, X, Printer } from "lucide-react";
import PeriodFilter from "@/components/PeriodFilter";
import { printReport } from "@/lib/print";
import { toast } from "sonner";

import { todayIso } from "@/lib/DateService";
// Map audit action codes to human-readable Arabic labels
const ACTION_AR = {
  create: "إضافة",
  update: "تعديل",
  edit: "تعديل",
  delete: "حذف",
  hard_delete: "حذف نهائي",
  cancel: "إلغاء",
  disable: "تعطيل",
  approve: "موافقة",
  reject: "رفض",
  approve_register_request: "موافقة على طلب إنشاء حساب",
  reset_password: "تعديل كلمة المرور",
  reset_customer_password: "تعديل كلمة مرور العميل",
  unbind_device: "فك ربط الجهاز",
  unbind_customer_device: "فك ربط هاتف العميل",
  unlock: "فك حظر",
  reset_attempts: "إعادة ضبط المحاولات الفاشلة",
  add_cards: "إضافة كروت",
  restore: "استرجاع نسخة احتياطية",
  direct_card_sale: "بيع مباشر بدون حساب",
  direct_purchase: "بيع مباشر بدون حساب",
};

const ENTITY_AR = {
  user: "مستخدم",
  customer: "عميل",
  supplier: "مورد",
  sale: "فاتورة مبيعات",
  purchase: "فاتورة مشتريات",
  receipt: "سند",
  expense: "مصروف",
  expense_account: "حساب مصروفات",
  card: "كرت",
  cards: "كروت",
  category: "فئة كروت",
  transfer: "تحويل",
  payment_request: "طلب تسديد",
  register_request: "طلب إنشاء حساب",
};

const humanDetails = (value) => {
  if (!value || typeof value !== "object") return "-";
  const labels = { voucher_date:"\u062a\u0627\u0631\u064a\u062e\u0020\u0627\u0644\u0633\u0646\u062f", entered_at:"\u0648\u0642\u062a\u0020\u0627\u0644\u0625\u062f\u062e\u0627\u0644", alt_number:"\u0627\u0644\u0631\u0642\u0645\u0020\u0627\u0644\u0628\u062f\u064a\u0644",     amount: "المبلغ", number: "رقم المستند", name: "الاسم", account_name: "الحساب", account_id: "معرّف الحساب", user_id: "المستخدم", username: "اسم المستخدم", description: "البيان", list_id: "القائمة", category_id: "الفئة", category_name: "اسم الفئة", party_id: "الحساب المرتبط", party_name: "اسم الحساب", customer_id: "العميل", supplier_id: "المورد", total: "الإجمالي", paid: "المدفوع", remaining: "المتبقي", kind: "النوع", status: "الحالة", source_name: "الحساب المرسل", dest_name: "الحساب المستلم", operation: "العملية", invoice_type: "نوع الفاتورة", phone: "الجوال", alternate_number: "الرقم البديل", account_type: "تصنيف الحساب", password: "كلمة المرور المُدخلة", channel: "قناة الإرسال", requested_at: "وقت الطلب", device_label: "الجهاز", reason: "السبب" };
  return Object.entries(value).filter(([k, v]) => v !== null && v !== undefined && v !== "").map(([k, v]) => `${labels[k] || k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" — ") || "-";
};

const detailRows = (value) => (value && typeof value === "object" ? Object.entries(value).filter(([k, v]) => v !== null && v !== undefined && v !== "") : []);

const humanize = (action, entity, entityId, valuePreview) => {
  const act = action || "";
  const actLabel = ACTION_AR[act] || act;
  const entLabel = ENTITY_AR[entity] || entity || "";
  // Special-case things like "set_status:active" or "edit"
  if (act.startsWith("set_status:")) {
    const s = act.split(":")[1];
    return `${s === "active" ? "تفعيل" : "تعطيل"} ${entLabel}`;
  }
  // Try to pull a "number" out of value to reference the invoice/voucher
  let ref = "";
  if (valuePreview && typeof valuePreview === "object") {
    const num = valuePreview.number || valuePreview.new_number;
    if (num) ref = ` رقم ${num}`;
    else if (valuePreview.name) ref = ` — ${valuePreview.name}`;
    else if (valuePreview.username) ref = ` — ${valuePreview.username}`;
  }
  return `${actLabel} ${entLabel}${ref}`;
};

export default function AuditLog() {
  const [items, setItems] = useState([]);
  const _today = todayIso();
  const [period, setPeriod] = useState("day");
  const [start, setStart] = useState(_today);
  const [end, setEnd] = useState(_today);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [selected, setSelected] = useState(null);

  const load = async () => {
    setLoading(true);
    setLoadError("");
    try {
      const params = {};
      if (start) params.start = start;
      if (end) params.end = end;
      if (q.trim()) params.q = q.trim();
      const r = await api.get("/audit", { params });
      setItems(r.data);
    } catch (error) { setItems([]); setLoadError(errText(error)); }
    setLoading(false);
  };
  useEffect(() => { load(); }, [start, end]);

  const printAudit = () => {
    if (!displayItems.length) { toast.error("لا توجد عمليات للطباعة"); return; }
    printReport({ title: "سجل العمليات", headers: ["التاريخ والوقت", "المستخدم", "العملية", "التفاصيل"], rows: displayItems.map((a) => [fmtDate(a.created_at), a.username || "-", a.label, humanDetails(a.new_value || a.old_value || {})]), username: "" });
  };

  const clearFilters = () => {
    const today = todayIso();
    setPeriod("day"); setStart(today); setEnd(today); setQ("");
    setTimeout(load, 0);
  };

  const displayItems = useMemo(() => items.map((a) => {
    const preview = a.new_value || a.old_value || {};
    return { ...a, label: humanize(a.action, a.entity, a.entity_id, preview) };
  }), [items]);

  return (
    <div className="space-y-4" data-testid="audit-page">
      <Card className="p-3 flex flex-col sm:flex-row gap-2 sm:items-end flex-wrap no-print">
        <div className="w-full">
          <label className="text-xs text-slate-500 block mb-1">الفترة الزمنية</label>
          <PeriodFilter period={period} start={start} end={end} onChange={({ period: p, start: s, end: e }) => { setPeriod(p); setStart(s); setEnd(e); }} testidPrefix="audit-period" />
        </div>
        <div className="flex-1 min-w-[180px]"><label className="text-xs">بحث</label><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="اسم المستخدم أو نوع العملية" data-testid="audit-q"/></div>
        <Button onClick={load} disabled={loading} className="bg-[#221340]" data-testid="audit-search"><Search size={14} className="ml-1"/> {loading ? "جاري..." : "بحث"}</Button>
        <Button onClick={clearFilters} variant="outline" data-testid="audit-clear"><X size={14} className="ml-1"/> مسح</Button>
        <Button onClick={printAudit} variant="outline" data-testid="audit-print"><Printer size={14} className="ml-1"/> طباعة PDF</Button>
      </Card>

      {loadError && <Card className="p-4 border-red-200 bg-red-50 text-red-700">{loadError}</Card>}

      <Card className="overflow-x-auto">
        <table className="w-full text-sm min-w-[720px]">
          <thead className="bg-slate-50">
            <tr className="text-right">
              <th className="p-3">التاريخ والوقت</th>
              <th className="p-3">المستخدم</th>
              <th className="p-3">العملية</th>
              <th className="p-3">التفاصيل</th>
            </tr>
          </thead>
          <tbody>
            {displayItems.map((a) => (
              <tr key={a.id} className="border-t cursor-pointer hover:bg-[#F8F5FF]" onClick={() => setSelected(a)} data-testid={`audit-row-${a.id}`}>
                <td className="p-3 whitespace-nowrap">{fmtDate(a.created_at)}</td>
                <td className="p-3 font-medium">{a.username || "-"}</td>
                <td className="p-3">{a.label}</td>
                <td className="p-3 text-[11px] break-all max-w-xs text-slate-500">
                  {humanDetails(a.new_value || a.old_value || {})}
                </td>
              </tr>
            ))}
            {displayItems.length === 0 && (
              <tr><td colSpan={4} className="p-6 text-center text-slate-400">لا توجد عمليات في هذه الفترة</td></tr>
            )}
          </tbody>
        </table>
      </Card>
      {selected && <div className="fixed inset-0 z-[70] bg-black/40 flex items-center justify-center p-3" dir="rtl" onClick={() => setSelected(null)}><div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[85vh] overflow-auto p-5" onClick={(e) => e.stopPropagation()}><div className="flex items-center justify-between mb-4"><div className="text-lg font-bold text-[#221340]">تفاصيل العملية كاملة</div><Button variant="outline" size="sm" onClick={() => setSelected(null)}><X size={14}/> إغلاق</Button></div><div className="grid sm:grid-cols-2 gap-2 text-sm mb-4"><div><b>العملية:</b> {selected.label || "-"}</div><div><b>التاريخ:</b> {fmtDate(selected.created_at)}</div><div><b>المستخدم:</b> {selected.username || "-"}</div><div><b>المرجع:</b> {selected.entity_id || "-"}</div></div><div className="space-y-3"><div className="grid sm:grid-cols-2 gap-2">{[["القيمة السابقة", selected.old_value], ["القيمة الجديدة", selected.new_value]].map(([title, value]) => <div key={title} className="border rounded-lg p-3"><div className="font-bold text-[#221340] mb-2">{title}</div>{detailRows(value).length ? <dl className="space-y-1 text-sm">{detailRows(value).map(([key, value]) => <div key={key} className="flex gap-2 border-b border-slate-100 pb-1"><dt className="font-semibold text-slate-600">{key}</dt><dd className="break-words">{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd></div>)}</dl> : <div className="text-slate-400 text-sm">غير متوفر</div>}</div>)}</div><details className="border rounded-lg p-3"><summary className="cursor-pointer font-semibold">البيانات الخام الكاملة</summary><pre className="text-xs whitespace-pre-wrap break-words bg-slate-50 border rounded-lg p-3 mt-2">{JSON.stringify(selected, null, 2)}</pre></details></div></div></div>}
    </div>
  );
}
