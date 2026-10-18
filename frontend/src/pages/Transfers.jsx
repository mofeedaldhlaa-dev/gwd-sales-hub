import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api, { errText } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import PeriodFilter from "@/components/PeriodFilter";
import { fmt, fmtDate } from "@/lib/utils";
import { printReport } from "@/lib/print";
import { ArrowLeftRight, RefreshCw, Search, X, Printer, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { parseDateBoundary, parseServerDate, todayIso, monthStartIso } from "@/lib/DateService";

const operationLabel = (item) => item.operation_type === "quick_recharge"
  ? "تحويل رصيد"
  : (item.source_type === "cash" || item.dest_type === "cash" ? "تحويل رصيد" : "تحويل لمشترك");

export default function Transfers() {
  const [searchParams] = useSearchParams();
  const focusId = searchParams.get("focus") || "";
  const [items, setItems] = useState([]);
  const [q, setQ] = useState("");
  const [period, setPeriod] = useState("month");
  const [start, setStart] = useState(monthStartIso());
  const [end, setEnd] = useState(todayIso());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [deletingId, setDeletingId] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const r = await api.get("/transfers");
      setItems(Array.isArray(r.data) ? r.data : []);
    } catch (e) {
      setItems([]);
      setError(errText(e) || "تعذر تحميل التحويلات");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  // Opened from a notification: jump to the transfer it announces.
  useEffect(() => {
    if (!focusId) return undefined;
    if (!filtered.some((x) => x.id === focusId)) {
      const target = items.find((x) => x.id === focusId);
      const day = String(target?.created_at || "").slice(0, 10);
      if (day && period !== "custom") {
        setPeriod("custom");
        setStart(day);
        setEnd(todayIso());
      }
      return undefined;
    }
    const timer = setTimeout(() => {
      const el = document.getElementById(`focus-${focusId}`);
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("ring-2", "ring-amber-400", "rounded-md");
      setTimeout(() => el.classList.remove("ring-2", "ring-amber-400", "rounded-md"), 5000);
    }, 500);
    return () => clearTimeout(timer);
  }, [focusId, items, filtered, period]);

  const deleteTransfer = async (item) => {
    const number = item.number || item.reference || item.id || "—";
    const amount = fmt(item.amount);
    const source = item.source_name || "الصندوق";
    const destination = item.dest_name || "الحساب المستلم";
    const confirmed = window.confirm(
      `تأكيد حذف التحويل؟\n\nرقم العملية: ${number}\nالمبلغ: ${amount}\nمن: ${source}\nإلى: ${destination}\n\nسيتم عكس أثر التحويل على الأرصدة ومخزون الرصيد عند وجوده، ولا يمكن التراجع عن الحذف.`
    );
    if (!confirmed) return;
    setDeletingId(item.id);
    try {
      await api.delete(`/transfers/${item.id}`);
      setItems((current) => current.filter((entry) => entry.id !== item.id));
      toast.success(`تم حذف التحويل ${number} وعكس أثره المالي`);
    } catch (e) {
      toast.error(errText(e) || "تعذر حذف التحويل");
    } finally {
      setDeletingId("");
    }
  };

  const filtered = useMemo(() => {
    if (period === "custom" && (!start || !end || end < start)) return [];
    const s = parseDateBoundary(start);
    const e = parseDateBoundary(end, true);
    const ql = q.trim().toLowerCase();
    return items.filter((item) => {
      const d = parseServerDate(item.created_at);
      if (!d || (s && d < s) || (e && d > e)) return false;
      if (ql && !`${item.source_name || ""} ${item.dest_name || ""} ${item.number || ""} ${item.description || ""}`.toLowerCase().includes(ql)) return false;
      return true;
    }).sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  }, [items, period, start, end, q]);

  const printFiltered = () => {
    if (!filtered.length) { toast.error("لا توجد تحويلات للطباعة"); return; }
    printReport({
      title: "تقرير التحويلات",
      headers: ["التاريخ والوقت", "الرقم", "المرسل", "المستلم", "نوع العملية", "المبلغ", "البيان"],
      rows: filtered.map((item) => [fmtDate(item.created_at), item.number || "-", item.source_name || "-", item.dest_name || "-", operationLabel(item), fmt(item.amount), item.description || "-"]),
      totals: [{ label: "عدد العمليات", value: filtered.length }, { label: "إجمالي المبالغ", value: fmt(filtered.reduce((sum, item) => sum + Number(item.amount || 0), 0)) }],
      username: "",
    });
  };

  const clear = () => {
    const d = todayIso();
    setQ(""); setPeriod("day"); setStart(d); setEnd(d);
  };

  return (
    <div className="space-y-4" data-testid="transfers-page">
      <div className="flex items-center justify-between gap-2">
        <div><h1 className="text-xl font-black text-[#221340] flex items-center gap-2"><ArrowLeftRight size={20}/> التحويلات</h1><p className="text-xs text-slate-500 mt-1">تحويل رصيد وتحويل لمشترك والتحويلات بين الحسابات</p></div>
        <div className="flex gap-2"><Button variant="outline" onClick={printFiltered} disabled={loading}><Printer size={14} className="ml-1"/> طباعة PDF</Button><Button variant="outline" onClick={load} disabled={loading}><RefreshCw size={14} className="ml-1"/> تحديث</Button></div>
      </div>
      <Card className="p-3 space-y-3">
        <div className="w-full"><label className="text-xs text-slate-500 block mb-1">الفترة الزمنية</label><PeriodFilter period={period} start={start} end={end} onChange={({ period: nextPeriod, start: nextStart, end: nextEnd }) => { setPeriod(nextPeriod); setStart(nextStart); setEnd(nextEnd); }} testidPrefix="transfers-period" /></div>
        <div className="flex gap-2"><div className="relative flex-1"><Search size={16} className="absolute right-3 top-2.5 text-slate-400"/><Input className="pr-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder="بحث باسم الحساب المرسل أو المستلم..." data-testid="transfers-search"/></div><Button variant="outline" onClick={clear}><X size={14} className="ml-1"/> مسح</Button></div>
      </Card>
      {error && <Card className="p-4 border-red-200 bg-red-50 text-red-700">{error}</Card>}
      {loading ? <Card className="p-8 text-center text-slate-500">جاري تحميل التحويلات...</Card> : (
        <Card className="overflow-x-auto"><table className="w-full min-w-[930px] text-sm"><thead className="bg-slate-50"><tr className="text-right"><th className="p-3">التاريخ والوقت</th><th className="p-3">الرقم</th><th className="p-3">المرسل</th><th className="p-3">المستلم</th><th className="p-3">نوع العملية</th><th className="p-3">المبلغ</th><th className="p-3">البيان</th><th className="p-3 text-center">إجراء</th></tr></thead><tbody>
          {filtered.map((item) => <tr key={item.id} id={`focus-${item.id}`} className="border-t"><td className="p-3 whitespace-nowrap">{fmtDate(item.created_at)}</td><td className="p-3 font-mono">{item.number || "-"}</td><td className="p-3"><div>{item.source_name || "-"}</div>{item.source_phone && <div className="text-[11px] text-slate-500">{item.source_phone}</div>}</td><td className="p-3"><div>{item.dest_name || "-"}</div>{item.dest_phone && <div className="text-[11px] text-slate-500">{item.dest_phone}</div>}</td><td className="p-3">{operationLabel(item)}</td><td className="p-3 font-bold num">{fmt(item.amount)}</td><td className="p-3 text-slate-600"><div>{item.description || "-"}</div>{item.reference && <div className="text-[10px] text-slate-400">المرجع: {item.reference}</div>}</td><td className="p-3 text-center"><Button variant="outline" size="sm" onClick={() => deleteTransfer(item)} disabled={deletingId === item.id} className="border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700" data-testid={`delete-transfer-${item.id}`} title="حذف التحويل"><Trash2 size={14} className="ml-1" />{deletingId === item.id ? "جاري الحذف" : "حذف"}</Button></td></tr>)}
          {!filtered.length && <tr><td colSpan={8} className="p-8 text-center text-slate-400">لا توجد تحويلات ضمن الفلترة</td></tr>}
        </tbody></table></Card>
      )}
    </div>
  );
}
